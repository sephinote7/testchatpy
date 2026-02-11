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

    # 내부 함수: Whisper STT 호출
    def _transcribe(upload: UploadFile | None) -> str:
        if not upload or not upload.filename:
            return ""
        try:
            content = upload.file.read()
            if not content: return ""
            bio = io.BytesIO(content)
            bio.name = upload.filename or "audio.webm"
            tr = client.audio.transcriptions.create(
                model="whisper-1",
                file=bio,
            )
            return (tr.text or "").strip()
        except Exception as e:
            print(f"STT 오류: {e}")
            return ""

    # 2. STT 처리 (각 화자별)
    user_text = _transcribe(audio_user) if audio_user else ""
    cnsler_text = _transcribe(audio_cnsler) if audio_cnsler else ""

    # 텍스트 합치기 (GPT 참고용)
    transcript = f"user: {user_text}\ncnsler: {cnsler_text}".strip()
    stt_items = [
        SttItem(speaker="user", text=user_text or "(음성 없음)"),
        SttItem(speaker="cnsler", text=cnsler_text or "(음성 없음)")
    ]

    # 3. GPT-4o-mini를 이용한 대화 복원 및 요약 (핵심!)
    reorder_and_sum_prompt = f"""
    당신은 상담 데이터 정리 전문가입니다. [음성 인식 결과]와 [채팅 기록]을 분석하여 다음을 수행하세요.

    1. 대화 복원: 채팅 시간과 음성 내용을 문맥적으로 파악하여, 상담사와 사용자의 대화를 시간순으로 재배열한 JSON 배열을 만드세요.
    2. 내용 요약: 전체 대화의 핵심을 300자 이내로 요약하세요.

    [음성 인식 결과]
    {transcript}

    [채팅 기록]
    {msg_data}

    반드시 다음 JSON 형식으로만 응답하세요:
    {{
      "reordered_msg": [
        {{"type": "chat|stt", "speaker": "user|cnsler", "text": "...", "timestamp": "..."}}
      ],
      "summary": "요약 내용"
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "너는 데이터를 정교하게 정렬하는 JSON API 서버야."},
                {"role": "user", "content": reorder_and_sum_prompt},
            ],
            response_format={ "type": "json_object" }
        )
        
        result_json = json.loads(response.choices[0].message.content)
        final_messages = result_json.get("reordered_msg", [])
        final_summary = result_json.get("summary", "(요약 실패)")
    except Exception as e:
        print(f"GPT 처리 오류: {e}")
        final_messages = chat_messages # 실패 시 원본 채팅이라도 유지
        final_summary = "요약 중 오류가 발생했습니다."

    # 4. 최종 결과 반환 (하나의 return문으로 정리)
    return SummarizeResponse(
        transcript=transcript,
        summary=final_summary,
        msg_data=final_messages,
        stt=stt_items
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
    # 여러 단계 거치지 말고 한 번에 명확하게 지시
    prompt = (
        "상담 내용을 300자 이내의 단락으로 요약하세요. "
        "반드시 한국어 문장 완결형(.니다)으로 끝내야 합니다. "
        f"원문:\n{text}"
    )
    return _summarize_with_openai(prompt) # 300자 넘으면 그때만 문장 단위 절삭

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