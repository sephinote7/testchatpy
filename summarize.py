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
    msg_data: list | None = None


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

    all_combined = chat_messages + user_stt_list + cnsler_stt_list
    all_combined.sort(key=lambda x: int(x.get("timestamp", 0)))

    prompt = f"""
당신은 상담 데이터를 정리하는 전문가입니다.
제공된 [데이터]는 채팅 기록과 음성 인식 결과가 섞여 있습니다.
1. reordered_msg: 시간순 대화록 배열.
2. summary: 서술형 요약(300자 이내).
3. summary_line: 핵심 한 줄 요약.

[데이터]
{json.dumps(all_combined, ensure_ascii=False)}

응답 형식(JSON만 출력):
{{ "reordered_msg": [...], "summary": "...", "summary_line": "..." }}
"""

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        res_json = json.loads(completion.choices[0].message.content)
        final_messages = res_json.get("reordered_msg", all_combined)
        final_summary = res_json.get("summary", "요약 생성 실패")
        final_summary_line = (res_json.get("summary_line", "") or "").strip() or None
    except Exception as e:
        logger.exception(f"GPT 처리 에러: {e}")
        final_messages = all_combined
        final_summary = "정리 중 오류가 발생했습니다."
        final_summary_line = None

    summary_ok = (final_summary or "").strip()
    if len(summary_ok) > 300:
        summary_ok = summary_ok[:297].rstrip() + "…"

    return SummarizeResponse(
        transcript="",
        summary=summary_ok or "요약 없음",
        summary_line=final_summary_line,
        msg_data=final_messages,
    )

