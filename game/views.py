# backend/game/multi_mode/views.py
import datetime
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.hashers import check_password

from game.models import (
    GameRoom, GameJoin, Scenario, Genre,
    Difficulty, Mode, GameRoomSelectScenario, Character, MultimodeSession,SinglemodeSession
)
from game.serializers import (
    GameRoomSerializer, ScenarioSerializer, GenreSerializer,
    DifficultySerializer, ModeSerializer, GameRoomSelectScenarioSerializer, CharacterSerializer, MultimodeSessionSerializer, SinglemodeSessionSerializer
)

import json
import uuid
import re
import random
from openai import AsyncAzureOpenAI # 비동기 호출을 위해 유지
import os
from dotenv import load_dotenv

from .gm_engine import AIGameMaster  # 멀티플레이 전용
from . import gm_engine_single       # 싱글플레이 전용

# Channels 브로드캐스트
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from game import scenarios_turn

load_dotenv()
oai_client = AsyncAzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview"),
)
OAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
GM_ENGINE = AIGameMaster()

def create_system_prompt_for_json(scenario, characters):
    # 이 함수의 내용은 consumers.py에 있던 것과 동일합니다.
    # ... (이전 답변에 제공된 전체 함수 코드를 여기에 붙여넣으세요) ...
    char_descriptions = "\n".join(
        [f"- **{c['name']}** ({c['description']})\n  - 능력치: {c.get('stats', {})}" for c in characters]
    )
    json_schema = """
    {
      "id": "string (예: scene0)", "index": "number (예: 0)", "roleMap": { "캐릭터이름": "역할ID" },
      "round": {
        "title": "string", "description": "string",
        "choices": { "역할ID": [{ "id": "string", "text": "string", "appliedStat": "string", "modifier": "number" }] }
      }
    }"""
    prompt = f"""
    당신은 TRPG 게임의 시나리오를 실시간으로 생성하는 AI입니다. 당신의 임무는 사용자 행동에 따라 다음 게임 씬 데이터를 "반드시" 아래의 JSON 스키마에 맞춰 생성하는 것입니다.
    ## 게임 배경\n- 시나리오: {scenario.title} ({scenario.description})\n- 참가 캐릭터 정보: {char_descriptions}
    ## 출력 JSON 스키마 (필수 준수)\n- `appliedStat` 필드의 값은 반드시 '힘', '민첩', '지식', '의지', '매력', '운' 중 하나여야 합니다.\n\n```json\n{json_schema}\n```"""
    return {"role": "system", "content": prompt}

def extract_json_block(text: str) -> str:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if match: return match.group(1)
    return text

async def ask_llm_for_scene_json(oai_client, OAI_DEPLOYMENT, history, user_message):
    history.append({"role": "user", "content": user_message})
    try:
        completion = await oai_client.chat.completions.create(
            model=OAI_DEPLOYMENT, messages=history, max_tokens=4000, temperature=0.7
        )
        response_text = completion.choices[0].message.content
        json_str = extract_json_block(response_text)
        scene_json = json.loads(json_str)
        history.append({"role": "assistant", "content": response_text})
        return scene_json, history
    except Exception as e:
        print(f"❌ LLM 응답 처리 중 오류: {e}")
        return None, history

def get_scene_templates(request):
    """
    턴제 모드의 씬 데이터만 JSON으로 반환하도록 수정
    (실시간 모드는 이제 WebSocket Consumer가 LLM으로 직접 생성)
    """
    mode = request.GET.get("mode", "turn_based") # 기본값을 turn_based로 변경

    source_templates = None
    if mode == "turn_based":
        source_templates = scenarios_turn.SCENE_TEMPLATES
    else:
        # 실시간 모드는 더 이상 여기서 데이터를 제공하지 않음
        return JsonResponse({"scenes": [], "message": "Realtime mode is now handled by WebSocket."}, status=404)

    data = [tpl for tpl in source_templates]

    return JsonResponse({"scenes": data})

def broadcast_room(room_id, payload):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"room_{room_id}",
        {"type": "room.broadcast", "payload": payload},
    )

