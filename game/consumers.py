# backend\game\consumers.py
import json
import random
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

from django.contrib.auth.models import AnonymousUser

from game.models import GameRoom, GameJoin, GameRoomSelectScenario
from game.serializers import GameJoinSerializer
from .scenarios_turn import get_scene_template
from .round import perform_round_judgement, perform_turn_judgement
from .state import GameState


@database_sync_to_async
def _ensure_participant(room_id, user):
    print(f"➡️ ensure_participant: room={room_id}, user={user}")
    if not user or not user.is_authenticated:
        return None
    room = GameRoom.objects.filter(id=room_id).first()
    if not room:
        return None
    # join API가 이미 만들었으면 그대로, 없으면 만들어준다(개발 편의)
    participant, _ = GameJoin.objects.get_or_create(gameroom=room, user=user)
    return participant


@database_sync_to_async
def _toggle_ready(room_id, user):
    try:
        rp = GameJoin.objects.get(gameroom_id=room_id, user=user)
        rp.is_ready = not rp.is_ready
        rp.save(update_fields=["is_ready"])
        return True
    except GameJoin.DoesNotExist:
        return False


@database_sync_to_async
def _serialize_selected_by_room(room_id):
    qs = (
        GameJoin.objects.filter(gameroom_id=room_id)
        .select_related("user")
        .order_by("joined_at", "id")
    )
    return GameJoinSerializer(qs, many=True).data

class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        try:
            # [수정 🔥] int() 변환을 제거합니다. UUID는 문자열입니다.
            self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
            self.group_name = f"room_{self.room_id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            print("➡️ calling self.accept()")
            await self.accept()
            print("✅ accept() 완료")

            user = self.scope.get("user", AnonymousUser())
            print("👤 scope.user:", user)
            print("👀 scope:", self.scope)

            if getattr(user, "is_authenticated", False):
                pass

            print("✅ WebSocket connect user:", user)
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

        if action == "toggle_ready":
            if not getattr(user, "is_authenticated", False):
                await self.send_json({"type": "error", "message": "로그인이 필요합니다."})
                return
            ok = await _toggle_ready(self.room_id, user)
            if not ok:
                await self.send_json({"type": "error", "message": "참가자가 아닙니다."})
                return
            await self._broadcast_state()

        elif action == "ping":
            await self.send_json({"type": "pong"})

        elif action == "start_game":  # ✅ 방장만 가능
            if not getattr(user, "is_authenticated", False):
                await self.send_json({"type": "error", "message": "로그인이 필요합니다."})
                return

            # ✅ 방장 여부 확인
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
                # database_sync_to_async 데코레이터와 함께 사용할 쿼리 함수 정의
                @database_sync_to_async
                def get_selected_options(room_id):
                    # related_name을 사용하여 역참조
                    return GameRoomSelectScenario.objects.select_related(
                        'scenario', 'difficulty', 'mode', 'genre'
                    ).get(gameroom_id=room_id)

                selected_options = await get_selected_options(self.room_id)
            
            except GameRoomSelectScenario.DoesNotExist:
                await self.send_json({"type": "error", "message": "게임 옵션이 선택되지 않았습니다."})
                return

            # ✅ 상태 변경 (waiting → play)
            room.status = "play"
            await database_sync_to_async(room.save)(update_fields=["status"])

            # ✅ 모든 클라이언트에 브로드캐스트
            # 💡 수정: 프론트에서 받은 값이 아닌, DB에서 조회한 값을 사용합니다.
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "room_broadcast",
                    "message": {
                        "event": "game_start",
                        "roomId": str(self.room_id),
                        "topic": selected_options.scenario.title,
                        "difficulty": selected_options.difficulty.name,
                        "mode": selected_options.mode.name, # mode도 추가
                        "genre": selected_options.genre.name,
                    },
                },
            )

        elif action == "end_game":  # ✅ 방장만 가능
            if not getattr(user, "is_authenticated", False):
                await self.send_json({"type": "error", "message": "로그인이 필요합니다."})
                return

            # ✅ 방장 여부 확인
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

            # ✅ 상태 변경 (play → waiting)
            room.status = "waiting"
            # ✅ 모든 참가자의 is_ready 상태를 False로 초기화
            await database_sync_to_async(room.selected_by_room.update)(is_ready=False)
            await database_sync_to_async(room.save)(update_fields=["status"])

            # ✅ 모든 클라이언트에 브로드캐스트 (상태 갱신을 위해)
            await self._broadcast_state()

    async def _broadcast_state(self):
        selected_by_room = await _serialize_selected_by_room(self.room_id)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "room_state", "selected_by_room": selected_by_room},
        )

    async def room_state(self, event):
        await self.send_json({"type": "room_state", "selected_by_room": event["selected_by_room"]})

    async def room_broadcast(self, event):
        # broadcast 메시지를 클라이언트로 그대로 전달
        await self.send_json({
            "type": "room_broadcast",
            "message": event.get("message")
        })

    @database_sync_to_async
    def ensure_participant(room_id, user):  # self 제거
        room = GameRoom.objects.get(pk=room_id)
        participant, created = GameJoin.objects.get_or_create(
            # [수정] 모델 필드명 `gameroom`을 사용합니다.
            gameroom=room, user=user
        )
        return participant

class GameConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.group_name = f"game_{self.room_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # 게임 상태 초기화
        await GameState.ensure_scene(self.room_id, 0)
        # [수정 🔥] UUID 객체를 JSON으로 보내기 위해 str()로 변환합니다.
        await self.send_json({"type": "game_connect", "roomId": str(self.room_id)})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "scene_enter":
            scene_index = content.get("sceneIndex", 0)
            await GameState.ensure_scene(self.room_id, scene_index)
            # 모든 유저에게 알림
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "scene_state", "sceneIndex": scene_index}
            )

        elif msg_type == "choice_submit":
            role = content.get("role")
            choice_id = content.get("choiceId")
            scene_index = content.get("sceneIndex")

            await GameState.store_choice(self.room_id, scene_index, role, choice_id)

            all_submitted = await GameState.check_all_submitted(self.room_id, scene_index)
            if all_submitted:
                # 라운드 락
                await self.channel_layer.group_send(
                    self.group_name,
                    {"type": "round_locked", "sceneIndex": scene_index}
                )
                # 판정 수행
                results = await perform_round_judgement(self.room_id, scene_index)
                await self.channel_layer.group_send(
                    self.group_name,
                    {"type": "round_result", "sceneIndex": scene_index, "payload": results}
                )

        elif msg_type == "request_next_scene":
            scene_index = content.get("sceneIndex")
            next_index = await GameState.advance_scene(self.room_id, scene_index)
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "scene_advance", "sceneIndex": scene_index, "nextIndex": next_index}
            )

    # 그룹 이벤트 → 클라 전달
    async def scene_state(self, event):
        await self.send_json({"type": "scene_state", "sceneIndex": event["sceneIndex"]})

    async def round_locked(self, event):
        await self.send_json({"type": "round_locked", "sceneIndex": event["sceneIndex"]})

    async def round_result(self, event):
        await self.send_json({
            "type": "round_result",
            "sceneIndex": event["sceneIndex"],
            "payload": event["payload"]
        })

    async def scene_advance(self, event):
        await self.send_json({
            "type": "scene_advance",
            "sceneIndex": event["sceneIndex"],
            "nextIndex": event["nextIndex"]
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
        await GameState.set_game_state(self.room_id, initial_state)
        # connect 시 바로 상태를 보내지 않고, 클라이언트의 요청을 기다림
        
    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        state = await GameState.get_game_state(self.room_id)
        if not state: return

        # ✅ [수정] 클라이언트가 초기 상태를 요청하면 그때 전송
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
            # 씬 구조가 round.choices 대신 round.perRole 하위로 변경된 것을 반영
            choices_for_role = template.get("round", {}).get("choices", {}).get(player["role"], [])
            
            if not choices_for_role:
                # 선택지가 없는 경우의 예외 처리
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

    # 그룹 메시지 핸들러
    async def broadcast_game_state(self, event):
        await self.send_game_state()

    async def turn_roll_update(self, event):
        await self.send_json({
            "type": "turn_roll_update",
            "rolls": event["rolls"]
        })