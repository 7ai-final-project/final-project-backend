from django.urls import path # re_path 대신 path 사용을 권장
from chat.consumers import ChatConsumer
from game.consumers import RoomConsumer, GameConsumer
from game.routing import websocket_urlpatterns as game_websocket_urlpatterns

websocket_urlpatterns = [
    # room_id가 UUID라면 <uuid:room_id> 사용, 숫자라면 <int:room_id> 사용
    path("ws/chat/<uuid:room_id>/", ChatConsumer.as_asgi()), 
    path("ws/game/<uuid:room_id>/", RoomConsumer.as_asgi()),
    path("ws/multi_game/<uuid:room_id>/", GameConsumer.as_asgi()),
]
