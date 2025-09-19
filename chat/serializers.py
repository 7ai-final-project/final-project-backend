from rest_framework import serializers
from .models import ChatMessage

class MessageSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    user_id = serializers.UUIDField(source='user.id', read_only=True)

    class Meta:
        model = ChatMessage
        fields = ["id", "user_id", "username", "message", "created_at"]

    def get_username(self, obj):
        return obj.user.nickname or obj.user.name