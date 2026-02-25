"""
ai_msg 테이블 접근.
스키마: ai_id(PK), cnsl_id, member_id(varchar), msg_data(jsonb), summary(text), created_at, updated_at
cnsl_id당 1행, msg_data = { "content": [ { "speaker": "user"|"ai", "text": "...", "type": "chat", "timestamp": 123 } ] }
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


def get_bot_msg(cnsl_id: int, member_id: str) -> Optional[dict]:
    if not DATABASE_URL:
        return None
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT ai_id, cnsl_id, member_id, msg_data, summary, created_at, updated_at
                   FROM ai_msg WHERE cnsl_id = %s AND member_id = %s LIMIT 1""",
                (cnsl_id, member_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def upsert_bot_msg(cnsl_id: int, member_id: str, msg_data: dict, summary: Optional[str] = None) -> dict:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    content_list = (msg_data or {}).get("content") or []
    msg_data_json = json.dumps({"content": content_list}, ensure_ascii=False)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO ai_msg (cnsl_id, member_id, msg_data, summary, created_at, updated_at)
                   VALUES (%s, %s, %s::jsonb, %s, %s::timestamp, %s::timestamp)
                   ON CONFLICT (cnsl_id, member_id)
                   DO UPDATE SET msg_data = EXCLUDED.msg_data,
                       summary = COALESCE(EXCLUDED.summary, ai_msg.summary), updated_at = EXCLUDED.updated_at
                   RETURNING ai_id, cnsl_id, member_id, msg_data, summary, created_at, updated_at""",
                (cnsl_id, member_id, msg_data_json, summary or None, now, now),
            )
            row = cur.fetchone()
    if not row:
        raise RuntimeError("upsert_bot_msg failed")
    return dict(row)


def append_message(cnsl_id: int, member_id: str, speaker: str, text: str) -> dict:
    existing = get_bot_msg(cnsl_id, member_id)
    msg_data = (existing or {}).get("msg_data") if existing else None

    if isinstance(msg_data, dict):
        content = msg_data.get("content") or []
    else:
        content = []

    # content가 문자열이거나 리스트가 아니면 초기화
    if isinstance(content, str) or not isinstance(content, list):
        content = []

    content.append(
        {
            "speaker": speaker,
            "text": text,
            "type": "chat",
            "timestamp": int(time.time() * 1000),
        }
    )
    return upsert_bot_msg(cnsl_id, member_id, {"content": content})


def update_summary(cnsl_id: int, member_id: str, summary: str) -> Optional[dict]:
    """ai_msg.summary 컬럼만 업데이트. msg_data는 건드리지 않음."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """UPDATE ai_msg SET summary = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE cnsl_id = %s AND member_id = %s
                   RETURNING ai_id, cnsl_id, member_id, msg_data, summary, created_at, updated_at""",
                (summary, cnsl_id, member_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None
