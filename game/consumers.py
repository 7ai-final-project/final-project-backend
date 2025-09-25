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

from game.models import MultimodeSession, GameRoom, GameJoin, GameRoomSelectScenario, Scenario, Character, Difficulty, Mode, Genre
from game.serializers import GameJoinSerializer, GameRoomSerializer
from .state import GameState

from asgiref.sync import sync_to_async
from game.gm_engine import AIGameMaster, apply_gm_result_to_state

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
            # Serializer를 사용하여 참가자 목록을 직렬화합니다.
            participants_qs = GameJoin.objects.filter(gameroom_id=room_id, left_at__isnull=True).select_related("user")
            serialized_participants = GameJoinSerializer(participants_qs, many=True).data
            
            # 각 참가자에게 'selected_character' 기본값을 추가합니다.
            participants_for_state = [
                {**p, "selected_character": None} for p in serialized_participants
            ]
            
            state = {"participants": participants_for_state}
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
        return rp.is_ready
    except GameJoin.DoesNotExist:
        return None
    
@database_sync_to_async
def _get_session_by_room_id(room_id):
    """
    유저가 아닌 방 ID를 기준으로 가장 최근에 저장된 세션을 찾습니다.
    """
    try:
        return MultimodeSession.objects.select_related('scenario').get(gameroom_id=room_id)

    except MultimodeSession.DoesNotExist:
        return None
    
