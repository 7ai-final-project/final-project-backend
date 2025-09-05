# backend\game\routing.py
from django.urls import path, re_path
from . import consumers as game_consumers
from game import consumers as multi_mode_consumers

websocket_urlpatterns = [
    # 대기실 Consumer
    path("ws/game/<uuid:room_id>/", game_consumers.RoomConsumer.as_asgi()),
    
    # 실시간 게임 Consumer
    path("ws/game_realtime/<uuid:room_id>/", multi_mode_consumers.GameConsumer.as_asgi()),
    
    # 턴제 게임 Consumer
    path("ws/game_turnbased/<uuid:room_id>/", multi_mode_consumers.TurnBasedGameConsumer.as_asgi()),
]