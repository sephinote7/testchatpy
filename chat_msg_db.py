"""
chat_msg 테이블 접근 (화상상담 채팅용).
스키마: chat_id(PK), cnsl_id, member_id, cnsler_id, role, msg_data(jsonb), summary, created_at
cnsl_id당 1행, msg_data.content = [ { speaker, text, type, timestamp }, ... ]
Spring CnslChatController와 동일한 구조.
"""
import json
import os
import time
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cnsl_reg_exists(cnsl_id: int) -> bool:
    """cnsl_reg에 cnsl_id 존재 여부."""
    if not DATABASE_URL or cnsl_id <= 0:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM cnsl_reg WHERE cnsl_id = %s LIMIT 1",
                (cnsl_id,),
            )
            return cur.fetchone() is not None


def get_cnsl_reg(cnsl_id: int) -> Optional[dict]:
    """cnsl_reg에서 member_id, cnsler_id 조회."""
    if not DATABASE_URL or cnsl_id <= 0:
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT cnsl_id, member_id, cnsler_id FROM cnsl_reg
                   WHERE cnsl_id = %s LIMIT 1""",
                (cnsl_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_chat_msg_by_cnsl(cnsl_id: int) -> Optional[dict]:
    """cnsl_id에 해당하는 chat_msg 1건 조회 (created_at 오름차순 첫 행)."""
    if not DATABASE_URL or cnsl_id <= 0:
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT chat_id, cnsl_id, member_id, cnsler_id, role, msg_data, summary, created_at
                   FROM chat_msg WHERE cnsl_id = %s ORDER BY created_at ASC LIMIT 1""",
                (cnsl_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def append_chat_content(
    cnsl_id: int,
    member_email: str,
    cnsler_email: str,
    speaker: str,
    text: str,
    summary_val: Optional[str] = None,
    request_role: Optional[str] = None,
) -> dict:
    """
    기존 chat_msg에 content 추가 또는 새 행 생성.
    speaker: 'user' | 'cnsler'
    request_role: 'user' | 'counselor' | 'cnsler'
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")

    entry = {
        "speaker": speaker,
        "text": text,
        "type": "chat",
        "timestamp": int(time.time() * 1000),
    }

    existing = get_chat_msg_by_cnsl(cnsl_id)
    role_val = (request_role or "user").strip().lower() or "user"

    if existing:
        msg_data = existing.get("msg_data") or {}
        content = msg_data.get("content")
        if not isinstance(content, list):
            content = []
        content = list(content)
        content.append(entry)
        msg_data = dict(msg_data)
        msg_data["content"] = content

        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                updates = ["msg_data = %s::jsonb"]
                params = [json.dumps(msg_data, ensure_ascii=False)]
                if summary_val:
                    updates.append("summary = %s")
                    params.append(summary_val)
                if existing.get("role") in (None, "") and role_val:
                    updates.append("role = %s")
                    params.append(role_val)
                params.extend([cnsl_id])
                cur.execute(
                    f"""UPDATE chat_msg SET {", ".join(updates)}
                        WHERE cnsl_id = %s
                        RETURNING chat_id, cnsl_id, member_id, cnsler_id, role, msg_data, summary, created_at""",
                    params,
                )
                row = cur.fetchone()
        return dict(row)
    else:
        content = [entry]
        msg_data = {"content": content}
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO chat_msg (cnsl_id, member_id, cnsler_id, role, msg_data, summary)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                       RETURNING chat_id, cnsl_id, member_id, cnsler_id, role, msg_data, summary, created_at""",
                    (
                        cnsl_id,
                        member_email or "",
                        cnsler_email or "",
                        role_val,
                        json.dumps(msg_data, ensure_ascii=False),
                        summary_val,
                    ),
                )
                row = cur.fetchone()
        return dict(row)


def member_exists_by_email(email: str) -> bool:
    """member 테이블에 email 존재 여부."""
    if not DATABASE_URL or not (email or "").strip():
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM member WHERE email = %s LIMIT 1",
                (email.strip(),),
            )
            return cur.fetchone() is not None
