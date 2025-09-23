# -*- coding: utf-8 -*-
"""
llm/multi_mode/gm_engine.py

멀티플레이 TRPG의 AI GM 엔진 (SHARI 방식 고정).
- 각 플레이어에게 **서로 다른 선택지**를 제시 (propose_choices)
- 플레이어 입력(선택)을 모아 **다음 턴 내러티브/상태**를 계산 (resolve_turn)
- 결과(JSON)를 세션 상태에 병합 (apply_gm_result_to_state)
- 세션 상태는 호출자가 관리(캐시/DB). 본 모듈은 상태 JSON을 입력/출력으로만 다룸.

상태(JSON) 최소 스펙:
{
  "session_id": "uuid 혹은 식별자",
  "turn": 1,
  "scenario": { "title": "...", "summary": "..." },
  "world": { "time": "밤", "location": "폐허 성곽", "notes": "..." },
  "party": [
    { "id":"p1", "name":"엘라", "role":"정찰수",
      "sheet": {
        "skills":["잠입","생존","절벽오르기"],
        "items":[{"name":"밧줄","charges":1},{"name":"단검"}],
        "spells":[{"name":"라이트","charges":3}],
        "notes":"..."
      },
      "memory":"..." }
  ],
  "log": [ {"turn":0, "narration":"..."}, ... ]
}

선택지 제안 응답:
{
  "turn": 1,
  "options": { "p1": [{"id":"A","text":"...","tags":["잠입"]}, ... up to 3] }
}

해결 응답(핵심 키):
{
  "turn": 2,
  "narration": "...",
  "personal": { "p1":"..." },
  "world": {...},
  "party": [...변경...],
  "log_append": [...],
  "shari": {
    "assess":[...], "rolls":[...],
    "update": {
      "characterHurt": {"p1": false},
      "currentLocation":"...", "previousLocation":"...",
      "notes":"...",
      "inventory": {
        "consumed": {"p1":["밧줄"]},
        "added": {"p1":["금화 10"]},
        "charges": {"p1":{"라이트": -1}}
      },
      "skills": {
        "cooldown": {"p1":{"전력질주": 2}}
      }
    }
  }
}
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from django.conf import settings
from openai import AzureOpenAI

from game.prompt_builders import build_scene_prompt
from game.azure_image import generate_scene_image
import os

IMAGE_GEN_ENABLED = os.getenv("IMAGE_GEN_ENABLED", "true").lower() in ("1","true","yes")

logger = logging.getLogger(__name__)


# ----------------------------- 공통 유틸 -----------------------------
def _extract_json_block(text: str) -> str:
    """모델 응답에서 JSON 블록을 안전하게 추출."""
    if not text:
        return "{}"
    fence = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if fence:
        return fence.group(1).strip()
    bracket = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if bracket:
        return bracket.group(1).strip()
    return text.strip()


def _summarize_party_capabilities(state: Dict[str, Any], max_per_section: int = 5) -> str:
    """
    party[].sheet 내의 skills/items/spells를 간결 요약해 LLM 컨텍스트에 주입.
    - 너무 길어지면 앞에서부터 max_per_section 개로 자름
    - items/spells는 name과 charges(있으면)를 같이 표기
    """
    out_lines: List[str] = []
    for p in state.get("party", []):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id"))
        name = str(p.get("name", pid))
        sheet = p.get("sheet") or {}
        skills = sheet.get("skills") or []
        items = sheet.get("items") or []
        spells = sheet.get("spells") or []
        # format
        sk = ", ".join(map(str, skills[:max_per_section])) if skills else "-"
        it_fmt = []
        for it in items[:max_per_section]:
            if isinstance(it, dict):
                n = it.get("name")
                ch = it.get("charges")
                it_fmt.append(f"{n}(x{ch})" if ch is not None else str(n))
            else:
                it_fmt.append(str(it))
        sp_fmt = []
        for sp in spells[:max_per_section]:
            if isinstance(sp, dict):
                n = sp.get("name")
                ch = sp.get("charges")
                sp_fmt.append(f"{n}(x{ch})" if ch is not None else str(n))
            else:
                sp_fmt.append(str(sp))
        it = ", ".join(it_fmt) if it_fmt else "-"
        sp = ", ".join(sp_fmt) if sp_fmt else "-"
        out_lines.append(f"- {name}({pid}) | skills: {sk} | items: {it} | spells: {sp}")
    return "\n".join(out_lines) if out_lines else "- (no capabilities provided)"


def _normalize_result(state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """
    모델 출력 스키마를 보정해 프런트가 기대하는 shape을 보장.
    - 필수 키 기본값 세팅
    - personal을 party id에 맞게 채움
    - shari.update.inventory/skills 기본 구조 보장
    """
    # 필수 키
    result.setdefault("turn", int(state.get("turn", 0)) + 1)
    result.setdefault("narration", "")
    result.setdefault("personal", {})
    result.setdefault("world", state.get("world", {}))
    result.setdefault("party", [])
    result.setdefault("log_append", [])

    # 파티 id
    party_ids = [str(p.get("id")) for p in state.get("party", []) if isinstance(p, dict)]

    # personal 보정
    personal = result.get("personal", {})
    if not isinstance(personal, dict):
        personal = {}
    for pid in party_ids:
        personal.setdefault(pid, "")
    result["personal"] = personal

    # shari 블록 보정
    shari = result.get("shari")
    if not isinstance(shari, dict):
        shari = {}
    shari.setdefault("assess", [])
    shari.setdefault("rolls", [])
    upd = shari.get("update")
    if not isinstance(upd, dict):
        upd = {}
    upd.setdefault("characterHurt", {})
    upd.setdefault("currentLocation", state.get("world", {}).get("location"))
    upd.setdefault("previousLocation", None)
    upd.setdefault("notes", "")

    # 인벤토리/스킬 변화 기본 구조
    inv = upd.get("inventory")
    if not isinstance(inv, dict):
        inv = {}
    inv.setdefault("consumed", {})  # {"p1":["밧줄"]}
    inv.setdefault("added", {})     # {"p1":["금화 10"]}
    inv.setdefault("charges", {})   # {"p1":{"라이트": -1}}
    upd["inventory"] = inv

    skl = upd.get("skills")
    if not isinstance(skl, dict):
        skl = {}
    skl.setdefault("cooldown", {})  # {"p1":{"전력질주": 2}}
    upd["skills"] = skl

    shari["update"] = upd

    # assess/rolls 내 player_id 정리
    for section in ("assess", "rolls"):
        arr = shari.get(section, [])
        if isinstance(arr, list):
            fixed = []
            for item in arr:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("player_id", ""))
                if pid in party_ids or not pid:  # 빈 값은 허용(모델 변동 방지)
                    fixed.append(item)
            shari[section] = fixed
        else:
            shari[section] = []
    result["shari"] = shari

    return result


# ----------------------------- 프롬프트 -----------------------------

def _get_genre_interpretation_guide(genre: str) -> str:
    """주어진 장르 이름에 대한 상세한 재해석 가이드를 텍스트로 반환합니다."""
    
    # DB의 Genre 모델 name 필드에 저장된 값을 기반으로 분기합니다.
    if genre == "미스터리":
        return (
            "1. **핵심 재해석**: 이 이야기의 목표는 '누가, 왜, 어떻게 이 사건을 일으켰는가?'라는 수수께끼를 푸는 것이다.\n"
            "2. **서사 스타일**: 모든 묘사는 단서, 증거, 알리바이, 용의자의 숨겨진 동기에 집중한다. 분위기는 긴장감 있고 의심스러워야 한다.\n"
            "3. **능력 해석**: '관찰' 스킬은 숨겨진 단서를 찾는 데, '매력' 스킬은 용의자로부터 증언을 얻어내는 데 사용된다. '마법'은 '프로파일링'이나 '과학 수사' 같은 특수 능력으로 해석된다.\n"
            "4. **선택지/결과 예시**: '현장을 조사하여 지문을 찾는다', '용의자의 알리바이를 추궁한다' 등 수사와 관련된 행동과 결과를 묘사해야 한다."
        )
    
    if genre == "사이버펑크":
        return (
            "1. **핵심 재해석**: 이 이야기의 배경은 거대 기업이 모든 것을 통제하는 미래 도시이다. 목표는 기업의 통제에서 벗어나거나 시스템의 비밀을 파헤치는 것이다.\n"
            "2. **서사 스타일**: 네온사인, 사이버웨어, 해킹, 기업 용병 등의 용어를 적극적으로 사용한다.\n"
            "3. **능력 해석**: '마법'은 '해킹 프로그램'으로, '검'은 '플라즈마 카타나'로, '치유 물약'은 '나노머신 주사기'로 해석된다.\n"
            "4. **선택지/결과 예시**: '보안 시스템을 해킹한다', '뒷골목 정보상과 거래한다' 등 기술과 사회적 상호작용에 집중된 행동과 결과를 묘사해야 한다."
        )
        
    # 기본값 또는 장르 이름이 "판타지"일 경우
    return (
        "1. **핵심 재해석**: 이 이야기의 배경은 마법과 신화가 살아 숨 쉬는 세계이다. 목표는 사악한 존재를 물리치고 세계를 구하는 것이다.\n"
        "2. **서사 스타일**: 고대의 주문, 신화 속의 존재, 마법이 깃든 유물 등 신비롭고 장엄한 분위기를 연출한다.\n"
        "3. **능력 해석**: 스킬, 아이템, 주문을 문자 그대로 해석한다. 검, 마법, 기도 등 고전 판타지의 요소를 충실히 따른다.\n"
        "4. **선택지/결과 예시**: '고대의 룬 문자를 해독한다', '드래곤의 둥지를 습격한다' 등 모험적인 행동과 결과를 묘사해야 한다."
    )

### ▼▼▼▼▼ 1. 난이도/페이스 조절용 헬퍼 함수 추가 ▼▼▼▼▼
def _get_difficulty_instructions(difficulty: str) -> str:
    if difficulty == "상급":
        return "플레이어가 마주하는 역경의 빈도와 강도를 높여라. 성공을 위해서는 자원을 소모하거나 창의적인 해결책이 필요하도록 상황을 묘사하라. 실패 시 명확한 불이익을 부여하라."
    if difficulty == "초급":
        return "플레이어의 행동을 긍정적으로 해석하고, 대부분의 행동이 큰 어려움 없이 성공하도록 서술하라. 역경은 최소화하라."
    # 기본값은 '보통'
    return "성공과 실패가 균형을 이루도록 하라. 논리적인 행동은 보상받아야 하지만, 가끔 예상치 못한 어려움도 발생할 수 있다."

def _get_pacing_instructions(current_turn: int, max_turns: int) -> str:
    if current_turn < max_turns * 0.75: # 게임의 75%가 지나기 전
        return f"현재 {current_turn}턴이다. 이야기의 절정(클라이맥스)을 향해 서서히 긴장감을 고조시켜라."
    elif current_turn >= max_turns:
        # 아래와 같이 "is_final_turn" 키를 포함하도록 명시합니다.
        return f"현재 {current_turn}턴으로, 마지막 턴이다. 반드시 이야기의 모든 갈등을 마무리하고 최종 결말을 제시하라. 응답 JSON 최상단에 `\"is_final_turn\": true` 키를 반드시 포함시켜라."
    else: # 게임 후반부
        return f"현재 {current_turn}턴이다. 이제 이야기의 절정(클라이맥스) 또는 결말을 향해 빠르게 전개하라. 곧 엔딩이 가까워졌음을 암시하라."

GM_SYSTEM = (
    "너는 공정하고 창의적인 TRPG 게임 마스터(GM)이며, 주어진 **{genre} 장르의 전문가**다. "
    "플레이어별로 상호작용적 선택지를 제시하고, 그 선택의 결과를 일관된 세계관과 규칙에 따라 판정한다. "
    "메타 발언/설정 파괴 금지. 플레이 템포는 경쾌하되 과도한 설명은 피한다."
)

PROPOSE_TEMPLATE = """아래의 세션 상태를 바탕으로, **각 플레이어에게 서로 다른 2~3개의 선택지**를 제시하라.

