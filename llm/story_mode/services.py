from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import re
import json

# --- 1. 설정 및 데이터 로드 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, '.env'))
API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
API_VERSION = os.getenv("AZURE_OPENAI_VERSION")
if not all([API_KEY, ENDPOINT, DEPLOYMENT, API_VERSION]):
    raise ValueError("Azure OpenAI 환경 변수가 .env 파일에 설정되지 않았습니다.")

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VERSION)
stories_dir = os.path.join(BASE_DIR, 'llm', 'stories', 'json')
stories = {}
if os.path.exists(stories_dir):
    for file in os.listdir(stories_dir):
        if file.endswith(".json"):
            with open(os.path.join(stories_dir, file), "r", encoding="utf-8") as f:
                story = json.load(f)
                stories[story["id"]] = story


# --- 2. AI 네비게이터 프롬프트 (★★★ 최종 업그레이드 버전!) ★★★ ---
def create_story_prompt(story, player_action, current_moment_description, choice_instructions, is_ending_scene):
    
    # 마지막 장면인지 아닌지에 따라 '선택지 생성' 임무와 '응답 형식'이 달라집니다.
    if is_ending_scene:
        mission_part = """
2.  **이야기 마무리:** 이 장면은 이야기의 끝입니다. 아이가 동화 속에서 얻은 교훈이나 감동을 느낄 수 있도록, 3~4 문장으로 아름답게 이야기를 마무리해주세요. **선택지는 절대로 만들지 마세요.**
"""
        response_format_part = """
[응답 형식]
반드시 다음 JSON 형식으로만 응답해야 합니다. **choices는 빈 배열([])**이어야 합니다.
{{
"scene_text": "AI가 '장면 생성'과 '이야기 마무리' 임무에 따라 창작한 감동적인 이야기 내용.",
"choices": []
}}
"""
    else:
        mission_part = f"""
2.  **선택지 생성:** 위에서 만든 장면에 이어서, 아이에게 직접 말을 거는 듯한 질문 형식으로 3개의 선택지를 제시하세요.
    *   **선택지 형식:** "해식이는 이제 어떻게 할까?", "어떤 말을 해줄까?" 와 같은 질문 형식.
    *   **선택지 내용:** 아래 '선택지 생성 가이드'의 목표를 달성하는 구체적인 행동이어야 합니다.
    *   **선택지 생성 가이드:** {choice_instructions}
"""
        response_format_part = """
[응답 형식]
반드시 다음 JSON 형식으로만 응답해야 합니다:
{{
"scene_text": "AI가 '장면 생성' 임무에 따라 창작한 이야기 내용.",
"choices": ["'선택지 생성' 임무에 따라 만든 첫 번째 선택지", "두 번째 선택지", "세 번째 선택지"]
}}
"""

    # 최종 프롬프트 템플릿
    template = f"""
당신은 아이들에게 동화를 들려주는 다정한 '이야기 요정'입니다. 당신의 임무는 아이의 선택을 반영하여 이야기를 만들면서도, 정해진 핵심 줄거리대로 이야기가 흘러가도록 자연스럽게 유도하는 것입니다.

[이야기 요정의 규칙]
*   항상 다정한 말투를 사용하고, 아이의 눈높이에 맞춰 설명합니다.
*   '살랑살랑', '쿵쾅쿵쾅' 같은 의성어, 의태어를 사용하여 생동감 넘치는 장면을 만듭니다.
*   장면을 묘사할 때는 아이가 무엇을 보고, 듣고, 느끼는지에 집중합니다.

[현재 상황]
*   현재 동화: {story.get('world', '신비한 동화 세상')}
*   아이의 행동: {player_action}

[당신의 임무]
1.  **장면 생성:** 아래 '이번 장면의 핵심 목표'를 달성하는 다음 장면을 3~4개의 문장으로 흥미롭게 묘사하세요.
    *   이번 장면의 핵심 목표: {current_moment_description}
{mission_part}
{response_format_part}
"""
    return template


