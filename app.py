"""
화상 채팅 음성 요약 API
- STT: Google Gemini로 음성 → 텍스트
- 요약: Google Gemini로 텍스트 요약
- Render 배포용 (PORT 환경변수 사용)
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google import genai
from google.genai import types


def get_client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY가 설정되지 않았습니다.",
        )
    return genai.Client(api_key=key)


# 업로드 음성/영상 확장자 → Gemini 인라인용 MIME 타입
# Gemini 지원: audio/wav, audio/mp3, audio/aiff, audio/aac, audio/ogg, audio/flac, video/mp4 등
MIME_MAP = {
    ".webm": "video/webm",
    ".mp3": "audio/mp3",
    ".mp4": "video/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="화상채팅 음성 요약 API",
    description="음성/영상 파일 업로드 → STT(Gemini) → Gemini 요약",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SummarizeTextRequest(BaseModel):
    """텍스트만 보내서 요약할 때"""
    text: str


class SummarizeResponse(BaseModel):
    transcript: str | None = None
    summary: str


@app.get("/")
async def root():
    return {"service": "testchatpy", "docs": "/docs", "engine": "gemini"}


@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_audio(audio: UploadFile = File(...)):
    """
    음성/영상 파일을 받아 Gemini로 STT 후 요약합니다.
    지원 형식: webm, mp3, mp4, wav, ogg 등
    """
    client = get_client()
    suffix = ".webm"
    if audio.filename and "." in audio.filename:
        suffix = "." + audio.filename.rsplit(".", 1)[-1].lower()
    mime_type = MIME_MAP.get(suffix, "video/webm")

    content = await audio.read()
    if not content:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    # 20MB 초과 시 Files API 사용 권장 (여기서는 인라인으로 처리)
    try:
        audio_part = types.Part.from_bytes(data=content, mime_type=mime_type)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식이거나 파일이 너무 큽니다. (Gemini 인라인 제한 20MB) {e!s}",
        ) from e

    transcript = ""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                "이 음성/영상의 말을 그대로 텍스트로 옮겨 주세요. 한국어면 한국어로, 영어면 영어로 적어 주세요. 말이 없으면 빈 문자열만 반환해 주세요.",
                audio_part,
            ],
        )
        transcript = (response.text or "").strip()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini STT 처리 실패: {e!s}",
        ) from e

    if not transcript:
        return SummarizeResponse(
            transcript=transcript or None,
            summary="(녹음 내용이 없거나 인식되지 않았습니다.)",
        )

    summary = _summarize_text(client, transcript)
    return SummarizeResponse(transcript=transcript, summary=summary)


@app.post("/api/summarize-text", response_model=SummarizeResponse)
async def summarize_text_only(body: SummarizeTextRequest):
    """
    이미 있는 텍스트(예: 채팅 로그, STT 결과)만 Gemini로 요약합니다.
    """
    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text가 비어 있습니다.")
    client = get_client()
    summary = _summarize_text(client, body.text.strip())
    return SummarizeResponse(transcript=body.text, summary=summary)


def _summarize_text(client: genai.Client, text: str) -> str:
    """Gemini로 요약 생성"""
    prompt = (
        "당신은 회의나 대화 내용을 간결하게 요약하는 도우미입니다. "
        "한국어로 핵심만 요약해 주세요.\n\n"
        f"다음 내용을 요약해 주세요:\n\n{text}"
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(max_output_tokens=500),
        )
        return (response.text or "").strip()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini 요약 처리 실패: {e!s}",
        ) from e
