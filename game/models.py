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

    class Meta:
        db_table = 'story'

    def __str__(self):
        return self.title

# 스토리 분기점
class StorymodeMoment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='moments')
    title = models.CharField(max_length=100)
    title_eng = models.CharField(max_length=100, null=True, blank=True)
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
    
# 게임방
class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('waiting', 'Waiting'),
        ('play', 'Playing'),
        ('finish', 'Finished'),
    ]

    ROOM_TYPE_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owner_gameroom')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')         # waiting, play, finish
    room_type = models.CharField(max_length=20, choices=ROOM_TYPE_CHOICES, default='public')    # public, private
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    max_players = models.IntegerField(default=1)
    password = models.CharField(max_length=128, null=True, blank=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'gameroom'

    def __str__(self):
        return self.name

# 게임 참여
class GameJoin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gameroom = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='selected_by_room')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='selected_by_user')
    is_ready = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'gamejoin'

    def __str__(self):
        return f"{self.user.name} joined {self.gameroom.name}"

# 장르
class Genre(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)    # 판타지, 미스터리, 사이버펑크
    is_display = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'genre'

    def __str__(self):
        return self.name
    
# 난이도
class Difficulty(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)     # 초급, 중급, 상급
    is_display = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'difficulty'

    def __str__(self):
        return self.name

# 모드
class Mode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)     # 동시 선택, 턴제
    is_display = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mode'

    def __str__(self):
        return self.name

# 시나리오
class Scenario(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_display = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scenario'

    def __str__(self):
        return self.title

# 캐릭터
class Character(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name='character')
    name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    items = models.JSONField(default=dict)
    ability = models.JSONField(default=dict)
    image_path = models.CharField(max_length=500, null=True, blank=True)
    is_display = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'character'

    def __str__(self):
        return self.name

# 게임방별 선택된 시나리오
class GameRoomSelectScenario(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gameroom = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='selected_room')
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name='selected_scenario')
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name='selected_genre', null=True, blank=True)
    difficulty = models.ForeignKey('Difficulty', on_delete=models.CASCADE, related_name='selected_difficulty', null=True, blank=True)
    mode = models.ForeignKey('Mode', on_delete=models.CASCADE, related_name='selected_mode', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gameroom_select_scenario'

    def __str__(self):
        return f"Room {self.gameroom.name} selected {self.scenario.title}"

# 세션 모델
class BaseSession(models.Model):
    STATUS_CHOICES = [
        ('play', 'Playing'),
        ('finish', 'Finished'),
    ]
        
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    choice_history = models.JSONField(default=dict)
    character_history = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='play')    # play, finish

    class Meta:
        abstract = True

# 싱글모드 세션
class SinglemodeSession(BaseSession):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_singlemode_session')
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name='scenario_singlemode_session')
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name='genre_singlemode_session', null=True, blank=True)
    difficulty = models.ForeignKey(Difficulty, on_delete=models.CASCADE, related_name='difficulty_singlemode_session', null=True, blank=True)
    mode = models.ForeignKey(Mode, on_delete=models.CASCADE, related_name='mode_singlemode_session', null=True, blank=True)
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='character_singlemode_session', null=True, blank=True)
    
    class Meta:
        db_table = 'singlemode_session'

    def __str__(self):
        return f"{self.user.name} with {self.scenario.title}"

# 멀티모드 세션
class MultimodeSession(BaseSession):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_multimode_session')
    gameroom = models.ForeignKey(GameRoom, on_delete=models.CASCADE, related_name='gameroom_multimode_session')
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name='scenario_multimode_session')
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name='character_multimode_session', null=True, blank=True)

    class Meta:
        db_table = 'multimode_session'

    def __str__(self):
        return f"{self.user.name} in {self.gameroom.name}"