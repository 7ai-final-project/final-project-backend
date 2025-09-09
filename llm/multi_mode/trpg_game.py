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
    role: str                    # 클래스/아키타입(탱커, 정찰자, 현자 등)
    stats: Dict[str, int]        # {"힘":7,"민첩":6,"지식":8,"의지":5,"매력":6,"운":4}
    skills: List[str]            # 특기/재능
    starting_items: List[str]    # 시작 아이템
    playstyle: str               # 플레이 스타일 가이드(행동 성향, 말투 등)

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

        # 캐릭터 관련
        self.characters: List[Character] = []
        self.selected_character: Optional[Character] = None
        self.character_locked = False  # 선택 완료 플래그

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
        system_first = None
        rest = []
        for m in self.conversation_history:
            if m.get("role") == "system" and system_first is None:
                system_first = m
            else:
                rest.append(m)
        if len(rest) > self.max_history_messages:
            rest = rest[-self.max_history_messages:]
        self.conversation_history = ([system_first] if system_first else []) + rest

    # ===== 스토리 로드/요약 =====
    def load_story_data(self, json_file_path: str) -> bool:
        """JSON 스토리 데이터 로드 (파일 전체를 문자열+dict로 보관)"""
        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                raw = f.read()
            self.story_raw = raw
            try:
                self.story = json.loads(raw)
            except json.JSONDecodeError:
                self.story = None
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
        system = {"role": "system", "content": "너는 스토리 분석가다. 캐릭터 창작에 도움이 되는 핵심만 간결히 요약해라."}
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
            scenario_title = "해와달"
            self.current_scenario_obj, created = Scenario.objects.get_or_create(
                title=scenario_title,
                defaults={'description': data.get('description','')}
            )
            if created:
                print(f"시나리오 '{scenario_title}'가 새로 생성되었습니다.")
            else:
                print(f"시나리오 '{scenario_title}'가 이미 존재합니다.")

            lines = []
            lines.append(f"배경: {data.get('setting','')}")
            lines.append(f"주제: {', '.join(data.get('themes', []))}")
            lines.append(f"톤: {data.get('tone','')}")
            lines.append(f"주요 인물/세력: {', '.join(data.get('notable_characters', []))}")
            lines.append(f"갈등: {', '.join(data.get('conflicts', []))}")
            return "\n".join(lines)
        except Exception:
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
]
제약:
- 각 캐릭터의 스탯 합이 34~40 범위가 되도록.
- 캐릭터 간 역할/플레이스타일이 명확히 다르게.
"""
        system = {
            "role": "system",
            "content": "너는 TRPG 캐릭터 디자이너다. 서로 다른 플레이스타일과 역할이 충돌/보완되도록 설계하라. 반드시 JSON만 출력."
        }
        user = {
            "role": "user",
            "content": f"""다음 요약에 어울리는 캐릭터 {count}명 생성.
스토리 요약:
{story_brief}

