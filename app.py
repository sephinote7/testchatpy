import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from summarize import router as summarize_router
from ml_routes import router as ml_router, load_ml_data

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_ml_data()
    yield

app = FastAPI(title="화상채팅 음성 요약 API", lifespan=lifespan)

# --- [수정 포인트 1] 고정 엔드포인트를 라우터보다 먼저 선언 ---
# 이렇게 해야 외부 라우터의 경로 매칭 간섭을 받지 않습니다.

@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Render 헬스체크용: 최상단에 위치하여 즉시 응답 유도"""
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "running"}


# --- [수정 포인트 2] CORS 설정 최적화 ---
# CORS 설정: credentials 사용 시 allow_origins는 "*" 불가 → 구체적 origin 목록 필요
_required_origins = [
    "https://testchat-alpha.vercel.app",
    "https://www.gmss.site",
    "https://gmss.site",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
_cors_origins = os.environ.get("CORS_ORIGINS", "").strip()
_extra = [o.strip() for o in _cors_origins.split(",") if o.strip()]
_cors_list = list(dict.fromkeys(_required_origins + _extra))  # 중복 제거, 필수 origin 우선
# main.py의 middleware 설정 부분
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    # 아래 설정은 에러 상황에서도 브라우저가 원인을 볼 수 있게 돕습니다.
    max_age=3600, 
)

# --- [수정 포인트 3] 라우터 포함 순서 확인 ---
# 만약 cnsl_chat_router 내부에 /api/cnsl/{cnsl_id}/chat 경로가 있다면 
# 해당 파일 내부의 @router.get() 경로 설정을 다시 확인해야 합니다.

from ai_chat import history_router, router as ai_chat_router
from cnsl_chat import router as cnsl_chat_router
from chatbot import router as site_chat_router

app.include_router(history_router)
app.include_router(ai_chat_router)
app.include_router(cnsl_chat_router)
app.include_router(site_chat_router)
app.include_router(summarize_router)
app.include_router(ml_router)

if __name__ == "__main__":
    import uvicorn
    # Render 환경의 PORT 대응
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)