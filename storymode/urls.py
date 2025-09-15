from django.urls import path
from storymode.views import StartGameView, MakeChoiceView, StoryListView

urlpatterns = [
    path('story/start/', StartGameView.as_view(), name='story-start'),
    path('story/choice/', MakeChoiceView.as_view(), name='story-make-choice'),
    path('story/stories/', StoryListView.as_view(), name='story-list'),
]