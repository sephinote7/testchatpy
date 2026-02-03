# testchatpy

화상 채팅 음성 → **STT(Gemini)** → **Gemini 요약** API (Render 배포용)

## API

- `POST /api/summarize` — 음성/영상 파일 업로드 → Gemini STT 후 요약 (webm, mp3, wav 등)
- `POST /api/summarize-text` — 텍스트만 보내서 Gemini로 요약

## 로컬 실행

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set GEMINI_API_KEY=...
uvicorn app:app --reload
```

## Render 배포

1. [Render](https://render.com)에서 New → Web Service
2. 저장소 연결 후 루트를 `testchatpy`로 지정 (또는 render.yaml 사용)
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. 환경 변수에 `GEMINI_API_KEY` 설정 (발급: [Google AI Studio](https://aistudio.google.com/apikey))

배포된 URL을 testchat 프론트의 "요약 API 주소"에 넣으면 녹화 후 "STT + Gemini 요약" 버튼으로 연동됩니다.
