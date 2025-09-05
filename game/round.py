#backend\game\round.py
import random
from .scenarios_realtime import get_scene_template
from .scenarios_turn import get_scene_template as get_turn_based_template 

from .state import GameState

def roll_dice():
    return random.randint(1, 20)

def map_grade(dice, total, DC):
    if dice == 20:
        return "SP"
    if dice == 1:
        return "SF"
    if total >= DC + 4:
        return "SP"
    if total >= DC:
        return "S"
    if total >= DC - 3:
        return "F"
    return "SF"

async def perform_round_judgement(room_id, scene_index):
    """서버에서 판정 수행 후 결과 리턴"""
    template = get_scene_template(scene_index)
    round_spec = template["round"]

    choices = await GameState.get_choices(room_id, scene_index)
    results = []
    logs = []

    for role, choice_id in choices.items():
        choice = None
        for c in round_spec["choices"].get(role, []):
            if c["id"] == choice_id:
                choice = c
                break

        dice = roll_dice()
        stat_value = 2  # TODO: DB에서 해당 캐릭터 스탯 가져오기
        total = dice + stat_value + choice["modifier"]
        DC = 10  # TODO: 난이도별 DC 가져오기

        grade = map_grade(dice, total, DC)
        log = f"{role}: d20={dice} + {choice['appliedStat']}({stat_value}) + 보정({choice['modifier']}) = {total} → {grade}"

        results.append({
            "role": role,
            "choiceId": choice_id,
            "grade": grade,
            "dice": dice,
            "appliedStat": choice["appliedStat"],
            "statValue": stat_value,
            "modifier": choice["modifier"],
            "total": total,
        })
        logs.append(log)

    payload = {"sceneIndex": scene_index, "results": results, "logs": logs}
    return payload

async def perform_turn_judgement(room_id, scene_index, role, choice_id):
    """단일 플레이어의 턴에 대한 판정을 수행"""
    template = get_turn_based_template(scene_index)
    
    # 해당 씬의 턴 순서에서 현재 역할(role)의 턴 정보를 찾음
    turn_spec = None
    for turn in template.get("turns", []):
        if turn["role"] == role:
            turn_spec = turn
            break
    
    # 선택지 정보를 찾음
    choice = None
    for c in turn_spec["choices"]:
        if c["id"] == choice_id:
            choice = c
            break

    dice = roll_dice()
    stat_value = 2  # TODO: DB에서 스탯 가져오기
    total = dice + stat_value + choice["modifier"]
    DC = 10  # TODO: 난이도별 DC 가져오기
    grade = map_grade(dice, total, DC)
    
    log = f"{role}: d20={dice} + {choice['appliedStat']}({stat_value}) + 보정({choice['modifier']}) = {total} → {grade}"

    result = {
        "role": role,
        "choiceId": choice_id,
        "grade": grade,
        "dice": dice,
        "appliedStat": choice["appliedStat"],
        "statValue": stat_value,
        "modifier": choice["modifier"],
        "total": total,
    }
    
    return {"sceneIndex": scene_index, "result": result, "log": log}