**[게임 규칙]**
- **난이도 규칙**: {difficulty_instructions}
- **게임 진행 페이스**: 이 게임은 총 {max_turns}턴 내외로 진행된다. {pacing_instructions}

**[장르 재해석 가이드: {genre}]**
{genre_interpretation_guide}

제시 원칙:
- 각 플레이어의 역할/시트/기억과 **보유 스킬/아이템/주문**을 고려하여 차별화
- 한글 {language}로 간결하게 작성
- 각 선택지는 "text" 1문장, 필요 시 "tags"(예: "잠입","교섭") 부여
- 최소 1개 선택지는 해당 플레이어의 **핵심 스킬 또는 보유 아이템**을 활용하는 방향을 제시
- 결과는 JSON (스펙 하단)

세션 상태(JSON):
{state_json}

[파티 능력/아이템 요약]
{cap_summary}

응답 JSON 스펙:
{{
  "turn": {next_turn},
  "options": {{
    "PLAYER_ID": [
      {{ "id": "A", "text": "선택지 한 줄", "tags": ["태그"] }},
      {{ "id": "B", "text": "..." }}
    ]
  }}
}}
"""

# === SHARI 전용 Resolve 템플릿 (ANU + 1d6 룰) — 항상 이 템플릿만 사용 ===
RESOLVE_TEMPLATE_SHARI = """아래의 세션 상태와 플레이어 선택을 바탕으로, **한 턴의 결과**를 작성하라.

