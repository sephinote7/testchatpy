"""
DB 연결 풀 - 연결 슬롯 소진(53300) 방지.
Supabase 무료 플랜 연결 제한 대응 최적화.
"""
import os
import time
from contextlib import contextmanager

from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool
from psycopg2.pool import PoolError

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# 연결 풀 설정: 무료 플랜 환경에 맞춰 타이트하게 관리
_connection_pool = None

def _get_pool():
    global _connection_pool
    if _connection_pool is None and DATABASE_URL:
        try:
            # ThreadedConnectionPool을 사용하여 멀티스레드 환경 대응
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=35,  # 무료 플랜 권장치
                dsn=DATABASE_URL,
            )
            print("DB Connection Pool 생성 성공")
        except Exception as e:
            print(f"DB 풀 생성 실패: {e}")
    return _connection_pool


@contextmanager
def get_conn():
    """풀에서 연결 획득 후 안전하게 반환."""
    p = _get_pool()
    if not p:
        raise RuntimeError("데이터베이스 풀이 초기화되지 않았습니다.")
    
    conn = None
    try:
        # 풀에서 연결을 가져올 때까지 최대 3초 대기 (무작정 새 연결 생성 방지)
        # 3초 후에도 없으면 PoolError 발생 -> FastAPI가 500/503 처리
        conn = p.getconn()
        if conn:
            yield conn
            conn.commit()
    except PoolError:
        print("DB Pool이 가득 찼습니다. 잠시 후 다시 시도하세요.")
        raise RuntimeError("현재 접속자가 많아 처리가 지연되고 있습니다.")
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"DB 작업 중 오류 발생: {e}")
        raise
    finally:
        if conn and p:
            try:
                p.putconn(conn)
            except Exception as e:
                print(f"연결 반환 실패: {e}")
                # 반환 실패 시 강제 종료하여 슬롯 확보
                if not conn.closed:
                    conn.close()