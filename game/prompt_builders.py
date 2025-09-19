# -*- coding: utf-8 -*-
# game/prompt_builders.py
from typing import Dict, Any, List, Optional
import textwrap

MAX_LOG_ITEMS = 12

def _compact_history(log: List[Dict[str, Any]]) -> str:
    if not log:
        return "이전 내러티브 없음."
    use = log[-MAX_LOG_ITEMS:]
    lines = []
    for ev in use:
        t = ev.get("turn")
        nar = (ev.get("narration") or ev.get("story") or "" ).strip().replace("\n", " ")
        if nar:
            lines.append(f"[턴 {t}] {nar}")
    return " / ".join(lines) if lines else "이전 내러티브 없음."

def _describe_party(party: List[Dict[str, Any]]) -> str:
    if not party:
        return "파티 정보 없음."
    chunks = []
    for p in party:
        name = p.get("name") or p.get("id") or "이름미상"
        role = p.get("role") or "역할미상"
        sheet = p.get("sheet") or {}
        hp = sheet.get("hp", "N/A")
        status = sheet.get("status") or {}
        hurt = [k for k, v in status.items() if v]
        hurt_s = ", ".join(hurt) if hurt else "이상 없음"
        chunks.append(f"{name}({role}) HP:{hp}, 상태:{hurt_s}")
    return " / ".join(chunks)

def _describe_world(world: Dict[str, Any]) -> str:
    if not world:
        return "세계 정보 없음."
    time = world.get("time") or "시간 불명"
    loc = world.get("location") or "장소 불명"
    weather = world.get("weather")
    notes = world.get("notes")
    extra = []
    if weather:
        extra.append(f"날씨:{weather}")
    if notes:
        extra.append(notes.strip().replace("\n", " "))
    extra_s = (" / ".join(extra)) if extra else "추가 정보 없음"
    return f"{time}, {loc} ({extra_s})"

def build_scene_prompt(session_state: Dict[str, Any], gm_result: Optional[Dict[str, Any]] = None) -> str:
    scenario = session_state.get("scenario", {})
    world = session_state.get("world", {})
    party = session_state.get("party", [])
    log = session_state.get("log", [])

    title = scenario.get("title") or "제목 미상 시나리오"
    world_s = _describe_world(world)
    party_s = _describe_party(party)
    hist_s = _compact_history(log)

    turn_focus = ""
    if gm_result:
        key_nar = (gm_result.get("narration") or "").strip().replace("\n", " ")
        if key_nar:
            turn_focus = f"이번 장면의 핵심: {key_nar}"

    style_guide = (
        "— 장면 묘사 지시 — "
        "텍스트/자막/간판의 글씨는 넣지 말 것. "
        "주요 인물의 의상/표정/자세, 주변 배경(지형/구조물/소품), "
        "조명(달빛/횃불 등), 색감, 카메라 구도(로우 앵글/와이드 샷 등)를 구체적으로. "
        "실사풍과 일러스트풍 사이에서 시네마틱하게."
    )

    prompt = textwrap.dedent(f"""
    [시나리오] {title}
    [세계] {world_s}
    [파티] {party_s}
    [이전 요약] {hist_s}
    {turn_focus}

    {style_guide}
    """).strip()

    return prompt
