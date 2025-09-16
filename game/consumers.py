# backend/game/consumers.py
import json
import re
from uuid import UUID
import random
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache

from openai import AsyncAzureOpenAI
import os
from dotenv import load_dotenv

from django.contrib.auth.models import AnonymousUser

from game.models import MultimodeSession, GameRoom, GameJoin, GameRoomSelectScenario, Scenario, Character
from game.serializers import GameJoinSerializer
from .scenarios_turn import get_scene_template
from .round import perform_turn_judgement
from .state import GameState

# ★ SHARI 엔진 연동
from asgiref.sync import sync_to_async
from llm.multi_mode.gm_engine import AIGameMaster, apply_gm_result_to_state  # ★

# .env 파일 로드
load_dotenv()

# LLM 클라이언트 초기화 (씬 생성/요약 등 기존 용도 유지)
oai_client = AsyncAzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview"),
)
OAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")


@database_sync_to_async
def _get_character_from_db(character_id):
    try:
        # UUID 문자열을 UUID 객체로 변환하여 검색
        return Character.objects.get(id=UUID(character_id))
    except (Character.DoesNotExist, ValueError):
        return None

@database_sync_to_async
def _ensure_participant(room_id, user):
    print(f"➡️ ensure_participant: room={room_id}, user={user}")
    if not user or not user.is_authenticated:
        return None
    room = GameRoom.objects.filter(id=room_id).first()
    if not room:
        return None
    participant, _ = GameJoin.objects.get_or_create(gameroom=room, user=user)
    return participant

def _get_room_state_from_cache(room_id):
    state = cache.get(f"room_{room_id}_state")
    if state is None:
        try:
            participants = list(GameJoin.objects.filter(gameroom_id=room_id, left_at__isnull=True).select_related("user"))
            state = {
                "participants": [
                    {
                        "id": str(p.id),
                        "username": p.user.name,
                        "is_ready": p.is_ready,
                        "selected_character": None
                    } for p in participants
                ]
            }
            cache.set(f"room_{room_id}_state", state, timeout=3600)
        except Exception as e:
            print(f"❌ 캐시 초기화 중 오류 발생: {e}")
            return {"participants": []}
    return state

def _set_room_state_in_cache(room_id, state):
    cache.set(f"room_{room_id}_state", state, timeout=3600)

@database_sync_to_async
def _get_participants_from_db(room_id):
    return list(GameJoin.objects.filter(gameroom_id=room_id, left_at__isnull=True).select_related("user"))

