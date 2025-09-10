import os
import sys

# 현재 스크립트 파일의 경로를 가져옵니다.
# C:\Users\USER\Desktop\git\final-project\backend\llm\multi_mode
current_dir = os.path.dirname(os.path.abspath(__file__))

# 'backend' 디렉토리의 경로를 계산합니다.
# 경로를 두 단계 위로 이동하면 'backend' 폴더에 도착합니다.
# 'multi_mode' -> 'llm' -> 'backend'
backend_dir = os.path.dirname(os.path.dirname(current_dir))

# 'backend' 디렉토리를 파이썬 모듈 검색 경로에 추가합니다.
# 이로써 파이썬이 'config'와 'game' 모듈을 찾을 수 있게 됩니다.
sys.path.insert(0, backend_dir)

# DJANGO_SETTINGS_MODULE 환경 변수를 설정합니다.
# 'backend'가 검색 경로에 있으므로 'config' 폴더를 바로 찾을 수 있습니다.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Django를 설정하여 모델을 로드합니다.
import django
django.setup()
from game.models import Scenario, Character as DjangoCharacter

import json
import re
import random
import hashlib
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from openai import AzureOpenAI

# .env 파일 로드
load_dotenv()

# ===== 캐릭터 데이터 클래스 (게임 스탯 중심) =====
@dataclass
class Character:
    id: str
    name: str
    role: str                  # 클래스/아키타입(탱커, 정찰자, 현자 등)
    stats: Dict[str, int]      # {"힘":7,"민첩":6,"지식":8,"의지":5,"매력":6,"운":4}
    skills: List[str]          # 특기/재능
    starting_items: List[str]  # 시작 아이템
    playstyle: str             # 플레이 스타일 가이드(행동 성향, 말투 등)

