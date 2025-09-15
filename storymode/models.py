import uuid
from django.db import models
from django.conf import settings


# 스토리
class Story(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    title_eng = models.CharField(max_length=200, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    description_eng = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Django 모델에서 ForeignKey나 OneToOneField, ManyToManyField 등을 정의할 때, 참조하려는 모델 클래스가 아직 정의되지 않았을 경우(즉, 현재 파일의 아래쪽에 정의될 경우)에는 문자열로 모델 이름을 지정
    start_moment = models.ForeignKey('StorymodeMoment', on_delete=models.SET_NULL, null=True, blank=True, related_name='start_of_stories')
    is_display = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    image_path = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'story'

    def __str__(self):
        return self.title

# 스토리 분기점
class StorymodeMoment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='moments')
    title = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    description_eng = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    image_path = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'storymode_moment'

    def __str__(self):
        return f"[{self.story.title}] {self.title}"

    # 엔딩 분기점인지 확인 (선택지가 없으면 엔딩)
    def is_ending(self):
        return not self.choices.exists()

# 스토리 선택지
class StorymodeChoice(models.Model):
    ACTION_TYPE_CHOICES = [
        ('GOOD', 'Good'),
        ('NEUTRAL', 'Neutral'),
        ('BAD', 'Bad'),
        ('ENDING_GOOD', 'Ending_good'),
        ('ENDING_BAD', 'Ending_bad'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    moment = models.ForeignKey(StorymodeMoment, on_delete=models.CASCADE, related_name='choices')
    next_moment = models.ForeignKey(StorymodeMoment, on_delete=models.SET_NULL, null=True, blank=True, related_name='previous_choices')
    action_type = models.CharField(max_length=50, choices=ACTION_TYPE_CHOICES)
    # choice_text = models.CharField(max_length=255)

    class Meta:
        db_table = 'storymode_choice'

    # 선택지 내용도 함께 표시
    def __str__(self):
        # next_moment가 없을 경우 'End'로 표시하여 엔딩 분기점을 명확히 함
        return f"From {self.moment.title} to {self.next_moment.title if self.next_moment else 'End'}"

# 스토리모드 세션
class StorymodeSession(models.Model):
    STATUS_CHOICES = [
        ('play', 'Playing'),
        ('finish', 'Finished'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_storymode_session')
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='story_storymode_session')
    current_moment = models.ForeignKey(StorymodeMoment, on_delete=models.SET_NULL, null=True, blank=True)
    history = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='play')
    start_at = models.DateTimeField(auto_now_add=True)
    end_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'storymode_session'

    def __str__(self):
        return f"[{self.story.title}] {self.user.name if self.user else 'Unknown User'} - {self.get_status_display()}"

    # 진행률 계산
    def get_progress_percentage(self):
        total_moments = self.story.moments.count()
        # 히스토리에 저장된 moment_id를 사용하여 고유한 방문 분기점 계산
        visited_moment_ids = {item['moment_id'] for item in self.history if 'moment_id' in item}
        # 현재 분기점도 방문한 것으로 간주하고 추가
        if self.current_moment and str(self.current_moment.id) not in visited_moment_ids:
            visited_moment_ids.add(str(self.current_moment.id))
        
        visited_moments = len(visited_moment_ids)
        return round((visited_moments / total_moments) * 100, 2) if total_moments > 0 else 0