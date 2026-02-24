"""OpenAI로 AI 상담 응답 생성."""
import os
from openai import OpenAI

SYSTEM_PROMPT = """당신은 공감적이고 차분한 AI 상담사입니다.
사용자의 고민을 경청하고, 감정을 정리하며, 구체적이고 실천 가능한 조언을 해주세요.
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
