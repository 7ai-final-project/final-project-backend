# backend/game/multi_mode/views.py

from rest_framework import generics, permissions, status, viewsets 
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.hashers import check_password

from game.models import GameRoom, GameJoin
from game.serializers import GameRoomSerializer

# Channels 브로드캐스트
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .. import scenarios_turn, scenarios_realtime

def get_scene_templates(request):
    """
    모든 씬 데이터를 JSON으로 반환
    """
    mode = request.GET.get("mode", "realtime")

    source_templates = None
    if mode == "turn_based":
        source_templates = scenarios_turn.SCENE_TEMPLATES
    else:
        # 기본값은 realtime 모드
        source_templates =scenarios_realtime.SCENE_TEMPLATES

    data = [tpl for tpl in source_templates]

    return JsonResponse({"scenes": data})

def broadcast_room(room_id, payload):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"room_{room_id}",
        {"type": "room.broadcast", "payload": payload},
    )

class RoomListCreateView(generics.ListCreateAPIView):
    queryset = GameRoom.objects.all().order_by("-created_at")
    serializer_class = GameRoomSerializer

    def get_queryset(self):
        queryset = GameRoom.objects.all().order_by("-created_at")
        
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
            instance.delete()
            broadcast_room(room_id, {"type": "room_deleted", "room_id": room_id})
        except Exception as e:
            raise ValidationError({"detail": f"방 삭제 실패: {str(e)}"})

class JoinRoomView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        room = get_object_or_404(GameRoom, pk=pk)
        user = request.user

        # 이미 참가 중인지 확인
        if room.selected_by_room.filter(user=user).exists():
            # 이미 참가 중이면 그냥 성공 처리
            data = GameRoomSerializer(room).data
            return Response(data, status=status.HTTP_200_OK)
        
        # 방이 꽉 찼는지 확인
        if room.selected_by_room.count() >= room.max_players:
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
        print("👀 leave view user:", request.user)
        print("👀 room owner:", room.owner)
        print("👀 participants:", list(room.selected_by_room.all()))

        try:
            # 👇 [수정] 'room=room'을 'gameroom=room'으로 수정
            participant = GameJoin.objects.get(gameroom=room, user=request.user)
        except GameJoin.DoesNotExist:
            raise NotFound("이 방의 참가자가 아닙니다.")

        participant.delete()
        broadcast_room(room.id, {"type": "leave", "user": request.user.email})
        print(f"✅ {request.user} leave 성공 (owner={room.owner})")
        print("👀 leave view user:", request.user.email)

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
        participants = room.selected_by_room.all()
        all_ready = participants.exists() and all(p.is_ready for p in participants)

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

        participants = room.selected_by_room.all()
        if not (participants.exists() and all(p.is_ready for p in participants)):
            raise PermissionDenied("모든 참가자가 준비해야 합니다.")

        room.status = "in_game"
        room.save()

        # 'leave'가 아니라 'start' 이벤트를 보내는 것이 더 명확할 수 있습니다.
        broadcast_room(room.id, {"type": "game_started", "user": request.user.email})
        return Response(GameRoomSerializer(room).data, status=status.HTTP_200_OK)
    
class RoomViewSet(viewsets.ModelViewSet):
    queryset = GameRoom.objects.all()
    serializer_class = GameRoomSerializer

    @action(detail=True, methods=["post"], url_path="start")
    def start_game(self, request, pk=None):
        room = self.get_object()
        if room.owner != request.user:
            return Response({"error": "방장만 게임을 시작할 수 있습니다."}, status=403)
        room.status = "in_game"
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