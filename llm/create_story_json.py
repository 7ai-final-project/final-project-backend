# --- 필요한 도구들 불러오기 ---
import os
import json
import sys
from openai import AzureOpenAI
from dotenv import load_dotenv

# --- 1. 기본 설정 (API 키 준비) ---
# 이 코드 파일이 있는 곳을 기준으로, 상위 폴더(프로젝트 폴더)에 있는 .env 파일을 찾습니다.
# 만약 .env 파일 위치가 다르다면 이 경로를 수정해야 합니다.
try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(BASE_DIR, '..', '.env'))
except Exception as e:
    print(f".env 파일을 로드하는 데 실패했습니다. 위치를 확인해주세요. 오류: {e}")
    exit() # .env 파일이 없으면 실행을 멈춥니다.

# .env 파일에서 API 키 정보를 읽어와서 Azure OpenAI에 연결 준비를 합니다.
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_VERSION")
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# 텍스트 파일을 읽어올 폴더와 JSON 파일을 저장할 폴더의 경로를 지정합니다.
TXT_INPUT_DIR = os.path.join('llm', 'stories', 'txt')
JSON_OUTPUT_DIR = os.path.join('llm', 'stories', 'json')

# --- 2. AI에게 내리는 명령서 (프롬프트 템플릿) ---
# 이 부분이 가장 중요합니다! AI가 어떤 일을 해야 할지 아주 자세하게 적어줍니다.
PROMPT_TEMPLATE = """
당신은 주어진 이야기를 분석해서, 플레이어가 선택하며 즐길 수 있는 '인터랙티브 게임'의 데이터로 바꿔주는 전문 게임 작가입니다.

[당신의 임무]
아래 [입력 스토리]를 읽고, 이야기의 흐름에 따라 4~5개의 중요한 장면(Moment)으로 나누어 게임 시나리오를 만드세요.

[작업 규칙]
1.  **장면 나누기:** 이야기의 시작, 위기, 절정, 결말 등을 고려하여 장면을 나누고, 각 장면에 고유한 영어 ID(예: MOMENT_START)를 붙여주세요.
2.  **구조화:** 각 장면은 'description' 키에 설명을 담아야 합니다.
3.  **선택지 구조:** 각 장면의 'choices'는 객체(Object)들의 배열(Array)이어야 합니다. 각 객체는 'action_type'과 다음 장면을 가리키는 'next_moment_id' 키를 반드시 포함해야 합니다.
4.  **엔딩 처리:** 이야기의 끝을 맺는 장면(엔딩)에는 'choices' 키 자체를 포함하지 마세요.
5.  **JSON 형식 준수:** 최종 결과는 반드시 아래 [출력 JSON 형식]과 똑같은 구조의 JSON 데이터로만 출력해야 합니다. 다른 말은 절대 덧붙이지 마세요.

[입력 스토리]
---
{story_text}
---

[출력 JSON 형식]
{{
  "id": "이야기의_한글_ID",
  "world": "이야기의 전체적인 배경이나 주제 (한 문장으로 요약)",
  "start_moment_id": "MOMENT_START",
  "moments": {{
    "MOMENT_START": {{
      "description": "첫 번째 장면에 대한 핵심 목표 설명. (예: 주인공이 모험을 떠나게 되는 계기)",
      "choices": [
        {{ "action_type": "NEUTRAL", "next_moment_id": "MOMENT_CONFLICT" }}
      ]
    }},
    "MOMENT_CONFLICT": {{
      "description": "두 번째 장면에 대한 핵심 목표 설명. (예: 주인공이 첫 번째 시련이나 갈등에 부딪힘)",
      "choices": [
        {{ "action_type": "GOOD", "next_moment_id": "MOMENT_CLIMAX" }},
        {{ "action_type": "BAD", "next_moment_id": "ENDING_A" }}
      ]
    }},
    "ENDING_A": {{
      "description": "[배드 엔딩] 비극적인 결말에 대한 핵심 목표 설명."
    }}
  }}
}}
"""

def convert_story_to_json(story_text: str):
    """AI를 호출해서, 텍스트를 게임 JSON으로 변환하는 함수"""

    # 1. 명령서(프롬프트)에 실제 이야기 텍스트를 채워넣어 최종 명령서를 완성합니다.
    final_prompt = PROMPT_TEMPLATE.format(story_text=story_text)

    print("AI에게 이야기 분석을 요청하고 있습니다... (시간이 조금 걸릴 수 있어요)")
    try:
        # 2. Azure OpenAI API에 요청을 보냅니다.
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.5, # 너무 제멋대로 만들지 않도록 온도를 약간 낮춥니다.
            response_format={"type": "json_object"} # "결과는 무조건 JSON 형식으로 줘!" 라는 강력한 옵션입니다.
        )
        # 3. AI의 응답 내용(JSON 텍스트)을 가져옵니다.
        ai_response_content = response.choices[0].message.content
        print("AI가 응답을 완료했습니다!")

        # 4. JSON 텍스트를 파이썬이 다룰 수 있는 데이터(딕셔너리)로 변환합니다.
        story_json = json.loads(ai_response_content)
        return story_json

    except Exception as e:
        print(f"죄송합니다. AI를 호출하는 중에 오류가 발생했습니다: {e}")
        return None

# --- 3. 실제 프로그램 실행 부분 ---
# 이 파일(create_story_json.py)을 직접 실행했을 때만 아래 코드가 동작합니다.
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("🛑 오류: 변환할 txt 파일 이름을 입력해주세요.")
        print("   사용법: python llm/create_story_json.py [변환할_파일이름.txt]")
        exit()
    
    input_filename = sys.argv[1]
    input_filepath = os.path.join(TXT_INPUT_DIR, input_filename)
    
    try:
        print(f"📖 '{input_filepath}' 파일을 읽습니다...")
        with open(input_filepath, "r", encoding="utf-8") as f:
            my_story_text = f.read()
    except FileNotFoundError:
        print(f"🛑 오류: '{input_filepath}' 파일을 찾을 수 없습니다.")
        print("   파일 이름이 정확한지, 파일이 'backend/llm/stories/txt' 폴더 안에 있는지 확인해주세요.")
        exit()

    converted_game_data = convert_story_to_json(my_story_text)

    if converted_game_data:
        os.makedirs(JSON_OUTPUT_DIR, exist_ok=True)
        file_id = converted_game_data.get("id", input_filename.replace('.txt', ''))
        output_filename = f"{file_id}.json"
        output_filepath = os.path.join(JSON_OUTPUT_DIR, output_filename)
        print("\n🎉 === 변환 성공! 생성된 JSON 데이터 === 🎉")
        print(json.dumps(converted_game_data, indent=2, ensure_ascii=False))
        with open(output_filepath, "w", encoding="utf-8") as f:
            json.dump(converted_game_data, f, indent=2, ensure_ascii=False)
        print(f"\n✅ 성공! 결과가 '{output_filepath}' 경로에 저장되었습니다.")