@database_sync_to_async
def _toggle_ready(room_id, user):
    try:
        rp = GameJoin.objects.get(gameroom_id=room_id, user=user)
        rp.is_ready = not rp.is_ready
        rp.save(update_fields=["is_ready"])
        return True
    except GameJoin.DoesNotExist:
        return False


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        try:
            self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
            self.group_name = f"room_{self.room_id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            await self._broadcast_state()
        except Exception as e:
            import traceback
            print("❌ connect error:", e)
            traceback.print_exc()
            await self.close()

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        user = self.scope.get("user", AnonymousUser())
        print("📩 receive_json:", content)
        
        if action == "select_character":
            if not getattr(user, "is_authenticated", False):
                await self.send_json({"type": "error", "message": "로그인이 필요합니다."})
                return
            
            character_id = content.get("characterId")
            room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
            
            participant_to_update = next((p for p in room_state["participants"] if p["username"] == user.name), None)
            
            if not participant_to_update:
                await self.send_json({"type": "error", "message": "참가자를 찾을 수 없습니다."})
                return

            # ✅ "선택 해제" 처리 우선
            if not character_id:
                participant_to_update["selected_character"] = None
            else:
                character = await _get_character_from_db(character_id)
                if not character:
                    await self.send_json({"type": "error", "message": "존재하지 않는 캐릭터입니다."})
                    return

                # 중복 선택 방지
                is_already_taken = any(
                    p["selected_character"] and p["selected_character"]["id"] == character_id
                    for p in room_state["participants"] if p["username"] != user.name
                )
                if is_already_taken:
                    await self.send_json({"type": "error", "message": "다른 플레이어가 이미 선택한 캐릭터입니다."})
                    return

                participant_to_update["selected_character"] = {
                    "id": str(character.id),
                    "name": character.name,
                    "description": character.description,
                    "image_path": character.image_path,
                }

            await database_sync_to_async(_set_room_state_in_cache)(self.room_id, room_state)
            await self._broadcast_state()

        elif action == "confirm_selections":
            final_setup_data = content.get("setup_data")
            if not final_setup_data:
                await self.send_json({"type": "error", "message": "설정 데이터가 없습니다."})
                return

            room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
            room_state["final_setup"] = final_setup_data
            await database_sync_to_async(_set_room_state_in_cache)(self.room_id, room_state)

            await self.channel_layer.group_send(
                self.group_name,
                { "type": "selections_confirmed", "payload": final_setup_data },
            )

        elif action == "toggle_ready":
            room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
            found = False
            for participant in room_state["participants"]:
                if participant["username"] == user.name:
                    participant["is_ready"] = not participant["is_ready"]
                    found = True
                    break
            if not found:
                await self.send_json({"type": "error", "message": "참가자를 찾을 수 없습니다."})
                return

            await database_sync_to_async(_set_room_state_in_cache)(self.room_id, room_state)
            await self._broadcast_state()
        
        elif action == "request_selection_state":
            await self._broadcast_state()

        elif action == "start_game":
            if not getattr(user, "is_authenticated", False):
                await self.send_json({"type": "error", "message": "로그인이 필요합니다."})
                return
            try:
                get_room_with_owner = database_sync_to_async(
                    GameRoom.objects.select_related("owner").get
                )
                room = await get_room_with_owner(pk=self.room_id)
            except GameRoom.DoesNotExist:
                await self.send_json({"type": "error", "message": "존재하지 않는 방입니다."})
                return

            if room.owner != user:
                await self.send_json({"type": "error", "message": "방장만 게임을 시작할 수 있습니다."})
                return

            try:
                @database_sync_to_async
                def get_selected_options(room_id):
                    return GameRoomSelectScenario.objects.select_related(
                        'scenario', 'difficulty', 'mode', 'genre'
                    ).get(gameroom_id=room_id)
                selected_options = await get_selected_options(self.room_id)
            except GameRoomSelectScenario.DoesNotExist:
                await self.send_json({"type": "error", "message": "게임 옵션이 선택되지 않았습니다."})
                return

            room.status = "play"
            await database_sync_to_async(room.save)(update_fields=["status"])
            await database_sync_to_async(cache.delete)(f"room_{self.room_id}_state")

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "room_broadcast",
                    "message": {
                        "event": "game_start",
                        "roomId": str(self.room_id),
                        "topic": selected_options.scenario.title,
                        "difficulty": selected_options.difficulty.name,
                        "mode": selected_options.mode.name,
                        "genre": selected_options.genre.name,
                    },
                },
            )

        elif action == "end_game":
            if not getattr(user, "is_authenticated", False):
                await self.send_json({"type": "error", "message": "로그인이 필요합니다."})
                return
            try:
                get_room_with_owner = database_sync_to_async(
                    GameRoom.objects.select_related("owner").get
                )
                room = await get_room_with_owner(pk=self.room_id)
            except GameRoom.DoesNotExist:
                await self.send_json({"type": "error", "message": "존재하지 않는 방입니다."})
                return

            if room.owner != user:
                await self.send_json({"type": "error", "message": "방장만 게임을 종료할 수 있습니다."})
                return

            room.status = "waiting"
            await database_sync_to_async(room.save)(update_fields=["status"])
            await database_sync_to_async(cache.delete)(f"room_{self.room_id}_state")
            await self._broadcast_state()

    async def _broadcast_state(self):
        room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "room_state", "selected_by_room": room_state["participants"]},
        )

    async def room_state(self, event):
        await self.send_json({"type": "room_state", "selected_by_room": event["selected_by_room"]})

    async def room_broadcast(self, event):
        await self.send_json({
            "type": "room_broadcast",
            "message": event.get("message")
        })
    
    async def selections_confirmed(self, event):
        await self.send_json({
            "type": "selections_confirmed",
            "payload": event["payload"]
        })

    @database_sync_to_async
    def ensure_participant(room_id, user):
        room = GameRoom.objects.get(pk=room_id)
        participant, created = GameJoin.objects.get_or_create(
            gameroom=room, user=user
        )
        return participant


