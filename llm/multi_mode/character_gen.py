# -*- coding: utf-8 -*-
"""
llm/multi_mode/character_gen.py

시나리오 설명/요약을 입력받아 캐릭터(1~N명)를 JSON 스펙에 맞게 생성합니다.
- Azure OpenAI (chat.completions) 사용
- JSON 강제(response_format) + 안전 파싱 보강
- (선택) Django 모델(Character)에 저장하는 헬퍼 제공

환경변수/설정 (settings.py):
AZURE_OPENAI_API_KEY
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_VERSION
AZURE_OPENAI_DEPLOYMENT

사용 예:
    gen = CharacterGenerator()
    chars = gen.generate_characters(
        scenario_text="사막의 고성에서 공주를 구출하는 하이판타지",
        count=3,
        language="ko"
    )
    # (선택) DB 저장
    gen.persist_characters(scenario_id, chars)
"""
from __future__ import annotations
import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings

# Azure OpenAI (openai>=1.x 계열)
from openai import AzureOpenAI

# (선택) DB 저장을 위한 import — 없으면 무시 가능
try:
    from ..models import Character  # 프로젝트 구조에 맞게 조정
except Exception:
    Character = None  # 저장 기능을 안 쓰는 경우를 허용


def _extract_json_block(text: str) -> str:
    """```json ...``` 혹은 중괄호/대괄호 블록을 안전히 추출."""
    if not text:
        return "{}"
    fence = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if fence:
        return fence.group(1).strip()
    bracket = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if bracket:
        return bracket.group(1).strip()
    return text.strip()


CHARACTER_JSON_SPEC = """\
[
  {
    "name": "이름(고유)",
    "description": "한 줄 소개",
    "items": ["아이템1","아이템2"],
    "ability": {
      "stats": {"힘":5,"민첩":6,"지식":7,"의지":5,"매력":6,"운":4},
      "skills": ["스킬1","스킬2"]
    },
    "image_prompt": "이미지 생성용 자연어 프롬프트(선택)"
  }
]
"""

SYSTEM_PROMPT = (
    "너는 TRPG 캐릭터 생성 전문가다. 시나리오에 적합하고 파티 밸런스를 고려한 캐릭터를 만든다. "
    "과장되지 않게, 게임에 바로 쓸 수 있도록 간결하고 일관된 톤으로 작성한다."
)

USER_TEMPLATE = """아래 시나리오를 바탕으로 캐릭터 {count}명을 만들어라.

요구사항:
- 언어: {language}
- 각 캐릭터는 역할/전술/서사를 분산하여 파티 밸런스를 갖출 것
- ability.stats는 1~10 정수만 사용
- 결과는 반드시 JSON 배열(스펙 하단)에 맞출 것

시나리오:
{scenario_text}

JSON 스펙:
{json_spec}
"""


