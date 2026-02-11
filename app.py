import os
import io
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI

# 1. OpenAI 클라이언트 설정
def get_openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY가 설정되지 않았습니다.",
        )
    return OpenAI(api_key=key)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="화상채팅 음성 요약 API", lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SummarizeTextRequest(BaseModel):
    text: str

class SttItem(BaseModel):
    speaker: str  # "user" | "cnsler"
    text: str

class SummarizeResponse(BaseModel):
    transcript: str | None = None
    summary: str
    msg_data: list | None = None
    stt: list[SttItem] | None = None

@app.get("/")
async def root():
    return {
        "status": "running",
        "stt_engine": "whisper-1",
        "summary_engine": "gpt-4o-mini",
    }

@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_audio(
    audio: UploadFile = File(None),
    audio_user: UploadFile = File(None),
    audio_cnsler: UploadFile = File(None),
    msg_data: str | None = Form(None),
):
    client = get_openai_client()
    transcript = ""
    chat_messages: list = []
    stt_items: list[SttItem] = []

    # 1. 채팅 로그 파싱
    if msg_data:
        try:
            chat_messages = json.loads(msg_data)
        except Exception:
            chat_messages = []

    def _transcribe(upload: UploadFile | None) -> str:
        if not upload or not upload.filename:
            return ""
        try:
            # 메모리 내에서 파일 객체 생성
            content = upload.file.read()
            if not content:
                return ""
            bio = io.BytesIO(content)
            bio.name = upload.filename or "audio.webm"
            print(f"Whisper STT 요청: {bio.name}, 크기: {len(content)} bytes")
            tr = client.audio.transcriptions.create(
                model="whisper-1",
                file=bio,
            )
            text = (tr.text or "").strip()
            print(f"Whisper STT 결과 샘플: {text[:50]}...")
            return text
        except Exception as e:
            print(f"Whisper STT 오류: {e}")
            return ""

    # 2. 오디오/영상 파일 처리 (Whisper STT)
    # 분리 업로드가 있으면 speaker별로 따로 STT
    user_text = _transcribe(audio_user) if audio_user else ""
    cnsler_text = _transcribe(audio_cnsler) if audio_cnsler else ""

    if audio_user or audio_cnsler:
        stt_items = [
            SttItem(speaker="user", text=user_text or "(음성 인식 결과 없음)"),
            SttItem(speaker="cnsler", text=cnsler_text or "(음성 인식 결과 없음)"),
        ]
        transcript = "\n".join(
            [
                f"user: {user_text}".strip(),
                f"cnsler: {cnsler_text}".strip(),
            ]
        ).strip()
    else:
        # 기존 단일 업로드 호환
        transcript = _transcribe(audio) if audio else ""
        if audio:
            stt_items = [SttItem(speaker="user", text=transcript or "(음성 인식 결과 없음)")]

    # 3. 텍스트 통합
    combined_text = transcript or ""
    if chat_messages:
        chat_lines = [
            f"{m.get('from', '?')}: {m.get('text', '')}"
            for m in chat_messages
            if m.get("text")
        ]
        chat_str = "\n".join(chat_lines)
        combined_text = (
            f"{combined_text}\n\n[채팅 로그]\n{chat_str}"
            if combined_text
            else chat_str
        )

    # 4. 최종 요약 생성 (gpt-4o-mini)
    summary = "(분석할 내용이 없습니다.)"
    if combined_text.strip():
        try:
            summary = _summarize_with_openai_300(combined_text)
        except Exception as e:
            print(f"Summary Error (OpenAI): {e}")
            summary = f"(요약 중 오류 발생: {str(e)})"

    return SummarizeResponse(
        transcript=transcript or None,
        summary=summary,
        msg_data=chat_messages if chat_messages else None,
        stt=stt_items if stt_items else None,
    )

@app.post("/api/summarize-text", response_model=SummarizeResponse)
async def summarize_text_only(body: SummarizeTextRequest):
    summary = _summarize_with_openai_300(body.text.strip())
    return SummarizeResponse(transcript=body.text, summary=summary)

def _summarize_with_openai(text: str) -> str:
    client = get_openai_client()
    prompt = (
        "당신은 회의/상담/대화 내용을 정리해 주는 한국어 요약 도우미입니다.\n"
        "- 핵심만 3~5줄 정도로 요약해 주세요.\n"
        "- 중요한 결정 사항과 TODO가 있다면 함께 적어 주세요.\n\n"
        f"원문:\n{text}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 한국어 요약 전문가입니다."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"OpenAI summary error: {e}")
        return f"(OpenAI 요약 오류: {e})"

def _summarize_with_openai_300(text: str) -> str:
    """
    요구사항:
    - 300자 이내
    - 중간에 내용을 자르지 않기 (slice로 절단 금지)
    전략:
    - 1차: 모델에 300자 이내로 요약하도록 강하게 제약
    - 2차(초과 시): 결과를 다시 '300자 이내로 자연스럽게' 재요약
    """
    base_prompt = (
        "당신은 상담/대화 내용을 정리하는 한국어 요약가입니다.\n"
        "- 결과는 반드시 300자 이내로 작성하세요.\n"
        "- 문장이 중간에 끊기지 않도록 자연스럽게 마무리하세요.\n"
        "- 핵심만 간결하게 3~5문장으로 요약하세요.\n\n"
        f"원문:\n{text}"
    )
    summary = _summarize_with_openai(base_prompt)
    if len(summary) <= 300:
        return summary

    retry_prompt = (
        "아래 요약을 문장이 끊기지 않게 자연스럽게 다듬되, 반드시 300자 이내로 줄여주세요.\n\n"
        f"요약:\n{summary}"
    )
    summary2 = _summarize_with_openai(retry_prompt)
    # 그래도 초과하면 한 번 더 강하게
    if len(summary2) <= 300:
        return summary2

    retry_prompt2 = (
        "반드시 300자 이내로, 문장 마무리를 완결형으로 작성하세요. 불릿/번호 없이 문장으로만.\n\n"
        f"요약:\n{summary2}"
    )
    summary3 = _summarize_with_openai(retry_prompt2).strip()

    # 그래도 300자를 넘으면 "문장 경계"에서만 줄여서(중간 절단 방지) 300자 이내 보장
    return _truncate_korean_sentence_boundary(summary3, 300)

def _truncate_korean_sentence_boundary(text: str, limit: int) -> str:
    """
    '중간에 끊기지 않게' 요구사항을 지키기 위해,
    limit 안쪽의 마지막 문장/구분자 경계에서만 잘라냅니다.
    """
    t = (text or "").strip()
    if len(t) <= limit:
        return t

    head = t[:limit]
    # 한국어 문장 종결/구분자 후보
    seps = ["\n", ". ", "…", "!", "?", "。", "다.", "요.", "니다.", "."]
    cut = -1
    for sep in seps:
        idx = head.rfind(sep)
        if idx > cut:
            cut = idx

    if cut >= 0:
        # sep 끝까지 포함하도록
        trimmed = head[: cut + 1].strip()
        return trimmed if trimmed else head.strip()

    # 경계가 없으면 마지막 공백에서 자름(최후의 수단)
    ws = head.rfind(" ")
    if ws > 0:
        return head[:ws].strip()
    return head.strip()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)