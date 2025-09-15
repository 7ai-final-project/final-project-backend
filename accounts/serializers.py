from rest_framework import serializers
from accounts.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'social_type', 'joined_at', 'last_login']
        read_only_fields = ['email', 'name', 'social_type', 'joined_at', 'last_login']