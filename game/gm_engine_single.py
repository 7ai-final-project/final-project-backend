# backend/game/multi_mode/gm_engine_single.py (이 파일의 전체 내용을 교체)

import json
import re
from openai import AsyncAzureOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

# --- 유틸리티 함수 ---
def _extract_json_block(text: str) -> str:
    """LLM 응답에서 JSON 코드 블록을 추출합니다."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if match:
        return match.group(1)
    match = re.search(r"(\{.*\})", text, re.S)
    if match:
        return match.group(1)
    return text

### ▼▼▼▼▼ gm_engine.py에서 가져온 헬퍼 함수 추가 ▼▼▼▼▼
def _get_difficulty_instructions(difficulty: str) -> str:
    if difficulty == "상급":
        return "플레이어가 마주하는 역경의 빈도와 강도를 높여라. 성공을 위해서는 자원을 소모하거나 창의적인 해결책이 필요하도록 상황을 묘사하라. 실패 시 명확한 불이익을 부여하라."
    if difficulty == "초급":
        return "플레이어의 행동을 긍정적으로 해석하고, 대부분의 행동이 큰 어려움 없이 성공하도록 서술하라. 역경은 최소화하라."
    # 기본값은 '중급'
    return "성공과 실패가 균형을 이루도록 하라. 논리적인 행동은 보상받아야 하지만, 가끔 예상치 못한 어려움도 발생할 수 있다."

def _get_pacing_instructions(current_turn: int, max_turns: int) -> str:
    if current_turn < max_turns * 0.75: # 게임의 75%가 지나기 전
        return f"현재 {current_turn + 1}턴이다. 이야기의 절정(클라이맥스)을 향해 서서히 긴장감을 고조시켜라."
    elif current_turn >= max_turns - 1: # 4번째 턴(index=3)에 종료되도록 조건 수정
        # 아래와 같이 "is_final_turn" 키를 포함하도록 명시합니다.
        return f"현재 {current_turn + 1}턴으로, 마지막 턴이다. 반드시 이야기의 모든 갈등을 마무리하고 최종 결말을 제시하라. 응답 JSON 최상단에 `\"is_final_turn\": true` 키를 반드시 포함시켜라."
    else: # 게임 후반부
        return f"현재 {current_turn + 1}턴이다. 이제 이야기의 절정(클라이맥스) 또는 결말을 향해 빠르게 전개하라. 곧 엔딩이 가까워졌음을 암시하라."


# --- 프롬프트 생성 함수 ---
def create_system_prompt(scenario, all_characters, current_turn: int, difficulty: str):
    """싱글플레이 게임에 맞는 시스템 프롬프트를 생성합니다."""
    
    max_turns = 4
    difficulty_instructions = _get_difficulty_instructions(difficulty)
    pacing_instructions = _get_pacing_instructions(current_turn, max_turns)
    
    char_descriptions = "\n".join(
        [f"- **{c['name']}** ({c['description']})\n  - 능력치: {c.get('stats', {})}" for c in all_characters]
    )
    
    json_schema = """
    {
      "id": "string (예: scene0)",
      "index": "number (정수, 예: 0)",
      "roleMap": {
        "캐릭터1 이름": "역할ID_1",
        "캐릭터2 이름": "역할ID_2"
      },
      "round": {
        "title": "string (현재 씬의 제목)",
        "description": "string (현재 상황에 대한 구체적인 묘사, 2~3 문장)",
        "choices": {
          "역할ID_1": [ { "id": "string", "text": "string", "appliedStat": "string", "modifier": "number" } ],
          "역할ID_2": [ { "id": "string", "text": "string", "appliedStat": "string", "modifier": "number" } ]
        }
      }
    }
    """
    prompt = f"""
    당신은 1인용 TRPG 게임의 시나리오를 실시간으로 생성하는 AI 게임 마스터입니다.
    당신의 임무는 사용자 행동에 따라 다음 게임 씬 데이터를 "반드시" 아래의 JSON 스키마에 맞춰 생성하는 것입니다.

    ## 게임 규칙
    - **난이도 규칙**: {difficulty_instructions}
    - **게임 진행 페이스**: 이 게임은 총 {max_turns}턴 내외로 진행된다. {pacing_instructions}

    ## 게임 배경
    - 시나리오: {scenario.title} ({scenario.description})
    - 등장하는 모든 캐릭터 정보:
    {char_descriptions}

    ## 출력 JSON 스키마 (필수 준수)
    - `roleMap`에는 반드시 '등장하는 모든 캐릭터'의 이름과 역할 ID가 포함되어야 합니다.
    - `round.choices`에는 `roleMap`에 정의된 '모든 역할 ID'에 대한 선택지가 포함되어야 합니다.
    - `appliedStat` 값은 반드시 '힘', '민첩', '지식', '의지', '매력', '운' 중 하나여야 합니다.

    ```json
    {json_schema}
    ```
    """
    return {"role": "system", "content": prompt}

# --- LLM 호출 함수 (변경 없음) ---
async def ask_llm_for_scene(history, user_message):
    """LLM을 호출하여 씬 JSON을 생성하고 대화 기록과 함께 반환합니다."""
    oai_client = AsyncAzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview"),
    )
    OAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    history.append({"role": "user", "content": user_message})
    try:
        completion = await oai_client.chat.completions.create(
            model=OAI_DEPLOYMENT,
            messages=history,
            max_tokens=4000,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        response_text = completion.choices[0].message.content
        scene_json = json.loads(_extract_json_block(response_text))
        
        history.append({"role": "assistant", "content": response_text})
        
        return scene_json, history
    except Exception as e:
        print(f"❌ 싱글플레이 LLM 응답 처리 중 오류: {e}")
        return None, history
    
async def ask_llm_for_narration(history, scene_title, all_player_results, current_turn: int, difficulty: str, usage_text=""):
    """모든 플레이어의 턴 결과를 바탕으로 통합된 서사와 Shari 데이터를 생성합니다."""
    oai_client = AsyncAzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview"),
    )
    OAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    results_summary = []
    grade_text_map = {"S": "성공", "F": "실패", "SP": "대성공", "SF": "치명적 실패"}
    for result in all_player_results:
        grade_text = grade_text_map.get(result.get('grade'), "판정")
        results_summary.append(
            f"- {result['characterName']}({result['characterId']})가 '{result.get('choiceText', '알 수 없는 행동')}'(을)를 시도: {grade_text}"
        )
    results_text = "\n".join(results_summary)

    max_turns = 4
    # ✅ [핵심 수정] LLM 응답에 의존하지 않고, 서버가 직접 마지막 턴인지 판단합니다.
    is_final_turn_on_server = (current_turn >= max_turns - 1)
    
    difficulty_instructions = _get_difficulty_instructions(difficulty)
    pacing_instructions = _get_pacing_instructions(current_turn, max_turns)
    
    system_prompt = f"""
    당신은 TRPG 게임의 감독(Director)이자 작가다. 당신의 임무는 주어진 정보를 바탕으로 게임의 결과를 서술하고, JSON 데이터를 정확히 생성하는 것이다.

    ### 너의 임무
    1. 주어진 캐릭터들의 행동 결과를 바탕으로, 소설처럼 자연스러운 서사(narration)를 3~4 문장으로 생성하라.
    2. 게임 상태의 구조적인 변화(shari)를 규칙에 따라 정확히 작성하라.
    3. 스킬/아이템 사용이 있다면 그 효과를 narration과 shari.update에 모두 반영해야 한다.
    4. **[매우 중요]** 아래 [게임 규칙]의 '게임 진행 페이스' 지시에 따라, 현재 턴이 마지막 턴이라고 판단되면, 반드시 응답 JSON 최상단에 `"is_final_turn": true` 키를 포함시켜라.

    ### 게임 규칙
    - **난이도 규칙**: {difficulty_instructions}
    - **게임 진행 페이스**: 이 게임은 총 {max_turns}턴 내외로 진행된다. {pacing_instructions}
    """
    
    user_prompt = f"""
    현재 상황: {scene_title}
    
    캐릭터들의 행동 결과:
    {results_text}

    추가 정보:
    {usage_text if usage_text else "이번 턴에 특별히 사용한 스킬이나 아이템은 없습니다."}

    ---
    위 정보를 바탕으로, 아래 JSON 형식에 맞춰 응답을 생성해주세요.
    
    ```json
    {{
      "narration": "여기에 자연스러운 서사를 작성...",
      "shari": {{
        "update": {{
          "characterHurt": {{ "캐릭터ID": true/false }},
          "currentLocation": "현재 위치 (변경 없으면 그대로)",
          "notes": "게임 월드의 주요 변화 요약",
          "inventory": {{
            "consumed": {{ "캐릭터ID": ["사용한 아이템 이름"] }},
            "added": {{}},
            "charges": {{}}
          }},
          "skills": {{
            "cooldown": {{ "캐릭터ID": {{ "사용한 스킬 이름": 2 }} }}
          }}
        }}
      }}
    }}
    ```
    """

    messages = [ {"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt} ]
    
    try:
        completion = await oai_client.chat.completions.create(
            model=OAI_DEPLOYMENT, messages=messages, max_tokens=2000, temperature=0.7,
            response_format={"type": "json_object"},
        )
        response_text = completion.choices[0].message.content.strip()
        response_json = json.loads(_extract_json_block(response_text))
        
        # ✅ [핵심 수정] LLM이 반환한 is_final_turn 값 대신, 서버가 직접 계산한 값을 사용합니다.
        return (
            response_json.get("narration", "이야기를 생성하지 못했습니다."),
            response_json.get("shari", {}),
            is_final_turn_on_server 
        )
    except Exception as e:
        print(f"❌ 서사/Shari 생성 중 LLM 오류: {e}")
        # ✅ [핵심 수정] 오류 발생 시에도 서버가 계산한 값을 반환합니다.
        return "예상치 못한 정적이 흘렀다.", {}, is_final_turn_on_server

async def ask_llm_for_summary(conversation_history):
    """대화 기록을 바탕으로 AI가 줄거리를 요약합니다."""
    oai_client = AsyncAzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview"),
    )
    OAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    # 요약할 스토리를 추출 (AI의 나레이션만 필터링)
    story_parts = [msg['content'] for msg in conversation_history if msg.get('role') == 'assistant']
    story_text = "\n".join(story_parts)

    if not story_text:
        return "아직 진행된 이야기가 없습니다."

    prompt = f"""
    다음은 지금까지 진행된 TRPG 게임의 스토리입니다. 이 전체 내용을 세 문장 이내의 흥미진진한 줄거리로 요약해주세요.

    ---
    {story_text}
    ---
    """
    
    messages = [
        {"role": "system", "content": "당신은 게임 스토리를 전문적으로 요약하는 작가입니다."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        completion = await oai_client.chat.completions.create(
            model=OAI_DEPLOYMENT,
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        summary = completion.choices[0].message.content.strip()
        return summary
    except Exception as e:
        print(f"❌ 줄거리 요약 중 LLM 오류: {e}")
        return "줄거리를 요약하는 데 실패했습니다."