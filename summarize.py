import io
import json
import logging
import os
import re
import time
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from openai import OpenAI
from pydantic import BaseModel


router = APIRouter(tags=["summarize"])


def get_openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY가 설정되지 않았습니다.")
    return OpenAI(api_key=key)


class SummarizeResponse(BaseModel):
    transcript: str | None = None
    summary: str
    summary_line: str | None = None
    # 채팅 + STT가 섞인 최종 대화 로그
    msg_data: list


class _SttRefineResponse(BaseModel):
    refined_stt: list[dict[str, Any]]


@router.post("/api/summarize", response_model=SummarizeResponse)
async def summarize_audio(
    audio_user: UploadFile = File(None),
    audio_cnsler: UploadFile = File(None),
    msg_data: str | None = Form(None),
):
    logger = logging.getLogger("uvicorn.error")
    logger.info("POST /api/summarize: request received")
    client = get_openai_client()

    chat_messages = []
    if msg_data:
        try:
            chat_messages = json.loads(msg_data)
        except Exception as e:
            logger.warning(f"채팅 파싱 에러: {e}")
            chat_messages = []

    base_time = (
        int(chat_messages[0].get("timestamp", time.time() * 1000))
        if chat_messages
        else int(time.time() * 1000)
    )

    def _get_stt_with_time(upload: UploadFile | None, speaker: str) -> list:
        if not upload or not upload.filename:
            return []
        try:
            upload.file.seek(0)
            content = upload.file.read()
            if not content:
                logger.info(f"[{speaker}] 음성 파일 크기 0바이트, STT 생략")
                return []
            logger.info(
                f"[{speaker}] STT 처리 중, 크기: {len(content)} bytes, filename={upload.filename}"
            )

            bio = io.BytesIO(content)
            bio.name = upload.filename or "audio.webm"

            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=bio,
                response_format="verbose_json",
            )

            stt_data = resp if isinstance(resp, dict) else resp.model_dump()
            segments = stt_data.get("segments", [])

            results = []
            for seg in segments:
                msg_time = base_time + int(seg.get("start", 0) * 1000)
                text = (seg.get("text", "") or "").strip()
                if (
                    not text
                    or text.lower() == "silence"
                    or re.fullmatch(r"[.\-_,\s]+", text)
                    or len(text) <= 1
                ):
                    continue
                results.append(
                    {
                        "type": "stt",
                        "speaker": speaker,
                        "text": text,
                        "timestamp": str(msg_time),
                    }
                )
            return results
        except Exception as e:
            logger.exception(f"[{speaker}] STT 에러: {e}")
            return []

    user_stt_list = _get_stt_with_time(audio_user, "user")
    cnsler_stt_list = _get_stt_with_time(audio_cnsler, "cnsler")

    # STT 문장 정제
    try:
        stt_only = user_stt_list + cnsler_stt_list
        if stt_only:
            refine_prompt = f"""
당신은 한국어 음성 인식(STT) 결과를 '사용자에게 보여줄 대화 문장' 형태로 정제하는 역할입니다.

규칙:
- 입력 STT의 의미를 바꾸거나 새로운 사실/문장을 만들어내지 마세요(환각 금지).
- 가능한 경우 끊긴 조각을 자연스러운 문장으로 이어 붙이되, 추정이 필요한 부분은 그대로 둡니다.
- 이상한 단어/오탈자는 '발음상 근접한 단어'로만 아주 보수적으로 보정합니다.
- 말끝의 반복, 불필요한 군더더기(어, 음, 그, ...)는 제거해도 됩니다.
- 출력은 speaker별로 문장 단위로 끊어서 반환하고, timestamp는 해당 문장을 구성한 첫 조각의 timestamp를 사용하세요.
- '.' 같은 구두점/한 글자 잡음, "Silence" 같은 무음 표기는 제거하세요.

입력(JSON):
{json.dumps(stt_only, ensure_ascii=False)}

출력(JSON만):
{{ "refined_stt": [ {{"type":"stt","speaker":"user|cnsler","text":"문장","timestamp":"ms-string"}} ] }}
"""
            refine = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": refine_prompt}],
                response_format={"type": "json_object"},
            )
            refined_obj = json.loads(refine.choices[0].message.content or "{}")
            refined_list = refined_obj.get("refined_stt", [])
            if isinstance(refined_list, list) and refined_list:
                normalized = []
                for it in refined_list:
                    if not isinstance(it, dict):
                        continue
                    t = (it.get("text") or "").strip()
                    if (
                        not t
                        or t.lower() == "silence"
                        or re.fullmatch(r"[.\-_,\s]+", t)
                        or len(t) <= 1
                    ):
                        continue
                    sp = (it.get("speaker") or "").strip().lower()
                    sp = "cnsler" if sp in ("counselor", "cnsler", "system") else "user"
                    ts = str(it.get("timestamp") or "")
                    if not ts.isdigit():
                        ts = str(int(time.time() * 1000))
                    normalized.append(
                        {"type": "stt", "speaker": sp, "text": t, "timestamp": ts}
                    )
                if normalized:
                    user_stt_list = [x for x in normalized if x["speaker"] == "user"]
                    cnsler_stt_list = [x for x in normalized if x["speaker"] == "cnsler"]
    except Exception as e:
        logger.exception(f"STT 정제 에러: {e}")

    # 최종 대화 로그: 원본 채팅 + STT를 모두 포함, timestamp 기준 정렬
    all_combined = chat_messages + user_stt_list + cnsler_stt_list
    all_combined = [
        x for x in all_combined
        if isinstance(x, dict) and x.get("text")
    ]
    for msg in all_combined:
        try:
            msg["timestamp"] = str(int(msg.get("timestamp") or 0))
        except Exception:
            msg["timestamp"] = str(int(time.time() * 1000))
    all_combined.sort(key=lambda x: int(x.get("timestamp", 0)))

    # 요약/요약문은 LLM에게 맡기고, msg_data 구조는 그대로 유지한다.
    prompt = f"""
당신은 상담 데이터를 정리하는 전문가입니다.
제공된 [데이터]는 채팅 기록과 음성 인식(STT) 결과가 섞여 있습니다.

1. "summary": 전체 상담 내용을 250자 이내의 자연스러운 한국어 서술형 문단으로 요약합니다.
   - 핵심 내용과 흐름이 드러나도록 2~4문장 정도로 작성합니다.
   - "안녕하세요" 같은 인사 한 줄처럼 지나치게 짧은 문장은 피하고, 충분한 정보를 담으세요.
2. "summary_line": 전체 내용에서 가장 중요한 핵심을 한 줄(한 문장)로 표현합니다.
   - 1문장으로만 작성하고, 80자 이내로 간결하게 정리합니다.

[데이터]
{json.dumps(all_combined, ensure_ascii=False)}

응답 형식(JSON만 출력):
{{ "summary": "...", "summary_line": "..." }}
"""

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        res_json = json.loads(completion.choices[0].message.content or "{}")
        final_summary = (res_json.get("summary") or "").strip()
        final_summary_line = (res_json.get("summary_line") or "").strip() or None
    except Exception as e:
        logger.exception(f"GPT 처리 에러: {e}")
        final_summary = ""
        final_summary_line = None

    # summary 최소/최대 길이 방어: 너무 짧으면 기본 텍스트에서 재구성, 너무 길면 250자로 자름
    def build_fallback_summary() -> str:
        texts = [str(m.get("text") or "") for m in all_combined if m.get("text")]
        if not texts:
            return "화상 상담 내용 요약입니다."
        joined = " ".join(texts)
        if len(joined) <= 250:
            return joined
        sliced = joined[:251]
        last_space = sliced.rfind(" ")
        return (sliced[:last_space] if last_space > 0 else sliced[:250]).strip()

    summary_ok = final_summary or ""
    if len(summary_ok) < 10:
        summary_ok = build_fallback_summary()
    if len(summary_ok) > 250:
        sliced = summary_ok[:251]
        last_space = sliced.rfind(" ")
        summary_ok = (sliced[:last_space] if last_space > 0 else sliced[:250]).strip()

    return SummarizeResponse(
        transcript="",
        summary=summary_ok or "요약 없음",
        summary_line=final_summary_line,
        msg_data=all_combined,
    )