**[게임 규칙]**
- **난이도 규칙**: {difficulty_instructions}
- **게임 진행 페이스**: 이 게임은 총 {max_turns}턴 내외로 진행된다. {pacing_instructions}

**[장르 재해석 가이드: {genre}]**
{genre_interpretation_guide}

원칙:
- Assess → Narrate → Update(ANU)를 따른다.
- 위험하거나 불확실한 행동은 1d6 판정(1~3 불리, 4~6 유리)을 적용한다.
- 단, **플레이어의 보유 스킬/아이템/주문이 직접적으로 적용되어 위험·불확실성이 충분히 낮아지면** 주사위를 생략해도 된다(안전하고 개연적이면 곧바로 성공으로 처리).
- 플레이어 에이전시를 침해하지 말고(결과만 서술), 세계/파티 상태 갱신을 간단 JSON으로 제시한다.
- 결과는 반드시 JSON으로만.
- 공통 내러티브 문장 수는 최대 4문장, personal은 각 1~2문장으로 제한.
- party 배열 길이는 입력 party와 동일하거나 더 작아야 하며, 각 항목의 changes는 3개 키 이하로 요약.

세션 상태(JSON):
{state_json}

플레이어 선택(JSON):
{choices_json}

[파티 능력/아이템 요약]
{cap_summary}

