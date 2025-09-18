from django.urls import path
from game.views import (
    RoomListCreateView, RoomDetailView, JoinRoomView, LeaveRoomView, 
    ToggleReadyView, StartMultiGameView, EndMultiGameView,
    ScenarioListView, GenreListView, DifficultyListView, ModeListView, get_scene_templates,
    GameRoomSelectScenarioView, CharacterListView, MySessionDetailView,
    SingleGameInitialView, SingleGameProceedView, SingleGameSaveView, SingleGameNextSceneView,
    SingleGameSessionCheckView, SingleGameContinueView
)
from game.gm_engine import ProposeAPIView, ResolveAPIView  # ← 추가

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

    # --- SHARI GM 엔드포인트 (추가) ---
    path("llm/multi_mode/gm/propose", ProposeAPIView.as_view(), name="gm-propose"),
    path("llm/multi_mode/gm/resolve", ResolveAPIView.as_view(), name="gm-resolve"),

    path("single/initial/", SingleGameInitialView.as_view(), name="single-game-initial"),
    path("single/proceed/", SingleGameProceedView.as_view(), name="single-game-proceed"),
    path('single/next-scene/', SingleGameNextSceneView.as_view(), name='single_game_next_scene'),
    path("single/save/", SingleGameSaveView.as_view(), name="single-game-save"),
    path("single/session-check/", SingleGameSessionCheckView.as_view(), name="single-game-session-check"),
    path("single/continue/", SingleGameContinueView.as_view(), name="single-game-continue"),
]