class GameConsumer(AsyncJsonWebsocketConsumer):
    """
    [수정] AI 턴 시뮬레이션을 포함하여 모든 게임 로직을 총괄하는 Consumer
    """
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"game_{self.room_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        self.gm = AIGameMaster()  # ★ SHARI GM 엔진 인스턴스
        print(f"✅ LLM GameConsumer connected for room: {self.room_id}")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        user = self.scope.get("user", AnonymousUser())

        if msg_type == "request_initial_scene":
            scenario_title = content.get("topic")
            characters_data = content.get("characters", [])
            is_loaded_game = content.get("isLoadedGame", False) 
            await self.handle_start_game_llm(user, scenario_title, characters_data, is_loaded_game)

        elif msg_type == "submit_player_choice":
            player_result_data = content.get("player_result")
            all_characters = content.get("all_characters")
            await self.handle_turn_resolution_with_ai(player_result_data, all_characters)

        elif msg_type == "request_next_scene":
            history_data = content.get("history")
            await self.handle_request_next_scene(user, history_data)

        elif msg_type == "continue_game":
            pass

        elif msg_type == "save_game_state":
            save_data = content.get("data")
            if user.is_authenticated and save_data:
                await self.handle_save_game_state(user, save_data)

    def _get_dc(self, difficulty_str="초급"):
        return {"초급": 10, "중급": 13, "상급": 16}.get(difficulty_str, 10)

    def _get_stat_value(self, character, stat_kr):
        if 'stats' in character and isinstance(character['stats'], dict):
            return character['stats'].get(stat_kr, 0)
        stats_dict = character.get('ability', {}).get('stats', {})
        return stats_dict.get(stat_kr, 0)

    def _simulate_ai_turn(self, ai_character, choices_for_role, difficulty):
        """(폴백용) AI 캐릭터의 d20 판정"""
        if not choices_for_role:
            return None
        ai_choice = random.choice(choices_for_role)
        dice = random.randint(1, 20)
        stat_value = self._get_stat_value(ai_character, ai_choice['appliedStat'])
        modifier = ai_choice['modifier']
        total = dice + stat_value + modifier
        dc = self._get_dc(difficulty)
        grade = "F"
        if dice == 20: grade = "SP"
        elif dice == 1: grade = "SF"
        elif total >= dc: grade = "S"
        return {
            "role": ai_character['role_id'],
            "choiceId": ai_choice['id'],
            "grade": grade,
            "dice": dice,
            "appliedStat": ai_choice['appliedStat'],
            "statValue": stat_value,
            "modifier": modifier,
            "total": total,
        }

    # ★ SHARI 엔진용 state 구성
    def _build_gm_state(self, all_characters: list, current_scene: dict, turn: int = 0) -> dict:
        world = {
            "time": "밤",
            "location": current_scene.get("round", {}).get("title") or current_scene.get("id") or "현장",
            "notes": current_scene.get("round", {}).get("description", "")
        }
        party = []
        for ch in all_characters or []:
            pid = str(ch.get("role_id") or ch.get("id") or ch.get("name"))
            sheet = {
                "stats": (ch.get("ability", {}) or {}).get("stats", {}),
                "skills": ch.get("skills", []),
                "items": ch.get("items", []),
                "spells": ch.get("spells", []),
            }
            party.append({
                "id": pid,
                "name": ch.get("name") or pid,
                "role": ch.get("role_id") or "",
                "sheet": sheet,
                "memory": ch.get("memory", "")
            })
        return {
            "session_id": str(self.room_id),
            "turn": int(turn),
            "scenario": { "title": "In-Game", "summary": "" },
            "world": world,
            "party": party,
            "log": []
        }

    # backend/game/consumers.py 안의 GameConsumer 클래스에 있는 함수 교체
    async def handle_turn_resolution_with_ai(self, player_result, all_characters):
        """플레이어 결과를 받고, AI 턴을 시뮬레이션한 후, 종합 결과를 LLM에 보내 서술을 생성합니다."""
        state = await GameState.get_game_state(self.room_id)
        current_scene = state.get("current_scene")
        history = state.get("conversation_history", [])

        if not current_scene:
            await self.send_error_message("오류: 현재 씬 정보를 찾을 수 없습니다.")
            return

        # 1) 플레이어 + AI 결과 합치기
        final_results = [player_result]

        player_role_id = player_result['role']
<<<<<<< HEAD
        role_to_char_map = { char['role_id']: char for char in all_characters }
        all_roles_in_scene = current_scene['round']['choices'].keys()
=======
        
        # 역할 ID와 캐릭터 객체를 매핑
        role_to_char_map = {
            char['role_id']: char for char in all_characters
        }

        # 전체 역할 목록에서 플레이어 역할을 제외하고 AI 역할만 남깁니다.
        scene_choices = current_scene.get('round', {}).get('choices', {})
        all_roles_in_scene = scene_choices.keys()
>>>>>>> origin/develop
        ai_roles = [role for role in all_roles_in_scene if role != player_role_id]

        for role_id in ai_roles:
            ai_char_obj = role_to_char_map.get(role_id)
<<<<<<< HEAD
            choices_for_role = current_scene['round']['choices'].get(role_id, [])
=======
            choices_for_role = scene_choices.get(role_id, [])
            
>>>>>>> origin/develop
            if ai_char_obj and choices_for_role:
                ai_result = self._simulate_ai_turn(ai_char_obj, choices_for_role, "초급")
                if ai_result:
                    ai_result['characterName'] = ai_char_obj['name']
                    final_results.append(ai_result)

        # 2) 결과 요약(스킬/아이템 사용 정보 반영)
        results_summary = ""
        for res in final_results:
            try:
