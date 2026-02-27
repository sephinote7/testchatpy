"""
DB 연결 풀 - 연결 슬롯 소진(53300) 방지.
Supabase 무료 플랜 연결 제한 대응.
"""
import os
from contextlib import contextmanager

from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool
from psycopg2.pool import PoolError

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# 연결 풀: min 1, max 5 (동시 요청 제한으로 슬롯 절약)
_connection_pool = None


def _get_pool():
    global _connection_pool
    if _connection_pool is None and DATABASE_URL:
        try:
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=DATABASE_URL,
            )
        except Exception as e:
            print(f"DB 풀 생성 실패: {e}")
    return _connection_pool


@contextmanager
def get_conn():
    """풀에서 연결 획득 후 반환. 연결 소진 시 fallback으로 직접 연결."""
    p = _get_pool()
    conn = None
    from_pool = False
    try:
        if p:
            try:
                conn = p.getconn()
                from_pool = True
            except PoolError:
                conn = psycopg2.connect(DATABASE_URL) if DATABASE_URL else None
        else:
            conn = psycopg2.connect(DATABASE_URL) if DATABASE_URL else None
        if conn:
            yield conn
            conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            if from_pool and p:
                try:
                    p.putconn(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            else:
                try:
                    conn.close()
                except Exception:
                    pass
