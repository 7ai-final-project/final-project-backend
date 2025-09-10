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
# ★★ 최종 업그레이드 버전! ★★
PROMPT_TEMPLATE = """
당신은 주어진 평면적인 이야기를 분석해서, 플레이어의 선택에 따라 이야기가 달라지는 '가지가 나뉘는 인터랙티브 게임(branching narrative)'의 데이터로 '재창조'하는 전문 게임 시나리오 작가입니다.

[당신의 임무]
아래 [입력 스토리]를 기반으로, 플레이어에게 흥미로운 선택의 순간을 제공하는 게임 시나리오용 JSON을 만드세요.

[작업 규칙]
1.  **ID 생성:**
    *   `id` 키에는 이야기의 제목을 바탕으로 한 **'한글 ID'**를 만들어주세요. (예: "의좋은 형제")
    *   `id_eng` 키에는 한글 ID를 영어로 번역하고, 띄어쓰기를 하이픈(-)으로 연결한 **'영문 ID'**를 만들어주세요. (예: "good-brothers")

2.  **장면 나누기:** 이야기의 전통적인 구조(기승전결)를 참고하여 4~5개의 핵심 장면(Moment)으로 나누고, 각 장면에 고유한 영어 ID(예: MOMENT_START)를 붙여주세요.

3.  **분기 생성:** 플레이어의 선택이 의미 있도록, 원작에 없더라도 선택의 결과로 이어질 '새로운 장면'이나 '짧은 엔딩'(좋은/나쁜/재미있는 엔딩 등)을 1~2개 이상 창의적으로 만들어내야 합니다. 단, 모든 새로운 분기는 원작의 핵심 교훈을 강화하거나, 등장인물의 성격을 더 깊이 탐구하는 방향으로 만들어져야 합니다.

4.  **장면 묘사 원칙 (클리프행어):** 선택지가 있는 장면(엔딩이 아닌 장면)의 'description'은, 반드시 플레이어가 선택을 내리기 직전의 긴장감 넘치는 상황까지만 묘사해야 합니다. 선택의 결과를 미리 암시하거나 결론을 내리면 절대 안 됩니다.
    *   (예시): "주인공은 동굴 깊은 곳에서 거대한 무언가가 천천히 눈을 뜨는 것을 보았다." 처럼, "그래서 어떻게 됐을까?" 하고 궁금해하는 순간에 묘사를 멈춰야 합니다.

5.  **논리적 일관성 검증 (인과관계):** 선택지는 '원인(Cause)', 이어지는 장면의 내용은 '결과(Effect)'입니다. 이 둘은 반드시 명확하고 설득력 있는 인과관계로 이어져야 합니다. '친구를 구하러 간다'는 선택지가 '혼자 보물을 발견하는' 장면으로 이어지는 것처럼, 논리적으로 말이 안 되는 연결은 절대 만들면 안 됩니다.

6.  **완벽한 기술적 연결:** 각 'choices' 배열 안의 모든 선택지는, 반드시 'next_moment_id' 키를 통해 이 JSON 파일 내에 실제로 '정의된' 다른 장면 ID로 연결되어야 합니다. 이것은 매우 중요한 기술적 규칙입니다.

7.  **엔딩 처리:** 이야기의 끝을 맺는 장면(엔딩)에는 'choices' 키 자체를 포함하지 마세요. 엔딩의 'description'은 최종적인 결과와 이야기가 주는 교훈을 요약해야 합니다.

8.  **JSON 형식 준수:** 최종 결과는 반드시 아래 [출력 JSON 형식]과 똑같은 구조의 JSON 데이터로만 출력해야 합니다. 설명이나 다른 말을 절대 덧붙이지 마세요.

[입력 스토리]
---
{story_text}
---

[출력 JSON 형식]
{{
  "id": "이야기의_한글_ID",
  "id_eng": "이야기의_영어_ID",
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
        {{ "action_type": "BAD", "next_moment_id": "ENDING_BAD_A" }}
      ]
    }},
    "MOMENT_CLIMAX": {{
        "description": "이야기의 절정. 주인공이 중요한 결정을 내림.",
        "choices": [
            {{ "action_type": "GOOD", "next_moment_id": "ENDING_GOOD" }},
            {{ "action_type": "NEUTRAL", "next_moment_id": "ENDING_BAD_A" }}
        ]
    }},
    "ENDING_GOOD": {{
      "description": "[해피 엔딩] 원작의 교훈을 따랐을 때의 긍정적인 결말."
    }},
    "ENDING_BAD_A": {{
      "description": "[배드 엔딩] 다른 선택을 했을 때 이어지는 비극적인 결말."
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