# --- 3. AI 응답 파싱 ---
def parse_ai_response(llm_output):
    if not llm_output:
        print("파싱 오류: AI로부터 받은 내용이 비어있습니다(None).")
        return {"scene_text": "(AI로부터 응답을 받지 못했습니다. Azure 콘텐츠 필터 문제일 수 있습니다.)", "choices": []}
    
    try:
        # 1. 마크다운(` ```json `)이나 공백을 먼저 제거합니다.
        cleaned = re.sub(r"```json|```", "", llm_output).strip()
        
        # 2. ★★★ AI가 실수로 {{ }} 를 사용했는지 확인하고, 맞다면 한겹 벗겨내줍니다! ★★★
        if cleaned.startswith("{{") and cleaned.endswith("}}"):
            cleaned = cleaned[1:-1] # 문자열의 첫 글자와 마지막 글자를 잘라냅니다.
            
        # 3. 이제 안전하게 JSON으로 변환합니다.
        data = json.loads(cleaned)
        
        # 4. choices가 없는 엔딩 장면을 위해, .get()으로 안전하게 값을 가져옵니다.
        return {"scene_text": data.get("scene_text"), "choices": data.get("choices", [])}
    
    except Exception as e:
        # 이 코드는 이제 거의 실행될 일이 없을 겁니다!
        print(f"JSON 파싱 실패: {e}\n원본 출력: {llm_output}")
        return {"scene_text": f"(AI 응답 오류: {llm_output})", "choices": []}


# --- 4. 외부에서 호출할 유일한 '싱글플레이 대표 함수' ---
def generate_single_play_step(story_id: str, current_moment_id: str, choice_index: int = None) -> dict:
    story = stories.get(story_id)
    if not story: raise ValueError(f"'{story_id}' 스토리를 찾을 수 없습니다.")
    all_moments = story.get("moments", {})
    moment_to_process = all_moments.get(current_moment_id)
    if not moment_to_process: raise ValueError(f"'{current_moment_id}' 장면을 찾을 수 없습니다.")

    next_moment_id = current_moment_id
    if choice_index is not None and "choices" in moment_to_process:
        choices_map = moment_to_process["choices"]
        if 0 <= choice_index < len(choices_map):
            next_moment_id = choices_map[choice_index].get("next_moment_id", current_moment_id)

    moment_for_ai = all_moments.get(next_moment_id)
    if not moment_for_ai: raise ValueError(f"다음 장면 '{next_moment_id}'을 찾을 수 없습니다.")
    
    current_moment_description = moment_for_ai.get("description", "")
    
    is_ending = "choices" not in moment_for_ai

    choice_instructions = ""
    if not is_ending:
        choice_instructions += "다음 선택지들은 아래 목표들로 이어지도록 만들어줘:\n"
        for i, choice_info in enumerate(moment_for_ai["choices"]):
            target_moment_id = choice_info.get("next_moment_id")
            target_moment_desc = all_moments.get(target_moment_id, {}).get("description", "")
            action_type = choice_info.get("action_type", "보통")
            choice_instructions += f"- 선택지 {i+1}: ({action_type} 결과) {target_moment_desc}\n"
    else:
        choice_instructions = "이야기의 끝입니다. 선택지가 필요 없습니다."

    player_action_text = "이제 이야기가 시작되었어." if choice_index is None else f"플레이어가 {choice_index + 1}번째 선택지를 골랐어."
    prompt = create_story_prompt(story, player_action_text, current_moment_description, choice_instructions, is_ending)

    resp = client.chat.completions.create(model=DEPLOYMENT, messages=[{"role": "user", "content": prompt}], temperature=0.7)
    parsed_data = parse_ai_response(resp.choices[0].message.content)
    
    final_response = {
        "scene": parsed_data.get("scene_text"),
        "choices": parsed_data.get("choices"),
        "story_id": story_id,
        "current_moment_id": next_moment_id
    }
    return final_response