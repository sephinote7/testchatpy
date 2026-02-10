import os
import io
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SummarizeTextRequest(BaseModel):
    text: str


class SummarizeResponse(BaseModel):
    transcript: str | None = None
    summary: str
    msg_data: list | None = None


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
    msg_data: str | None = Form(None),
):
    client = get_openai_client()
    transcript = ""
    chat_messages: list = []

    # 1. 채팅 로그 파싱
    if msg_data:
        try:
            chat_messages = json.loads(msg_data)
        except Exception:
            chat_messages = []

    # 2. 오디오/영상 파일 처리 (Whisper STT)
    if audio and audio.filename:
        content = await audio.read()
        if content:
            try:
                bio = io.BytesIO(content)
                bio.name = audio.filename or "audio.webm"
                print(
                    f\"Whisper STT 요청: {audio.filename}, 크기: {len(content)} bytes\"
                )
                tr = client.audio.transcriptions.create(
                    model=\"whisper-1\",
                    file=bio,
                )
                transcript = (tr.text or \"\").strip()
                print(f\"Whisper STT 결과 샘플: {transcript[:50]}...\")
            except Exception as e:
                print(f\"Whisper STT 오류: {e}\")
                transcript = \"\"

    # 3. 텍스트 통합
    combined_text = transcript or \"\"
    if chat_messages:
        chat_lines = [
            f\"{m.get('from', '?')}: {m.get('text', '')}\"
            for m in chat_messages
            if m.get(\"text\")
        ]
        chat_str = \"\\n\".join(chat_lines)
        combined_text = (
            f\"{combined_text}\\n\\n[채팅 로그]\\n{chat_str}\"
            if combined_text
            else chat_str
        )

    # 4. 최종 요약 생성 (gpt-4o-mini)
    summary = \"(분석할 내용이 없습니다.)\"
    if combined_text.strip():
        try:
            summary = _summarize_with_openai(combined_text)
        except Exception as e:
            print(f\"Summary Error (OpenAI): {e}\")
            summary = f\"(요약 중 오류 발생: {str(e)})\"

    return SummarizeResponse(
        transcript=transcript or None,
        summary=summary,
        msg_data=chat_messages if chat_messages else None,
    )


@app.post(\"/api/summarize-text\", response_model=SummarizeResponse)
async def summarize_text_only(body: SummarizeTextRequest):
    summary = _summarize_with_openai(body.text.strip())
    return SummarizeResponse(transcript=body.text, summary=summary)


def _summarize_with_openai(text: str) -> str:
    client = get_openai_client()
    prompt = (
        \"당신은 회의/상담/대화 내용을 정리해 주는 한국어 요약 도우미입니다.\\n\"
        \"- 핵심만 3~5줄 정도로 요약해 주세요.\\n\"
        \"- 중요한 결정 사항과 TODO가 있다면 함께 적어 주세요.\\n\\n\"
        f\"원문:\\n{text}\"
    )
    try:
        resp = client.chat.completions.create(
            model=\"gpt-4o-mini\",
            messages=[
                {\"role\": \"system\", \"content\": \"당신은 한국어 요약 전문가입니다.\"},
                {\"role\": \"user\", \"content\": prompt},
            ],
            max_tokens=800,
        )
        return (resp.choices[0].message.content or \"\").strip()
    except Exception as e:
        print(f\"OpenAI summary error: {e}\")
        return f\"(OpenAI 요약 오류: {e})\"


if __name__ == \"__main__\":
    import uvicorn

    port = int(os.environ.get(\"PORT\", 8000))
    uvicorn.run(\"app:app\", host=\"0.0.0.0\", port=port)