class CharacterGenerator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
        deployment: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or getattr(settings, "AZURE_OPENAI_API_KEY", None)
        self.endpoint = endpoint or getattr(settings, "AZURE_OPENAI_ENDPOINT", None)
        self.api_version = api_version or getattr(settings, "AZURE_OPENAI_VERSION", None)
        self.deployment = deployment or getattr(settings, "AZURE_OPENAI_DEPLOYMENT", None)

        missing = [k for k, v in {
            "AZURE_OPENAI_API_KEY": self.api_key,
            "AZURE_OPENAI_ENDPOINT": self.endpoint,
            "AZURE_OPENAI_VERSION": self.api_version,
            "AZURE_OPENAI_DEPLOYMENT": self.deployment
        }.items() if not v]
        if missing:
            raise RuntimeError(f"Azure OpenAI 설정 누락: {', '.join(missing)}")

        self.client = AzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
        )

    def generate_characters(
        self,
        scenario_text: str,
        count: int = 3,
        language: str = "ko",
        temperature: float = 0.7,
        top_p: float = 0.95,
        max_tokens: int = 1800,
    ) -> List[Dict[str, Any]]:
        """시나리오를 기반으로 캐릭터 N명을 생성."""
        user_content = USER_TEMPLATE.format(
            count=count,
            language=language,
            scenario_text=scenario_text.strip(),
            json_spec=CHARACTER_JSON_SPEC,
        )

        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},  # 지원 안되면 주석 처리하고 _extract_json_block 사용
        )
        text = resp.choices[0].message.content
        try:
            data = json.loads(_extract_json_block(text))
        except Exception as e:
            raise ValueError(f"생성 JSON 파싱 실패: {e} / 원문 일부: {text[:200]}")

        # data가 {"characters":[...]} 형태로 올 수도 있으니 보정
        if isinstance(data, dict) and "characters" in data:
            data = data["characters"]

        if not isinstance(data, list):
            raise ValueError("응답은 JSON 배열이어야 합니다.")

        # 필드 보정 및 검증(필요 최소한)
        normalized: List[Dict[str, Any]] = []
        for ch in data[:count]:
            name = (ch.get("name") or "").strip()
            if not name:
                continue
            normalized.append({
                "name": name,
                "description": (ch.get("description") or "").strip(),
                "items": list(ch.get("items") or []),
                "ability": ch.get("ability") or {"stats": {}, "skills": []},
                "image_prompt": (ch.get("image_prompt") or "").strip()
            })
        return normalized

    def persist_characters(self, scenario_id: str, characters: List[Dict[str, Any]]) -> List[str]:
        """
        (선택) Character 모델에 저장. 프로젝트 모델 구조에 따라 수정.
        models.Character가 없으면 RuntimeError.
        """
        if Character is None:
            raise RuntimeError("Character 모델을 찾을 수 없습니다. 저장 기능을 사용하려면 import 경로를 조정하세요.")

        created_ids: List[str] = []
        for ch in characters:
            obj = Character.objects.create(
                scenario_id=scenario_id,
                name=ch["name"],
                description=ch.get("description", ""),
                items={"items": ch.get("items", [])},  # JSONField(dict)로 저장
                ability=ch.get("ability", {}),
                image_path=None,
            )
            created_ids.append(str(obj.id))
        return created_ids


# -------------------------------------------------------------------
# (선택) DRF 뷰 — /llm/multi_mode/characters/generate
# urls.py에 연결:
#   path("llm/multi_mode/characters/generate", CharacterGenerateAPIView.as_view()),
# -------------------------------------------------------------------
try:
    from rest_framework.views import APIView
    from rest_framework.permissions import IsAuthenticated
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from django.http import JsonResponse
    from django.utils.decorators import method_decorator
except Exception:
    APIView = object  # 타입만 만족시키는 더미

class CharacterGenerateAPIView(APIView):  # type: ignore
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        scenario_text = (request.data.get("scenario_text") or "").strip()
        scenario_id = request.data.get("scenario_id")
        count = int(request.data.get("count") or 3)
        language = (request.data.get("language") or "ko").strip()
        save = str(request.data.get("save") or "false").lower() in ("true", "1", "yes")

        if not scenario_text and not scenario_id:
            return JsonResponse({"message": "scenario_text 또는 scenario_id가 필요합니다."}, status=400)

        # scenario_id만 왔으면 DB에서 설명/요약을 읽어 scenario_text로 사용하도록 프로젝트에 맞게 구현하세요.
        if not scenario_text and scenario_id:
            try:
                from ..models import Scenario  # 경로는 프로젝트에 맞게 수정
                scn = Scenario.objects.get(id=scenario_id)
                scenario_text = (scn.description or scn.title or "Untitled").strip()
            except Exception:
                return JsonResponse({"message": "시나리오를 찾을 수 없거나 설명이 비어있습니다."}, status=404)

        try:
            gen = CharacterGenerator()
            characters = gen.generate_characters(scenario_text, count=count, language=language)
            result = {"message": "캐릭터 생성 성공", "characters": characters}
            if save and scenario_id:
                ids = gen.persist_characters(scenario_id, characters)
                result["saved_ids"] = ids
            return JsonResponse(result, status=201)
        except Exception as e:
            return JsonResponse({"message": f"캐릭터 생성 실패: {e}"}, status=500)
