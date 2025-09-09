from rest_framework import serializers
from game.models import (
    StorymodeMoment, StorymodeChoice, Story, GameRoom, GameJoin,
    Scenario, Genre, Difficulty, Mode, GameRoomSelectScenario
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
    selected_by_room = serializers.SerializerMethodField()
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