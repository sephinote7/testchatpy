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

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic 모델 정의 ---

class SummarizeTextRequest(BaseModel):
    text: str

class SttItem(BaseModel):
    speaker: str  # "user" | "cnsler"
    text: str
    timestamp: str

class SummarizeResponse(BaseModel):
    transcript: str | None = None
    summary: str
    msg_data: list | None = None
    stt: list[SttItem] | None = None

# --- 유틸리티 함수 ---

def _summarize_with_openai(client: OpenAI, text: str) -> str:
    prompt = (
        "당신은 회의/상담 내용을 정리해 주는 한국어 요약 도우미입니다.\n"
        "- 핵심 내용을 300자 이내의 단락으로 요약하세요.\n"
        "- 반드시 한국어 문장 완결형(.니다)으로 끝내야 합니다.\n\n"
        f"원문:\n{text}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 한국어 요약 전문가입니다."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"OpenAI summary error: {e}")
        return f"(요약 오류 발생)"

# --- API 엔드포인트 ---

@app.get("/")
async def root():
    return {
        "status": "running",
        "stt_engine": "whisper-1",
        "summary_engine": "gpt-4o-mini",
    }

@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_audio(
    audio: UploadFile = File(None),
    audio_user: UploadFile = File(None),
    audio_cnsler: UploadFile = File(None),
    msg_data: str | None = Form(None),
):
    client = get_openai_client()
    chat_messages: list = []
    
    # 1. 채팅 로그 파싱
    if msg_data:
        try:
            chat_messages = json.loads(msg_data)
        except Exception:
            chat_messages = []

    # 상담 시작 기준 시간 (채팅 데이터의 첫 번째 타임스탬프를 기준으로 삼음)
    # 채팅이 없다면 현재 서버 시간을 기준으로 설정
    if chat_messages:
        base_time = int(chat_messages[0].get('timestamp', time.time() * 1000))
    else:
        base_time = int(time.time() * 1000)

    # 2. 내부 함수: Whisper STT (문장별 타임스탬프 추출 버전)
    def _transcribe_with_timestamp(upload: UploadFile | None, speaker: str) -> list:
        if not upload or not upload.filename:
            return []
        try:
            content = upload.file.read()
            if not content: return []
            
            bio = io.BytesIO(content)
            bio.name = "audio.webm" 
            
            # [핵심] response_format="verbose_json"을 사용하여 각 문장의 초 단위 위치 정보를 가져옴
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=bio,
                response_format="verbose_json"
            )

            # resp.segments에 문장별 데이터가 리스트로 들어있음
            segments = getattr(resp, 'segments', [])
            extracted_items = []
            
            for seg in segments:
                # seg['start']는 녹음 시작 후 흐른 '초' (예: 10.5초)
                # 이를 밀리초(ms)로 변환하여 상담 시작 시각에 더함
                msg_timestamp = base_time + int(seg['start'] * 1000)
                
                extracted_items.append({
                    "type": "stt",
                    "speaker": speaker,
                    "text": seg['text'].strip(),
                    "timestamp": str(msg_timestamp)
                })
            return extracted_items
        except Exception as e:
            print(f"STT 처리 오류 ({speaker}): {e}")
            return []

    # 3. 각 화자별 음성 처리
    user_stt_messages = _transcribe_with_timestamp(audio_user, "user")
    cnsler_stt_messages = _transcribe_with_timestamp(audio_cnsler, "cnsler")

    # 4. 데이터 통합 및 1차 정렬 (채팅 + 사용자STT + 상담사STT)
    # 채팅 데이터에도 type이 누락된 경우를 대비해 보강
    for m in chat_messages:
        if "type" not in m: m["type"] = "chat"
        
    all_combined = chat_messages + user_stt_messages + cnsler_stt_messages
    all_combined.sort(key=lambda x: int(x.get('timestamp', 0)))

    # 5. GPT를 통한 대화 맥락 정제 및 요약
    # 텍스트가 너무 많을 경우를 대비해 GPT에게 정렬과 요약을 한 번에 시킴
    reorder_prompt = f"""
    당신은 상담 데이터를 정리하는 전문가입니다. 
    제공된 [데이터]에는 채팅 기록과 음성 인식 결과가 섞여 있으며, 시간이 다소 겹칠 수 있습니다.
    
    1. 대화 복원: 중복된 의미의 문장은 하나로 합치고, 상담사와 내담자의 대화가 문맥상 자연스럽게 이어지도록 최종 JSON 배열을 만드세요.
    2. 요약: 전체 상담의 핵심 내용을 300자 내외로 요약하세요.

    [데이터]
    {json.dumps(all_combined, ensure_ascii=False)}

    응답은 반드시 아래 JSON 형식을 지키세요:
    {{
      "reordered_msg": [
        {{"type": "chat|stt", "speaker": "user|cnsler", "text": "...", "timestamp": "..."}}
      ],
      "summary": "요약 내용"
    }}
    """

    try:
        gpt_resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "너는 상담 기록을 정제하는 JSON API 엔진이야."},
                {"role": "user", "content": reorder_prompt},
            ],
            response_format={ "type": "json_object" }
        )
        
        result_data = json.loads(gpt_resp.choices[0].message.content)
        final_messages = result_data.get("reordered_msg", all_combined)
        final_summary = result_data.get("summary", "(요약 생성 실패)")
    except Exception as e:
        print(f"GPT 처리 중 오류: {e}")
        final_messages = all_combined
        final_summary = "요약 중 오류가 발생했습니다."

    # 6. 최종 결과 구성
    transcript_summary = "\n".join([f"[{m['speaker']}] {m['text']}" for m in final_messages])
    stt_items = [SttItem(speaker=m['speaker'], text=m['text'], timestamp=m['timestamp']) 
                 for m in all_combined if m['type'] == 'stt']

    return SummarizeResponse(
        transcript=transcript_summary,
        summary=final_summary,
        msg_data=final_messages,
        stt=stt_items
    )

@app.post("/api/summarize-text", response_model=SummarizeResponse)
async def summarize_text_only(body: SummarizeTextRequest):
    client = get_openai_client()
    summary = _summarize_with_openai(client, body.text.strip())
    return SummarizeResponse(transcript=body.text, summary=summary)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)