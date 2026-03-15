# Render 환경 변수 점검 (testchatpy ML 서비스)

## 포트 바인딩 (No open ports detected 대응)

- 앱은 **ML 데이터를 백그라운드**에서 로드합니다. 서버는 기동 직후 포트를 열어 Render 포트 스캔을 통과합니다.
- ML 로딩이 끝나기 전에는 `/recommend`, `/weekly-keywords` 등이 503을 반환할 수 있습니다. 수십 초 후 재시도하면 됩니다.

---

## 필수 환경 변수

| KEY | 필수 | 설명 |
|-----|------|------|
| `OPENAI_API_KEY` | ✅ | OpenAI API 키. 없으면 앱 기동 실패. |
| `DATABASE_URL` | ✅ | PostgreSQL 연결 문자열 (Supabase Pooler **6543** 포트 권장). |

## ML 라우트용 (/recommend, /weekly-keywords, /monthly-top)

- **DATABASE_URL** 이 올바르면 ML도 같은 DB를 사용합니다.
- DATABASE_URL 대신 **user, password, host, port, dbname** 만 설정해도 됩니다.

| KEY | DATABASE_URL 미사용 시 |
|-----|-------------------------|
| `user` | DB 사용자 (예: postgres) |
| `password` | DB 비밀번호 |
| `host` | 호스트 (예: aws-1-ap-southeast-2.pooler.supabase.com) |
| `port` | 포트 (예: 6543) |
| `dbname` | DB 이름 (예: postgres) |

---

## 자주 나는 오류와 확인 사항

### 1. DATABASE_URL 형식 오류 → DB 연결 실패 / 503

- **형식**: `postgresql://USER:PASSWORD@HOST:PORT/DBNAME`
- **비밀번호와 호스트 사이에 반드시 `@` 가 있어야 합니다.**
- ❌ 잘못된 예: `...rhalstnstkr1234!maws-1-ap-southeast-2...` (비밀번호 끝 `!` 뒤에 `@` 없음)
- ✅ 올바른 예: `...rhalstnstkr1234!@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres`
- 비밀번호에 `@`, `#`, `%` 등이 있으면 [URL 인코딩](https://www.w3schools.com/tags/ref_urlencode.asp) 후 넣기.

### 2. OPENAI_API_KEY 없음 → 앱 기동 실패

- Render 대시보드 → Service → Environment 에서 `OPENAI_API_KEY` 값이 비어 있지 않은지 확인.

### 3. /recommend 503 "데이터가 아직 로딩되지 않았습니다"

- **원인**: 앱 시작 시 `load_ml_data()` 가 실패해 ML 데이터(bbs 등)가 로드되지 않음.
- **확인**:
  1. **DB 연결**: 위 DATABASE_URL 또는 user/password/host/port/dbname 이 맞는지.
  2. **테이블**: Supabase에 `bbs`, `bbs_like`, `bbs_comment`, `cmt_like` 등이 있어야 함.
  3. **JVM(konlpy)**: Docker 이미지에 Java가 있어야 주간 키워드/추천 TF-IDF가 동작함. 없으면 ML 로딩이 스킵되고 503 발생.

### 4. Render에서 host 값

- Supabase Pooler 사용 시 host 는 보통  
  `aws-1-ap-southeast-2.pooler.supabase.com`  
  앞에 `m` 이 붙어 있으면 오타일 수 있음 (`maws` → `aws`).

---

## 빠른 점검 체크리스트

- [ ] `OPENAI_API_KEY` 설정됨
- [ ] `DATABASE_URL` 설정됨 **또는** `user`, `password`, `host`, `port`, `dbname` 모두 설정됨
- [ ] `DATABASE_URL` 사용 시 문자열 안에 `@` 가 **한 번** 포함됨 (USER:PASSWORD**@**HOST)
- [ ] Supabase 사용 시 **포트 6543**(Pooler) 사용
- [ ] 수정 후 **재배포**(Manual Deploy 또는 재저장 후 자동 배포) 실행
