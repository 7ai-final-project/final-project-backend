from rest_framework import serializers
from game.models import GameRoom, GameJoin
from django.contrib.auth.hashers import make_password


class GameJoinSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.name")

    class Meta:
        model = GameJoin
        fields = ["id", "username", "is_ready"]

class GameRoomSerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source='owner.name', read_only=True)
    participants = GameJoinSerializer(source='selected_by_room', many=True, read_only=True)

    class Meta:
        model = GameRoom
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "max_players",
            "status",
            "participants",
            "created_at",
            "room_type",
            "password",
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False, 'allow_null': True}
        }

    def get_owner(self, obj):
        # username 대신 email 사용 (필요하다면 name 같은 다른 필드도 가능)
        return obj.owner.email if obj.owner else None

    def get_current_players(self, obj):
        return obj.participants.count()
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = super().create(validated_data)
        if password:
            instance.password = make_password(password) # 비밀번호를 해싱하여 저장
            instance.save()
        return instance