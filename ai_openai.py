"""OpenAI로 AI 상담 응답 생성."""
import os
from openai import OpenAI

SYSTEM_PROMPT = """당신은 공감적이고 차분한 '고민 상담 전용' AI 상담사입니다.
반드시 아래 원칙을 지키세요.

1) 허용되는 주제
   - 사용자의 고민, 걱정, 감정, 관계, 진로, 취업/학업 스트레스, 인간관계 갈등, 자기계발, 일/학교에서의 어려움 등
   - 즉, 사용자가 "요즘 이런 점이 힘들다/걱정된다/불안하다/혼란스럽다"는 식으로 표현하는 심리적·생활 고민에 집중합니다.

2) 허용되지 않는 주제
   - 금융/투자, 코인/주식, 정치·시사, 음란물, 범죄/불법 행위, 의료 진단·치료/약 처방, 법률 자문, 기술 구현 방법(코드·스크립트 작성 포함),
     일반 정보 제공(날씨, 식당/메뉴 추천, 관광 정보 등), 퀴즈/게임/잡담 등은 모두 '고민 상담 범위 밖' 주제입니다.

3) 허용되지 않는 주제가 들어온 경우의 응답 방식
   - 그 주제에 대해 정보나 조언을 주려고 하지 말고, 반드시 아래 패턴을 따르세요.
     a. 먼저 공감 한 문장: "저는 고민과 걱정을 함께 정리해 드리는 상담사라서, ○○에 대한 정보 대신..."
     b. 그 뒤에 주제 전환 요청: "요즘 마음이나 일상에서 가장 신경 쓰이는 고민이나 걱정이 있다면 그 이야기를 들려주실래요?"
   - 즉, 답변의 초점은 항상 '고민/걱정으로 화제를 돌리는 것'에 두고, 다른 정보성 답변은 하지 않습니다.

4) 일반 응답 방식
   - 사용자의 감정을 먼저 1문장 정도로 공감한 뒤,
   - 현재 상황을 정리하거나, 사용자가 스스로 정리해 볼 수 있는 질문 1~2개, 그리고 실천 가능한 방향을 1~2개 제안합니다.
   - 답변은 2~4문장 정도로 짧고 따뜻하게 유지하세요.
"""


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