class RoomListCreateView(generics.ListCreateAPIView):
    queryset = GameRoom.objects.filter(is_deleted=False).order_by("-created_at")  
    #queryset = GameRoom.objects.filter(deleted_at__isnull=True).order_by("-created_at") # 삭제되지 않은 방만 조회하도록 변경
    serializer_class = GameRoomSerializer

    def get_queryset(self):
        queryset = GameRoom.objects.exclude(
            Q(is_deleted=True) | Q(status='finish')
        ).order_by("-created_at")
        #queryset = GameRoom.objects.filter(deleted_at__isnull=True).order_by("-created_at")
        
        # 이름으로 검색 (search 쿼리 파라미터)
        search_query = self.request.query_params.get('search', None)
        if search_query:
            queryset = queryset.filter(name__icontains=search_query)

        # 상태로 필터링 (status 쿼리 파라미터)
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        return queryset

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        if not self.request.user.is_authenticated:
            raise PermissionDenied("로그인이 필요합니다.")
        try:
            room = serializer.save(owner=self.request.user)
            # 👇 이 부분은 이미 올바르게 수정되어 있었습니다.
            GameJoin.objects.get_or_create(gameroom=room, user=self.request.user)
            broadcast_room(room.id, {"type": "room_created", "room_id": room.id})
        except Exception as e:
            raise ValidationError({"detail": f"방 생성 실패: {str(e)}"})


class RoomDetailView(generics.RetrieveDestroyAPIView):
    queryset = GameRoom.objects.all()
    serializer_class = GameRoomSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def perform_destroy(self, instance):
        if not self.request.user.is_authenticated:
            raise PermissionDenied("로그인이 필요합니다.")
        if instance.owner != self.request.user:
            raise PermissionDenied("방장은 본인 방만 삭제할 수 있습니다.")
        try:
            room_id = instance.id
            instance.deleted_at = timezone.now()
            instance.status = "finish"
            instance.is_deleted = True 
            
            #instance.save(update_fields=["status", "is_deleted"])
            instance.save(update_fields=["deleted_at", "status", "is_deleted"])
            
            instance.selected_by_room.update(is_ready=False)

            broadcast_room(room_id, {"type": "room_deleted", "room_id": room_id})
        except Exception as e:
            raise ValidationError({"detail": f"방 삭제 실패: {str(e)}"})

class JoinRoomView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(GameRoom, pk=pk)
        user = request.user

        # 이미 참가 중인지 확인 (left_at이 null인 경우만)
        if room.selected_by_room.filter(user=user, left_at__isnull=True).exists():
            # 이미 참가 중이면 그냥 성공 처리
            data = GameRoomSerializer(room).data
            return Response(data, status=status.HTTP_200_OK)
        
        # 방이 꽉 찼는지 확인 (left_at이 null인 경우만)
        if room.selected_by_room.filter(left_at__isnull=True).count() >= room.max_players:
            raise ValidationError("방이 가득 찼습니다.")
        
        # 비밀방인 경우, 비밀번호 확인
        if room.room_type == 'private':
            password = request.data.get('password')
            # room.password가 None이거나 비어있는지, 혹은 비밀번호가 맞는지 확인
            if not room.password or not check_password(password, room.password):
                raise PermissionDenied("비밀번호가 올바르지 않습니다.")

        # 모든 검사를 통과했으면 참가자로 추가
        GameJoin.objects.create(gameroom=room, user=user)
        
        # 참가자가 추가된 최신 방 상태를 다시 로드
        room.refresh_from_db()
        
        data = GameRoomSerializer(room).data
        broadcast_room(room.id, {"type": "join", "user": user.email})
        return Response(data, status=status.HTTP_200_OK)