<<<<<<< HEAD
                choice_text = next(c['text'] for c in current_scene['round']['choices'][res['role']] if c['id'] == res['choiceId'])
                used_bits = []
                if res.get("usedSkillId"): used_bits.append(f"스킬:{res['usedSkillId']}")
                if res.get("usedItemId"):  used_bits.append(f"아이템:{res['usedItemId']}")
                used_str = f" (보조: {', '.join(used_bits)})" if used_bits else ""
                ue = res.get("usedEffects") or {}
                bonus_note = []
                if ue.get("advantage"): bonus_note.append("이점")
                if (ue.get("extraBonus") or 0) != 0: bonus_note.append(f"보정+{ue['extraBonus']}")
                if bonus_note:
                    used_str += f"{' ' if used_str else ''}[{', '.join(bonus_note)}]"
                results_summary += (
                    f"- {res.get('characterName', res['role'])} (역할: {res['role']}): "
                    f"'{choice_text}' 행동{used_str} -> {res['grade']} 판정\n"
                )
            except (KeyError, StopIteration):
                results_summary += f"- {res.get('characterName', res['role'])}: 행동 정보 없음 -> {res['grade']} 판정\n"
=======
                # 'choices' 딕셔너리에서 선택지 텍스트를 찾습니다.
                choice_text = next(c['text'] for c in scene_choices.get(res['role'], []) if c['id'] == res['choiceId'])
                results_summary += f"- {res.get('characterName', res['role'])} (역할: {res['role']}): '{choice_text}' 행동 -> {res['grade']} 판정\n"
            except (KeyError, StopIteration):
                 results_summary += f"- {res.get('characterName', res['role'])}: 행동 정보 없음 -> {res['grade']} 판정\n"

        character_details_summary_list = []
        for char in all_characters:
            skills_str = ", ".join([s['name'] for s in char.get('skills', [])])
            items_str = ", ".join([i['name'] for i in char.get('items', [])])
            character_details_summary_list.append(
                f"{char['name']} (스킬: {skills_str if skills_str else '없음'}, 아이템: {items_str if items_str else '없음'})"
            )
        character_details_summary = "\n".join(character_details_summary_list)

