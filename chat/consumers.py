import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import ChatMessage
from game.models import GameRoom

class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_name = f"chat_{self.room_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # ✅ 1. 연결 시 이전 채팅 기록을 불러와 전송
        message_history = await self.fetch_messages(self.room_id)
        await self.send_json({
            'type': 'history',
            'messages': message_history
        })

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # ✅ 2. 이전 채팅 기록을 DB에서 조회하는 함수 추가
    @database_sync_to_async
    def fetch_messages(self, room_id):
        """
        DB에서 이전 채팅 내역을 가져와 직렬화합니다. (최신 50개)
        """
        messages = ChatMessage.objects.filter(gameroom_id=room_id).order_by('-created_at')[:50]
        
        result = []
        for message in messages:
            user = message.user
            username = getattr(user, "name", None) or getattr(user, "username", None) or "Unknown"
            result.append({
                'user_id': str(user.id),
                'user': username,
                'message': message.message,
                'created_at': message.created_at.isoformat(),
            })
        
        # 최신 메시지가 아래에 오도록 순서를 뒤집어 반환
        result.reverse()
        return result

    @database_sync_to_async
    def create_chat_message(self, user, room_id, message):
        try:
            game_room = GameRoom.objects.get(id=room_id)
            message_type = 'Play' if game_room.status == 'play' else 'Lobby'
            
            # ✅ 생성된 메시지 객체를 반환하도록 수정 (생성 시간 등을 활용하기 위함)
            chat_message = ChatMessage.objects.create(
                gameroom=game_room,
                user=user,
                message_type=message_type,
                message=message
            )
            return chat_message
        except GameRoom.DoesNotExist:
            print(f"Error: GameRoom with id={room_id} does not exist.")
            return None
        except Exception as e:
            print(f"Error saving chat message: {e}")
            return None

    async def receive_json(self, content, **kwargs):
        message_text = content.get("message")
        user = self.scope.get("user")

        if message_text and user and user.is_authenticated:
            # DB에 메시지 저장 후, 저장된 객체(타임스탬프 포함)를 받아옴
            new_message_obj = await self.create_chat_message(user, self.room_id, message_text)

            if new_message_obj:
                username = getattr(user, "name", None) or getattr(user, "username", None) or "Unknown"

                # ✅ 3. 채널 그룹에 메시지 타입과 전체 데이터를 함께 전송
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat.message",
                        "message_data": {
                            'user_id': str(user.id),
                            "user": username,
                            "message": new_message_obj.message,
                            "created_at": new_message_obj.created_at.isoformat(),
                        }
                    }
                )

    # ✅ 3. 클라이언트로 메시지를 보낼 때, 타입을 명시하여 전송
    async def chat_message(self, event):
        """
        그룹으로부터 메시지를 받아 클라이언트에게 전송
        """
        await self.send_json({
            'type': 'new_message',
            'message': event["message_data"]
        })