class LeaveRoomView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(GameRoom, pk=pk)
        user = request.user
        
        try:
            participant = GameJoin.objects.get(gameroom=room, user=user, left_at__isnull=True)
        except GameJoin.DoesNotExist:
            raise NotFound("이 방의 참가자가 아닙니다.")

        # 먼저, 나가는 유저의 상태를 업데이트합니다.
        participant.is_ready = False
        participant.left_at = timezone.now()
        participant.save(update_fields=['is_ready', 'left_at'])
        
        # 유저가 나간 후, 방에 남은 활성 참가자 수를 확인합니다.
        remaining_count = room.selected_by_room.filter(left_at__isnull=True).count()
        
        if remaining_count == 0:
            # 남은 인원이 0명이면 방을 삭제(소프트 삭제) 처리합니다.
            room.deleted_at = timezone.now()
            room.status = "finish"
            room.is_deleted = True
            #room.save(update_fields=["status", "is_deleted"])
            room.save(update_fields=["deleted_at", "status", "is_deleted"])
            
            # 모든 클라이언트에게 방이 삭제되었음을 알립니다.
            broadcast_room(room.id, {"type": "room_deleted", "room_id": room.id})
            
            # 방이 삭제되었으므로 별도 콘텐츠 없이 성공 응답을 보냅니다.
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        else:
            # 아직 방에 다른 유저가 남아있으면, 퇴장 사실만 알립니다.
            broadcast_room(room.id, {"type": "leave", "user": user.email})
            return Response(GameRoomSerializer(room).data, status=status.HTTP_200_OK)


class ToggleReadyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(GameRoom, pk=pk)
        
        # 👇 [수정] 'room=room'을 'gameroom=room'으로 수정
        participant, _ = GameJoin.objects.get_or_create(
            gameroom=room, user=request.user
        )
        participant.is_ready = not participant.is_ready
        participant.save()

        # 모두 준비됐는지 체크(방장 포함)
        selected_by_room = room.selected_by_room.filter(left_at__isnull=True)
        all_ready = selected_by_room.exists() and all(p.is_ready for p in selected_by_room)

        payload = {
            "type": "ready_update",
            "user": request.user.email,
            "all_ready": all_ready,
        }
        broadcast_room(room.id, payload)

        return Response(GameRoomSerializer(room).data, status=status.HTTP_200_OK)

class StartMultiGameView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(GameRoom, pk=pk)
        if room.owner != request.user:
            raise PermissionDenied("방장만 시작할 수 있습니다.")

        selected_by_room = room.selected_by_room.filter(left_at__isnull=True)
        if not (selected_by_room.exists() and all(p.is_ready for p in selected_by_room)):
            raise PermissionDenied("모든 참가자가 준비해야 합니다.")

        try:
            room_options = GameRoomSelectScenario.objects.get(gameroom=room)
        except GameRoomSelectScenario.DoesNotExist:
            raise NotFound("게임 옵션이 설정되지 않았습니다.")

        # 🟢 WebSocket 페이로드에 게임 옵션 데이터를 포함시킵니다.
        #    참고: Serializer를 사용하여 객체를 JSON으로 변환합니다.
        payload = {
            "type": "room_broadcast",
            "message": {
                "event": "game_start",
                "topic": room_options.scenario.title, # 시나리오 제목
                "difficulty": room_options.difficulty.name, # 난이도 이름
                "mode": room_options.mode.name, # 모드 이름
                "genre": room_options.genre.name, # 장르 이름
            }
        }

        room.status = "play"
        room.save()

        # 🟢 수정된 페이로드를 브로드캐스트합니다.
        broadcast_room(room.id, payload)
        
        # API 응답
        return Response(GameRoomSerializer(room).data, status=status.HTTP_200_OK)
    
class RoomViewSet(viewsets.ModelViewSet):
    queryset = GameRoom.objects.all()
    serializer_class = GameRoomSerializer

    @action(detail=True, methods=["post"], url_path="start")
    def start_game(self, request, pk=None):
        room = self.get_object()
        if room.owner != request.user:
            return Response({"error": "방장만 게임을 시작할 수 있습니다."}, status=403)
        room.status = "play"
        room.save()
        return Response({"status": "게임 시작"}, status=200)

    @action(detail=True, methods=["post"], url_path="end")
    def end_game(self, request, pk=None):
        room = self.get_object()
        if room.owner != request.user:
            return Response({"error": "방장만 게임을 종료할 수 있습니다."}, status=403)
        room.status = "waiting"
        room.save()
        return Response({"status": "게임 종료"}, status=200)
    