>>>>>>> origin/develop

        narration_prompt = f"""
        TRPG 게임의 한 턴이 진행되었습니다. 모든 캐릭터의 행동과 판정 결과는 다음과 같습니다.
        {results_summary}
<<<<<<< HEAD
        이 모든 상황을 종합하여, 2~3문장으로 흥미진진하게 서술해주세요.
        가능하면 사용된 스킬/아이템의 효과(이점/추가 보정, 연막/빛/치유 등)를 자연스럽게 묘사에 녹여주세요.
=======
        아래는 현재 캐릭터들의 정보입니다. 이들의 스킬이나 아이템을 활용하여 서술하면 좋습니다.
        {character_details_summary}
        이 모든 상황을 종합하여, 무슨 일이 일어났는지 2~3 문장으로 흥미진진하게 서술해주세요.
>>>>>>> origin/develop
        """

        # 3) LLM 호출
        try:
            completion = await oai_client.chat.completions.create(
                model=OAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "당신은 모든 상황을 종합하여 결과를 서술하는 TRPG 게임 마스터입니다."},
                    {"role": "user", "content": narration_prompt}
                ],
                max_tokens=500, temperature=0.8
            )
            narration = completion.choices[0].message.content.strip()
            history.append({"role": "user", "content": f"(이번 턴 요약:\n{results_summary})"})
            history.append({"role": "assistant", "content": narration})
            await GameState.set_game_state(self.room_id, {"current_scene": current_scene, "conversation_history": history})
        except Exception as e:
            print(f"❌ 서사 생성 중 오류: {e}")
            narration = "예상치 못한 사건이 발생하여 숲 전체가 술렁였습니다."

        # 4) 프론트로 브로드캐스트
        await self.broadcast_to_group({
            "event": "turn_resolved",
            "narration": narration,
            "roundResult": {
                "sceneIndex": current_scene['index'],
                "results": final_results,
            }
        })


    async def handle_request_next_scene(self, user, history_data):
        """
        이전 씬의 선택 결과를 바탕으로 LLM에게 다음 씬(JSON)을 요청합니다.
        """
        state = await GameState.get_game_state(self.room_id)
        history = state.get("conversation_history", [])
        username = user.name if user.is_authenticated else "플레이어"
        
        last_choice = history_data.get("lastChoice", {})
        last_narration = history_data.get("lastNarration", "특별한 일은 없었다.")
        current_scene_index = history_data.get("sceneIndex", 0)

        usage_data = history_data.get("usage")
        usage_text = ""
        if usage_data:
            usage_type = "스킬" if usage_data.get("type") == "skill" else "아이템"
            usage_name = usage_data.get("data", {}).get("name", "")
            usage_text = f"또한, 플레이어는 방금 '{usage_name}' {usage_type}을(를) 사용했어."

        user_message = f"""
        플레이어 '{username}' (역할: {last_choice.get('role')})가 이전 씬에서 다음 선택지를 골랐고, 아래와 같은 결과를 얻었어.
        - 선택 내용: "{last_choice.get('text')}"
        - 결과: "{last_narration}"
        {usage_text}

        이 결과를 반영해서, 다음 씬(sceneIndex: {current_scene_index + 1})의 JSON 데이터를 생성해줘.
        """
        scene_json = await self.ask_llm_for_scene_json(history, user_message)
        if scene_json:
            await self.broadcast_to_group({ "event": "scene_update", "scene": scene_json })

    @database_sync_to_async
    def _get_session_data_from_db(self, user, room_id):
        try:
            session = MultimodeSession.objects.select_related('scenario').get(user=user, gameroom_id=room_id)
            return session
        except MultimodeSession.DoesNotExist:
            return None

    async def handle_continue_game(self, user, saved_session):
        """
        DB에서 직접 불러온 세션 정보로 게임을 이어갑니다.
        """
        choice_history = saved_session.choice_history
        character_history = saved_session.character_history
        scenario = saved_session.scenario

        characters_data = character_history.get("allCharacters", [])
        system_prompt = self.create_system_prompt_for_json(scenario, characters_data)

        conversation_history = choice_history.get("conversation_history", [system_prompt])

        last_full_summary = choice_history.get("summary", "이전 기록을 찾을 수 없습니다.")
        recent_logs = choice_history.get("recent_logs", [])
        previous_index = choice_history.get('sceneIndex', 0)

        recent_logs_text = "\n".join(
            [f"- 상황: {log.get('scene', '')}, 유저 선택: {log.get('choice', '')}" for log in recent_logs]
        )

        user_message = f"""
        이전에 저장된 게임을 이어서 진행하려고 해.
        지금까지의 줄거리 요약은 다음과 같아: "{last_full_summary}"
        최근에 진행된 상황은 다음과 같아:
        {recent_logs_text if recent_logs_text else "최근 기록 없음."}
        이 요약과 최근 기록에 이어서, 모든 캐릭터가 참여하는 다음 씬을 생성해줘.
        이전 씬의 sceneIndex가 {previous_index} 이었으니, 다음 씬의 index는 {previous_index + 1}(으)로 생성해야 해.
        """

        scene_json = await self.ask_llm_for_scene_json(conversation_history, user_message)
        if scene_json:
            player_state = choice_history.get("playerState", {})
            await self.broadcast_to_group({
                "event": "game_loaded", # ✅ 새로운 이벤트 이름
                "scene": scene_json,
                "playerState": player_state,
            })

    @database_sync_to_async
    def get_scenario_title_from_session(self, user, room_id):
        try:
            session = MultimodeSession.objects.select_related('scenario').get(user=user, gameroom_id=room_id)
            return session.scenario.title
        except MultimodeSession.DoesNotExist:
            return None

    async def handle_start_game_llm(self, user, scenario_title, characters_data, is_loaded_game: bool):
        if is_loaded_game:
            print(f"ℹ️  불러온 게임을 시작합니다. User: {user.name}")
            saved_session = await self._get_session_data_from_db(user, self.room_id)
            if saved_session:
                await self.handle_continue_game(user, saved_session)
            else:
                await self.send_error_message("이어할 게임 기록을 찾을 수 없습니다.")
            return

        print(f"ℹ️  새 게임 시작으로 판단하여 이전 기록을 초기화합니다. User: {user.name}")
        if user.is_authenticated:
            await self.clear_previous_session_history(user)
        
        await GameState.set_game_state(self.room_id, {})

        scenario = await self.get_scenario_from_db(scenario_title)
        if not scenario:
            await self.send_error_message(f"시나리오 '{scenario_title}'를 찾을 수 없습니다.")
            return

        system_prompt = self.create_system_prompt_for_json(scenario, characters_data)
        initial_history = [system_prompt]

        user_message = "모든 캐릭터가 참여하는 게임의 첫 번째 씬(sceneIndex: 0)을 생성해줘. 비극적인 사건 직후의 긴장감 있는 상황으로 시작해줘."
        scene_json = await self.ask_llm_for_scene_json(initial_history, user_message)

        if scene_json:
            await self.broadcast_to_group({ "event": "scene_update", "scene": scene_json })

    async def ask_llm_for_scene_json(self, history, user_message):
        """LLM을 호출하여 JSON 형식의 씬 데이터를 받고, 파싱하여 반환"""
        history.append({"role": "user", "content": user_message})
        
        try:
            completion = await oai_client.chat.completions.create(
                model=OAI_DEPLOYMENT,
                messages=history,
                max_tokens=4000,
                temperature=0.7
            )
            response_text = completion.choices[0].message.content
            json_str = self.extract_json_block(response_text)
            scene_json = json.loads(json_str)
            
            history.append({"role": "assistant", "content": response_text})
            
            # GameState에 씬 JSON 전체를 저장
            await GameState.set_game_state(
                self.room_id, 
                {
                    "current_scene": scene_json,
                    "conversation_history": history,
                }
            )
            return scene_json
        except Exception as e:
            error_message = f"LLM 응답 처리 중 오류: {e}"
            print(f"❌ {error_message}")
            await self.send_error_message(error_message)
            return None

    async def clear_previous_session_history(self, user):
        """데이터베이스에서 해당 유저와 게임방의 choice_history를 비웁니다."""
        await self._clear_history_in_db(user, self.room_id)

    @database_sync_to_async
    def _clear_history_in_db(self, user, room_id):
        try:
            gameroom = GameRoom.objects.get(id=room_id)
            session = MultimodeSession.objects.filter(user=user, gameroom=gameroom).first()
            if session:
                session.choice_history = {}
                session.save(update_fields=['choice_history'])
                print(f"✅ DB 기록 초기화 성공: User {user.name}, Room {room_id}")
        except GameRoom.DoesNotExist:
            print(f"⚠️ DB 기록 초기화 경고: Room {room_id}를 찾을 수 없습니다.")
        except Exception as e:
            print(f"❌ DB 기록 초기화 중 오류 발생: {e}")

    async def handle_player_choice(self, user, choice_data):
        """플레이어의 선택을 기반으로 LLM에게 다음 씬(JSON)을 요청"""
        state = await GameState.get_game_state(self.room_id)
        history = state.get("conversation_history", [])
        username = user.name
        user_message = f"""
        플레이어 '{username}' (역할: {choice_data['role']})가 이전 씬에서 다음 선택지를 골랐어:
        - 선택지 ID: "{choice_data['choiceId']}"
        - 선택지 내용: "{choice_data['text']}"
        이 선택의 결과를 반영해서, 다음 씬(sceneIndex: {choice_data['sceneIndex'] + 1})의 JSON 데이터를 생성해줘.
        """
        scene_json = await self.ask_llm_for_scene_json(history, user_message)
        if scene_json:
            await self.broadcast_to_group({ "event": "scene_update", "scene": scene_json })

    async def _summarize_with_llm(self, text: str) -> str:
        """주어진 텍스트를 LLM을 사용해 한두 문장으로 요약합니다."""
        if not text:
            return "아직 기록된 행동이 없습니다."
        try:
            summary_prompt = [
                {"role": "system", "content": "너는 플레이 로그를 분석하고 핵심만 간결하게 한 문장으로 요약하는 AI다."},
                {"role": "user", "content": f"다음 게임 플레이 기록을 한 문장으로 요약해줘:\n\n{text}"}
            ]
            completion = await oai_client.chat.completions.create(
                model=OAI_DEPLOYMENT,
                messages=summary_prompt,
                max_tokens=200,
                temperature=0.5
            )
            summary = completion.choices[0].message.content
            return summary.strip()
        except Exception as e:
            print(f"❌ 요약 생성 중 오류 발생: {e}")
            return "요약을 생성하는 데 실패했습니다."

    @database_sync_to_async
    def _get_choice_history_from_db(self, user, room_id):
        try:
            session = MultimodeSession.objects.get(user=user, gameroom_id=room_id)
            return session.choice_history
        except MultimodeSession.DoesNotExist:
            return None

    async def handle_save_game_state(self, user, data):
        """
        DB와 GameState 캐시에서 모든 기록을 가져와 DB에 저장합니다.
        """
        room_id = self.room_id

        previous_history = await self._get_choice_history_from_db(user, room_id)
        log_history = previous_history.get("full_log_history", []) if isinstance(previous_history, dict) else []
        
        current_choice_text = data.get("selectedChoice", {}).get(next(iter(data.get("selectedChoice", {})), ''))
        new_log_entry = {
            "scene": data.get('title', '어떤 상황'),
            "choice": current_choice_text if current_choice_text else "선택 없음"
        }
        log_history.append(new_log_entry)

        game_state = await GameState.get_game_state(room_id)
        conversation_history = game_state.get("conversation_history", [])
        
        formatted_log_text = "\n".join([f"- {e.get('scene', '')}: {e.get('choice', '')}" for e in log_history])
        full_summary = await self._summarize_with_llm(formatted_log_text)
        recent_logs_to_save = log_history[-3:]

        new_history_entry = {
            "summary": full_summary,
            "recent_logs": recent_logs_to_save,
            "full_log_history": log_history,
            "conversation_history": conversation_history,
            "sceneIndex": data.get("sceneIndex", 0),
<<<<<<< HEAD
=======
            "playerState": data.get("playerState", {}),
            # 프론트엔드 표시에 필요할 수 있는 기타 정보들
>>>>>>> origin/develop
            "description": data.get("description", ""),
            "choices": data.get("choices", {}),
            "selectedChoices": data.get("selectedChoice", {}),
        }

        room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
        character_data = room_state.get("final_setup")
        was_successful = await self._save_to_db(user, self.room_id, new_history_entry, character_data)

        if was_successful:
            await self.send_json({"type": "save_success", "message": "게임 진행 상황이 저장되었습니다."})
        else:
            await self.send_error_message("게임 저장에 실패했습니다.")

    @database_sync_to_async
    def _save_to_db(self, user, room_id, new_entry, character_data):
        """DB에 choice_history와 character_history를 저장합니다."""
        try:
            try:
                selected_options = GameRoomSelectScenario.objects.select_related('gameroom', 'scenario').get(gameroom_id=room_id)
                gameroom = selected_options.gameroom
                scenario_obj = selected_options.scenario
            except GameRoomSelectScenario.DoesNotExist:
                print(f"❌ DB 저장 오류: gameroom_id {room_id}에 대한 시나리오 선택 정보가 없습니다.")
                return False

            if not gameroom or not scenario_obj:
                print(f"❌ DB 저장 오류: gameroom 또는 scenario 객체를 찾을 수 없습니다.")
                return False

            session, created = MultimodeSession.objects.get_or_create(
                user=user,
                gameroom=gameroom,
                defaults={
                    'scenario': scenario_obj,
                    'choice_history': {},
                    'character_history': character_data if character_data else {}
                }
            )

            session.choice_history = new_entry
            if character_data:
                session.character_history = character_data
            session.save(update_fields=['choice_history', 'character_history'])

            print("✅ DB 저장 성공! (캐릭터 정보 포함, 덮어쓰기)")
            return True

        except Exception as e:
            print(f"❌ DB 저장 중 심각한 오류 발생: {e}")
            return False

    def create_system_prompt_for_json(self, scenario, characters):
        """LLM이 구조화된 JSON을 생성하도록 지시하는 시스템 프롬프트"""
