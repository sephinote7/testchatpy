# ![로고(마크)](https://crrxqwzygpifxmzxszdz.supabase.co/storage/v1/object/public/site_img/h_logo.png) 고민순삭 (GMSS) – AI/요약/ML 서버 (`testchatpy`)

`testchatpy`는 고민순삭 서비스의 **AI 상담, 화상/채팅 상담 요약, 사이트 챗봇, ML 통계/추천**을 담당하는 FastAPI 기반 백엔드입니다.  
단일 Render 서비스(uvicorn `app:app`)에서 다음 기능을 제공합니다.

1. **화상/채팅 상담 음성 요약** – STT(OpenAI Whisper) → GPT 요약 → Supabase 저장
2. **AI 상담 채팅** – `ai_msg`/`bot_msg` 기반 대화 저장 및 OpenAI 응답
3. **사이트 챗봇(site-chat)** – 고민순삭 홈페이지 이용 안내 전용 챗봇
4. **ML/통계 API** – 게시판 기반 주간 키워드, 워드클라우드, 추천·인기글

---

## 👥 Who are we?

(공통 팀 구성에서 Python/AI 파트 관련)

- **김태길**
  - AI 상담, 화상 상담 STT·요약, 텍스트 상담 요약
  - 사이트 챗봇 API 설계·구현
  - Supabase / Spring / React와의 연동
- **박종석**
  - Supabase 스키마 설계 (`ai_msg`, `chat_msg`, `bbs*` 등)
  - 통계·추천용 SQL/쿼리 설계
- **이하늘**
  - 상담 플로우 요구사항 정의, AI/요약 기능 기획
- 기타 팀원
  - 프론트/스프링과의 도메인 모델 협업

---

## 🧩 역할 개요

이 서비스는 **Spring 메인 백엔드(`pjt-gmss-back`)와 Supabase(PostgreSQL)** 사이에서 AI·요약·추천 기능을 담당합니다.

- AI 텍스트 상담(내담자 ↔ AI) – OpenAI Chat 사용
- 화상/채팅 상담 종료 후 **음성(STT) + 채팅**을 기반으로 요약 생성
- 텍스트 상담(1:1 채팅) 종료 시 요약 생성
- 고민순삭 사이트 이용 방법 안내용 사이트 챗봇
- 게시판 데이터 기반 주간 키워드·워드클라우드·추천글·인기글 제공

---

## 🛠 기술 스택

<div>

<img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white"/>
<img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white"/>
<img src="https://img.shields.io/badge/OpenAI_API-412991?style=flat-square&logo=openai&logoColor=white"/>
<img src="https://img.shields.io/badge/Whisper_STT-000000?style=flat-square"/>
<img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white"/>
<img src="https://img.shields.io/badge/Uvicorn-000000?style=flat-square"/>

</div>

- FastAPI
- PostgreSQL (Supabase DB – `DATABASE_URL` / Pooler 사용)
- OpenAI Chat (GPT 계열 모델, `ai_openai.py`)
- OpenAI Whisper STT (음성 인식)
- Uvicorn (Render / Docker 환경에서 실행)
- (선택) konlpy + JVM (ML/워드클라우드용)

---

## 📦 주요 모듈 및 기능

### 1. 엔트리포인트 – `app.py`

- FastAPI 앱 생성, CORS 설정
- ML 데이터 비동기 로딩 (`load_ml_data`)
- 라우터 등록:
  - `ai_chat` – AI 상담
  - `cnsl_chat` – 채팅 상담 API (요약 저장)
  - `summarize` – STT + 요약
  - `chatbot` – 사이트 챗봇
  - `ml_routes` – 주간 키워드, 추천, 인기글 등

---

### 2. AI 상담 – `ai_chat.py`, `ai_openai.py`, `ai_db.py`

**AI 상담은 cnsl_tp=3(AI 상담) 전용이며, Spring + React `AIChat`과 연동됩니다.**

주요 API:

| Method | 경로                             | 설명                                                                  |
| ------ | -------------------------------- | --------------------------------------------------------------------- |
| GET    | `/api/ai/chat/history`           | AI 상담 목록 조회 (cnsl_tp=3, `cnsl_reg` 조회)                        |
| GET    | `/api/ai/chat/{cnsl_id}`         | `ai_msg` 상세 조회 (VisualChat 형식에 맞춘 구조)                      |
| POST   | `/api/ai/chat/{cnsl_id}`         | 사용자 메시지 저장 → OpenAI 응답 생성·저장 후 1건 반환                |
| POST   | `/api/ai/chat/{cnsl_id}/summary` | 전체 대화 요약 생성 후 `ai_msg.summary`, `cnsl_reg.cnsl_content` 저장 |
| DELETE | `/api/ai/chat/{cnsl_id}`         | AI 상담 소프트 삭제 (`cnsl_reg.del_yn='Y'`)                           |

구현 포인트:

- `ai_openai.py`
  - 공감형 상담사 시스템 프롬프트
  - MBTI / persona 정보를 받아 톤·조언 스타일 조정
- `ai_db.py`
  - `ai_msg` 테이블에 `msg_data.content`(speaker, text, timestamp) 리스트 구조로 저장
  - `member` / `cnsl_reg`와 조인해 접근 제어

> **필수 환경변수**: `OPENAI_API_KEY`, `DATABASE_URL` (Supabase Pooler URL 권장)

---

### 3. 채팅 상담·요약 – `cnsl_chat.py`, `chat_msg_db.py`, `summarize.py`

#### 3-1. 채팅 API (`cnsl_chat.py`)

