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

# --- 프롬프트 생성 함수 ---
def create_system_prompt(scenario, all_characters): # ✅ character -> all_characters로 변경
    """싱글플레이 게임에 맞는 시스템 프롬프트를 생성합니다."""
    
    # ✅ [수정] 모든 캐릭터의 정보를 프롬프트에 포함시킵니다.
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

    ## 게임 배경
    - 시나리오: {scenario.title} ({scenario.description})
    - ✅ 등장하는 모든 캐릭터 정보:
    {char_descriptions}

    ## 출력 JSON 스키마 (필수 준수)
    - ✅ `roleMap`에는 반드시 '등장하는 모든 캐릭터'의 이름과 역할 ID가 포함되어야 합니다.
    - ✅ `round.choices`에는 `roleMap`에 정의된 '모든 역할 ID'에 대한 선택지가 포함되어야 합니다.
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
    
async def ask_llm_for_narration(history, scene_title, all_player_results, usage_text=""):
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

    # ✅ [수정] 시스템 프롬프트에 Shari 데이터 생성 규칙을 추가합니다.
    system_prompt = """
    당신은 TRPG 게임의 흥미진진한 스토리를 만드는 전문 작가이자, 게임의 상태를 구조적으로 관리하는 GM입니다.
    주어진 캐릭터들의 행동 결과를 바탕으로, 아래 JSON 형식에 맞춰 'narration'과 'shari' 데이터를 모두 생성해야 합니다.
    - narration: 소설처럼 자연스러운 서사. 3~4 문장으로 요약.
    - shari: 게임 상태의 구조적 변화. 규칙에 따라 정확히 작성.
    - 스킬/아이템 사용이 있다면 그 효과를 narration과 shari.update에 모두 반영해야 합니다.
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
            response_format={"type": "json_object"}, # JSON 모드 강제
        )
        response_text = completion.choices[0].message.content.strip()
        response_json = json.loads(_extract_json_block(response_text))
        
        # ✅ 반환값에 shari 블록을 추가합니다.
        return response_json.get("narration", "이야기를 생성하지 못했습니다."), response_json.get("shari", {})
    except Exception as e:
        print(f"❌ 서사/Shari 생성 중 LLM 오류: {e}")
        return "예상치 못한 정적이 흘렀다.", {}

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