class TRPGGameMaster:
    def __init__(self):
        # 환경변수에서 설정값 로드
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview")

        # 게임 모드(프롬프트 톤): classic(일반 TRPG) | edu(독서교육형)
        self.trpg_mode = os.getenv("TRPG_MODE", "classic").lower()

        # AI 모델 파라미터
        self.max_tokens = int(os.getenv("MAX_TOKENS", "2000"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.7"))
        self.top_p = float(os.getenv("TOP_P", "0.95"))
        self.frequency_penalty = float(os.getenv("FREQUENCY_PENALTY", "0"))
        self.presence_penalty = float(os.getenv("PRESENCE_PENALTY", "0"))

        # 기본 파일 경로
        self.default_json_path = os.getenv("DEFAULT_JSON_PATH", "sun_moon_play_json.json")
        self.default_save_file = os.getenv("DEFAULT_SAVE_FILE", "game_log.json")

        # 히스토리 최대 길이(과도한 프롬프트 팽창 방지)
        self.max_history_messages = int(os.getenv("MAX_HISTORY_MESSAGES", "40"))

        # 필수 환경변수 체크
        if not all([self.endpoint, self.deployment, self.api_key]):
            raise ValueError("필수 환경변수가 설정되지 않았습니다. .env 파일을 확인해주세요.")

        self.client = AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version,
        )

        # 상태
        self.conversation_history: List[Dict[str, Any]] = []
        self.story_raw: Optional[str] = None      # 스토리 원문(JSON 문자열)
        self.story: Optional[dict] = None         # 파싱된 스토리
        self.game_initialized = False
        self.current_scenario_obj: Optional[Scenario] = None

        # 캐릭터 관련
        self.characters: List[Character] = []
        ## <<< 변경: 단일 캐릭터 선택 관련 변수 삭제
        # self.selected_character: Optional[Character] = None
        # self.character_locked = False  # 선택 완료 플래그

    # ===== 유틸 =====
    def _print_header(self, text: str):
        print("\n" + "=" * 60)
        print(text)
        print("=" * 60 + "\n")

    def _ask_model(self, messages: List[Dict[str, Any]], **kwargs) -> str:
        """공통 모델 호출"""
        completion = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            temperature=kwargs.get("temperature", self.temperature),
            top_p=kwargs.get("top_p", self.top_p),
            frequency_penalty=kwargs.get("frequency_penalty", self.frequency_penalty),
            presence_penalty=kwargs.get("presence_penalty", self.presence_penalty),
            stream=False,
        )
        return completion.choices[0].message.content

    def _trim_history(self):
        """히스토리 길이 제한을 적용. system 1개는 항상 유지."""
        if not self.conversation_history:
            return
        system_first = self.conversation_history[0] if self.conversation_history[0]['role'] == 'system' else None
        if not system_first:
            # 시스템 프롬프트가 없는 비정상적인 경우, 전체 히스토리를 유지
            if len(self.conversation_history) > self.max_history_messages:
                self.conversation_history = self.conversation_history[-self.max_history_messages:]
            return
            
        user_assistant_msgs = [msg for msg in self.conversation_history if msg['role'] != 'system']
        if len(user_assistant_msgs) > self.max_history_messages:
            user_assistant_msgs = user_assistant_msgs[-self.max_history_messages:]
        self.conversation_history = [system_first] + user_assistant_msgs


    # ===== 스토리 로드/요약 =====
    def load_story_data(self, json_file_path: str) -> bool:
        """JSON 스토리 데이터 로드 (파일 전체를 문자열+dict로 보관)"""
        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                raw = f.read()
            self.story_raw = raw
            self.story = json.loads(raw)
            print("📚 스토리 데이터가 성공적으로 로드되었습니다!")
            return True
        except FileNotFoundError:
            print(f"❌ 파일을 찾을 수 없습니다: {json_file_path}")
            return False
        except Exception as e:
            print(f"❌ 파일 로드 중 오류 발생: {e}")
            return False

    def _extract_story_brief(self) -> str:
        """캐릭터 생성용 최소 요약(배경/주제/톤/등장세력/갈등)"""
        system = {"role": "system", "content": "너는 스토리 분석가다. 캐릭터 창작에 도움이 되는 핵심만 간결히 요약해라. 반드시 JSON 형식으로만 응답하라."}
        user = {
            "role": "user",
            "content": f"""다음 JSON 스토리를 캐릭터 창작용으로 요약.
형식(JSON):
{{
  "setting": "시대/장소/분위기",
  "themes": ["주제1","주제2"],
  "tone": "전체 톤",
  "notable_characters": ["핵심 인물/집단 3~6개"],
  "conflicts": ["갈등/과제 2~4개"],
  "description": "한줄요약"
}}
스토리:
{self.story_raw}"""
        }
        try:
            text = self._ask_model([system, user], max_tokens=600, temperature=0.3)
            json_str = self._extract_json_block(text)
            data = json.loads(json_str)

            # Scenario DB 저장
            scenario_title = self.story.get("title", "해와달")
            self.current_scenario_obj, created = Scenario.objects.get_or_create(
                title=scenario_title,
                defaults={'description': data.get('description','')}
            )
            if created:
                print(f"시나리오 '{scenario_title}'가 새로 생성되었습니다.")
            else:
                print(f"시나리오 '{scenario_title}'가 이미 존재합니다.")

            lines = [
                f"배경: {data.get('setting','')}",
                f"주제: {', '.join(data.get('themes', []))}",
                f"톤: {data.get('tone','')}",
                f"주요 인물/세력: {', '.join(data.get('notable_characters', []))}",
                f"갈등: {', '.join(data.get('conflicts', []))}"
            ]
            return "\n".join(lines)
        except Exception as e:
            print(f"⚠️ 스토리 요약 중 JSON 파싱 오류 발생: {e}. 기본 요약으로 대체합니다.")
            if not self.current_scenario_obj:
                scenario_title = self.story.get("title", "해와달")
                self.current_scenario_obj, _ = Scenario.objects.get_or_create(title=scenario_title)
            return "배경/주제/갈등 중심. 가족, 희생, 보상, 자연/천체 상징이 중요."

    def _seed_from_story(self):
        """스토리 내용으로부터 랜덤 시드 도출 → 캐릭터 생성 재현성."""
        if self.story_raw:
            h = int(hashlib.sha256(self.story_raw.encode("utf-8")).hexdigest(), 16)
            random.seed(h % (2**32))

    # ===== 캐릭터 생성 (게임 스탯 중심) =====
    def generate_character_candidates(self, count: int = 4) -> List[Character]:
        """스토리 톤/주제에 정합적인 캐릭터 후보 N명 생성."""
        self._seed_from_story()
        story_brief = self._extract_story_brief()

        ## <<< 추가: LLM에게 보여줄 완벽한 JSON 예시
        example_character_json = """
[
  {
    "id": "guardian_sister",
    "name": "누의",
    "role": "수호자",
    "stats": {"힘":6,"민첩":7,"지식":8,"의지":9,"매력":7,"운":6},
    "skills": ["기도하기", "상처 치료"],
    "starting_items": ["어머니의 비녀", "따뜻한 떡"],
    "playstyle": "동생을 보호하는 것을 최우선으로 하며, 신중하고 침착하게 행동한다. 위기 상황에서는 기도를 통해 해법을 찾으려 한다."
  }
]
"""

        schema_hint = """JSON 배열로만 대답해. 각 원소는 다음 키를 가져야 한다:
[
  {
    "id": "string(짧고 유니크)",
    "name": "캐릭터 이름",
    "role": "클래스/아키타입(탱커/정찰자/현자/외교가/트릭스터 등)",
    "stats": {"힘":1-10,"민첩":1-10,"지식":1-10,"의지":1-10,"매력":1-10,"운":1-10},
    "skills": ["대표 스킬1","대표 스킬2"],
    "starting_items": ["시작 아이템1","시작 아이템2"],
    "playstyle": "행동/대화 성향, 선택 경향, 말투 가이드"
  }
]"""

        system = {
            "role": "system",
            "content": "너는 TRPG 캐릭터 디자이너다. 서로 다른 플레이스타일과 역할이 충돌/보완되도록 설계하라. 반드시 JSON만 출력."
        }
        
        ## <<< 수정: user 메시지에 예시와 규칙 강조 추가
        user = {
            "role": "user",
            "content": f"""다음 스토리 요약에 어울리는 TRPG 캐릭터 {count}명을 생성해줘.

### 스토리 요약:
{story_brief}

### 출력 규칙 (매우 중요):
1.  반드시 아래의 `출력 형식`을 완벽하게 따르는 JSON 배열만 출력해야 한다.
2.  `name`, `role` 뿐만 아니라 `stats`, `skills`, `starting_items`, `playstyle` 필드를 **절대로 생략해서는 안 된다.**
3.  각 캐릭터의 스탯 합은 36~42 범위가 되도록 분배한다.
4.  캐릭터 간 역할과 플레이스타일이 명확히 달라야 한다.

### 출력 형식:
{schema_hint}

### 좋은 출력의 예시:
{example_character_json}
"""
        }

        text = self._ask_model([system, user], max_tokens=2000, temperature=0.7)
        json_str = self._extract_json_block(text)
        try:
            raw_list = json.loads(json_str)
        except json.JSONDecodeError:
            print("⚠️ 캐릭터 생성 결과 JSON 파싱 실패. 일부 데이터만 복구합니다.")
            raw_list = self._best_effort_json_array(json_str)

        self.characters = []
        for i, ch in enumerate(raw_list):
            try:
                stats_raw = ch.get("stats", {})
                stats: Dict[str, int] = {}
                for key in ["힘", "민첩", "지식", "의지", "매력", "운"]:
                    stats[key] = int(stats_raw.get(key, 5))

                char_dataclass = Character(
                    id=str(ch.get("id", f"ch{i+1}")),
                    name=ch.get("name", f"무명{i+1}"),
                    role=ch.get("role", "탐험가"),
                    stats=stats,
                    skills=list(ch.get("skills", [])),
                    starting_items=list(ch.get("starting_items", [])),
                    playstyle=ch.get("playstyle", ""),
                )
                self.characters.append(char_dataclass)

                if self.current_scenario_obj:
                    DjangoCharacter.objects.update_or_create(
                        scenario=self.current_scenario_obj,
                        name=char_dataclass.name,
                        defaults={
                            'description' : f"역할: {char_dataclass.role}\n플레이 스타일: {char_dataclass.playstyle}",
                            'items' : {'items': char_dataclass.starting_items},
                            'ability' : {
                                'stats': char_dataclass.stats,
                                'skills': char_dataclass.skills,
                            }
                        }
                    )
            except Exception as e:
                print(f"⚠️ 캐릭터 데이터 처리 중 오류 발생: {e}")
                continue
        return self.characters

    ## <<< 변경: 단일 캐릭터 선택 대신 파티 정보를 보여주는 함수
    def display_character_party(self):
        """CLI에 생성된 캐릭터 파티 정보를 렌더링"""
        if not self.characters:
            print("⚠️ 생성된 캐릭터가 없습니다.")
            return
        self._print_header("🎭 우리 파티")
        for ch in self.characters:
            print(f"👤 {ch.name}  |  역할: {ch.role}")
            stat_order = ["힘", "민첩", "지식", "의지", "매력", "운"]
            stat_line = " / ".join(f"{k}:{ch.stats.get(k, 0)}" for k in stat_order)
            print(f"   스탯  : {stat_line}")
            print(f"   스킬  : {', '.join(ch.skills) if ch.skills else '-'}")
            print(f"   시작템: {', '.join(ch.starting_items) if ch.starting_items else '-'}")
            print("-" * 60)

    ## <<< 삭제: 단일 캐릭터 선택 관련 함수들
    # def present_character_choices(self): ...
    # def select_character(self, choice_index: int) -> Optional[Character]: ...
    # def _available_choices(self) -> int: ...
    # def _normalize_player_input(self, raw: str) -> str: ...

    # ===== d20 판정 유틸 (새로운 기능) =====
    def _mod(self, score: int) -> int:
        """스탯(1~10)을 보정치로 변환"""
        table = {1:-3,2:-2,3:-2,4:-1,5:0,6:1,7:2,8:3,9:4,10:5}
        return table.get(int(score), 0)

    def _get_roll_grade(self, roll: int, total: int, dc: int) -> str:
        """d20 판정 결과를 SP/S/F/SF 등급으로 변환"""
        if roll == 20 or total >= dc + 8:  # 자연 20 또는 DC보다 8 이상 높으면 대성공
            return "SP"
        elif roll == 1 or total <= dc - 8:  # 자연 1 또는 DC보다 8 이상 낮으면 대실패
            return "SF"
        elif total >= dc:
            return "S"
        else:
            return "F"

    def ability_check(self, character: Character, stat: str, dc: int = 12) -> dict:
        """캐릭터 객체를 받아 d20 판정을 수행하고 결과를 등급으로 반환"""
        roll = random.randint(1, 20)
        stat_score = character.stats.get(stat, 5)
        mod = self._mod(stat_score)
        total = roll + mod
        grade = self._get_roll_grade(roll, total, dc)
        grade_map = {"SP": "🎉대성공🎉", "S": "성공", "F": "실패", "SF": "💥대실패💥"}

        note = f"d20={roll} | {stat}보정={mod} | 최종값={total} vs 목표값={dc} → {grade_map.get(grade)}"
        return {"grade": grade, "note": note}

    # ===== 게임 초기화/진행 (수정된 부분) =====
    def initialize_game(self):
        """게임 시스템 프롬프트 구성 (모든 캐릭터 정보 포함)"""
        if not self.story_raw:
            print("❌ 먼저 스토리 데이터를 로드해주세요.")
            return
        if not self.characters:
            print("❌ 캐릭터를 먼저 생성해주세요.")
            return

        characters_json = json.dumps([asdict(c) for c in self.characters], ensure_ascii=False, indent=2)
        
        header = "너는 싱글 플레이어용 '클래식' TRPG의 AI 게임 마스터이다."
        goal = "- 플레이어의 선택에 반응해 긴장감 있는 장면 전환과 의미 있는 결과를 제공한다.\n" \
               "- 서사적 일관성과 재미, 선택의 영향(서술/자원/관계)을 명확히 보여준다."

        system_prompt = {
            "role": "system",
            "content": f"""{header}

## 목표
{goal}

## 등장 캐릭터 파티 정보
{characters_json}

## 상호작용 포맷 (⭐중요⭐)
**현재 상황**: [장면 묘사]

---
**(모든 캐릭터에 대해 아래 형식을 반복)**
**[캐릭터 1 이름]의 선택:**
1) [행동 옵션 1] - [예상 판정: (스탯)]
2) [행동 옵션 2] - [예상 판정: (스탯)]
---

- 플레이어가 특정 캐릭터의 행동과 판정 결과를 '[판정결과] ...' 형식으로 알려주면, 그 결과를 반영하여 다음 장면을 서술하라.
- 플레이어의 자유로운 행동 서술에도 유연하게 반응하라.
"""
        }

        initial_prompt = {
            "role": "user",
            "content": "아래 JSON 스토리로 TRPG를 시작해줘. 모든 캐릭터가 참여하는 첫 장면을 열어줘.\n\n" + self.story_raw
        }

        self.conversation_history = [system_prompt, initial_prompt]
        resp = self._get_ai_response()
        self._print_header("🎮 TRPG 시작")
        print(f"🎭 게임 마스터: {resp}\n")
        self.game_initialized = True

    def _get_ai_response(self) -> str:
        """AI 응답 받기 + 대화 기록 적재(방어코드 포함)"""
        try:
            content = self._ask_model(self.conversation_history)
            if not content:
                content = "(GM이 잠시 생각에 잠겼습니다...)"
            self.conversation_history.append({"role": "assistant", "content": content})
            self._trim_history()
            return content
        except Exception as e:
            msg = f"❌ AI 응답 생성 중 오류가 발생했습니다: {e}"
            self.conversation_history.append({"role": "assistant", "content": msg})
            return msg

    def send_player_input(self, user_input: str) -> str:
        """플레이어 입력 처리(판정 명령 중심)"""
        if not self.game_initialized:
            return "❌ 게임이 초기화되지 않았습니다."

        cmd = user_input.strip()
        # !판정 명령어 처리
        m_roll = re.match(r"^(?:!판정|/roll)\s+([\w가-힣]+)\s+(힘|민첩|지식|의지|매력|운)\s*(\d{1,2})?", cmd)
        
        if m_roll:
            char_name, stat, dc_str = m_roll.groups()
            dc = int(dc_str) if dc_str else 12
            
            target_char = next((c for c in self.characters if c.name == char_name), None)
            
            if not target_char:
                print(f"❌ 캐릭터 '{char_name}'를 찾을 수 없습니다. 파티원: {[c.name for c in self.characters]}")
                return "" # 오류 발생 시 AI에게 추가 요청하지 않음

            result = self.ability_check(target_char, stat, dc=dc)
            print(f"🎲 판정 결과: {result.get('note')}")
            
            outcome_message = f"[판정결과] 캐릭터 '{target_char.name}'의 '{stat}' 판정 결과는 '{result.get('grade')}' 등급이었어. 이 결과를 서사에 반영하여 다음 장면을 진행해줘."
            self.conversation_history.append({"role": "user", "content": outcome_message})
        
        else: # 일반 입력
            self.conversation_history.append({"role": "user", "content": cmd})
        
        resp = self._get_ai_response()
        print(f"🎭 게임 마스터: {resp}\n")
        return resp

    # ===== 인터랙티브 루프 (CLI) - 수정된 부분 =====
    def play_interactive_game(self):
        """대화형 게임 진행: 캐릭터 파티 생성 → 본게임"""
        if not self.story_raw:
            print("❌ 먼저 스토리 데이터를 로드해주세요.")
            return

        # 1) 캐릭터 파티 생성 (선택 과정 없음)
        if not self.characters:
            self.characters = self.generate_character_candidates(count=4)
        
        if not self.characters:
            print("❌ 캐릭터 생성에 실패하여 게임을 시작할 수 없습니다.")
            return

        self.display_character_party()

        # 2) 본게임 시작
        self.initialize_game()
        if not self.game_initialized:
            return

        print("💡 게임 진행 중입니다. '종료' 또는 'quit' 입력 시 종료됩니다.")
        print("💬 판정 예시: !판정 루나 지식 12")
        print("💬 자유롭게 행동을 서술하거나, GM의 선택지에 대한 행동을 입력하세요.")
        while True:
            try:
                user_input = input("🎯 당신의 행동/대사 또는 명령: ").strip()
                if user_input.lower() in ["종료", "quit", "exit", "끝"]:
                    print("🎉 게임을 종료합니다. 수고하셨습니다!")
                    break
                if not user_input:
                    continue
                self.send_player_input(user_input)
            except KeyboardInterrupt:
                print("\n\n🎉 게임을 종료합니다. 수고하셨습니다!")
                break
            except Exception as e:
                print(f"❌ 오류가 발생했습니다: {e}")
                continue

    # ===== 저장/불러오기 (기존 파일 저장 방식 유지) =====
    def save_game_log(self, filename: str = "game_log.json"):
        """게임 진행 로그 + 캐릭터 파티 정보 저장"""
        try:
            payload = {
                "conversation_history": self.conversation_history,
                "characters": [asdict(c) for c in self.characters],
                "meta": { "trpg_mode": self.trpg_mode }
            }
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"📝 게임 로그가 {filename}에 저장되었습니다.")
        except Exception as e:
            print(f"❌ 로그 저장 중 오류 발생: {e}")

    def load_game_log(self, filename: str = "game_log.json"):
        """저장된 게임 로그 불러오기"""
        try:
            with open(filename, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.conversation_history = payload.get("conversation_history", [])
            self.characters = [Character(**c) for c in payload.get("characters", [])]
            self.game_initialized = bool(self.conversation_history)
            print(f"📖 게임 로그가 {filename}에서 불러와졌습니다.")
            # 불러온 후 게임 바로 시작
            self.display_character_party()
            print("--- 지난 줄거리 ---")
            last_gm_message = self.conversation_history[-1]['content'] if self.conversation_history and self.conversation_history[-1]['role'] == 'assistant' else "저장된 내용이 없습니다."
            print(last_gm_message)
            print("------------------\n")
            self.play_interactive_game() # 바로 게임 루프 진입
        except FileNotFoundError:
            print(f"❌ 로그 파일을 찾을 수 없습니다: {filename}")
        except Exception as e:
            print(f"❌ 로그 로드 중 오류 발생: {e}")


    # ===== JSON 추출 보조 (오류 방지를 위해 강화된 버전) =====
    @staticmethod
    def _extract_json_block(text: str) -> str:
        """응답에서 JSON 블록만 추출."""
        if text is None:
            return "[]"
        # 마크다운 코드 블록(```json ... ```)에서 JSON 추출
        code_fence = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
        if code_fence:
            return code_fence.group(1).strip()
        # 일반 텍스트에서 가장 먼저 나오는 {...} 또는 [...] 블록 추출
        bracket = re.search(r"(\[.*\]|\{.*\})", text, flags=re.S)
        if bracket:
            return bracket.group(1).strip()
        return text.strip()

    @staticmethod
    def _best_effort_json_array(text: str) -> List[dict]:
        """JSON 배열 파싱 실패 시, 내부의 {객체} 조각이라도 최대한 모아 배열로 복구."""
        if text is None:
            return []
        # 정규표현식으로 {...} 형태의 모든 문자열 조각을 찾음
        objs = re.findall(r"\{.*?\}", text, flags=re.S)
        out: List[dict] = []
        for o in objs:
            try:
                # 각 조각을 JSON으로 파싱 시도
                out.append(json.loads(o))
            except Exception:
                # 파싱 실패 시 무시하고 다음 조각으로 넘어감
                continue
        return out

# ===== 빠른 실행 헬퍼 =====
def main():
    game_master = TRPGGameMaster()
    print("🌟 === TRPG 게임에 오신 것을 환영합니다! ===\n")
    while True:
        print("📋 메뉴를 선택해주세요:")
        print("1) 새 게임 (스토리 파일 → 캐릭터 파티 생성 후 시작)")
        print("2) 저장된 게임 불러오기")
        print("3) 종료")
        choice = input("\n선택 (1-3): ").strip()
        if choice == "1":
            # 스크립트 위치 기준으로 파일 경로 자동 설정
            try:
                current_script_dir = os.path.dirname(os.path.abspath(__file__))
                json_path = os.path.join(current_script_dir, "sun_moon_play_json.json")
                print(f"📁 기본 스토리 파일: {json_path}")
            except NameError: # 대화형 인터프리터 등에서 실행될 경우
                json_path = "sun_moon_play_json.json"

            if game_master.load_story_data(json_path):
                game_master.play_interactive_game()
                # 게임 종료 후 저장 여부 질문
                save_choice = input("\n💾 게임 진행 상황을 저장하시겠습니까? (y/n): ").strip().lower()
                if save_choice.startswith("y"):
                    game_master.save_game_log()
            break
        elif choice == "2":
            game_master.load_game_log()
            # load_game_log 안에서 play_interactive_game 루프가 돌기 때문에 break 필요 없음
            break
        elif choice == "3":
            print("👋 게임을 종료합니다. 안녕히 가세요!")
            break
        else:
            print("❌ 잘못된 선택입니다. 1-3 사이의 숫자를 입력해주세요.")

# quick_start_game, continue_game_from_log 함수는 main 함수에 통합되어 삭제

if __name__ == "__main__":
    main()