| Method | 경로                                    | 설명                                                       |
| ------ | --------------------------------------- | ---------------------------------------------------------- |
| GET    | `/api/cnsl/{cnsl_id}/chat`              | 채팅 메시지 목록을 프론트가 사용하기 쉬운 형식으로 flatten |
| POST   | `/api/cnsl/{cnsl_id}/chat`              | 메시지 추가 (`msg_data.content`에 append)                  |
| PATCH  | `/api/cnsl/{cnsl_id}/stat`              | 상담 상태 C/D 업데이트                                     |
| POST   | `/api/cnsl/{cnsl_id}/chat/summary-full` | 요약/요약문/최종 msg_data를 Supabase에 저장                |

`chat_msg_db.py`에서 `chat_msg`, `cnsl_reg`에 접근하여 content 병합 및 정렬을 수행합니다.

#### 3-2. 요약 API (`summarize.py`)

- `POST /api/summarize`
  - **입력**
    - `audio_user`: 사용자 음성(webm 등)
    - `audio_cnsler`: 상담사 음성
    - `msg_data`: 기존 채팅 로그(JSON string)
  - **처리**
    1. Whisper STT로 화자별 텍스트 + timestamp 생성
    2. STT 결과를 한번 더 LLM으로 정제(불필요한 잡음 제거)
    3. 채팅 + STT를 합쳐 시간순 대화 로그로 정렬
    4. GPT로 `summary` / `summary_line` 생성 (길이 제한 포함)
  - **출력**
    - `transcript` (선택)
    - `summary` (250자 이내)
    - `summary_line` (한 줄 요약)
    - `msg_data` (최종 대화 로그 리스트)

VisualChat / CounselorChat은 이 결과를 `/api/cnsl/{id}/chat/summary-full`로 Supabase에 저장합니다.

---

### 4. 사이트 챗봇 – `chatbot.py`

- `POST /api/site-chat`
  - 입력: `{ message, history[], siteContext[], source? }`
  - 출력: `{ answer, summary }`
  - 역할: 고민순삭 홈페이지 UI(메뉴 위치, 이용 방법, 기능 설명 등) 안내 전용 챗봇

React `FloatingChatbot` 컴포넌트에서 이 API를 호출해  
“순삭이” 챗봇 대화와 요약을 제공합니다.

---

### 5. ML/통계 API – `ml_routes.py` 등

`app.py`에 ML 라우터가 포함되어 있어 같은 서비스에서 동작합니다.

| Method | 경로                | 설명                                                                                     |
| ------ | ------------------- | ---------------------------------------------------------------------------------------- |
| GET    | `/weekly-keywords`  | 최근 7일 게시글 TF-IDF 기반 이번 주 키워드 (`{ count, keywords: [{ keyword, score }] }`) |
| GET    | `/weekly-wordcloud` | 위 키워드 기반 워드클라우드 이미지 (PNG)                                                 |
| POST   | `/recommend`        | `{ \"user_id\": \"email\" }` → 해당 유저 추천 게시글                                     |
| GET    | `/monthly-top`      | 월간 인기글                                                                              |

- 의존성: `bbs`, `bbs_like`, `bbs_comment`, `cmt_like` 테이블
- DB 접속: `.env`의 `user`, `password`, `host`, `port`, `dbname`
- 로딩 실패 시: 앱은 기동되며 ML 경로만 503/빈 응답

별도로 ML만 띄우고 싶다면 `python mlfcForFastAPI.py`(포트 8000)를 사용할 수 있습니다.

---

## 🔌 API 정리 (요약)

### 요약 API

- `POST /api/summarize` – 음성/채팅 기반 상담 요약

### AI 상담 API

- `GET /api/ai/chat/history`
- `GET /api/ai/chat/{cnsl_id}`
- `POST /api/ai/chat/{cnsl_id}`
- `POST /api/ai/chat/{cnsl_id}/summary`
- `DELETE /api/ai/chat/{cnsl_id}`

### 채팅 상담 API

- `GET /api/cnsl/{cnsl_id}/chat`
- `POST /api/cnsl/{cnsl_id}/chat`
- `PATCH /api/cnsl/{cnsl_id}/stat`
- `POST /api/cnsl/{cnsl_id}/chat/summary-full`

### 사이트 챗봇 API

- `POST /api/site-chat`

### ML/통계 API

- `GET /weekly-keywords`
- `GET /weekly-wordcloud`
- `POST /recommend`
- `GET /monthly-top`

---

## ⚙ 환경 변수

| 변수                                             | 필수                 | 용도                                               |
| ------------------------------------------------ | -------------------- | -------------------------------------------------- |
| `OPENAI_API_KEY`                                 | 필수                 | OpenAI API 키 (요약·AI 상담·챗봇)                  |
| `DATABASE_URL`                                   | AI 상담 사용 시 필수 | PostgreSQL 연결 문자열 (Supabase Pooler 6543 권장) |
| `user` / `password` / `host` / `port` / `dbname` | ML 라우트 사용 시    | 게시판·댓글 통계/추천용 DB 접속 정보               |

- **채팅/요약/AI 상담만** 사용할 경우: `OPENAI_API_KEY`, `DATABASE_URL`만 설정
- **ML 라우트까지** 사용할 경우: 위 5개 변수도 설정 (Supabase 값 사용)

---

## 🖥 로컬 실행

```bash
cd testchatpy

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt

# 환경 변수 설정
set OPENAI_API_KEY=...          # Windows
# export OPENAI_API_KEY=...     # macOS/Linux

uvicorn app:app --reload
# 기본: http://localhost:8000
```