class EndMultiGameView(APIView):
    def post(self, request, pk):
        try:
            room = GameRoom.objects.get(pk=pk)
        except GameRoom.DoesNotExist:
            return Response({"error": "방을 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        if room.owner != request.user:
            return Response({"error": "방장만 게임을 종료할 수 있습니다."}, status=status.HTTP_403_FORBIDDEN)

        room.status = "waiting"
        room.save()
        return Response({"status": "게임 종료"}, status=status.HTTP_200_OK)
    
class ScenarioListView(generics.ListAPIView):
    """모든 시나리오 목록을 반환하는 API"""
    queryset = Scenario.objects.filter(is_display=True)
    serializer_class = ScenarioSerializer
    permission_classes = [permissions.AllowAny]

class GenreListView(generics.ListAPIView):
    """모든 장르 목록을 반환하는 API"""
    queryset = Genre.objects.filter(is_display=True)
    serializer_class = GenreSerializer
    permission_classes = [permissions.AllowAny]

class DifficultyListView(generics.ListAPIView):
    """모든 난이도 목록을 반환하는 API"""
    queryset = Difficulty.objects.filter(is_display=True)
    serializer_class = DifficultySerializer
    permission_classes = [permissions.AllowAny]

class ModeListView(generics.ListAPIView):
    """모든 게임 모드 목록을 반환하는 API"""
    queryset = Mode.objects.filter(is_display=True)
    serializer_class = ModeSerializer
    permission_classes = [permissions.AllowAny]

# --- 게임방 옵션 선택/저장 API View ---

class GameRoomSelectScenarioView(APIView):
    """게임방의 시나리오/옵션을 설정하는 API"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(GameRoom, pk=pk)

        if room.owner != request.user:
            raise PermissionDenied("방장만 게임 옵션을 변경할 수 있습니다.")

        serializer = GameRoomSelectScenarioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        selection, created = GameRoomSelectScenario.objects.update_or_create(
            gameroom=room,
            defaults=serializer.validated_data
        )

        # ✅ [핵심 수정] 옵션 저장 후, 모든 클라이언트에게 변경 내용을 브로드캐스트합니다.
        # Serializer의 .data는 객체가 아닌 ID를 포함하므로, 직접 객체에서 이름을 추출합니다.
        payload = {
            "type": "options_update",
            "options": {
                "scenarioId": selection.scenario.id,
                "scenarioTitle": selection.scenario.title,
                "genreId": selection.genre.id,
                "genreName": selection.genre.name,
                "difficultyId": selection.difficulty.id,
                "difficultyName": selection.difficulty.name,
                "modeId": selection.mode.id,
                "modeName": selection.mode.name,
            }
        }
        broadcast_room(room.id, payload)
        # ✅ 여기까지 추가

        response_serializer = GameRoomSelectScenarioSerializer(instance=selection)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

class CharacterListView(generics.ListAPIView):
    """
    쿼리 파라미터 'topic'으로 전달된 시나리오(Scenario)에 해당하는
    캐릭터 목록을 반환하는 API 뷰입니다.
    """
    serializer_class = CharacterSerializer # 수정된 Serializer를 그대로 사용

    def get_queryset(self):
        topic_name = self.request.query_params.get('topic', None)
        if topic_name:
            return Character.objects.filter(scenario__title=topic_name)
        return Character.objects.none()
    
class MySessionDetailView(APIView):
    """
    현재 로그인한 유저가 특정 방(room_id)에 저장한 세션 정보를 반환하는 API
    """
    permission_classes = [IsAuthenticated] # 로그인한 유저만 접근 가능

    def get(self, request, pk, format=None): # URL의 <uuid:pk>는 방의 ID 입니다.
        try:
            session = MultimodeSession.objects.get(gameroom_id=pk)
            serializer = MultimodeSessionSerializer(session)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except MultimodeSession.DoesNotExist:
            return Response(
                {"detail": "해당 방에 저장된 세션이 없습니다."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
class SingleGameInitialView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        topic = request.data.get("topic")
        characters_data = request.data.get("characters", [])
        my_character_data = request.data.get("myCharacter")

        if not topic or not characters_data or not my_character_data:
            return Response({"error": "토픽과 캐릭터 정보(myCharacter, characters)가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

        scenario = Scenario.objects.filter(title=topic).first()
        if not scenario:
            return Response({"error": f"시나리오 '{topic}'을(를) 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
        
        # ✅ [수정] create_system_prompt에 my_character 대신 characters_data(전체 목록)를 전달합니다.
        system_prompt = gm_engine_single.create_system_prompt(scenario, characters_data)
        initial_history = [system_prompt]
        user_message = "모든 캐릭터가 참여하는 게임의 첫 번째 씬(sceneIndex: 0)을 생성해줘. 비극적인 사건 직후의 긴장감 있는 상황으로 시작해줘."
        
        scene_json, history = async_to_sync(gm_engine_single.ask_llm_for_scene)(initial_history, user_message)
        
        if scene_json:
            initial_state = {
                "conversation_history": history,
                "scenario": {"title": scenario.title, "summary": scenario.description},
                "party": characters_data
            }
            return Response({"scene": scene_json, "initial_state": initial_state}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "첫 씬을 생성하는 데 실패했습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SingleGameProceedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        player_result = request.data.get("playerResult")
        ai_characters = request.data.get("aiCharacters", [])
        current_scene = request.data.get("currentScene")
        game_state = request.data.get("gameState")
        usage_data = request.data.get("usage")
        
        if not all([player_result, current_scene, game_state]):
            return Response({"error": "필수 데이터가 누락되었습니다."}, status=status.HTTP_400_BAD_REQUEST)
        
        all_player_results = [player_result]
        scene_choices_data = current_scene.get('round', {}).get('choices', {})

        # 1. AI 캐릭터 턴 시뮬레이션 (기존과 동일)
        for ai_char in ai_characters:
            # ... (이 부분의 코드는 변경 없이 그대로 둡니다) ...
            role_id = current_scene.get('roleMap', {}).get(ai_char['name'])
            if not role_id: continue
            choices_for_role = scene_choices_data.get(role_id, [])
            if not choices_for_role: continue
            ai_choice = random.choice(choices_for_role)
            dice = random.randint(1, 20)
            stats = ai_char.get('stats', {})
            stat_value = stats.get(ai_choice['appliedStat'], 0)
            modifier = ai_choice['modifier']
            total = dice + stat_value + modifier
            dc = 13
            grade = "F"
            if dice == 20: grade = "SP"
            elif dice == 1: grade = "SF"
            elif total >= dc: grade = "S"
            ai_result = {
                "role": role_id, "choiceId": ai_choice['id'], "grade": grade, "dice": dice,
                "appliedStat": ai_choice['appliedStat'], "statValue": stat_value, "modifier": modifier, 
                "total": total, "characterName": ai_char['name'], "characterId": ai_char['id'],
            }
            all_player_results.append(ai_result)

        # 2. AI 서사 생성을 위한 정보 준비
        for result in all_player_results:
            try:
                result['choiceText'] = next(c['text'] for c in scene_choices_data.get(result['role'], []) if c['id'] == result['choiceId'])
            except (StopIteration, KeyError):
                result['choiceText'] = "알 수 없는 행동"
        
        # ✅ [핵심 수정] 스킬/아이템 사용 정보를 텍스트로 변환
        usage_text = ""
        if usage_data:
            usage_type = "스킬" if usage_data.get("type") == "skill" else "아이템"
            usage_name = usage_data.get("data", {}).get("name", "")
            player_name = player_result.get("characterName", "플레이어")
            if usage_name:
                usage_text = f"또한, {player_name}은(는) '{usage_name}' {usage_type}을(를) 사용했습니다."

        # ✅ 수정된 ask_llm_for_narration 함수에 usage_text 전달
        scene_title = current_scene.get('round', {}).get('title', '알 수 없는 곳')
        narration, shari_data = async_to_sync(gm_engine_single.ask_llm_for_narration)(
            game_state.get('conversation_history', []),
            scene_title,
            all_player_results,
            usage_text
        )
        
        history = game_state.get('conversation_history', [])
        history.append({"role": "user", "content": "플레이어들의 행동 결과 요약."})
        history.append({"role": "assistant", "content": narration})
        game_state['conversation_history'] = history

        response_data = {
            "narration": narration,
            "roundResult": { "results": all_player_results },
            "nextGameState": game_state,
            "shari": shari_data, # ✅ 응답에 shari 데이터를 추가합니다.
        }
        return Response(response_data, status=status.HTTP_200_OK)

class SingleGameSaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        game_state_to_save = request.data.get("gameState")
        character_history_to_save = request.data.get("characterHistory")
        character_id = request.data.get("characterId")
        difficulty_name = request.data.get("difficulty")
        genre_name = request.data.get("genre")
        mode_name = request.data.get("mode")

        if not all([game_state_to_save, character_history_to_save, character_id, difficulty_name, genre_name, mode_name]):
            return Response({"error": "저장에 필요한 모든 데이터가 전송되지 않았습니다."}, status=status.HTTP_400_BAD_REQUEST)
        
        # ✅ [핵심 수정] 저장하기 전에 AI를 호출하여 줄거리 요약본을 생성합니다.
        conversation_history = game_state_to_save.get('conversation_history', [])
        summary = async_to_sync(gm_engine_single.ask_llm_for_summary)(conversation_history)
        
        # ✅ 생성된 요약본을 저장할 데이터(choice_history)에 추가합니다.
        game_state_to_save['summary'] = summary
        
        user = request.user
        scenario_title = game_state_to_save.get("scenario", {}).get("title")
        
        try:
            scenario = Scenario.objects.filter(title=scenario_title).first()
            character = Character.objects.filter(id=character_id).first()
            difficulty = Difficulty.objects.filter(name=difficulty_name).first()
            genre = Genre.objects.filter(name=genre_name).first()
            mode = Mode.objects.filter(name=mode_name).first()

            if not scenario:
                return Response({"error": "저장할 시나리오 정보를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
            if not character:
                return Response({"error": "저장할 캐릭터 정보를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
            if not difficulty:
                difficulty = Difficulty.objects.first()
            if not genre:
                genre = Genre.objects.first()
            if not mode:
                mode = Mode.objects.first()

            if not all([difficulty, genre, mode]):
                return Response({"error": "DB에 난이도, 장르 또는 모드 데이터가 하나 이상 존재해야 합니다."}, status=500)

        except Exception as e:
            return Response({"error": f"저장에 필요한 기본 정보를 찾는 중 예외 발생: {str(e)}"}, status=500)

        try:
            session, created = SinglemodeSession.objects.update_or_create(
                user=user,
                scenario=scenario,
                defaults={
                    'choice_history': game_state_to_save, # ❗ summary가 포함된 gameState
                    'character_history': character_history_to_save,
                    'character': character,
                    'difficulty': difficulty,
                    'genre': genre,
                    'mode': mode,
                    'status': 'play'
                }
            )
            return Response({"message": "게임 진행 상황이 저장되었습니다."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"세션 저장 중 DB 오류 발생: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class SingleGameSessionCheckView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        scenario_id = request.query_params.get('scenario_id')
        if not scenario_id:
            return Response({"error": "scenario_id가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 현재 유저와 시나리오 ID로 저장된 세션을 찾습니다.
            session = SinglemodeSession.objects.get(user=request.user, scenario_id=scenario_id)
            # 세션이 존재하면, Serializer를 통해 상세 정보를 반환합니다.
            serializer = SinglemodeSessionSerializer(session)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except SinglemodeSession.DoesNotExist:
            # 세션이 없으면 404 Not Found를 반환합니다.
            return Response({"detail": "저장된 세션이 없습니다."}, status=status.HTTP_404_NOT_FOUND)

class SingleGameContinueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        session_id = request.data.get('session_id')
        if not session_id:
            return Response({"error": "세션 ID가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 전달받은 ID로 저장된 세션을 불러옵니다.
            session = SinglemodeSession.objects.get(id=session_id, user=request.user)
        except SinglemodeSession.DoesNotExist:
            return Response({"error": "저장된 세션을 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        # 저장된 기록(gameState)을 가져옵니다.
        game_state = session.choice_history
        history = game_state.get('conversation_history', [])
        last_narration = "이전 줄거리에 이어서 계속됩니다."
        
        # 마지막 씬의 인덱스를 가져옵니다. (없으면 0)
        current_scene_index = -1
        for i in range(len(history) - 1, -1, -1):
            if history[i].get('role') == 'assistant':
                try:
                    # assistant의 응답에서 scene index를 찾아봅니다.
                    content_json = json.loads(gm_engine_single._extract_json_block(history[i]['content']))
                    current_scene_index = content_json.get('index', -1)
                    if current_scene_index != -1:
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # 저장된 기록을 바탕으로 "다음" 씬을 생성하도록 AI에게 요청합니다.
        user_message = f"이전에 저장된 게임을 이어서 진행합니다. 지금까지의 대화 기록을 바탕으로 다음 씬(sceneIndex: {current_scene_index + 1})을 생성해주세요."
        
        scene_json, updated_history = async_to_sync(gm_engine_single.ask_llm_for_scene)(history, user_message)

        if scene_json:
            game_state['conversation_history'] = updated_history
            # 프론트엔드에 필요한 모든 데이터를 반환합니다.
            return Response({
                "scene": scene_json,
                "loadedGameState": game_state,
                "loadedCharacterHistory": session.character_history
            }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "다음 씬을 생성하는 데 실패했습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class SingleGameNextSceneView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        game_state = request.data.get("gameState")
        last_narration = request.data.get("lastNarration")
        current_scene_index = request.data.get("currentSceneIndex", 0)

        if not game_state:
            return Response({"error": "게임 상태 정보가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

        history = game_state.get('conversation_history', [])
        user_message = f"이전 턴의 결과는 다음과 같아: \"{last_narration}\"\n이 결과를 바탕으로, 흥미진진한 다음 이야기(sceneIndex: {current_scene_index + 1})를 JSON 형식으로 생성해줘."
        
        scene_json, updated_history = async_to_sync(gm_engine_single.ask_llm_for_scene)(history, user_message)

        if scene_json:
            game_state['conversation_history'] = updated_history
            return Response({ "scene": scene_json, "updatedGameState": game_state }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "다음 씬을 생성하는 데 실패했습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
class SingleGameSaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        game_state_to_save = request.data.get("gameState")
        character_history_to_save = request.data.get("characterHistory")
        character_id = request.data.get("characterId")
        difficulty_name = request.data.get("difficulty")
        genre_name = request.data.get("genre")
        mode_name = request.data.get("mode")

        if not all([game_state_to_save, character_history_to_save, character_id, difficulty_name, genre_name, mode_name]):
            return Response({"error": "저장에 필요한 모든 데이터가 전송되지 않았습니다."}, status=status.HTTP_400_BAD_REQUEST)
        
        conversation_history = game_state_to_save.get('conversation_history', [])
        summary = async_to_sync(gm_engine_single.ask_llm_for_summary)(conversation_history)
        game_state_to_save['summary'] = summary
        
        user = request.user
        scenario_title = game_state_to_save.get("scenario", {}).get("title")
        
        try:
            scenario = Scenario.objects.filter(title=scenario_title).first()
            character = Character.objects.filter(id=character_id).first()
            difficulty = Difficulty.objects.filter(name=difficulty_name).first()
            genre = Genre.objects.filter(name=genre_name).first()
            mode = Mode.objects.filter(name=mode_name).first()

            if not scenario: return Response({"error": "저장할 시나리오 정보를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
            if not character: return Response({"error": "저장할 캐릭터 정보를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
            if not difficulty: difficulty = Difficulty.objects.first()
            if not genre: genre = Genre.objects.first()
            if not mode: mode = Mode.objects.first()
            if not all([difficulty, genre, mode]): return Response({"error": "DB에 난이도, 장르 또는 모드 데이터가 하나 이상 존재해야 합니다."}, status=500)

        except Exception as e:
            return Response({"error": f"저장에 필요한 기본 정보를 찾는 중 예외 발생: {str(e)}"}, status=500)

        try:
            session, created = SinglemodeSession.objects.update_or_create(
                user=user, scenario=scenario,
                defaults={
                    'choice_history': game_state_to_save, 'character_history': character_history_to_save,
                    'character': character, 'difficulty': difficulty, 'genre': genre, 'mode': mode, 'status': 'play'
                }
            )
            return Response({"message": "게임 진행 상황이 저장되었습니다."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"세션 저장 중 DB 오류 발생: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
