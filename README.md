# testchatpy

단일 Render 서버에서 다음 두 가지를 제공합니다.

1. **화상 채팅 음성 요약** — STT(OpenAI Whisper) → gpt-4o-mini 요약  
2. **AI 상담 채팅** — bot_msg 저장, OpenAI 채팅 완료 (회원 전용, VisualChat 형식 반환)

## API

### 요약 (기존)
- `POST /api/summarize` — 음성/영상 파일 업로드 → OpenAI Whisper STT 후 gpt-4o-mini 요약 (webm, mp3, wav 등)

### AI 상담 (회원 전용, 헤더 `X-User-Email` 필수)

| Method | 경로 | 설명 |
|--------|------|------|
| GET | /api/ai/chat/history | AI 상담 목록 조회 (cnsl_tp=3, 반환: cnsl_stat, cnsl_dt, cnsl_start_time, cnsl_end_time, cnsl_title, cnsl_content) |
| GET | /api/ai/chat/{cnsl_id} | ai_msg 상세 조회 (VisualChat 형식) |
| POST | /api/ai/chat/{cnsl_id} | body `{"content":"메시지"}` → 사용자 메시지 저장 → OpenAI 응답 저장 후 1건 반환 |
| POST | /api/ai/chat/{cnsl_id}/summary | 대화 요약 생성 후 ai_msg.summary, cnsl_reg.cnsl_content 저장 |
| DELETE | /api/ai/chat/{cnsl_id} | AI 상담 삭제 처리 (cnsl_reg.del_yn='Y' 소프트 삭제) |

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

**53300 연결 슬롯 소진 방지**: Supabase 사용 시 `DATABASE_URL`에 **Pooler URL(포트 6543)** 사용을 권장합니다.  
Supabase 대시보드 → Settings → Database → Connection string → URI (Transaction pooler)

배포된 URL 하나로:
- testchat 프론트의 요약 API 주소 → 동일 URL (STT/요약)
- pjt-gmss 프론트의 `VITE_AI_CHAT_API_URL` → 동일 URL (AI 상담 GET/POST)

---

## Render 배포 URL 및 Postman 접근

### 기본 URL
```
https://testchatpy.onrender.com
```

### Postman에서 테스트하는 방법

1. **Base URL 설정**
   - Postman에서 Environment 또는 Collection Variables 생성
   - `base_url` = `https://testchatpy.onrender.com`

2. **AI 상담 API 요청 시 필수 헤더**
   | 헤더 | 값 | 설명 |
   |------|-----|------|
   | X-User-Email | 회원 이메일 | 회원 식별 (예: `user@example.com`) |

3. **요청 예시 (AI 상담)**
   - **GET** `{{base_url}}/api/ai/chat/history` — AI 상담 목록
   - **GET** `{{base_url}}/api/ai/chat/{cnsl_id}` — 상세 메시지
   - **POST** `{{base_url}}/api/ai/chat/{cnsl_id}` — Body: `{"content":"메시지"}`
   - **POST** `{{base_url}}/api/ai/chat/{cnsl_id}/summary` — 요약 생성
   - **DELETE** `{{base_url}}/api/ai/chat/{cnsl_id}` — 삭제

4. **요약 API**
   - **POST** `{{base_url}}/api/summarize` — multipart/form-data (audio_user, audio_cnsler, msg_data)

5. **참고**
   - Render 무료 플랜: 15분 미사용 시 슬립 → 첫 요청 시 약 30~60초 지연 가능
   - 헬스 체크: `GET /` → `{"status":"running"}`
