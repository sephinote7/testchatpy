"""
화상상담 채팅 API (chat_msg).
- GET  /api/cnsl/{cnsl_id}/chat : 채팅 메시지 목록 조회 (flattened, Spring 호환)
- POST /api/cnsl/{cnsl_id}/chat : 메시지 전송 및 저장
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from chat_msg_db import (
    DATABASE_URL,
    append_chat_content,
    cnsl_reg_exists,
    get_chat_msg_by_cnsl,
    get_cnsl_reg,
    member_exists_by_email,
)

router = APIRouter(prefix="/api/cnsl", tags=["cnsl-chat"])


def get_member_email(x_user_email: str | None = Header(None, alias="X-User-Email")) -> str:
    """X-User-Email 필수. member 테이블 존재 여부 검증."""
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="X-User-Email 헤더가 필요합니다.")
    if not member_exists_by_email(email):
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")
    return email


def _validate_cnsl_access(cnsl_id: int, current_email: str) -> None:
    """cnsl_reg 존재 및 본인 참여 여부 검증."""
    if not cnsl_reg_exists(cnsl_id):
        raise HTTPException(
            status_code=404,
            detail="해당 상담 ID를 찾을 수 없습니다.",
        )
    reg = get_cnsl_reg(cnsl_id)
    if not reg:
        raise HTTPException(status_code=404, detail="해당 상담 정보를 찾을 수 없습니다.")
    member_id = reg.get("member_id") or ""
    cnsler_id = reg.get("cnsler_id") or ""
    if current_email != member_id and current_email != cnsler_id:
        raise HTTPException(status_code=403, detail="해당 상담에 대한 접근 권한이 없습니다.")


def _flatten_to_frontend_format(row: dict, member_id: str, cnsler_id: str) -> list:
    """
    chat_msg 1행(msg_data.content 배열)을 프론트엔드용 flat 리스트로 변환.
    Spring GET은 row 단위 반환이나, 프론트는 message 단위를 기대.
    """
    if not row:
        return []
    msg_data = row.get("msg_data") or {}
    content = msg_data.get("content")
    if not isinstance(content, list):
        return []
    chat_id = row.get("chat_id")
    out = []
    for idx, item in enumerate(content):
        speaker = (item.get("speaker") or "user").lower()
        text = item.get("text") or ""
        ts = item.get("timestamp")
        role = "counselor" if speaker in ("cnsler", "counselor") else "user"
        sender_email = cnsler_id if role == "counselor" else member_id
        out.append({
            "chatId": f"{chat_id}-{idx}" if chat_id else f"msg-{ts or idx}",
            "role": role,
            "content": text,
            "memberId": member_id,
            "cnslerId": cnsler_id,
            "createdAt": ts,
            "created_at": ts,
        })
    return out


class PostChatBody(BaseModel):
    role: str
    content: str | None = None
    summary: str | None = None


@router.get("/{cnsl_id}/chat")
async def get_chat_messages(cnsl_id: int, member_id: str = Depends(get_member_email)):
    """채팅 메시지 목록 조회. flattened format (프론트엔드 호환)."""
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="서비스를 일시적으로 사용할 수 없습니다.")
    _validate_cnsl_access(cnsl_id, member_id)
    reg = get_cnsl_reg(cnsl_id)
    member_email = reg.get("member_id") or ""
    cnsler_email = reg.get("cnsler_id") or ""
    row = get_chat_msg_by_cnsl(cnsl_id)
    if not row:
        return []
    flat = _flatten_to_frontend_format(row, member_email, cnsler_email)
    return flat


@router.post("/{cnsl_id}/chat")
async def post_chat_message(
    cnsl_id: int,
    body: PostChatBody,
    member_id: str = Depends(get_member_email),
):
    """채팅 메시지 전송 및 저장. Spring ChatMsgPostResponse 호환 응답."""
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="서비스를 일시적으로 사용할 수 없습니다.")
    _validate_cnsl_access(cnsl_id, member_id)

    role = (body.role or "").strip().lower()
    if not role:
        raise HTTPException(status_code=400, detail="role 필수")

    content = (body.content or body.summary or "").strip()
    summary_val = body.summary.strip() if body.summary and body.summary.strip() else None
    if role == "summary":
        summary_val = content

    speaker = "cnsler" if role in ("counselor", "cnsler") else "user"
    reg = get_cnsl_reg(cnsl_id)
    member_email = reg.get("member_id") or ""
    cnsler_email = reg.get("cnsler_id") or ""

    row = append_chat_content(
        cnsl_id=cnsl_id,
        member_email=member_email,
        cnsler_email=cnsler_email,
        speaker=speaker,
        text=content,
        summary_val=summary_val,
        request_role=role,
    )

    created = row.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()

    return {
        "chatId": row.get("chat_id"),
        "cnslId": row.get("cnsl_id"),
        "cnslerId": row.get("cnsler_id"),
        "memberId": row.get("member_id"),
        "createdAt": created,
        "created_at": created,
        "msg_data": row.get("msg_data"),
    }