응답 JSON 스펙:
{{
  "turn": {next_turn},
  "narration": "공통 내러티브 2~4문장",
  "personal": {{ "PLAYER_ID": "개별 묘사 1~2문장" }},
  "world": {{ "time": "새벽", "location": "...", "notes": "..." }},
  "party": [
    {{ "id":"p1", "changes": {{ "hp": -2, "status": ["긴장"] }} }}
  ],
  "log_append": [
    {{ "turn": {prev_turn}, "events": ["p1: A 선택", "p2: B 선택"] }}
  ],

  "shari": {{
    "assess": [
      {{
        "player_id": "p1",
        "action": "원문 선택/행동 요약",
        "move": false,
        "destination": null,
        "dangerous": true,
        "plausible": "Uncertain",
        "win": false,
        "reasons": ["해당 스킬/아이템 고려 여부를 한 줄로 명시"]
      }}
    ],
    "rolls": [
      {{
        "player_id": "p1",
        "reason": "위험/불확실 행동",
        "d6": 5,
        "outcome": "favorable"
      }}
    ],
    "update": {{
      "characterHurt": {{ "p1": false }},
      "currentLocation": "그대로 혹은 이동한 방 ID/명",
      "previousLocation": "이전 위치",
      "notes": "방/출구/적 상태 변화 요약",
      "inventory": {{
        "consumed": {{}},
        "added": {{}},
        "charges": {{}}
      }},
      "skills": {{
        "cooldown": {{}}
      }}
    }}
  }}
}}
"""


# ----------------------------- 엔진 -----------------------------
class AIGameMaster:
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=getattr(settings, "AZURE_OPENAI_API_KEY", None),
            azure_endpoint=getattr(settings, "AZURE_OPENAI_ENDPOINT", None),
            api_version=getattr(settings, "AZURE_OPENAI_VERSION", None),
        )
        self.deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", None)
        missing = [k for k, v in {
            "AZURE_OPENAI_API_KEY": getattr(settings, "AZURE_OPENAI_API_KEY", None),
            "AZURE_OPENAI_ENDPOINT": getattr(settings, "AZURE_OPENAI_ENDPOINT", None),
            "AZURE_OPENAI_VERSION": getattr(settings, "AZURE_OPENAI_VERSION", None),
            "AZURE_OPENAI_DEPLOYMENT": self.deployment,
        }.items() if not v]
        if missing:
            raise RuntimeError(f"Azure OpenAI 설정 누락: {', '.join(missing)}")

    # 1) 선택지 제안
    def propose_choices(
        self,
        state: Dict[str, Any],
        language: str = "ko",
        temperature: float = 0.6,
        top_p: float = 0.9,
        max_tokens: int = 1400,
    ) -> Dict[str, Any]:
        next_turn = int(state.get("turn", 0)) + 1
        state_json = json.dumps(state, ensure_ascii=False)
        cap_summary = _summarize_party_capabilities(state)
        scenario = state.get("scenario", {})
        genre = scenario.get("genre", "판타지")
        difficulty = state.get("difficulty", "중급")
        current_turn = state.get("turn", 1)
        max_turns = 10 # 최대 턴 수 설정

        genre_guide = _get_genre_interpretation_guide(genre)
        difficulty_instructions = _get_difficulty_instructions(difficulty)
        pacing_instructions = _get_pacing_instructions(current_turn, max_turns)        

        prompt = PROPOSE_TEMPLATE.format(
            state_json=state_json,
            next_turn=next_turn,
            language=language,
            cap_summary=cap_summary,
            genre=genre,                      
            genre_interpretation_guide=genre_guide,
            difficulty_instructions=difficulty_instructions,
            max_turns=max_turns,
            pacing_instructions=pacing_instructions            
        )
        logger.debug(
            "propose_choices: tokens[max]=%s, state_len=%s, cap_len=%s",
            max_tokens, len(state_json), len(cap_summary)
        )

        system_prompt_content = GM_SYSTEM.format(genre=genre)

        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system_prompt_content},
                      {"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content
        logger.debug("propose_choices: response_len=%s", len(txt or ""))
        try:
            return json.loads(_extract_json_block(txt))
        except Exception as e:
            logger.exception("선택지 JSON 파싱 실패: %s", e)
            raise ValueError("선택지 JSON 파싱 실패(응답 형식 오류).")

    # 2) 턴 해결(선택 반영) — SHARI 고정 + 능력/아이템 반영
    def resolve_turn(
        self,
        state: Dict[str, Any],
        choices: Dict[str, Any],
        language: str = "ko",
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_tokens: int = 2500,
    ) -> Dict[str, Any]:
        next_turn = int(state.get("turn", 0)) + 1
        prev_turn = next_turn - 1

        # (선택) 클라가 붙여 보낸 고정 주사위 힌트 읽기
        rolls_hint: Dict[str, int] = {}
        try:
            rh = choices.get("_rolls") or {}
            if isinstance(rh, dict):
                rolls_hint = {
                    str(k): int(v) for k, v in rh.items()
                    if isinstance(v, (int, float)) and 1 <= int(v) <= 6
                }
        except Exception:
            rolls_hint = {}

        extra_hint = ""
        if rolls_hint:
            extra_hint = (
                "\n\n[고정 주사위 결과]\n"
                + json.dumps(rolls_hint, ensure_ascii=False)
                + "\n"
                + "위 값이 제공된 플레이어의 판정에는 반드시 해당 d6 값을 사용하라."
            )

        state_json = json.dumps(state, ensure_ascii=False)
        choices_json = json.dumps(choices, ensure_ascii=False)
        cap_summary = _summarize_party_capabilities(state)
        scenario = state.get("scenario", {})
        genre = scenario.get("genre", "판타지")
        difficulty = state.get("difficulty", "중급")
        current_turn = state.get("turn", 1)
        max_turns = 10 # 최대 턴 수 설정

        genre_guide = _get_genre_interpretation_guide(genre)
        difficulty_instructions = _get_difficulty_instructions(difficulty)
        pacing_instructions = _get_pacing_instructions(current_turn, max_turns)

        prompt = RESOLVE_TEMPLATE_SHARI.format(
            state_json=state_json,
            choices_json=choices_json,
            next_turn=next_turn,
            prev_turn=prev_turn,
            language=language,
            cap_summary=cap_summary,
            genre=genre,                      
            genre_interpretation_guide=genre_guide,
            difficulty_instructions=difficulty_instructions,
            max_turns=max_turns,
            pacing_instructions=pacing_instructions            
        ) + extra_hint

        logger.debug(
            "resolve_turn: tokens[max]=%s, state_len=%s, choices_len=%s, cap_len=%s, rolls_hint=%s",
            max_tokens, len(state_json), len(choices_json), len(cap_summary), bool(rolls_hint)
        )

        system_prompt_content = GM_SYSTEM.format(genre=genre)

        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system_prompt_content},
                      {"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content
        logger.debug("resolve_turn: response_len=%s", len(txt or ""))

        try:
            result = json.loads(_extract_json_block(txt))
        except Exception as e:
            logger.exception("해결 JSON 파싱 실패: %s", e)
            raise ValueError("해결 JSON 파싱 실패(응답 형식 오류).")

        # 결과 보정 (필수 키/개인 묘사/인벤토리·스킬 구조 등)
        result = _normalize_result(state, result)
        # ✅ (신규) 이번 턴 장면 이미지 생성
        if IMAGE_GEN_ENABLED:
            try:
                scene_prompt = build_scene_prompt(state, result)  # 현 상태 + 이번 턴 결과를 반영
                img_res = generate_scene_image(
                    scene_prompt,
                    size="1024x1024",
                    quality="standard",
                    style="vivid",
                    n=1
                )
                if img_res.get("ok"):
                    data = (img_res["result"].get("data") or [])
                    image_url = data[0].get("url") if data else None
                    result["image"] = {
                        "url": image_url,
                        "prompt": img_res.get("prompt")
                    }
                else:
                    result["image"] = {
                        "url": None,
                        "error": img_res.get("error"),
                        "prompt": img_res.get("prompt")
                    }
            except Exception as e:
                # 로거가 있으니 그대로 사용
                logger.exception("이미지 생성 실패: %s", e)
                result["image"] = {"url": None, "error": str(e)}
        return result


# ----------------------------- 결과 병합 -----------------------------
def apply_gm_result_to_state(state: dict, result: dict) -> dict:
    """
    GM 결과(JSON)를 세션 상태(state)에 반영해서 '다음 턴의 상태'를 돌려줍니다.
    - world/party/log 기본 반영
    - shari.update의 inventory/skills/characterHurt/location 반영
    - party[].sheet.hp / status는 예시로 처리(프로젝트 규약에 맞게 커스터마이즈 가능)
    """
    import copy
    new_state = copy.deepcopy(state)

    # 1) 기본 세계/로그/턴
    if "world" in result and isinstance(result["world"], dict):
        new_state.setdefault("world", {}).update(result["world"])
    for entry in result.get("log_append", []) or []:
        if isinstance(entry, dict):
            new_state.setdefault("log", []).append(entry)
    new_state["turn"] = int(state.get("turn", 0)) + 1

    # 2) 파티 변경(체력/상태 등)
    party_index = {str(p.get("id")): i for i, p in enumerate(new_state.get("party", [])) if isinstance(p, dict)}
    for change in result.get("party", []) or []:
        if not isinstance(change, dict):
            continue
        pid = str(change.get("id"))
        idx = party_index.get(pid)
        if idx is None:
            continue
        target = new_state["party"][idx]
        ch = change.get("changes") or {}
        sheet = target.setdefault("sheet", {})
        # HP 변화
        if "hp" in ch:
            try:
                sheet["hp"] = int(sheet.get("hp", 0)) + int(ch["hp"])
            except Exception:
                pass
        # status 병합
        if "status" in ch:
            old = set(map(str, sheet.get("status", [])))
            new = set(map(str, ch.get("status", [])))
            sheet["status"] = list(old | new)

    # 3) SHARI 업데이트(인벤토리/쿨다운/부상/위치)
    upd = (result.get("shari") or {}).get("update") or {}

    # 3-1) 위치 이동
    cur = upd.get("currentLocation")
    if cur:
        new_state.setdefault("world", {})["location"] = cur
    prev = upd.get("previousLocation")
    if prev is not None:
        new_state.setdefault("world", {})["prev_location"] = prev

    # 3-2) 부상 누적(2회=사망 규칙 등은 상위 룰 엔진에서 해석)
    churt = upd.get("characterHurt") or {}
    hc = new_state.setdefault("hurt_count", {})
    for pid, hurt in churt.items():
        if hurt:
            hc[pid] = int(hc.get(pid, 0)) + 1

    # 3-3) 인벤토리 반영
    inv = upd.get("inventory") or {}
    consumed = inv.get("consumed") or {}
    added = inv.get("added") or {}
    charges = inv.get("charges") or {}

    def _each_party_items(pid: str):
        i = party_index.get(pid)
        if i is None:
            return None
        p = new_state["party"][i]
        sheet = p.setdefault("sheet", {})
        items = sheet.setdefault("items", [])
        spells = sheet.setdefault("spells", [])
        return items, spells

    # 소비 제거
    for pid, names in consumed.items():
        pair = _each_party_items(pid)
        if not pair:
            continue
        items, spells = pair
        names = set(map(str, names or []))

        def _filter(l):
            out = []
            for it in l:
                if isinstance(it, dict):
                    n = str(it.get("name"))
                else:
                    n = str(it)
                if n not in names:
                    out.append(it)
            return out

        sheet = new_state["party"][party_index[pid]]["sheet"]
        sheet["items"] = _filter(items)
        sheet["spells"] = _filter(spells)

    # 획득 추가
    for pid, names in added.items():
        pair = _each_party_items(pid)
        if not pair:
            continue
        items, _ = pair
        for n in names or []:
            items.append(n)  # 문자열 또는 dict 그대로 추가

    # 충전/내구도 증감
    for pid, name_delta in charges.items():
        pair = _each_party_items(pid)
        if not pair:
            continue
        items, spells = pair

        def _apply_delta(lst):
            for it in lst:
                if isinstance(it, dict):
                    n = str(it.get("name"))
                    if n in name_delta:
                        try:
                            it["charges"] = int(it.get("charges", 0)) + int(name_delta[n])
                        except Exception:
                            pass

        _apply_delta(items)
        _apply_delta(spells)

    # 3-4) 스킬 쿨다운
    skl = upd.get("skills") or {}
    cooldown = skl.get("cooldown") or {}
    cdstore = new_state.setdefault("cooldowns", {})  # {"p1":{"전력질주": 2}}
    for pid, skill_turns in cooldown.items():
        bucket = cdstore.setdefault(pid, {})
        for sname, turns in (skill_turns or {}).items():
            try:
                bucket[str(sname)] = int(turns)
            except Exception:
                continue

    return new_state


# ----------------------------- (선택) DRF 뷰 -----------------------------
try:
    from rest_framework.views import APIView
    from rest_framework.permissions import IsAuthenticated
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from django.http import JsonResponse
except Exception:
    APIView = object  # 타입만 맞추는 더미


class ProposeAPIView(APIView):  # type: ignore
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        state = request.data.get("state")
        language = (request.data.get("language") or "ko").strip()
        if not isinstance(state, dict):
            return JsonResponse({"message": "state(JSON)가 필요합니다."}, status=400)
        try:
            gm = AIGameMaster()
            out = gm.propose_choices(state, language=language)
            return JsonResponse({"message": "선택지 생성 성공", "data": out}, status=200)
        except Exception as e:
            return JsonResponse({"message": f"선택지 생성 실패: {e}"}, status=500)


class ResolveAPIView(APIView):  # type: ignore
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        state = request.data.get("state")
        choices = request.data.get("choices")
        language = (request.data.get("language") or "ko").strip()
        if not isinstance(state, dict) or not isinstance(choices, dict):
            return JsonResponse({"message": "state, choices(JSON)가 필요합니다."}, status=400)

        # 입력 방어: 파티 id 화이트리스트 검증
        try:
            party_ids = {str(p.get("id")) for p in state.get("party", []) if isinstance(p, dict)}
            invalid = [pid for pid in choices.keys() if pid not in party_ids and pid != "_rolls"]
            if invalid:
                return JsonResponse({"message": f"유효하지 않은 플레이어 id: {invalid}"}, status=400)
        except Exception:
            pass

        try:
            gm = AIGameMaster()
            out = gm.resolve_turn(state, choices, language=language)

            # 여기서 바로 세션 상태에 반영하고 반환하고 싶다면 아래 주석 해제:
            # new_state = apply_gm_result_to_state(state, out)
            # return JsonResponse({"message": "턴 해결 성공", "data": out, "next_state": new_state}, status=200)

            return JsonResponse({"message": "턴 해결 성공", "data": out}, status=200)
        except Exception as e:
            return JsonResponse({"message": f"턴 해결 실패: {e}"}, status=500)