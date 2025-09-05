# final-project/backend/image_gen/urls.py

from django.urls import path
from .views import GenerateSceneImageView

urlpatterns = [
    # '/api/generate-scene-image/' 라는 경로로 요청이 오면
    # views.py 파일의 GenerateSceneImageView를 실행하라고 알려줍니다.
    path('api/generate-scene-image/', GenerateSceneImageView.as_view(), name='generate-scene-image'),
]