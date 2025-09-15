from django.urls import path
from game.views import (
    RoomListCreateView, RoomDetailView, JoinRoomView, LeaveRoomView, 
    ToggleReadyView, StartMultiGameView, EndMultiGameView,
    ScenarioListView, GenreListView, DifficultyListView, ModeListView, get_scene_templates,
    GameRoomSelectScenarioView, CharacterListView, MySessionDetailView
)

urlpatterns = [
    # --- 멀티플레이 모드 URL ---
    path("", RoomListCreateView.as_view(), name="room-list-create"),
    path("<uuid:pk>/", RoomDetailView.as_view(), name="room-detail"),
    path("<uuid:pk>/join/", JoinRoomView.as_view(), name="room-join"),
    path("<uuid:pk>/leave/", LeaveRoomView.as_view(), name="room-leave"),
    path("<uuid:pk>/toggle-ready/", ToggleReadyView.as_view(), name="room-toggle-ready"),
    path("<uuid:pk>/start/", StartMultiGameView.as_view(), name="room-start"),
    path("<uuid:pk>/end/", EndMultiGameView.as_view(), name="room-end"),
    path("api/scenes/", get_scene_templates, name="multi_api_scenes"),
    path("<uuid:pk>/my-session/", MySessionDetailView.as_view(), name="my-session-detail"),

    path("options/scenarios/", ScenarioListView.as_view(), name="scenario-list"),
    path("options/genres/", GenreListView.as_view(), name="genre-list"),
    path("options/difficulties/", DifficultyListView.as_view(), name="difficulty-list"),
    path("options/modes/", ModeListView.as_view(), name="mode-list"),
    path("characters/", CharacterListView.as_view(), name="character-list"),
    
    # --- 게임방 옵션 선택/저장 URL ---
    path("<uuid:pk>/options/", GameRoomSelectScenarioView.as_view(), name="room-select-scenario"),

]