# testchatpy

단일 Render 서버에서 다음 두 가지를 제공합니다.

1. **화상 채팅 음성 요약** — STT(OpenAI Whisper) → gpt-4o-mini 요약  
2. **AI 상담 채팅** — bot_msg 저장, OpenAI 채팅 완료 (회원 전용, VisualChat 형식 반환)

## API

### ML/통계 API (app.py에 라우터로 포함)

**app.py** 메인 앱에 `ml_routes` 라우터가 포함되어 있어, **같은 서비스(uvicorn app:app)** 하나로 채팅·요약·ML API를 모두 제공합니다.

| Method | 경로 | 설명 |
|--------|------|------|
| GET | /weekly-keywords | 최근 7일 게시글 TF-IDF 기반 이번 주 키워드 (응답: `{ count, keywords: [{ keyword, score }] }`) |
| GET | /weekly-wordcloud | 위 키워드 기반 워드클라우드 이미지 (PNG) |
| POST | /recommend | body `{ "user_id": "email" }` → 해당 유저 추천 게시글 |
| GET | /monthly-top | 월간 인기글 |

**의존성**: ML 데이터 로딩 시 PostgreSQL에서 `bbs`, `bbs_like`, `bbs_comment`, `cmt_like` 테이블 필요. `.env`에 `user`, `password`, `host`, `port`, `dbname` 설정. 로딩 실패 시 앱은 그대로 기동하며 ML 경로만 503/빈 응답을 반환합니다.  
**프론트 연동**: testchat 배포 시 **VITE_FASTAPI_URL**을 이 서비스(예: Render 배포 URL)로 설정하면 게시판 인기/추천/주간 키워드 요청이 이쪽으로 전달됩니다. 미설정 시 요청은 Spring(api.gmss.site)으로 가며 해당 경로가 없으면 프론트에서 빈 데이터로 처리됩니다.

**별도 실행(선택)**: ML만 단독 서비스로 돌리려면 `python mlfcForFastAPI.py` (포트 8000)로 기동할 수 있으며, 동일 라우트를 제공합니다.

### 요약 (기존)
- `POST /api/summarize` — 음성/영상 파일 업로드 → OpenAI Whisper STT 후 gpt-4o-mini 요약 (webm, mp3, wav 등)

### AI 상담 (회원 전용)

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

### A) Docker로 배포 (권장 — Java 포함, ML 라우트 동작)

Docker 이미지로 배포하면 Render 기본 Python 환경에 없는 **Java(JVM)**를 포함할 수 있어, **konlpy/Okt** 기반 ML 라우트가 그대로 동작합니다.

**기존 서비스에서 Docker로 전환하기**

이미 Render에 올려 둔 testchatpy(Python 런타임) 서비스가 있다면, 아래만 바꾸면 됩니다.

1. 저장소에 **Dockerfile**과 수정된 **render.yaml**이 `testchatpy` 폴더에 들어 있는지 확인한 뒤 푸시.
2. [Render Dashboard](https://dashboard.render.com) → 해당 **Web Service** 선택.
3. 왼쪽 **Settings** 탭에서:
   - **Environment** → **Runtime**: **Python** 을 **Docker** 로 변경.
   - (선택) **Build & Deploy**에서 **Dockerfile Path**가 비어 있으면 `Dockerfile`, **Docker Context**가 비어 있으면 `.` 또는 `testchatpy`(저장소 루트가 GMSS일 때는 보통 Root Directory가 이미 `testchatpy`이므로 `.` 로 두면 됨.)
4. **Manual Deploy** → **Deploy latest commit** 으로 재배포.

이후 빌드가 Dockerfile 기준으로 돌고, 이미지 안에 Java가 포함되어 ML 라우트가 동작합니다. 기존에 넣어 둔 `OPENAI_API_KEY`, `DATABASE_URL` 등 환경 변수는 그대로 쓰입니다. ML 라우트까지 쓰려면 **Environment**에 `user`, `password`, `host`, `port`, `dbname`을 추가하면 됩니다.

**1) Render에서 서비스 생성·연결** (새 서비스일 때)

- [Render](https://render.com) → New → **Web Service**
- 연결할 저장소 선택 후, **Root Directory**를 `testchatpy`로 설정 (저장소 최상단이 아닌 `testchatpy` 폴더를 서비스 루트로 사용)
- **Blueprint**로 배포하는 경우에도 동일하게 Root Directory를 `testchatpy`로 두면, 해당 폴더 안의 `render.yaml`이 적용됨

**2) render.yaml 동작**

- `render.yaml`에 `runtime: docker`, `dockerfilePath: ./Dockerfile`이 지정되어 있으면, Render는 **Python 대신 Docker** 런타임으로 빌드·실행함
- 빌드 시 `testchatpy` 디렉터리 기준으로 `Dockerfile`을 사용해 이미지를 만들고, 그 이미지로 서비스를 띄움

**3) Dockerfile에서 하는 일**

- **베이스 이미지**: `python:3.12-slim-bookworm` (Debian Bookworm 기반 Python 3.12)
- **시스템 패키지**: `openjdk-17-jre-headless` 설치 → konlpy의 **Okt(Open Korean Text)** 토크나이저가 사용하는 JVM 제공
- **앱 실행**: `pip install -r requirements.txt` 후 `uvicorn app:app --host 0.0.0.0 --port $PORT` 로 FastAPI 서버 기동 (Render가 부여하는 `PORT` 사용)

**4) 환경 변수**

| 변수 | 필수 여부 | 용도 |
|------|-----------|------|
| `OPENAI_API_KEY` | 필수 | OpenAI API 키 (요약·AI 상담) |
| `DATABASE_URL` | AI 상담 사용 시 필수 | PostgreSQL 연결 문자열. Supabase 사용 시 **Pooler(6543)** URL 권장 |
| `user` | ML 라우트 사용 시 | PostgreSQL 사용자명 (Supabase: `postgres`) |
| `password` | ML 라우트 사용 시 | DB 비밀번호 |
| `host` | ML 라우트 사용 시 | DB 호스트 (Supabase: `xxx.supabase.co`) |
| `port` | ML 라우트 사용 시 | DB 포트 (Supabase Pooler: `6543`) |
| `dbname` | ML 라우트 사용 시 | DB 이름 (Supabase: `postgres`) |

- **채팅·요약·AI 상담만** 쓰는 경우: `OPENAI_API_KEY`와 (AI 상담 시) `DATABASE_URL`만 설정하면 됨  
- **ML 라우트**(`/weekly-keywords`, `/recommend`, `/monthly-top`)까지 쓰는 경우: 위 표의 `user`, `password`, `host`, `port`, `dbname`을 Supabase(또는 사용 중인 PostgreSQL) 값으로 채워야 함. `mlFunctionVersion`의 `get_db_connection()`이 이 변수들을 읽음

### B) 네이티브 Python으로 배포 (Java 미포함)

- 대시보드에서 **Runtime**을 **Python**으로 선택하고, Build Command: `pip install -r requirements.txt`, Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT` 로 설정.
- 이 경우 JVM이 없어 **ML 라우트는 비동작**(503/빈 응답)하고, 채팅·요약·AI 상담만 동작합니다.

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
   | Query `member_id` | 회원 이메일(member_id) | 회원 식별 (예: `user@example.com`) |

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
