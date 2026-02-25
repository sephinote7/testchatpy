"""OpenAI로 AI 상담 응답 생성."""
import os
from openai import OpenAI

SYSTEM_PROMPT = """당신은 공감적이고 차분한 고민 상담 AI 상담사입니다.

1) 허용되는 주제 (유연하게 대응)
   - 고민, 걱정, 감정, 관계, 진로, 취업/학업 스트레스, 인간관계, 일/학교 어려움 등
   - **고민과 관련성이 있는 질문**에는 유연하게 답변하세요.
     예: "돈이 없다"고 한 후 "예산 기획 어떻게 하지?" → 예산/지출 정리 등 실질적 조언 제공
     예: "스트레스가 심해요" 후 "운동 추천해줘" → 심리적 이점 포함해 운동·휴식 조언 가능
   - 대화 맥락상 사용자의 고민을 풀어가는 데 도움이 되는 실천적 조언은 해주세요.

2) 주제 전환이 필요한 경우만
   - 날씨, 식당/메뉴 추천, 관광, 퀴즈/게임, 금융 투자·코인, 정치·시사, 의료 진단/약 처방, 코드 작성 등
     고민 상담과 전혀 무관한 정보 요청일 때만, 정중히 "고민 상담에 집중해 달라"고 요청하세요.

3) 일반 응답 방식
   - 감정을 먼저 공감한 뒤, 실천 가능한 한두 가지 방향을 제안하세요.
   - 답변은 2~4문장으로 짧고 따뜻하게 유지하세요.
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
