import os
import io
import json
import time
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

# CORS 설정: credentials 사용 시 allow_origins는 "*" 불가 → 구체적 origin 목록 필요
_required_origins = [
    "https://testchat-alpha.vercel.app",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
_cors_origins = os.environ.get("CORS_ORIGINS", "").strip()
_extra = [o.strip() for o in _cors_origins.split(",") if o.strip()]
_cors_list = list(dict.fromkeys(_required_origins + _extra))  # 중복 제거, 필수 origin 우선
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

from ai_chat import history_router, router as ai_chat_router
from cnsl_chat import router as cnsl_chat_router

# history 라우트를 {cnsl_id}보다 먼저 매칭되도록 먼저 include
app.include_router(history_router)
app.include_router(ai_chat_router)
app.include_router(cnsl_chat_router)

class SummarizeResponse(BaseModel):
    transcript: str | None = None
    summary: str
    summary_line: str | None = None
    msg_data: list | None = None

@app.get("/")
async def root():
    return {"status": "running"}

@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_audio(
    audio_user: UploadFile = File(None),
    audio_cnsler: UploadFile = File(None),
    msg_data: str | None = Form(None),
):
    client = get_openai_client()
    chat_messages = []
    
    # 1. 채팅 로그 파싱
    if msg_data:
        try:
            chat_messages = json.loads(msg_data)
        except Exception as e:
            print(f"채팅 파싱 에러: {e}")
            chat_messages = []

    # 상담 시작 기준 시간 설정 (정렬의 기준점)
    base_time = int(chat_messages[0].get('timestamp', time.time() * 1000)) if chat_messages else int(time.time() * 1000)

    # 2. 상세 STT 처리 함수 (segments 추출)
    def _get_stt_with_time(upload: UploadFile | None, speaker: str) -> list:
        if not upload or not upload.filename:
            print(f"[{speaker}] 음성 파일이 전송되지 않았습니다.")
            return []
        try:
            content = upload.file.read()
            if not content: return []
            
            bio = io.BytesIO(content)
            bio.name = "audio.webm" 
            
            # verbose_json을 사용하여 문장별 시작 시간 획득
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=bio,
                response_format="verbose_json"
            )

            # 응답 데이터에서 segments 안전하게 추출
            stt_data = resp if isinstance(resp, dict) else resp.model_dump()
            segments = stt_data.get('segments', [])
            
            results = []
            for seg in segments:
                # 시작 초(seg['start'])를 밀리초로 변환하여 기준 시각에 더함
                msg_time = base_time + int(seg.get('start', 0) * 1000)
                results.append({
                    "type": "stt",
                    "speaker": speaker,
                    "text": seg.get('text', '').strip(),
                    "timestamp": str(msg_time)
                })
            print(f"[{speaker}] STT 완료: {len(results)} 문장")
            return results
        except Exception as e:
            print(f"[{speaker}] STT 에러: {e}")
            return []

    # 3. 화자별 음성 인식 실행
    user_stt_list = _get_stt_with_time(audio_user, "user")
    cnsler_stt_list = _get_stt_with_time(audio_cnsler, "cnsler")

    # 4. 모든 메시지 통합 및 1차 정렬
    all_combined = chat_messages + user_stt_list + cnsler_stt_list
    all_combined.sort(key=lambda x: int(x.get('timestamp', 0)))

    # 5. GPT를 통한 대화 정제 및 요약
    prompt = f"""
    당신은 상담 데이터를 정리하는 전문가입니다. 
    제공된 [데이터]는 채팅 기록과 음성 인식 결과가 섞여 있습니다.
    1. 시간순으로 배열하되, 중복되거나 의미가 끊긴 문장을 자연스럽게 연결하여 최종 대화록(JSON)을 만드세요.
    2. 전체 상담 내용을 300자 이내로 요약(summary)하세요.
    3. 전체 내용을 관통하는 한 줄 문장(summary_line)을 작성하세요.

    [데이터]
    {json.dumps(all_combined, ensure_ascii=False)}

    응답 형식(JSON):
    {{
      "reordered_msg": [
        {{"type": "chat|stt", "speaker": "user|cnsler", "text": "...", "timestamp": "..."}}
      ],
      "summary": "300자 이내 요약",
      "summary_line": "한 줄 문장"
    }}
    """

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res_json = json.loads(completion.choices[0].message.content)
        final_messages = res_json.get("reordered_msg", all_combined)
        final_summary = res_json.get("summary", "요약 생성 실패")
        final_summary_line = res_json.get("summary_line", "").strip() or None
    except Exception as e:
        print(f"GPT 처리 에러: {e}")
        final_messages = all_combined
        final_summary = "정리 중 오류가 발생했습니다."
        final_summary_line = None

    return SummarizeResponse(
        transcript="",
        summary=final_summary[:300] if len(final_summary) > 300 else final_summary,
        summary_line=final_summary_line,
        msg_data=final_messages,
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))