# backend/game/story_mode/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import logging
from llm.story_mode.services import generate_single_play_step, stories

logger = logging.getLogger(__name__)

class StoryListView(APIView):
    def get(self, request):
        return Response(stories)

class StartGameView(APIView):
    def post(self, request):
        story_id = request.data.get('story_id')
        if not story_id:
            return Response({"error": "story_id가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            story = stories.get(story_id)
             # character_id = request.data.get('character')

            # if not story_id:
            #     return Response({"error": "storyId가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
            # if not character_id:
            #     return Response({"error": "character가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
            if not story: return Response({"error": "스토리를 찾을 수 없습니다."}, status=404)
            start_moment_id = story.get('start_moment_id')
            if not start_moment_id: return Response({"error": "시작 지점이 정의되지 않았습니다."}, status=500)

            ai_response = generate_single_play_step(
                story_id=story_id,
                current_moment_id=start_moment_id,
            )
            
            return Response(ai_response, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"StartGameView 오류: {e}")
            return Response({'error': f'서버 오류가 발생했습니다: {e}'}, status=500)

class MakeChoiceView(APIView):
    def post(self, request):
        story_id = request.data.get("story_id")
        choice_index = request.data.get("choice_index")
        current_moment_id = request.data.get("current_moment_id")

        if not all([story_id, choice_index is not None, current_moment_id]):
            return Response({"error": "story_id, choice_index, current_moment_id가 모두 필요합니다."}, status=400)

        try:
            ai_response = generate_single_play_step(
                story_id=story_id,
                current_moment_id=current_moment_id,
                choice_index=choice_index,
            )
            return Response(ai_response, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"MakeChoiceView 오류: {e}")
            return Response({'error': f'서버 오류가 발생했습니다: {e}'}, status=500)

# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from rest_framework.permissions import IsAuthenticated
# import logging

# # [수정] 필요한 모델과 서비스만 정확히 import 합니다.
# from ..models import GamePlaySession, Story, Scene, Choice 
# from llm.story_mode.services import process_player_choice, generate_ai_scene_from_db, get_total_endings_count

# logger = logging.getLogger(__name__)

# class StoryListWithProgressView(APIView):
#     """
#     DB에 저장된 스토리 목록과 현재 유저의 플레이 기록을 함께 반환합니다.
#     """
#     permission_classes = [IsAuthenticated]

#     def get(self, request):
#         user = request.user
#         story_list_with_progress = []
#         all_stories = Story.objects.all()

#         for story in all_stories:
#             session = GamePlaySession.objects.filter(player=user, story=story).first()
            
#             progress_data = {
#                 "id": story.id,
#                 "title": story.title,
#                 "description": story.description,
#                 "is_played": False,
#                 "unlocked_endings_count": 0,
#                 "total_endings_count": get_total_endings_count(story)
#             }

#             if session:
#                 progress_data.update({
#                     "is_played": True,
#                     "unlocked_endings_count": len(session.unlocked_ending_names),
#                 })
            
#             story_list_with_progress.append(progress_data)

#         return Response(story_list_with_progress)

# class StartGameView(APIView):
#     """
#     새로운 게임을 시작하고, DB에 플레이 기록을 생성/초기화합니다.
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         story_id = request.data.get('story_id')
#         try:
#             story = Story.objects.get(pk=story_id)
#         except Story.DoesNotExist:
#             return Response({"error": "존재하지 않는 이야기입니다."}, status=status.HTTP_404_NOT_FOUND)

#         # [수정 시작]
#         # '새로하기' 시에는 엔딩 기록을 초기화하지 않도록 update_or_create 로직을 변경합니다.
#         session, created = GamePlaySession.objects.get_or_create(
#             player=request.user,
#             story=story,
#             # 'get_or_create'를 사용하여 기존 세션이 있다면 가져오고, 없다면 새로 만듭니다.
#             # 'defaults'는 'create' 시에만 적용됩니다.
#         )
        
#         # '새로하기'이므로 게임 진행 관련 필드만 초기화합니다.
#         session.current_scene = None
#         session.scene_history = []
#         session.inventory = []
#         session.stats = {'wisdom': 0, 'courage': 0}
#         session.is_completed = False
#         session.save()
#         # [수정 끝]

#         updated_session, next_scene = process_player_choice(session, choice_id=None)
#         ai_data = generate_ai_scene_from_db(updated_session, next_scene, player_choice=None)

#         return Response({
#             "scene": ai_data.get("scene_text"),
#             "choices": ai_data.get("choices"),
#             "db_choices": list(next_scene.choices.all().values('id', 'text')),
#             "story_id": story.id,
#             "current_scene_id": next_scene.id,
#             "session_data": {
#                 "inventory": updated_session.inventory,
#                 "stats": updated_session.stats,
#             }
#         }, status=status.HTTP_200_OK)

# class ResumeGameView(APIView):
#     """ 중단했던 지점부터 게임을 다시 시작(이어하기)합니다. """
#     permission_classes = [IsAuthenticated]

#     def get(self, request, story_id):
#         try:
#             session = GamePlaySession.objects.get(player=request.user, story_id=story_id)
            
#             if not session.current_scene:
#                 return Response({"error": "저장된 기록이 없습니다. '새로하기'로 시작해주세요."}, status=status.HTTP_404_NOT_FOUND)
            
#             current_scene = session.current_scene
            
#             # 현재 장면으로 AI 텍스트 생성
#             ai_data = generate_ai_scene_from_db(session, current_scene, player_choice=None)
            
#             # 프론트엔드에 필요한 정보 조합
#             return Response({
#                 "scene": ai_data.get("scene_text"),
#                 "choices": ai_data.get("choices"),
#                 "db_choices": list(current_scene.choices.all().values('id', 'text')),
#                 "story_id": story_id,
#                 "current_scene_id": current_scene.id,
#                 "session_data": {
#                     "inventory": session.inventory,
#                     "stats": session.stats
#                 },
#                 "is_ending": not current_scene.choices.exists(),
#             }, status=status.HTTP_200_OK)

#         except GamePlaySession.DoesNotExist:
#             return Response({"error": "플레이 기록이 없습니다."}, status=status.HTTP_404_NOT_FOUND)

# class MakeChoiceView(APIView):
#     """
#     사용자의 선택을 받아 DB 상태를 업데이트하고 다음 장면을 반환합니다.
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         story_id = request.data.get("story_id")
#         choice_id = request.data.get("choice_id")

#         if not all([story_id, choice_id]):
#             return Response({"error": "story_id와 choice_id가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)
        
#         try:
#             session = GamePlaySession.objects.get(player=request.user, story_id=story_id)
#         except GamePlaySession.DoesNotExist:
#             return Response({"error": "플레이 기록이 없습니다."}, status=status.HTTP_404_NOT_FOUND)

#         updated_session, next_scene = process_player_choice(session, choice_id)
#         player_choice_obj = Choice.objects.get(pk=choice_id)
#         ai_data = generate_ai_scene_from_db(updated_session, next_scene, player_choice_obj)
        
#         # [핵심 수정!] 엔딩 도달 여부를 확인하고 DB에 기록합니다.
#         # 다음 장면에 선택지가 없다면(is_ending), 엔딩으로 간주합니다.
#         is_ending = not next_scene.choices.exists()
#         if is_ending:
#             # 이미 본 엔딩이 아니라면, unlocked_ending_names 목록에 추가합니다.
#             if next_scene.name not in updated_session.unlocked_ending_names:
#                  updated_session.unlocked_ending_names.append(next_scene.name)
#                  updated_session.is_completed = True # 스토리 완료 상태로 변경
#                  updated_session.save() # 변경사항을 DB에 최종 저장!

#         return Response({
#             "scene": ai_data.get("scene_text"),
#             "choices": ai_data.get("choices"),
#             "db_choices": list(next_scene.choices.all().values('id', 'text')),
#             "story_id": story_id,
#             "current_scene_id": next_scene.id,
#             "session_data": {
#                 "inventory": updated_session.inventory,
#                 "stats": updated_session.stats,
#             },
#             "is_ending": is_ending, # [추가] 프론트엔드에 현재 장면이 엔딩인지 알려줌
#         }, status=status.HTTP_200_OK)

# class UndoChoiceView(APIView):
#     """
#     가장 마지막 선택을 취소하고 이전 상태로 돌아갑니다.
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         story_id = request.data.get('story_id')
#         try:
#             session = GamePlaySession.objects.get(player=request.user, story_id=story_id)
            
#             if len(session.scene_history) < 2:
#                 return Response({"error": "더 이상 뒤로 갈 수 없습니다."}, status=status.HTTP_400_BAD_REQUEST)
            
#             session.scene_history.pop() # 현재 장면을 히스토리에서 제거
#             previous_scene_id = session.scene_history[-1]
#             previous_scene = Scene.objects.get(pk=previous_scene_id)
            
#             session.current_scene = previous_scene
#             # 참고: 이 방식은 아이템/스탯 변화를 되돌리지는 않습니다.
#             session.save()
            
#             ai_data = generate_ai_scene_from_db(session, previous_scene, player_choice=None)
            
#             return Response({
#                 "scene": ai_data.get("scene_text"),
#                 "choices": ai_data.get("choices"),
#                 "db_choices": list(previous_scene.choices.all().values('id', 'text')),
#                 "story_id": story_id,
#                 "current_scene_id": previous_scene.id,
#                 "session_data": {
#                     "inventory": session.inventory,
#                     "stats": session.stats
#                 }
#             }, status=status.HTTP_200_OK)
            
#         except GamePlaySession.DoesNotExist:
#             return Response({"error": "플레이 기록이 없습니다."}, status=status.HTTP_404_NOT_FOUND)