출력 형식(필수):
{schema_hint}"""
        }

        text = self._ask_model([system, user], max_tokens=1200, temperature=0.7)
        json_str = self._extract_json_block(text)
        try:
            raw_list = json.loads(json_str)
        except Exception:
            raw_list = self._best_effort_json_array(json_str)

        characters: List[Character] = []
        for i, ch in enumerate(raw_list):
            try:
                stats_raw = ch.get("stats", {})
                stats: Dict[str, int] = {}
                for key in ["힘", "민첩", "지식", "의지", "매력", "운"]:
                    val = stats_raw.get(key, 5)
                    try:
                        stats[key] = int(val)
                    except Exception:
                        stats[key] = 5

                # 스탯 합 34~40 보정
                ssum = sum(stats.values())
                target_min, target_max = 34, 40
                if ssum < target_min:
                    keys = list(stats.keys())
                    while ssum < target_min:
                        k = random.choice(keys)
                        if stats[k] < 10:
                            stats[k] += 1
                            ssum += 1
                elif ssum > target_max:
                    keys = list(stats.keys())
                    while ssum > target_max:
                        k = random.choice(keys)
                        if stats[k] > 1:
                            stats[k] -= 1
                            ssum -= 1
                
                char_dataclass = Character(
                    id=str(ch.get("id", f"ch{i+1}")),
                    name=ch.get("name", f"무명{i+1}"),
                    role=ch.get("role", "탐험가"),
                    stats=stats,
                    skills=list(ch.get("skills", []))[:5],
                    starting_items=list(ch.get("starting_items", []))[:5],
                    playstyle=ch.get("playstyle", ""),
                )
                characters.append(char_dataclass)

                # Character DB 저장
                django_char, created = DjangoCharacter.objects.get_or_create(
                    scenario=self.current_scenario_obj,
                    name=char_dataclass.name,
                    defaults={
                        'description' : f"역할: {char_dataclass.role}\n플레이 스타일: {char_dataclass.playstyle}",
                        'items' : char_dataclass.starting_items,
                        'ability' : {
                            'stats': char_dataclass.stats,
                            'skills': char_dataclass.skills,
                        }
                    }
                )

                if created:
                    print(f"캐릭터 '{char_dataclass.name}'가 시나리오 '{self.current_scenario_obj.title}'에 새로 생성되었습니다.")
                else:
                    print(f"캐릭터 '{char_dataclass.name}'가 시나리오 '{self.current_scenario_obj.title}'에 이미 존재합니다.")

            except Exception:
                continue
        self.characters = characters
        return characters

    def present_character_choices(self):
        """CLI에 캐릭터 후보를 보기 좋게 렌더링"""
        if not self.characters:
            print("⚠️ 캐릭터 후보가 없습니다. 먼저 generate_character_candidates()를 호출하세요.")
            return
        self._print_header("🎭 캐릭터 후보")
        for idx, ch in enumerate(self.characters, start=1):
            print(f"[{idx}] {ch.name}  |  역할: {ch.role}")
            stat_order = ["힘", "민첩", "지식", "의지", "매력", "운"]
            stat_line = " / ".join(f"{k}:{ch.stats.get(k, 0)}" for k in stat_order)
            print(f"   스탯  : {stat_line}")
            print(f"   스킬  : {', '.join(ch.skills) if ch.skills else '-'}")
            print(f"   시작템: {', '.join(ch.starting_items) if ch.starting_items else '-'}")
            print(f"   플레이: {ch.playstyle or '-'}")
            print("-" * 60)
        print("원하는 캐릭터 번호를 입력하세요. (예: 1)")
        print("선택을 취소하고 메인 메뉴로 돌아가려면 'back'을 입력하세요.")

    def select_character(self, choice_index: int) -> Optional[Character]:
        """인덱스로 캐릭터 선택"""
        if not (1 <= choice_index <= len(self.characters)):
            print("❌ 잘못된 번호입니다.")
            return None
        self.selected_character = self.characters[choice_index - 1]
        self.character_locked = True
        print(f"✅ 선택된 캐릭터: {self.selected_character.name} ({self.selected_character.role})")
        return self.selected_character

    # ===== 입력 정규화 & 선택지 검증 =====
    def _available_choices(self) -> int:
        """직전 GM 메시지에서 1)~4) 라인의 개수를 센다."""
        for msg in reversed(self.conversation_history):
            if msg.get("role") == "assistant":
                lines = (msg.get("content") or "").splitlines()
                return sum(1 for ln in lines if re.match(r"\s*[1-4]\)\s", ln))
        return 0

    def _normalize_player_input(self, raw: str) -> str:
        """
        숫자만 입력(예: '1','2','3','4')하면, 직전 GM 메시지의 선택지와 연결되는
        안전한 문장으로 변환. 그 외 자유 입력은 그대로 사용.
        """
        s = (raw or "").strip()
        if re.fullmatch(r"[1-4]", s):
            n = int(s)
            maxn = self._available_choices()
            if 1 <= n <= maxn if maxn else True:
                return f"선택지 {s}번을 고른다."
            else:
                return f"현재 장면에는 1~{maxn}번 선택지만 제공되었어. 장면에 맞는 번호로 다시 고를게."
        return s if s else "(무응답)"

    # ===== d20 판정 유틸 =====
    def _mod(self, score: int) -> int:
        """스탯(1~10)을 보정치로 변환"""
        table = {1:-3,2:-2,3:-2,4:-1,5:0,6:1,7:2,8:3,9:4,10:5}
        try:
            return table.get(int(score), 0)
        except Exception:
            return 0

    def ability_check(self, stat: str, dc: int = 12, advantage: Optional[str] = None,
                      skill: Optional[str] = None, item_tags: Optional[List[str]] = None) -> dict:
        """
        d20 판정: d20 + 스탯보정 + (스킬/아이템 보너스) >= DC ?
        - advantage: None | 'adv' | 'dis'
        - skill이 캐릭터 보유 스킬이면 +2
        - item_tags가 시작 아이템 이름과 키워드 매칭되면 키워드당 +1
        """
        if not self.selected_character:
            return {"error": "캐릭터 미선택"}

        # 굴림
        r1 = random.randint(1, 20)
        r2 = random.randint(1, 20) if advantage in ("adv", "dis") else None
        if advantage == "adv":
            roll = max(r1, r2)
        elif advantage == "dis":
            roll = min(r1, r2)
        else:
            roll = r1

        # 보정 계산
        stat_score = self.selected_character.stats.get(stat, 5)
        mod = self._mod(stat_score)
        bonus = 0

        if skill and (skill in (self.selected_character.skills or [])):
            bonus += 2

        if item_tags:
            # 단어 단위 매칭(간단 정규화)
            items_blob = " ".join(self.selected_character.starting_items or []).lower()
            items_blob = re.sub(r"[^a-z0-9가-힣\s]", " ", items_blob)
            for t in item_tags:
                token = re.sub(r"[^a-z0-9가-힣\s]", " ", (t or "").lower()).strip()
                if not token:
                    continue
                if re.search(rf"\b{re.escape(token)}\b", items_blob):
                    bonus += 1

        total = roll + mod + bonus
        success = total >= dc

        adv_name = {"adv": "이점", "dis": "불리"}.get(advantage or "", "보정 없음")
        note = f"d20={roll} | {adv_name} | mod({stat})={mod} | bonus={bonus} | total={total} vs DC{dc} → {'성공' if success else '실패'}"

        # 다음 응답에 반영되도록 user 메시지로 힌트 추가(드리프트 완화)
        self.conversation_history.append({
            "role": "user",
            "content": f"[판정결과] {stat} 판정 결과: {note}. 결과를 장면에 반영해 진행해줘."
        })
        self._trim_history()
        return {"roll": roll, "mod": mod, "bonus": bonus, "total": total, "dc": dc, "success": success, "note": note}

    # ===== 게임 초기화/진행 =====
    def initialize_game(self):
        """게임 시스템 프롬프트 구성 (캐릭터 선택 이후)"""
        if not self.story_raw:
            print("❌ 먼저 스토리 데이터를 로드해주세요.")
            return
        if not self.selected_character:
            print("❌ 캐릭터를 먼저 선택해주세요.")
            return

        # 모드에 따른 시스템 프롬프트
        if self.trpg_mode == "edu":
            header = "너는 싱글 플레이어를 위한 '독서 교육형' TRPG의 AI 게임 마스터이다."
            goal = (
                "- 플레이어가 제공된 스토리를 체험하며 주제/상징/심리를 자연스럽게 이해하도록 돕는다.\n"
                "- 원작의 큰 흐름/결말을 존중하되, 과정은 상호작용적으로 변주한다."
            )
        else:
            header = "너는 싱글 플레이어용 '클래식' TRPG의 AI 게임 마스터이다."
            goal = (
                "- 플레이어의 선택에 반응해 긴장감 있는 장면 전환과 의미 있는 결과를 제공한다.\n"
                "- 서사적 일관성과 재미, 선택의 영향(서술/자원/관계)을 명확히 보여준다."
            )

        system_prompt = {
            "role": "system",
            "content": f"""{header}

