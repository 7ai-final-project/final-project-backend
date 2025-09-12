from rest_framework import serializers
from game.models import (
    StorymodeMoment, StorymodeChoice, Story, GameRoom, GameJoin,
    Scenario, Genre, Difficulty, Mode, GameRoomSelectScenario,Character
)
from django.contrib.auth.hashers import make_password


class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorymodeChoice
        fields = '__all__'

class SceneSerializer(serializers.ModelSerializer):
    choices = ChoiceSerializer(many=True, read_only=True)
    class Meta:
        model = StorymodeMoment
        fields = '__all__'

class StorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Story
        fields = ['id', 'title', 'description']

class GameJoinSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.name")

    class Meta:
        model = GameJoin
        fields = ["id", "username", "is_ready"]

class GameRoomSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source='owner.name', read_only=True)
    # [수정 👇] SerializerMethodField를 사용하여 현재 참가자만 필터링합니다.
    selected_by_room = serializers.SerializerMethodField()
    # [추가 👇] 현재 인원 수를 정확하게 계산하는 필드를 추가합니다.
    current_players = serializers.SerializerMethodField()

    class Meta:
        model = GameRoom
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "max_players",
            "current_players",
            "status",
            "selected_by_room",
            "created_at",
            #'deleted_at',
            "room_type",
            "password",
            "is_deleted",
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False, 'allow_null': True}
        }

    def get_owner(self, obj):
        # username 대신 email 사용 (필요하다면 name 같은 다른 필드도 가능)
        return obj.owner.email if obj.owner else None
    
    def get_selected_by_room(self, obj):
        """현재 방에 있는 참가자(나가지 않은 사람) 목록만 반환합니다."""
        participants = obj.selected_by_room.filter(left_at__isnull=True)
        serializer = GameJoinSerializer(participants, many=True)
        return serializer.data

    def get_current_players(self, obj):
        return obj.selected_by_room.filter(left_at__isnull=True).count()
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = super().create(validated_data)
        if password:
            instance.password = make_password(password) # 비밀번호를 해싱하여 저장
            instance.save()
        return instance
    
class ScenarioSerializer(serializers.ModelSerializer):
    """시나리오 목록을 위한 Serializer"""
    class Meta:
        model = Scenario
        fields = ['id', 'title', 'description']

class GenreSerializer(serializers.ModelSerializer):
    """장르 목록을 위한 Serializer"""
    class Meta:
        model = Genre
        fields = ['id', 'name']

class DifficultySerializer(serializers.ModelSerializer):
    """난이도 목록을 위한 Serializer"""
    class Meta:
        model = Difficulty
        fields = ['id', 'name']

class ModeSerializer(serializers.ModelSerializer):
    """게임 모드 목록을 위한 Serializer"""
    class Meta:
        model = Mode
        fields = ['id', 'name']

class GameRoomSelectScenarioSerializer(serializers.ModelSerializer):
    """게임방의 옵션 선택을 저장하기 위한 Serializer"""
    class Meta:
        model = GameRoomSelectScenario
        # gameroom은 URL에서 받아오므로 필드에서 제외합니다.
        fields = ['scenario', 'genre', 'difficulty', 'mode']

class CharacterSerializer(serializers.ModelSerializer):
    """
    DB의 Character 모델에서 ability 필드를 분해하여
    stats와 skills를 별도의 필드로 가공합니다.
    """
    image = serializers.CharField(source='image_path', read_only=True)
    
    # [추가] 'stats'와 'skills'를 ability 필드에서 추출하기 위한 설정
    stats = serializers.SerializerMethodField()
    skills = serializers.SerializerMethodField()

    class Meta:
        model = Character
        # [수정] 프론트엔드에 최종적으로 보낼 필드 목록을 정의합니다.
        # DB 필드명인 'ability'는 포함하지 않습니다.
        fields = ['id', 'name', 'description', 'image', 'stats', 'skills', 'items']

    def get_stats(self, obj):
        """
        Character 인스턴스(obj)의 ability 필드에서 'stats' 딕셔너리를 추출합니다.
        .get()을 사용하여 'stats' 키가 없는 경우에도 에러 없이 빈 딕셔너리({})를 반환합니다.
        """
        return obj.ability.get('stats', {})

    def get_skills(self, obj):
        """
        Character 인스턴스(obj)의 ability 필드에서 'skills' 리스트를 추출합니다.
        .get()을 사용하여 'skills' 키가 없는 경우에도 에러 없이 빈 리스트([])를 반환합니다.
        """
        return obj.ability.get('skills', [])