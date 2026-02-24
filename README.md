# testchatpy

단일 Render 서버에서 다음 두 가지를 제공합니다.

1. **화상 채팅 음성 요약** — STT(OpenAI Whisper) → gpt-4o-mini 요약  
2. **AI 상담 채팅** — bot_msg 저장, OpenAI 채팅 완료 (회원 전용, VisualChat 형식 반환)

## API

### 요약 (기존)
- `POST /api/summarize` — 음성/영상 파일 업로드 → OpenAI Whisper STT 후 gpt-4o-mini 요약 (webm, mp3, wav 등)

### AI 상담 (회원 전용, 헤더 `X-User-Email` 필수)
- `GET /api/ai/chat/{cnsl_id}` — bot_msg 조회 (VisualChat 형식 목록)
- `POST /api/ai/chat/{cnsl_id}` — body `{"content":"메시지"}` → 사용자 메시지 저장 → OpenAI 응답 저장 후 1건 반환
- `POST /api/ai/chat/{cnsl_id}/summary` — 대화 요약 생성 후 summary 저장

AI 상담 사용 시 PostgreSQL `DATABASE_URL` 필요. `migrations/001_bot_msg.sql` 로 bot_msg 테이블 생성.

## 로컬 실행

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set OPENAI_API_KEY=...
uvicorn app:app --reload
```

## Render 배포

1. [Render](https://render.com)에서 New → Web Service
2. 저장소 연결 후 루트를 `testchatpy`로 지정 (또는 render.yaml 사용)
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. 환경 변수: `OPENAI_API_KEY` (필수), `DATABASE_URL` (AI 상담 사용 시 필수)

배포된 URL 하나로:
- testchat 프론트의 요약 API 주소 → 동일 URL (STT/요약)
- pjt-gmss 프론트의 `VITE_AI_CHAT_API_URL` → 동일 URL (AI 상담 GET/POST)