<<<<<<< HEAD
        char_descriptions = "\n".join(
            [f"- **{c['name']}** ({c['description']})\n  - 능력치: {c.get('ability', {}).get('stats', {})}" for c in characters]
        )
=======
        
        char_descriptions_list = []
        for c in characters:
            # 스킬 목록을 문자열로 변환
            skills_info = "\n".join([f"    - {s['name']}: {s['description']}" for s in c.get('skills', [])])
            # 아이템 목록을 문자열로 변환
            items_info = "\n".join([f"    - {i['name']}: {i['description']}" for i in c.get('items', [])])

            description = f"""- **{c['name']}** ({c['description']})
    - 능력치: {c.get('stats', {})}
    - 스킬:\n{skills_info if skills_info else "    - 없음"}
    - 아이템:\n{items_info if items_info else "    - 없음"}"""
            char_descriptions_list.append(description)
        
        char_descriptions = "\n".join(char_descriptions_list)
        
        # [수정] fragments 키를 JSON 스키마에서 완전히 제거합니다.
>>>>>>> origin/develop
        json_schema = """
        {
          "id": "string (예: scene0)",
          "index": "number (예: 0)",
          "roleMap": { "캐릭터이름": "역할ID" },
          "round": {
            "title": "string (현재 씬의 제목)",
            "description": "string (현재 상황에 대한 구체적인 묘사, 2~3 문장)",
            "choices": {
              "역할ID": [
                { 
                  "id": "string", 
                  "text": "string (선택지 내용)", 
                  "appliedStat": "string (반드시 '힘', '민첩', '지식', '의지', '매력', '운' 중 하나)", 
                  "modifier": "number (보정치)" 
                }
              ]
            }
          }
        }
        """
        prompt = f"""
        당신은 TRPG 게임의 시나리오를 실시간으로 생성하는 AI입니다.
        당신의 임무는 사용자 행동에 따라 다음 게임 씬 데이터를 "반드시" 아래의 JSON 스키마에 맞춰 생성하는 것입니다.
        'fragments' 필드는 절대로 생성하지 마세요.

        ## 게임 배경
        - 시나리오: {scenario.title} ({scenario.description})
        - 참가 캐릭터 정보 (이 능력치를 반드시 참고할 것):
        {char_descriptions}

        ## 출력 JSON 스키마 (필수 준수)
        - `appliedStat` 필드의 값은 반드시 캐릭터 정보에 명시된 6가지 능력치('힘', '민첩', '지식', '의지', '매력', '운') 중 하나여야 합니다.

        ```json
        {json_schema}
        ```
        """
        return {"role": "system", "content": prompt}
    
    def extract_json_block(self, text: str) -> str:
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
        if match:
            return match.group(1)
        return text

    @database_sync_to_async
    def get_scenario_from_db(self, scenario_title):
        try:
            return Scenario.objects.get(title=scenario_title)
        except Scenario.DoesNotExist:
            return None
    
    async def send_error_message(self, message):
        """현재 클라이언트에게만 에러 메시지를 전송"""
        await self.send_json({"type": "error", "message": message})
        
    async def broadcast_to_group(self, payload):
        """그룹의 모든 멤버에게 게임 상태 업데이트를 브로드캐스트"""
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "game_broadcast", "payload": payload}
        )
        
    async def game_broadcast(self, event):
        """그룹 메시지를 받아 클라이언트에게 전송"""
        await self.send_json({
            "type": "game_update",
            "payload": event["payload"]
        })


class TurnBasedGameConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"game_{self.room_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # 고정된 플레이어와 턴 순서로 초기 상태 생성
        scene0_template = get_scene_template(0)
        roles = scene0_template["roleMap"]
        
        players = [{"id": name, "name": name, "role": role_id} for name, role_id in roles.items()]
        
        turn_order_roles = ["brother", "sister", "tiger", "goddess"]
        turn_order_ids = [next(p["id"] for p in players if p["role"] == role) for role in turn_order_roles]

        initial_state = {
            "sceneIndex": 0,
            "players": players,
            "turnOrder": turn_order_ids,
            "currentTurnIndex": 0,
            "logs": [{"id": 0, "text": "게임 시작! 정해진 순서에 따라 진행합니다.", "isImportant": True}],
            "isSceneOver": False,
        }
        await GameState.set_game_state(self.room_id, {})
        
    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        state = await GameState.get_game_state(self.room_id)
        if not state: return

        if action == "request_initial_state":
            await self.send_game_state()

        elif action == "submit_turn_choice":
            player_id = content.get("playerId")
            choice_id = content.get("choiceId")
            player = next((p for p in state["players"] if p["id"] == player_id), None)
            
            result_payload = await perform_turn_judgement(self.room_id, state["sceneIndex"], player["role"], choice_id)
            
            state["logs"].append({"id": len(state["logs"]), "text": f"👉 [{player_id}] 님이 '{result_payload['result']['choiceId']}' 선택지를 골랐습니다."})
            state["logs"].append({"id": len(state["logs"]), "text": f"🎲 {result_payload['log']}"})
            state["currentTurnIndex"] += 1
            if state["currentTurnIndex"] >= len(state["turnOrder"]):
                state["isSceneOver"] = True

            await GameState.set_game_state(self.room_id, state)
            await self.channel_layer.group_send(self.group_name, {"type": "broadcast_game_state"})

        elif action == "run_ai_turn":
            player_id = content.get("playerId")
            player = next((p for p in state["players"] if p["id"] == player_id), None)
            
            template = get_scene_template(state["sceneIndex"])
            choices_for_role = template.get("round", {}).get("choices", {}).get(player["role"], [])
            
            if not choices_for_role:
                random_choice = {"id": "default", "text": "상황을 지켜본다"}
            else:
                random_choice = random.choice(choices_for_role)
            
            result_payload = await perform_turn_judgement(self.room_id, state["sceneIndex"], player["role"], random_choice["id"])
            
            state["logs"].append({"id": len(state["logs"]), "text": f"👉 [{player_id}](이)가 '{random_choice['text']}' 선택지를 골랐습니다."})
            state["logs"].append({"id": len(state["logs"]), "text": f"🎲 {result_payload['log']}"})
            state["currentTurnIndex"] += 1
            if state["currentTurnIndex"] >= len(state["turnOrder"]):
                state["isSceneOver"] = True
            
            await GameState.set_game_state(self.room_id, state)
            await self.channel_layer.group_send(self.group_name, {"type": "broadcast_game_state"})

        elif action == "request_next_scene":
            state["sceneIndex"] += 1
            state["currentTurnIndex"] = 0
            state["isSceneOver"] = False
            state["logs"].append({
                "id": len(state["logs"]),
                "text": f"--- 다음 이야기 시작 (Scene {state['sceneIndex']}) ---",
                "isImportant": True
            })
            
            await GameState.set_game_state(self.room_id, state)
            await self.channel_layer.group_send(self.group_name, {"type": "broadcast_game_state"})

    async def send_game_state(self):
        state = await GameState.get_game_state(self.room_id)
        await self.send_json({
            "type": "game_state_update",
            "payload": state
        })

    async def broadcast_game_state(self, event):
        await self.send_game_state()

    async def turn_roll_update(self, event):
        await self.send_json({
            "type": "turn_roll_update",
            "rolls": event["rolls"]
        })
