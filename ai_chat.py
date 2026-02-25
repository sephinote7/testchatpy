"""
AI 상담 API (회원 전용). cnsl_tp=3(AI상담) 전용.
- GET    /api/ai/chat/history       : AI 상담 목록 조회 (cnsl_reg, cnsl_tp=3)
- GET    /api/ai/chat/{cnsl_id}     : ai_msg 조회 (상세)
- POST   /api/ai/chat/{cnsl_id}     : 메시지 전송 → OpenAI 응답 저장 후 반환
- POST   /api/ai/chat/{cnsl_id}/summary : 요약 생성 후 ai_msg.summary, cnsl_reg.cnsl_content 저장
- DELETE /api/ai/chat/{cnsl_id}     : AI 상담 삭제 처리(소프트 삭제)
"""
import json
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ai_db import (
    DATABASE_URL,
    append_message,
    delete_ai_consult,
    get_ai_consult_cnsl,
    get_ai_consult_history,
    get_bot_msg,
    update_summary,
)
from ai_openai import get_ai_reply
from openai import OpenAI

router = APIRouter(prefix="/api/ai", tags=["ai-chat"])
# history는 {cnsl_id}보다 먼저 매칭되어야 함 → 별도 라우터로 먼저 include
history_router = APIRouter(prefix="/api/ai", tags=["ai-chat"])


def get_member_email(x_user_email: str | None = Header(None, alias="X-User-Email")) -> str:
    """회원 전용: X-User-Email 필수."""
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="회원만 이용 가능합니다.")
    return email


def _validate_cnsl_access(cnsl_id: int, member_id: str) -> None:
    """cnsl_id 존재 및 본인 소유 검증. 404(없음) 또는 403(타인 소유) raise."""
    cnsl = get_ai_consult_cnsl(cnsl_id)
    if not cnsl:
        raise HTTPException(status_code=404, detail="해당 상담 기록을 찾을 수 없습니다.")
    if cnsl.get("member_id") != member_id:
        raise HTTPException(status_code=403, detail="해당 상담에 접근할 수 없습니다.")


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


@history_router.get("/chat/history")
async def get_chat_history(member_id: str = Depends(get_member_email)):
    """AI 상담(cnsl_tp=3) 목록 조회. cnsl_stat, cnsl_dt, cnsl_start_time, cnsl_end_time, cnsl_title, cnsl_content 반환."""
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="서비스를 일시적으로 사용할 수 없습니다.")
    rows = get_ai_consult_history(member_id)
    out = []
    for r in rows:
        row = dict(r)
        if hasattr(row.get("cnsl_dt"), "isoformat"):
            row["cnsl_dt"] = row["cnsl_dt"].isoformat()
        out.append(row)
    return out


@router.get("/chat/{cnsl_id}")
async def get_chat(cnsl_id: int, member_id: str = Depends(get_member_email)):
    """ai_msg 조회. VisualChat 형식으로 목록 1건 반환."""
    _validate_cnsl_access(cnsl_id, member_id)
    row = get_bot_msg(cnsl_id, member_id)
    out = [_row_to_visual_format(row)] if row else []
    return out


class PostChatBody(BaseModel):
    content: str | None = None
    text: str | None = None


@router.post("/chat/{cnsl_id}")
async def post_chat(cnsl_id: int, body: PostChatBody, member_id: str = Depends(get_member_email)):
    """사용자 메시지 저장 → OpenAI 응답 생성·저장 → VisualChat 형식 1건 반환."""
    _validate_cnsl_access(cnsl_id, member_id)
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
    _validate_cnsl_access(cnsl_id, member_id)
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
                        "다음 상담 대화를 분석하여 JSON으로 답변하세요. 반드시 아래 형식만 사용하세요.\n\n"
                        '[summary] 3~5문장, 300자 이내. 상담자(내담자)와 상담사의 대화 내용을 객관적으로 요약. '
                        '예: "웹 개발을 공부하며 취업에 대한 불안감을 느끼고 있는 상담자가 자신의 프로젝트 경험을 공유했습니다. '
                        '이에 상담자는 웹 개발 분야의 성장 가능성을 언급하며..."\n\n'
                        '[cnsl_content] 한 줄, 80자 이내. 반드시 "~에 대한 상담을 진행했습니다." 로 끝나야 함. '
                        '예: "업무 중 손목 부상으로 어려움을 겪는 상황에 대한 상담을 진행했습니다."\n\n'
                        '출력 형식: {"summary": "...", "cnsl_content": "..."}'
                    ),
                },
                {"role": "user", "content": full_text},
            ],
            max_tokens=400,
        )
        raw = (r.choices[0].message.content or "").strip()
        # 마크다운 코드블록 제거 (```json\n{...}``` 등)
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:] if len(lines) > 1 else [raw[3:]])
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3].rstrip()
        json_str = raw.strip()

        summary = ""
        cnsl_content = ""
        try:
            parsed = json.loads(json_str)
            s = parsed.get("summary")
            c = parsed.get("cnsl_content")
            summary = str(s).strip() if s is not None else ""
            cnsl_content = str(c).strip() if c is not None else ""
        except Exception:
            summary = json_str[:300]
            cnsl_content = json_str[:80].rstrip()
            if not cnsl_content.endswith("상담을 진행했습니다."):
                cnsl_content = (cnsl_content.rstrip(".").rstrip() + "에 대한 상담을 진행했습니다.")[:80]
        if not summary:
            summary = json_str[:300]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SUMMARY_FAILED: {e}")
    row = update_summary(cnsl_id, member_id, summary)
    if not row:
        raise HTTPException(status_code=500, detail="summary 저장 실패")
    out = _row_to_visual_format(row)
    if out:
        out["cnsl_content"] = cnsl_content or summary
    return out


@router.delete("/chat/{cnsl_id}")
async def delete_chat(cnsl_id: int, member_id: str = Depends(get_member_email)):
    """AI 상담 기록 삭제 처리(소프트 삭제: cnsl_reg.del_yn='Y')."""
    _validate_cnsl_access(cnsl_id, member_id)
    ok = delete_ai_consult(cnsl_id, member_id)
    if not ok:
        raise HTTPException(status_code=404, detail="해당 상담 기록을 찾을 수 없거나 삭제할 수 없습니다.")
    return {"success": True}
