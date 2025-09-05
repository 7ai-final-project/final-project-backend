from rest_framework import serializers
from .models import ChatMessage

class MessageSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.name")

    class Meta:
        model = ChatMessage
        fields = ["id", "username", "content", "created_at"]