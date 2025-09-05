import redis.asyncio as aioredis
from .scenarios_turn import get_scene_template
import json

REDIS_URL = "redis://localhost:6379"

class GameState:
    @staticmethod
    async def _get_conn():
        # redis.asyncio.from_url 로 연결
        return aioredis.from_url(REDIS_URL, decode_responses=True)

    @staticmethod
    async def ensure_scene(room_id, scene_index):
        conn = await GameState._get_conn()
        key = f"game:{room_id}:scene_index"
        await conn.set(key, scene_index)

    @staticmethod
    async def store_choice(room_id, scene_index, role, choice_id):
        conn = await GameState._get_conn()
        key = f"game:{room_id}:scene:{scene_index}:choices"
        await conn.hset(key, role, choice_id)

    @staticmethod
    async def get_choices(room_id, scene_index):
        conn = await GameState._get_conn()
        key = f"game:{room_id}:scene:{scene_index}:choices"
        return await conn.hgetall(key)

    @staticmethod
    async def check_all_submitted(room_id, scene_index):
        # TODO: 방 인원 수 확인해서 비교 (일단은 3명이라고 가정)
        conn = await GameState._get_conn()
        key = f"game:{room_id}:scene:{scene_index}:choices"
        choices = await conn.hgetall(key)
        return len(choices) >= 3

    @staticmethod
    async def advance_scene(room_id, scene_index):
        next_index = scene_index + 1
        conn = await GameState._get_conn()
        await conn.set(f"game:{room_id}:scene_index", next_index)
        return next_index
    
    @staticmethod
    async def get_game_state(room_id):
        """방의 전체 게임 상태를 불러옵니다."""
        conn = await GameState._get_conn()
        state_json = await conn.get(f"game:{room_id}:state")
        if state_json:
            return json.loads(state_json)
        return None

    @staticmethod
    async def set_game_state(room_id, state):
        """방의 전체 게임 상태를 저장합니다."""
        conn = await GameState._get_conn()
        await conn.set(f"game:{room_id}:state", json.dumps(state))
    
    @staticmethod
    async def initialize_turn_order(room_id, scene_index):
        """씬 시작 시 턴 순서와 현재 턴 인덱스를 초기화"""
        conn = await GameState._get_conn()
        template = get_scene_template(scene_index) # 턴제용 템플릿 사용
        if not template or "turns" not in template:
            return

        turn_order = [turn["role"] for turn in template["turns"]]
        
        # 턴 순서(리스트)와 현재 턴 인덱스(0)를 저장
        await conn.set(f"game:{room_id}:scene:{scene_index}:turn_order", json.dumps(turn_order))
        await conn.set(f"game:{room_id}:scene:{scene_index}:current_turn_index", 0)

    @staticmethod
    async def record_turn_roll(room_id, player_id, roll):
        conn = await GameState._get_conn()
        await conn.hset(f"game:{room_id}:turn_rolls", player_id, roll)

    @staticmethod
    async def get_all_turn_rolls(room_id):
        conn = await GameState._get_conn()
        return await conn.hgetall(f"game:{room_id}:turn_rolls")

    @staticmethod
    async def get_current_turn_role(room_id, scene_index):
        """현재 턴인 역할(role)을 반환"""
        conn = await GameState._get_conn()
        order_str = await conn.get(f"game:{room_id}:scene:{scene_index}:turn_order")
        turn_order = json.loads(order_str)
        
        index_str = await conn.get(f"game:{room_id}:scene:{scene_index}:current_turn_index")
        current_index = int(index_str)
        
        return turn_order[current_index]

    @staticmethod
    async def advance_turn(room_id, scene_index):
        """턴을 1 증가시키고, 다음 턴 역할(role)을 반환. 마지막 턴이면 None 반환"""
        conn = await GameState._get_conn()
        order_str = await conn.get(f"game:{room_id}:scene:{scene_index}:turn_order")
        turn_order = json.loads(order_str)

        # 현재 턴 인덱스를 1 증가시킴
        new_index = await conn.incr(f"game:{room_id}:scene:{scene_index}:current_turn_index")

        if new_index < len(turn_order):
            return turn_order[new_index]
        else:
            return None