@database_sync_to_async
def _get_game_data_for_start(room_id, topic):
    """게임을 시작하기 위한 캐릭터와 참가자 정보를 가져오는 헬퍼 함수"""
    # 1. 시나리오에 맞는 캐릭터 목록 조회
    characters = Character.objects.filter(scenario__title=topic)
    character_data = [
        {
            "id": str(c.id), "name": c.name, "description": c.description,
            "image": c.image_path,
            "stats": c.ability.get('stats', {}),
            "skills": c.ability.get('skills', []),
            "items": c.items
        } for c in characters
    ]
    # 2. 현재 방의 참가자 목록 조회
    participants = GameJoin.objects.filter(gameroom_id=room_id, left_at__isnull=True).select_related("user")
    participant_data = [
        {"id": str(p.user.id), "username": p.user.nickname or p.user.name} for p in participants
    ]
    return character_data, participant_data


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"room_{self.room_id}"
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # [추가] 현재 연결된 유저 목록(set)에 자신을 추가
        connected_users = cache.get(f"room_{self.room_id}_connected_users", set())
        connected_users.add(self.user.id)
        cache.set(f"room_{self.room_id}_connected_users", connected_users)
        
        await self.force_state_broadcast({})

    async def disconnect(self, close_code):
        if self.user and self.user.is_authenticated:
            # [추가] 연결된 유저 목록에서 자신을 제거
            connected_users = cache.get(f"room_{self.room_id}_connected_users", set())
            connected_users.discard(self.user.id)
            cache.set(f"room_{self.room_id}_connected_users", connected_users)
            
            await self.force_state_broadcast({})

        await self.channel_layer.group_discard(self.group_name, self.channel_name)

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
            
            participant_to_update = next((p for p in room_state["participants"] if p["id"] == str(user.id)), None)
            
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
                    for p in room_state["participants"] if p["id"] != str(user.id)
                )
                if is_already_taken:
                    await self.send_json({"type": "error", "message": "다른 플레이어가 이미 선택한 캐릭터입니다."})
                    return

                # ✅ [수정 2] 선택 정보에 사용자 ID를 명확하게 포함
                participant_to_update["selected_character"] = {
                    "id": str(character.id),
                    "name": character.name,
                    "user_id": str(user.id), # 👈 이 줄이 가장 중요합니다!
                    "description": character.description,
                    "image_path": character.image_path,
                }

            await database_sync_to_async(_set_room_state_in_cache)(self.room_id, room_state)
            await self.force_state_broadcast({})

        elif action == "confirm_selections":
            # ✅ [수정] 방장만 이 액션을 실행할 수 있도록 권한 확인 로직 추가
            get_room_with_owner = database_sync_to_async(GameRoom.objects.select_related("owner").get)
            room = await get_room_with_owner(pk=self.room_id)
            if room.owner != user:
                await self.send_json({"type": "error", "message": "방장만 게임을 시작할 수 있습니다."})
                return

            # ✅ 1. 서버의 캐시에서 최종 상태를 가져옵니다. (클라이언트 데이터를 믿지 않음)
            room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
            
            # ✅ 2. 방의 시나리오(토픽)를 기반으로 DB에서 모든 캐릭터 목록을 가져옵니다.
            try:
                selected_options = await database_sync_to_async(
                    GameRoomSelectScenario.objects.select_related('scenario').get
                )(gameroom_id=self.room_id)
                
                all_characters_qs = await database_sync_to_async(list)(
                    Character.objects.filter(scenario=selected_options.scenario)
                )
                all_characters_data = [
                    {
                        "id": str(c.id), "name": c.name, "description": c.description,
                        "image": c.image_path,
                        "stats": c.ability.get('stats', {}),
                        "skills": c.ability.get('skills', []),
                        "items": c.items
                    } for c in all_characters_qs
                ]
            except Exception as e:
                await self.send_json({"type": "error", "message": f"캐릭터 목록 조회 실패: {e}"})
                return

            # ✅ 3. 플레이어가 선택한 캐릭터와 AI가 맡을 캐릭터를 분류합니다.
            player_assignments = {}
            player_selected_char_ids = set()

            for p in room_state.get("participants", []):
                if p.get("selected_character"):
                    char_id = p["selected_character"]["id"]
                    user_id = p["id"]
                    
                    # all_characters_data에서 전체 캐릭터 정보 찾기
                    char_full_data = next((c for c in all_characters_data if c["id"] == char_id), None)
                    
                    if char_full_data:
                        player_assignments[user_id] = char_full_data
                        player_selected_char_ids.add(char_id)

            ai_characters = [c for c in all_characters_data if c["id"] not in player_selected_char_ids]

            # ✅ 4. 모든 클라이언트에게 전달할 최종 페이로드를 만듭니다.
            # "myCharacter" 대신, 누가 어떤 캐릭터를 골랐는지 알려주는 "assignments" 맵을 전달합니다.
            final_payload = {
                "assignments": player_assignments,
                "aiCharacters": ai_characters,
                "allCharacters": all_characters_data,
            }

            # ✅ 5. "selections_confirmed" 이벤트를 모든 클라이언트에게 브로드캐스트합니다.
            game_state = await GameState.get_game_state(self.room_id)
            if game_state is None:
                game_state = {}
            game_state["character_setup"] = final_payload
            await GameState.set_game_state(self.room_id, game_state)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "selections_confirmed",
                    "payload": final_payload,
                },
            )

        elif action == "set_options":
            # 방장만 옵션을 변경할 수 있도록 권한을 확인합니다.
            try:
                get_room_with_owner = database_sync_to_async(
                    GameRoom.objects.select_related("owner").get
                )
                room = await get_room_with_owner(pk=self.room_id)
                if room.owner != user:
                    await self.send_json({"type": "error", "message": "방장만 옵션을 변경할 수 있습니다."})
                    return
            except GameRoom.DoesNotExist:
                await self.send_json({"type": "error", "message": "존재하지 않는 방입니다."})
                return

            options = content.get("options", {})
            scenario_id = options.get("scenarioId")
            difficulty_id = options.get("difficultyId")
            mode_id = options.get("modeId")
            genre_id = options.get("genreId")

            if not all([scenario_id, difficulty_id, mode_id, genre_id]):
                await self.send_json({"type": "error", "message": "모든 옵션 값이 필요합니다."})
                return

            # 받은 옵션 ID를 사용하여 데이터베이스를 업데이트합니다.
            @database_sync_to_async
            def update_options_in_db(room_id, s_id, d_id, m_id, g_id):
                try:
                    gameroom = GameRoom.objects.get(id=room_id)
                    scenario = Scenario.objects.get(id=s_id)
                    difficulty = Difficulty.objects.get(id=d_id)
                    mode = Mode.objects.get(id=m_id)
                    genre = Genre.objects.get(id=g_id)
                    
                    GameRoomSelectScenario.objects.update_or_create(
                        gameroom=gameroom,
                        defaults={
                            'scenario': scenario,
                            'difficulty': difficulty,
                            'mode': mode,
                            'genre': genre
                        }
                    )
                    return True
                except Exception as e:
                    print(f"❌ 옵션 DB 업데이트 오류: {e}")
                    return False

            success = await update_options_in_db(self.room_id, scenario_id, difficulty_id, mode_id, genre_id)

            # 성공적으로 DB 업데이트 후, 모든 클라이언트에게 변경된 옵션을 브로드캐스트합니다.
            if success:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "room_broadcast",
                        "payload": {
                            "type": "options_update",
                            "options": options
                        }
                    }
                )

        elif action == "toggle_ready":
            # 1. DB의 is_ready 상태를 업데이트하고, 그 결과를 new_ready_state에 받습니다.
            new_ready_state = await _toggle_ready(self.room_id, user)
            
            if new_ready_state is None:
                await self.send_json({"type": "error", "message": "참가자 정보를 찾을 수 없어 준비 상태를 변경할 수 없습니다."})
                return

            # 2. DB 업데이트 후, 캐시 상태도 동기화합니다.
            room_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
            found = False
            for participant in room_state["participants"]:
                if participant["id"] == str(user.id):
                    # [핵심 수정] 캐시 값을 토글하는 대신, DB에서 반환된 최종 값으로 설정합니다.
                    participant["is_ready"] = new_ready_state
                    found = True
                    break
            
            if found:
                await database_sync_to_async(_set_room_state_in_cache)(self.room_id, room_state)

            # 3. 모든 클라이언트에게 변경된 상태를 알립니다.
            await self.force_state_broadcast({})
        
        elif action == "request_selection_state":
            await self.force_state_broadcast({})

        elif action == "start_game":
            print("✅ [start_game] 액션 수신됨.")
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
                print("✅ [start_game] DB에서 게임 옵션 조회를 시도합니다...")
                # 데이터베이스에서 저장된 게임 옵션을 가져옵니다.
                selected_options = await database_sync_to_async(
                    GameRoomSelectScenario.objects.select_related('scenario', 'difficulty', 'mode', 'genre').get
                )(gameroom_id=self.room_id)
                
                print(f"✅ [start_game] 옵션 조회 성공: {selected_options.scenario.title}")
                # 위에서 추가한 헬퍼 함수를 호출합니다.
                characters, participants = await _get_game_data_for_start(self.room_id, selected_options.scenario.title)

            except GameRoomSelectScenario.DoesNotExist:
                # 옵션 정보가 없을 경우, 더 명확한 에러 메시지를 보냅니다.
                print("❌ [start_game] 오류: GameRoomSelectScenario.DoesNotExist. DB에 해당 방의 옵션이 없습니다.")
                await self.send_json({"type": "error", "message": "게임 옵션이 선택되지 않았습니다. 옵션 설정을 다시 저장 후 시도해주세요."})
                return
            except Exception as e:
                # 그 외 예기치 못한 오류 발생 시 서버 로그에 기록하고 클라이언트에 알립니다.
                print(f"❌ 게임 시작 준비 중 심각한 오류 발생: {e}")
                await self.send_json({"type": "error", "message": "게임을 시작하는 중 서버에서 오류가 발생했습니다."})
                return
            print("✅ [start_game] 모든 검사 통과. 게임 시작 이벤트를 브로드캐스트합니다.")
            room.status = "play"
            await database_sync_to_async(room.save)(update_fields=["status"])
            await database_sync_to_async(cache.delete)(f"room_{self.room_id}_state")

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "room_broadcast",
                    "payload": {
                        "event": "game_start",
                        "roomId": str(self.room_id),
                        "topic": selected_options.scenario.title,
                        "difficulty": selected_options.difficulty.name,
                        "mode": selected_options.mode.name,
                        "genre": selected_options.genre.name,
                        "characters": characters,
                        "participants": participants,
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
            await self.force_state_broadcast({})

    async def room_state(self, event):
        # 이제 room_state는 참가자 목록만이 아닌 방 전체 정보를 포함합니다.
        await self.send_json({
            "type": "room_state",
            **event["room_data"]
        })

    async def room_broadcast(self, event):
        await self.send_json({
            "type": "room_broadcast",
            "message": event.get("payload")
        })

    async def force_state_broadcast(self, event):
        # 1. DB에서 방의 기본 정보를 가져옵니다.
        room = await database_sync_to_async(GameRoom.objects.get)(pk=self.room_id)
        connected_user_ids = cache.get(f"room_{self.room_id}_connected_users", set())

        # 2. Serializer를 통해 기본 데이터를 JSON 형태로 만듭니다.
        serializer = GameRoomSerializer(
            room,
            context={'connected_user_ids': connected_user_ids}
        )
        serialized_data = await database_sync_to_async(lambda: serializer.data)()

        # 3. ✅ 캐시에서 캐릭터 선택 정보를 가져옵니다.
        selection_state = await database_sync_to_async(_get_room_state_from_cache)(self.room_id)
        #    사용자 ID를 키로, 선택한 캐릭터 정보를 값으로 하는 맵(map)을 만듭니다.
        selections_map = {p['id']: p.get('selected_character') for p in selection_state.get('participants', [])}

        # 4. ✅ 기본 데이터에 캐릭터 선택 정보를 합칩니다.
        for participant in serialized_data.get('selected_by_room', []):
            participant_id = participant.get('id')
            if participant_id in selections_map:
                participant['selected_character'] = selections_map[participant_id]
            else:
                # 선택 정보가 없는 경우를 대비한 기본값 설정
                participant['selected_character'] = None

        # 5. ✅ 정보가 합쳐진 최종 데이터를 모든 클라이언트에게 전송합니다.
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "room_state", "room_data": serialized_data}
        )
    
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
        self.gm = AIGameMaster()
        print(f"✅ LLM GameConsumer connected for room: {self.room_id}")

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        user = self.scope.get("user", AnonymousUser())
        
        # ✅ 어떤 요청이 들어왔는지 로그 추가
        print(f"📩 [GameConsumer] Received message type '{msg_type}' from user '{user.name}'")

        if msg_type == "request_initial_scene":
            scenario_title = content.get("topic")
            characters_data = content.get("characters", [])
            is_loaded_game = content.get("isLoadedGame", False) 
            await self.handle_start_game_llm(user, scenario_title, characters_data, is_loaded_game)

        elif msg_type == "submit_player_choice":
            player_result_data = content.get("player_result")
            all_characters = content.get("all_characters")
            
            await GameState.store_turn_result(self.room_id, str(user.id), player_result_data)

            active_participants = await self._get_active_participants()
            active_participant_ids = {str(p.user.id) for p in active_participants}
            
            submitted_results = await GameState.get_all_turn_results(self.room_id)
            submitted_user_ids = set(submitted_results.keys())

            if not active_participant_ids.issubset(submitted_user_ids):
                # ✅ 대기 상태 로그 추가
                print(f"➡️ [GameConsumer] Waiting for other players... ({len(submitted_user_ids)}/{len(active_participant_ids)})")
                await self.broadcast_to_group({
                    "event": "turn_waiting",
                    "submitted_users": list(submitted_user_ids),
                    "total_users": len(active_participant_ids),
                })
            else:
                print(f"✅ [GameConsumer] All players submitted. Starting turn resolution.")
                human_player_results = list(submitted_results.values())
                await self.handle_turn_resolution_with_ai(human_player_results, all_characters)
                await GameState.clear_turn_results(self.room_id)

        elif msg_type == "ready_for_next_scene":
            history_data = content.get("history")
            await self.handle_ready_for_next_scene(user, history_data)

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

    def _simulate_ai_turn_result(self, ai_character, choices_for_role, difficulty, role_id):
        """AI 캐릭터의 턴을 시뮬레이션하고 상세 판정 결과를 딕셔너리로 반환합니다."""
        if not choices_for_role:
            return None 

        ai_choice = random.choice(choices_for_role)
        dice = random.randint(1, 20)
        stat_kr = ai_choice['appliedStat']
        stat_value = self._get_stat_value(ai_character, stat_kr)
        modifier = ai_choice['modifier']
        total = dice + stat_value + modifier
        dc = self._get_dc(difficulty)
        grade = "F"
        if dice == 20: grade = "SP"
        elif dice == 1: grade = "SF"
        elif total >= dc: grade = "S"
        return {
            "role": role_id,
            "choiceId": ai_choice['id'],
            "grade": grade,
            "dice": dice,
            "appliedStat": stat_kr,
            "statValue": stat_value,
            "modifier": modifier,
            "total": total,
            "characterName": ai_character['name'],
            "characterId": ai_character['id'],
        }

    def _build_shari_state(self, all_characters: list, current_scene: dict, history: list) -> dict:
        """현재 게임 정보를 SHARI 엔진이 요구하는 state JSON 형식으로 변환합니다."""
        party = []
        for char in all_characters:
            # 기존 캐릭터 데이터 구조를 SHARI의 sheet 형식으로 맞춤
            sheet = {
                "stats": char.get('stats', {}),
                "skills": [s.get('name') for s in char.get('skills', [])],
                "items": char.get('items', []),
                "spells": [], # 주문이 있다면 여기에 추가
                "notes": char.get('description', '')
            }
            party.append({
                "id": char['id'], # user.id가 아닌 character.id를 고유 식별자로 사용
                "name": char['name'],
                "role": char.get('role_id', char['name']), # role_id가 없다면 이름으로 대체
                "sheet": sheet,
                "memory": "" # 필요한 경우 캐릭터별 기억을 여기에 추가
            })

        # 지난 대화 기록을 요약하여 로그에 추가
        log = [{"turn": i, "narration": h.get("content", "")} for i, h in enumerate(history) if h.get("role") == "assistant"]

        return {
            "session_id": str(self.room_id),
            "turn": current_scene.get('index', 0),
            "scenario": { "title": current_scene.get('id', 'N/A'), "summary": "" },
            "world": {
                "time": "밤", # 필요 시 동적으로 변경
                "location": current_scene.get('round', {}).get('title', '알 수 없는 장소'),
                "notes": current_scene.get('round', {}).get('description', '')
            },
            "party": party,
            "log": log
        }

    async def handle_turn_resolution_with_ai(self, human_player_results, all_characters):
        """
        [교체] 모든 인간 플레이어의 결과와 AI 턴을 종합하여 SHARI 엔진으로 턴을 처리하고, 게임 종료 조건을 확인합니다.
        """
        print("\n--- 턴 처리 시작 ---")
        state = await GameState.get_game_state(self.room_id)
        current_scene = state.get("current_scene")
        history = state.get("conversation_history", [])
        difficulty = state.get("difficulty", "초급") 

        if not current_scene:
            print("❌ [handle_turn_resolution_with_ai] Error: current_scene not found in state.")
            await self.send_error_message("오류: 현재 씬 정보를 찾을 수 없습니다.")
            return

        current_turn = current_scene.get("index", 0) + 1
        max_turns = 7
        
        # ✅ 현재 턴 정보 로그 추가
        print(f"➡️ [handle_turn_resolution_with_ai] Turn Info: Current Turn = {current_turn}, Max Turns = {max_turns}")
        print(f"➡️ [handle_turn_resolution_with_ai] Received Human Player Results: {human_player_results}")


        shari_state = self._build_shari_state(all_characters, current_scene, history)
        
        shari_choices = {}
        human_char_ids = {res['characterId'] for res in human_player_results}
        scene_choices_data = current_scene.get('round', {}).get('choices', {})

        for res in human_player_results:
            try:
                choice_text = next(c['text'] for c in scene_choices_data.get(res['role'], []) if c['id'] == res['choiceId'])
                shari_choices[res['characterId']] = choice_text
            except (KeyError, StopIteration):
                shari_choices[res['characterId']] = "알 수 없는 행동을 함"

        ai_characters = [c for c in all_characters if c['id'] not in human_char_ids]
        
        ai_player_results = []
        for ai_char in ai_characters:
            role_id = ai_char.get('role_id')
            choices_for_role = scene_choices_data.get(role_id, [])
            
            if choices_for_role:
                random_choice = random.choice(choices_for_role)
                shari_choices[ai_char['id']] = random_choice['text']
            else:
                shari_choices[ai_char['id']] = "상황을 지켜봄"
            
            ai_result = self._simulate_ai_turn_result(ai_char, choices_for_role, difficulty, role_id)
            if ai_result:
                ai_player_results.append(ai_result)
        
        # ✅ AI 시뮬레이션 결과 로그 추가
        print(f"➡️ [handle_turn_resolution_with_ai] Simulated AI Player Results: {ai_player_results}")

        all_player_results = human_player_results + ai_player_results
        
        try:
            print(f"➡️ [handle_turn_resolution_with_ai] Calling GM Engine (resolve_turn)...")
            gm_result = await sync_to_async(self.gm.resolve_turn)(state=shari_state, choices=shari_choices)
            print(f"✅ [handle_turn_resolution_with_ai] GM Engine returned successfully.")
        except Exception as e:
            print(f"❌ [handle_turn_resolution_with_ai] GM Engine call failed: {e}")
            await self.send_error_message(f"AI 게임 마스터 엔진 오류: {e}")
            return
        
        is_turn_limit_reached = current_turn >= max_turns
        is_llm_final_turn = gm_result.get("is_final_turn", False)
        is_game_over = is_turn_limit_reached or is_llm_final_turn

        # ✅ 게임 종료 조건 판단 결과 로그 추가
        print(f"➡️ [handle_turn_resolution_with_ai] Game Over Check: is_turn_limit_reached={is_turn_limit_reached}, is_llm_final_turn={is_llm_final_turn} -> is_game_over={is_game_over}")

        if is_game_over:
            final_narration = gm_result.get('narration', '이야기가 막을 내립니다.')
            if is_turn_limit_reached:
                print(f"✅ [handle_turn_resolution_with_ai] Game Over by reaching max turns.")
                final_narration = f"최대 턴({max_turns}턴)에 도달하여 이야기가 마무리됩니다.\n\n{final_narration}"
            else:
                print(f"✅ [handle_turn_resolution_with_ai] Game Over by LLM's 'is_final_turn' flag.")

            await self.broadcast_to_group({
                "event": "game_over",
                "narration": final_narration,
                "personal_narrations": gm_result.get('personal', {}),
                "image": gm_result.get('image'),
            })

            await self.clear_game_state(self.room_id)

            @database_sync_to_async
            def update_room_status(room_id):
                try:
                    room = GameRoom.objects.get(id=room_id)
                    room.status = "waiting"
                    room.save(update_fields=["status"])
                    print(f"✅ DB room status updated to 'waiting'.")
                    return True
                except GameRoom.DoesNotExist:
                    print(f"❌ Failed to update room status: Room not found.")
                    return False
            
            await update_room_status(self.room_id)

        else:
            # ✅ 게임 계속 진행 로그 추가
            print(f"➡️ [handle_turn_resolution_with_ai] Game continues. Broadcasting 'turn_resolved'.")
            next_game_state = apply_gm_result_to_state(state, gm_result)
            
            narration = gm_result.get('narration', '아무 일도 일어나지 않았습니다.')
            next_game_state["conversation_history"].append({"role": "user", "content": f"(이번 턴 요약:\n{shari_choices})"})
            next_game_state["conversation_history"].append({"role": "assistant", "content": narration})
            await GameState.set_game_state(self.room_id, next_game_state)

            party_update = gm_result.get('party', [])
            if party_update:
                # 전체 캐릭터 목록에서 ID-이름 맵을 만듭니다.
                char_name_map = {c['id']: c['name'] for c in all_characters}
                # party_update 목록을 돌면서 이름이 없는 경우 채워줍니다.
                for member in party_update:
                    if 'name' not in member or not member['name']:
                        member['name'] = char_name_map.get(member['id'], member['id'])
            
            # ✨ 5. 프론트엔드에 '모든' 결과를 담아 브로드캐스트합니다.
            await self.broadcast_to_group({
                "event": "turn_resolved",
                "narration": narration,
                "personal_narrations": gm_result.get('personal', {}),
                "roundResult": {
                    "sceneIndex": current_scene['index'],
                    "results": all_player_results, # ✨ human_player_results 대신 all_player_results를 사용
                    "shari_rolls": gm_result.get('shari', {}).get('rolls', []),
                    "image": gm_result.get('image'),
                },
                "world_update": gm_result.get('world'),
                "party_update": party_update,
                "shari": gm_result.get('shari'),
                "image": gm_result.get('image'),
            })
    
    async def clear_game_state(self, room_id):
        """지정된 방의 게임 상태를 캐시에서 삭제합니다."""
        try:
            await database_sync_to_async(cache.delete)(f"game_state_{room_id}")
            print(f"✅ 캐시에서 게임 상태 삭제 완료. Room: {room_id}")
        except Exception as e:
            print(f"❌ 캐시 게임 상태 삭제 중 오류 발생: {e}")

    async def handle_ready_for_next_scene(self, user, history_data):
        """
        한 플레이어가 다음 씬으로 갈 준비가 되었음을 처리합니다.
        모든 플레이어가 준비되면 다음 씬을 생성합니다.
        """
        if not user.is_authenticated:
            return

        # 1. 현재 유저를 '준비' 상태로 기록합니다.
        await GameState.set_user_ready_for_next_scene(self.room_id, str(user.id))
        ready_users_set = await GameState.get_ready_users_for_next_scene(self.room_id)
        
        # 2. 현재 방의 모든 활성 참가자 목록을 가져옵니다.
        #    (이 부분은 DB 조회 대신 캐시된 RoomConsumer의 참가자 목록을 활용할 수도 있습니다)
        active_participants = await self._get_active_participants()
        active_participant_ids = {str(p.user.id) for p in active_participants}
        
        # 3. 모든 클라이언트에게 현재 '준비' 상태를 브로드캐스트합니다.
        await self.broadcast_to_group({
            "event": "next_scene_ready_state_update",
            "ready_users": list(ready_users_set),
            "total_users": len(active_participant_ids),
        })

        # 4. 모든 참가자가 준비되었는지 확인합니다.
        if active_participant_ids.issubset(ready_users_set):
            print(f"✅ 모든 플레이어 준비 완료. 다음 씬을 생성합니다. Room: {self.room_id}")
            
            # 5. (기존 로직) LLM을 호출하여 다음 씬 JSON을 생성합니다.
            state = await GameState.get_game_state(self.room_id)
            history = state.get("conversation_history", [])
            username = user.name
            
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
                world_data = {
                    "location": scene_json.get("round", {}).get("title"),
                    "notes": scene_json.get("round", {}).get("description")
                }
                await self.broadcast_to_group({
                    "event": "scene_update",
                    "scene": scene_json,
                    "world": world_data
                })
                await GameState.clear_ready_users_for_next_scene(self.room_id)

    # ✅ [추가] 현재 방의 참가자 목록을 가져오는 헬퍼 함수
    @database_sync_to_async
    def _get_active_participants(self):
        return list(GameJoin.objects.filter(gameroom_id=self.room_id, left_at__isnull=True).select_related("user"))

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
            print(f"ℹ️  불러온 게임을 시작합니다. User: {user.name}, Room: {self.room_id}")
            saved_session = await _get_session_by_room_id(self.room_id)
            
            if saved_session:
                # 이 함수가 최종적으로 'game_loaded' 이벤트를 프론트엔드에 보냅니다.
                await self.handle_continue_game(user, saved_session)
            else:
                await self.send_error_message("이어할 게임 기록을 찾을 수 없습니다.")
            return
        
        # 1. 기존 상태를 먼저 불러와서 character_setup 정보를 확보합니다.
        game_state = await GameState.get_game_state(self.room_id)
        character_setup_data = game_state.get("character_setup")

        # 2. 이제 새 게임을 위해 대화 기록만 초기화합니다. 캐릭터 정보는 유지됩니다.
        print(f"ℹ️  새 게임 시작. 대화 기록을 초기화하지만 캐릭터 정보는 유지합니다.")
        game_state = { "character_setup": character_setup_data } # character_setup 보존
        await GameState.set_game_state(self.room_id, game_state)

        scenario = await self.get_scenario_from_db(scenario_title)
        if not scenario:
            await self.send_error_message(f"시나리오 '{scenario_title}'를 찾을 수 없습니다.")
            return
        
        # characters_data는 LLM 프롬프트 생성에만 사용됩니다.
        system_prompt = self.create_system_prompt_for_json(scenario, characters_data)
        initial_history = [system_prompt]

        user_message = "모든 캐릭터가 참여하는 게임의 첫 번째 씬(sceneIndex: 0)을 생성해줘. 비극적인 사건 직후의 긴장감 있는 상황으로 시작해줘."
        scene_json = await self.ask_llm_for_scene_json(initial_history, user_message)

        if scene_json:
            world_data = {
                "location": scene_json.get("round", {}).get("title"),
                "notes": scene_json.get("round", {}).get("description")
            }
            await self.broadcast_to_group({
                "event": "scene_update",
                "scene": scene_json,
                "world": world_data
            })

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
            
            game_state = await GameState.get_game_state(self.room_id)
            game_state["current_scene"] = scene_json
            game_state["conversation_history"] = history
            await GameState.set_game_state(self.room_id, game_state)
            
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

        # 2. 이전 기록이 있고, 딕셔너리 형태이며, 'full_log_history' 키가 리스트인 경우에만 로그를 가져옵니다.
        #    그 외 모든 경우에는 안전하게 빈 리스트로 시작합니다.
        log_history = []
        if isinstance(previous_history, dict):
            retrieved_logs = previous_history.get("full_log_history")
            if isinstance(retrieved_logs, list):
                log_history = retrieved_logs
        
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
            "description": data.get("description", ""),
            "choices": data.get("choices", {}),
            "selectedChoices": data.get("selectedChoice", {}),
        }

        # 6. 캐릭터 정보와 함께 DB에 저장
        game_state = await GameState.get_game_state(self.room_id)
        character_data = game_state.get("character_setup")
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
            
            character_obj = None
            if character_data and isinstance(character_data, dict):
                my_char = character_data.get("myCharacter") or character_data.get("assignments", {}).get(str(user.id))
                if my_char and isinstance(my_char, dict):
                    char_id = my_char.get("id")
                    if char_id:
                        try:
                            character_obj = Character.objects.get(id=char_id)
                        except Character.DoesNotExist:
                            character_obj = None

            session, created = MultimodeSession.objects.update_or_create(
                gameroom=gameroom,  # <- 조회 기준을 gameroom으로 한정
                defaults={
                    'user': user,  # 마지막으로 저장한 유저를 기록
                    'scenario': scenario_obj,
                    'choice_history': new_entry,
                    'character_history': character_data if character_data else {},
                    'character': character_obj
                }
            )

            action = "생성" if created else "업데이트"
            print(f"✅ DB 저장 성공! (Room: {room_id}, Action: {action})")
            return True

        except Exception as e:
            print(f"❌ DB 저장 중 심각한 오류 발생: {e}")
            return False

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
            
            game_state = await GameState.get_game_state(self.room_id)
            game_state["current_scene"] = scene_json
            game_state["conversation_history"] = history
            await GameState.set_game_state(self.room_id, game_state)
            
            return scene_json
        except Exception as e:
            error_message = f"LLM 응답 처리 중 오류: {e}"
            print(f"❌ {error_message}")
            await self.send_error_message(error_message)
            return None
            
    def create_system_prompt_for_json(self, scenario, characters):
        """LLM이 구조화된 JSON을 생성하도록 지시하는 시스템 프롬프트"""
        char_descriptions = "\n".join(
            [f"- **{c['name']}** ({c['description']})\n  - 능력치: {c.get('ability', {}).get('stats', {})}" for c in characters]
        )
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

