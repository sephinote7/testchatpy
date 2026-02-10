import os
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google import genai
from google.genai import types

# 1. Gemini 클라이언트 설정
def get_client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY가 설정되지 않았습니다.",
        )
    return genai.Client(api_key=key)

MIME_MAP = {
    ".webm": "video/webm",
    ".mp3": "audio/mp3",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="화상채팅 음성 요약 API", lifespan=lifespan)

# CORS 설정: 보안을 위해 나중에 Vercel 주소로 변경 권장
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
    return {"status": "running", "engine": "gemini-2.0-flash"}

@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_audio(
    audio: UploadFile = File(None),
    msg_data: str | None = Form(None),
):
    client = get_client()
    transcript = ""
    chat_messages: list = []

    # 1. 채팅 로그 파싱
    if msg_data:
        try:
            chat_messages = json.loads(msg_data)
        except Exception:
            chat_messages = []

    # 2. 오디오/영상 파일 처리 (STT)
    if audio and audio.filename:
        content = await audio.read()
        if content:
            suffix = "." + audio.filename.rsplit(".", 1)[-1].lower() if "." in audio.filename else ".webm"
            mime_type = MIME_MAP.get(suffix, "video/webm")
            
            try:
                audio_part = types.Part.from_bytes(data=content, mime_type=mime_type)
                # Gemini 2.0 Flash 모델 사용
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[
                        "영상/음성 대화 내용을 텍스트로 모두 추출해 주세요. 한국어로 작성해 주세요.",
                        audio_part,
                    ],
                )
                transcript = (response.text or "").strip()
            except Exception as e:
                print(f"STT Error: {e}") # STT 실패 시 에러 로그만 남김

    # 3. 텍스트 통합 (STT 결과 + 채팅 로그)
    combined_text = transcript
    if chat_messages:
        chat_lines = [f"{m.get('from', '?')}: {m.get('text', '')}" for m in chat_messages if m.get('text')]
        chat_str = "\n".join(chat_lines)
        combined_text = f"{combined_text}\n\n[채팅 로그]\n{chat_str}" if combined_text else chat_str

    # 4. 최종 요약 생성
    summary = "(분석할 내용이 없습니다.)"
    if combined_text.strip():
        try:
            summary = _summarize_text(client, combined_text)
        except Exception as e:
            summary = f"(요약 중 오류 발생: {str(e)})"

    return SummarizeResponse(
        transcript=transcript or None,
        summary=summary,
        msg_data=chat_messages if chat_messages else None,
    )

@app.post("/api/summarize-text", response_model=SummarizeResponse)
async def summarize_text_only(body: SummarizeTextRequest):
    client = get_client()
    summary = _summarize_text(client, body.text.strip())
    return SummarizeResponse(transcript=body.text, summary=summary)

def _summarize_text(client: genai.Client, text: str) -> str:
    prompt = f"다음 대화 내용을 핵심 위주로 친절하게 요약해 주세요:\n\n{text}"
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[prompt],
        config=types.GenerateContentConfig(max_output_tokens=1000),
    )
    return (response.text or "").strip()

# Render 배포를 위한 포트 설정
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)