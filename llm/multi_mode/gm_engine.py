# -*- coding: utf-8 -*-
"""
llm/multi_mode/gm_engine.py

멀티플레이 TRPG의 AI GM 엔진.
- 각 플레이어에게 **서로 다른 선택지**를 제시 (propose_choices)
- 플레이어 입력(선택)을 모아 **다음 턴 내러티브/상태**를 계산 (resolve_turn)
- 세션 상태는 호출자가 관리(캐시/DB). 본 모듈은 상태 JSON을 입력/출력으로만 다룸.

상태(JSON) 최소 스펙:
{
  "session_id": "uuid 혹은 식별자",
  "turn": 1,
  "scenario": { "title": "...", "summary": "..." },
  "world": { "time": "밤", "location": "폐허 성곽", "notes": "..." },
  "party": [{ "id": "p1", "name": "엘라", "role": "정찰수", "sheet": {...}, "memory": "..." }, ...],
  "log": [ {"turn":0, "narration":"..."}, ... ]
}

선택지 제안 응답:
{
  "turn": 1,
  "options": {
    "p1": [{"id":"A","text":"...","rationale":"...","tags":["잠입"]}, ... up to 3],
    "p2": [...]
  }
}

해결 응답:
{
  "turn": 2,
  "narration": "공통 내러티브",
  "personal": { "p1":"개별 묘사", "p2":"..." },
  "world": {...업데이트...},
  "party": [...필요 시 능력/상태 갱신...],
  "log_append": [{...}, ...]
}
"""
from __future__ import annotations
import re
import json
from typing import Any, Dict, List, Optional

from django.conf import settings
from openai import AzureOpenAI


def _extract_json_block(text: str) -> str:
    if not text:
        return "{}"
    import re
    fence = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if fence:
        return fence.group(1).strip()
    bracket = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if bracket:
        return bracket.group(1).strip()
    return text.strip()


GM_SYSTEM = (
    "너는 공정하고 창의적인 TRPG 게임 마스터(GM)다. "
    "플레이어별로 상호작용적 선택지를 제시하고, 그 선택의 결과를 일관된 세계관과 규칙에 따라 판정한다. "
    "메타 발언/설정 파괴 금지. 플레이 템포는 경쾌하되 과도한 설명은 피한다."
)

PROPOSE_TEMPLATE = """아래의 세션 상태를 바탕으로, **각 플레이어에게 서로 다른 2~3개의 선택지**를 제시하라.

제시 원칙:
- 각 플레이어의 역할/시트/기억을 고려하여 차별화
- 한글 {language}로 간결하게 작성
- 각 선택지는 "text" 1문장, 필요 시 "tags"(예: "잠입","교섭") 부여
- 결과는 JSON (스펙 하단)

세션 상태(JSON):
{state_json}

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

RESOLVE_TEMPLATE = """아래의 세션 상태와 플레이어들의 선택을 바탕으로, **한 턴의 결과**를 작성하라.

원칙:
- 공통 내러티브 + 플레이어별 비밀/개별 묘사를 함께 제공
- 세계 상태(world), 파티 상태(party)의 변화를 간단 JSON으로 제시
- 한글 {language}, 간결하고 진행 친화적으로
- 결과는 반드시 JSON (스펙 하단)

세션 상태(JSON):
{state_json}

플레이어 선택(JSON):
{choices_json}

응답 JSON 스펙:
{{
  "turn": {next_turn},
  "narration": "공통 내러티브 2~4문장",
  "personal": {{ "PLAYER_ID": "개별 묘사 1~2문장" }},
  "world": {{ "time": "새벽", "location": "..." , "notes": "..." }},
  "party": [
    {{ "id":"p1", "changes": {{ "hp": -2, "status": ["긴장"] }} }}
  ],
  "log_append": [
    {{ "turn": {next_turn-1}, "events": ["p1: A 선택", "p2: B 선택"] }}
  ]
}}
"""


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

    # ---------------------------
    # 1) 선택지 제안
    # ---------------------------
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
        prompt = PROPOSE_TEMPLATE.format(
            state_json=state_json,
            next_turn=next_turn,
            language=language
        )
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": GM_SYSTEM},
                      {"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content
        try:
            return json.loads(_extract_json_block(txt))
        except Exception as e:
            raise ValueError(f"선택지 JSON 파싱 실패: {e} / 원문 일부: {txt[:200]}")

    # ---------------------------
    # 2) 턴 해결(선택 반영)
    # ---------------------------
    def resolve_turn(
        self,
        state: Dict[str, Any],
        choices: Dict[str, Any],
        language: str = "ko",
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_tokens: int = 1800,
    ) -> Dict[str, Any]:
        next_turn = int(state.get("turn", 0)) + 1
        prompt = RESOLVE_TEMPLATE.format(
            state_json=json.dumps(state, ensure_ascii=False),
            choices_json=json.dumps(choices, ensure_ascii=False),
            next_turn=next_turn,
            language=language
        )
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": GM_SYSTEM},
                      {"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content
        try:
            result = json.loads(_extract_json_block(txt))
        except Exception as e:
            raise ValueError(f"해결 JSON 파싱 실패: {e} / 원문 일부: {txt[:200]}")

        # 호출자가 state를 저장하기 쉽게 약간 보정: turn 업데이트
        result.setdefault("turn", next_turn)
        return result


# -------------------------------------------------------------------
# (선택) DRF 뷰 — /llm/multi_mode/gm/propose , /llm/multi_mode/gm/resolve
# urls.py 예시:
#   path("llm/multi_mode/gm/propose", ProposeAPIView.as_view()),
#   path("llm/multi_mode/gm/resolve", ResolveAPIView.as_view()),
# -------------------------------------------------------------------
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
        try:
            gm = AIGameMaster()
            out = gm.resolve_turn(state, choices, language=language)
            return JsonResponse({"message": "턴 해결 성공", "data": out}, status=200)
        except Exception as e:
            return JsonResponse({"message": f"턴 해결 실패: {e}"}, status=500)