## 목표
{goal}

## 캐릭터
""" + json.dumps(asdict(self.selected_character), ensure_ascii=False, indent=2) + """

## 이야기 데이터
- JSON으로 주어진 원작 스토리를 기반으로 진행한다. acts → scenes 순서를 따르되, 선택지와 상호작용을 매 장면 제공한다.

## 상호작용 포맷(항상 유지)
**현재 상황**: [장면 묘사 — 감각/감정/상징을 간결히]
**당신의 선택:**
1) [행동 옵션 1] - [예상 의미/결과]
2) [행동 옵션 2] - [예상 의미/결과]
3) [행동 옵션 3] - [예상 의미/결과]
4) [자유 행동] "직접 말하거나 행동하기"

**생각해볼 점**: [작품/세계 해석 포인트 1가지, 질문형으로]

- 선택은 이야기적 의미와 캐릭터의 스탯/역할/동기를 함께 반영해 반응한다.
- 과도한 정보 과잉 설명은 피하고, '장면 전환'의 템포를 유지한다.
- 플레이어가 숫자(1~4)만 입력하면 해당 선택으로 처리한다.
"""
        }

        initial_prompt = {
            "role": "user",
            "content": "아래 JSON 스토리로 TRPG를 시작해줘. 첫 장면을 열어줘.\n\n" + self.story_raw
        }

        self.conversation_history = [system_prompt, initial_prompt]
        resp = self._get_ai_response()
        self._print_header("🎮 TRPG 시작")
        print(f"🎭 게임 마스터: {resp}\n")
        self.game_initialized = True

    def _get_ai_response(self) -> str:
        """AI 응답 받기 + 대화 기록 적재(방어코드 포함)"""
        try:
            completion = self.client.chat.completions.create(
                model=self.deployment,
                messages=self.conversation_history,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                frequency_penalty=self.frequency_penalty,
                presence_penalty=self.presence_penalty,
                stream=False,
            )
            content = completion.choices[0].message.content

            if content is None or str(content).strip() == "":
                self.conversation_history.append({
                    "role": "user",
                    "content": "방금 응답이 비어있었어. 같은 장면 맥락으로, 반드시 '선택지 형식'으로 다시 응답해줘."
                })
                completion2 = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=self.conversation_history,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    frequency_penalty=self.frequency_penalty,
                    presence_penalty=self.presence_penalty,
                    stream=False,
                )
                content = completion2.choices[0].message.content

            if content is None or str(content).strip() == "":
                safe = "⚠️ 잠시 응답이 고르지 않네요. 같은 요청을 다시 시도하거나, 선택지를 숫자 대신 문장으로 말해줘!"
                print(f"🎭 게임 마스터: {safe}\n")
                return safe

            self.conversation_history.append({"role": "assistant", "content": content})
            self._trim_history()
            return content

        except Exception as e:
            msg = f"❌ AI 응답 생성 중 오류가 발생했습니다."
            self.conversation_history.append({"role": "assistant", "content": msg})
            print(f"{msg} 상세: {e}")
            return msg

    def send_player_input(self, user_input: str) -> str:
        """플레이어 입력 처리(숫자 선택 정규화 + 판정 명령 + 방어)"""
        if not self.game_initialized:
            print("❌ 먼저 게임을 초기화해주세요. (캐릭터 선택 후 initialize_game())")
            return "게임 미초기화"

        # ── 판정 명령 처리 ──
        cmd = user_input.strip()
        m = re.match(
            r"^(?:/|!|roll|ROLL|Roll|판정|검사)\s*"
            r"(힘|민첩|지식|의지|매력|운)"
            r"(?:\s+(\d{1,2}))?"
            r"(?:\s+(이점|불리|adv|dis))?"
            r"(?:\s+skill:([^\s].*?))?"
            r"(?:\s+tags:([^\s].*))?$",
            cmd
        )
        if m:
            stat = m.group(1)
            dc = int(m.group(2)) if m.group(2) else 12
            adv_token = (m.group(3) or "").lower()
            advantage = "adv" if adv_token in ("이점", "adv") else ("dis" if adv_token in ("불리", "dis") else None)
            skill = (m.group(4) or "").strip() or None
            tags_raw = (m.group(5) or "").strip()
            tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else None

            result = self.ability_check(stat, dc=dc, advantage=advantage, skill=skill, item_tags=tags)
            print(f"🎲 판정: {result.get('note')}")
            return self._get_ai_response()

        # ── 일반 입력 ──
        normalized = self._normalize_player_input(user_input)
        if not normalized or normalized.strip() == "":
            normalized = "(무응답)"

        self.conversation_history.append({"role": "user", "content": normalized})
        resp = self._get_ai_response()
        print(f"🎭 게임 마스터: {resp}\n")
        return resp

    # ===== 인터랙티브 루프 (CLI) =====
    def play_interactive_game(self):
        """대화형 게임 진행: 캐릭터 선택 → 본게임"""
        if not self.story_raw:
            print("❌ 먼저 스토리 데이터를 로드해주세요.")
            return

        # 1) 캐릭터 고르기
        if not self.character_locked:
            self.characters = self.generate_character_candidates(count=4)
            self.present_character_choices()
            while True:
                choice = input("캐릭터 번호 입력(또는 'back'): ").strip().lower()
                if choice == "back":
                    print("↩️ 메인 메뉴로 돌아갑니다.")
                    return
                if choice.isdigit():
                    idx = int(choice)
                    if self.select_character(idx):
                        break
                else:
                    print("⚠️ 유효한 입력이 아닙니다. 숫자(1~4) 또는 'back'을 입력하세요.")

        # 2) 본게임 시작
        self.initialize_game()
        if not self.game_initialized:
            return

        print("💡 게임 진행 중입니다. '종료/quit' 입력 시 종료.\n")
        print("💬 예) 판정 지식 13 이점  |  roll 매력 12 tags:빛,설득  |  / 민첩 10 dis skill:은신")
        while True:
            try:
                user_input = input("🎯 당신의 행동/대사 또는 명령: ").strip()
                if user_input.lower() in ["종료", "quit", "exit", "끝"]:
                    print("🎉 게임을 종료합니다. 수고하셨습니다!")
                    break
                if not user_input:
                    print("⚠️ 입력이 비어있습니다. 다시 입력해주세요.")
                    continue
                self.send_player_input(user_input)
            except KeyboardInterrupt:
                print("\n\n🎉 게임을 종료합니다. 수고하셨습니다!")
                break
            except Exception as e:
                print(f"❌ 오류가 발생했습니다: {e}")
                continue

    # ===== 저장/불러오기 =====
    def save_game_log(self, filename: str = "game_log.json"):
        """게임 진행 로그 + 캐릭터 메타 저장"""
        try:
            payload = {
                "conversation_history": self.conversation_history,
                "selected_character": asdict(self.selected_character) if self.selected_character else None,
                "characters": [asdict(c) for c in self.characters],
                "meta": {
                    "trpg_mode": self.trpg_mode,
                    "max_history_messages": self.max_history_messages
                }
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
            sel = payload.get("selected_character")
            self.selected_character = Character(**sel) if sel else None
            self.character_locked = bool(self.selected_character)
            self.game_initialized = bool(self.conversation_history)
            meta = payload.get("meta") or {}
            self.trpg_mode = meta.get("trpg_mode", self.trpg_mode)
            self.max_history_messages = meta.get("max_history_messages", self.max_history_messages)
            print(f"📖 게임 로그가 {filename}에서 불러와졌습니다.")
        except FileNotFoundError:
            print(f"❌ 로그 파일을 찾을 수 없습니다: {filename}")
        except Exception as e:
            print(f"❌ 로그 로드 중 오류 발생: {e}")

    # ===== JSON 추출 보조 =====
    @staticmethod
    def _extract_json_block(text: str) -> str:
        """응답에서 JSON 블록만 추출."""
        if text is None:
            return "[]"
        code_fence = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
        if code_fence:
            return code_fence.group(1).strip()
        bracket = re.search(r"(\[.*\]|\{.*\})", text, flags=re.S)
        if bracket:
            return bracket.group(1).strip()
        return text.strip()

    @staticmethod
    def _best_effort_json_array(text: str) -> List[dict]:
        """JSON 파싱 실패 시 객체 조각을 최대한 모아 배열로 복구."""
        if text is None:
            return []
        objs = re.findall(r"\{.*?\}", text, flags=re.S)
        out: List[dict] = []
        for o in objs:
            try:
                out.append(json.loads(o))
            except Exception:
                continue
        return out

# ===== 빠른 실행 헬퍼 =====
def main():
    game_master = TRPGGameMaster()
    print("🌟 === TRPG 게임에 오신 것을 환영합니다! ===\n")
    while True:
        print("📋 메뉴를 선택해주세요:")
        print("1) 새 게임 (스토리 파일 → 캐릭터 고르고 시작)")
        print("2) 저장된 게임 불러오기")
        print("3) 종료")
        choice = input("\n선택 (1-3): ").strip()
        if choice == "1":
            json_path = input(f"\n📁 JSON 스토리 파일 경로 (엔터: {game_master.default_json_path}): ").strip()
            if not json_path:
                json_path = game_master.default_json_path
            if game_master.load_story_data(json_path):
                game_master.play_interactive_game()
                save_choice = input("\n💾 게임 진행 상황을 저장하시겠습니까? (y/n): ").strip().lower()
                if save_choice in ["y", "yes", "예", "ㅇ"]:
                    filename = input(f"저장할 파일명 (엔터: {game_master.default_save_file}): ").strip()
                    if not filename:
                        filename = game_master.default_save_file
                    game_master.save_game_log(filename)
            break
        elif choice == "2":
            filename = input(f"📖 불러올 로그 파일명 (엔터: {game_master.default_save_file}): ").strip()
            if not filename:
                filename = game_master.default_save_file
            game_master.load_game_log(filename)
            if game_master.game_initialized:
                game_master.play_interactive_game()
                save_choice = input("\n💾 게임 진행 상황을 저장하시겠습니까? (y/n): ").strip().lower()
                if save_choice in ["y", "yes", "예", "ㅇ"]:
                    save_filename = input(f"저장할 파일명 (엔터: {game_master.default_save_file}): ").strip()
                    if not save_filename:
                        save_filename = game_master.default_save_file
                    game_master.save_game_log(save_filename)
            break
        elif choice == "3":
            print("👋 게임을 종료합니다. 안녕히 가세요!")
            break
        else:
            print("❌ 잘못된 선택입니다. 1-3 사이의 숫자를 입력해주세요.")

def quick_start_game(json_file_path="C:/Users/USER/Downloads/sun_moon_play_json.json"):
    game = TRPGGameMaster()
    if game.load_story_data(json_file_path):
        game.play_interactive_game()
    return game

def continue_game_from_log(log_file_path="game_log.json"):
    game = TRPGGameMaster()
    game.load_game_log(log_file_path)
    if game.game_initialized:
        game.play_interactive_game()
    return game

if __name__ == "__main__":
    main()
