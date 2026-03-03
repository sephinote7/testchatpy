import os
import json
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI

# ---------- OpenAI 클라이언트 설정 ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY 환경 변수가 없습니다. Render 환경변수에 설정해 주세요.")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- APIRouter ----------
router = APIRouter(prefix="/api", tags=["site-chat"])


# ---------- 요청/응답 모델 ----------

class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SiteChatRequest(BaseModel):
    message: str
    history: List[HistoryItem] = []
    siteContext: List[str] = []
    source: Optional[str] = None  # 예: "gominsunsak-web"


class SiteChatResponse(BaseModel):
    answer: str
    summary: Optional[str] = None


# ---------- 고민순삭 홈페이지 전용 챗봇 엔드포인트 ----------

@router.post("/site-chat", response_model=SiteChatResponse)
async def site_chat(req: SiteChatRequest):
    """
    고민순삭 홈페이지 전용 챗봇 API.
    - Front: FloatingChatbot.jsx 에서 POST로 호출.
    - 입력: message, history[], siteContext[]
    - 출력: { answer, summary }
    """

    user_message = (req.message or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is empty")

    # 1) 시스템 프롬프트 + 사이트 컨텍스트
    system_text = (
        "너는 '고민순삭 어시스턴트 순삭이'야. "
        "오직 고민순삭 홈페이지와 직접적으로 관련된 질문(메뉴 위치, 이용 방법, 기능 설명 등)에만 답해야 해. "
        "법률, 의료, 금융, 정치, 건강, 회사 내부 정책처럼 사이트와 직접 관련 없는 주제는 "
        "정중하게 답변을 거절하고, 고객센터나 공식 안내를 확인하라고 안내해. "
        "답변에서는 괄호 안에 (/chat/withai) 같은 기술적인 경로나 URL을 넣지 말고, "
        "'AI 상담 메뉴', '상담사 찾기 메뉴', '상단 회원가입 버튼'처럼 사용자가 이해하기 쉬운 메뉴 이름만 사용해."
    )
    context_text = "\n".join(req.siteContext or [])

    messages = [{"role": "system", "content": system_text}]
    if context_text:
        messages.append(
            {
                "role": "system",
                "content": f"[사이트 컨텍스트]\n{context_text}",
            }
        )

    # 2) 기존 대화 히스토리 반영
    for h in req.history:
        messages.append(
            {
                "role": "user" if h.role == "user" else "assistant",
                "content": h.content,
            }
        )

    # 3) 이번 질문 + JSON 응답 강제
    prompt_for_json = (
        "다음은 사용자가 방금 입력한 질문이야. "
        "먼저 한국어로 친절하게 답변해 주고, "
        "그 뒤에 이 대화를 한 줄로 요약해 줘. "
        "반드시 JSON으로만 응답해. "
        '형식: {\"answer\": \"<답변>\", \"summary\": \"<요약>\"}\n\n'
        f"[질문]\n{user_message}"
    )

    messages.append({"role": "user", "content": prompt_for_json})

    # 4) OpenAI 호출
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",  # 필요 시 모델 변경 가능
            messages=messages,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI 호출 실패: {e}") from e

    content = completion.choices[0].message.content

    # 5) JSON 파싱
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # 혹시 JSON 형식을 안 지켜도, 답변은 보여주기
        return SiteChatResponse(answer=content, summary=None)

    answer = (parsed.get("answer") or "").strip()
    summary = parsed.get("summary")

    if not answer:
        answer = "죄송합니다. 지금은 정확한 답변을 드리기 어렵습니다. 잠시 후 다시 시도해 주세요."

    return SiteChatResponse(answer=answer, summary=summary)