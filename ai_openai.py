"""OpenAI로 AI 상담 응답 생성."""
import os
from openai import OpenAI

SYSTEM_PROMPT = """당신은 공감적이고 차분한 고민 상담 AI 상담사입니다.
대화 주제는 사용자의 고민, 걱정, 감정, 관계, 진로, 일/학업 스트레스 등 심리적·생활 고민에 한정됩니다.
금융/투자, 정치·시사, 음란물, 불법 행위, 의료 진단·치료, 의학적 처방, 기술 구현 방법(코드 작성 포함) 등
고민 상담 범위를 벗어나는 주제가 나오면 정중하게 답변을 거절하고,
\"오늘 가장 신경 쓰이는 고민이나 걱정\"으로 자연스럽게 화제를 다시 돌리도록 유도하세요.
사용자의 감정을 먼저 공감한 뒤, 구체적이고 실천 가능한 한두 가지 방향을 제안하세요.
답변은 2~4문장 정도로 짧고 따뜻하게 유지하세요."""


def get_ai_reply(user_text: str, history: list) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "죄송합니다. AI 상담이 일시적으로 이용 불가합니다."
    client = OpenAI(api_key=api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-20:]:
        role = "user" if h.get("speaker") == "user" else "assistant"
        messages.append({"role": role, "content": (h.get("text") or "").strip()})
    messages.append({"role": "user", "content": user_text})
    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            max_tokens=500,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"응답 생성 중 오류가 발생했습니다. ({getattr(e, 'message', str(e))})"
