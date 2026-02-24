"""
AI 상담 API (회원 전용). VisualChat 형식 반환.
- GET  /api/ai/chat/{cnsl_id}  : ai_msg 조회
- POST /api/ai/chat/{cnsl_id}  : 사용자 메시지 전송 → OpenAI 응답 저장 후 반환
- POST /api/ai/chat/{cnsl_id}/summary : 요약 생성 후 summary 저장
"""
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ai_db import append_message, get_bot_msg, update_summary
from ai_openai import get_ai_reply
from openai import OpenAI

router = APIRouter(prefix="/api/ai", tags=["ai-chat"])


def get_member_email(x_user_email: str | None = Header(None, alias="X-User-Email")) -> str:
    """회원 전용: X-User-Email 필수."""
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="회원만 이용 가능합니다.")
    return email


def _row_to_visual_format(row: dict | None) -> dict | None:
    """ai_msg 행을 VisualChat 응답 형식으로 변환."""
    if not row:
        return None
    msg_data = row.get("msg_data") or {"content": []}
    created = row.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return {
        "chatId": row.get("ai_id"),
        "cnslId": row.get("cnsl_id"),
        "cnslerId": "",
        "memberId": row.get("member_id"),
        "role": "user",
        "createdAt": created,
        "summary": row.get("summary"),
        "msg_data": msg_data,
    }


@router.get("/chat/{cnsl_id}")
async def get_chat(cnsl_id: int, member_id: str = Depends(get_member_email)):
    """ai_msg 조회. VisualChat 형식으로 목록 1건 반환."""
    row = get_bot_msg(cnsl_id, member_id)
    out = [_row_to_visual_format(row)] if row else []
    return out


class PostChatBody(BaseModel):
    content: str | None = None
    text: str | None = None


@router.post("/chat/{cnsl_id}")
async def post_chat(cnsl_id: int, body: PostChatBody, member_id: str = Depends(get_member_email)):
    """사용자 메시지 저장 → OpenAI 응답 생성·저장 → VisualChat 형식 1건 반환."""
    content = (body.content or body.text or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 필수")
    row = get_bot_msg(cnsl_id, member_id)
    content_list = (row.get("msg_data") or {}).get("content") if row else []
    if not isinstance(content_list, list):
        content_list = []
    history = [{"speaker": x.get("speaker"), "text": x.get("text")} for x in content_list]
    append_message(cnsl_id, member_id, "user", content)
    ai_text = get_ai_reply(content, history)
    row = append_message(cnsl_id, member_id, "ai", ai_text)
    return _row_to_visual_format(row)


@router.post("/chat/{cnsl_id}/summary")
async def post_summary(cnsl_id: int, member_id: str = Depends(get_member_email)):
    """대화 기준 요약 생성 후 summary 저장 (300자 이내)."""
    row = get_bot_msg(cnsl_id, member_id)
    if not row:
        raise HTTPException(status_code=404, detail="해당 상담 기록이 없습니다.")
    content_list = (row.get("msg_data") or {}).get("content") or []
    if not isinstance(content_list, list):
        content_list = []
    texts = [f"{x.get('speaker', '')}: {x.get('text', '')}" for x in content_list]
    full_text = "\n".join(texts)
    if not full_text.strip():
        raise HTTPException(status_code=400, detail="요약할 대화가 없습니다.")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        r = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "다음 상담 대화를 한국어로 3~5문장, 300자 이내로 요약해 주세요. "
                        "반드시 300자를 넘기지 마세요. "
                        "핵심 고민 주제와 감정, 주요 논의 포인트만 정리하고, 새로운 조언은 추가하지 마세요."
                    ),
                },
                {"role": "user", "content": full_text},
            ],
            max_tokens=300,
        )
        summary = (r.choices[0].message.content or "").strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SUMMARY_FAILED: {e}")
    row = update_summary(cnsl_id, member_id, summary)
    return _row_to_visual_format(row)
