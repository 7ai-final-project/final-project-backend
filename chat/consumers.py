import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer  # ✅ 추가

class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_name = f"chat_{self.room_id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        print("➡️ ChatConsumer.connect called")
        await self.accept()
        print("✅ ChatConsumer accept 완료")
        print("👤 Chat scope.user:", self.scope.get("user"))

    async def disconnect(self, close_code):
        print("❌ disconnect called, code=", close_code)
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive_json(self, content, **kwargs):
        message = content.get("message")
        if message:
            user = self.scope["user"]
            # ✅ 이메일 말고 name만 사용
            username = getattr(user, "name", None)
            if not username:
                username = getattr(user, "username", None) or "Unknown"

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat.message",
                    "user": username,
                    "message": message,
                }
            )

    async def chat_message(self, event):
        # 그룹에서 전달된 메시지를 WebSocket으로 전송
        await self.send_json({
            "user": event["user"],
            "message": event["message"]
        })