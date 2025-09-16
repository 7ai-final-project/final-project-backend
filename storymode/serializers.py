from rest_framework import serializers
from .models import Story, StorymodeMoment, StorymodeChoice, StorymodeSession # 👈 수정된 부분

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
    has_saved_session = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = [
            'id', 'title', 'title_eng', 'description', 'description_eng', 
            'created_at', 'start_moment', 'is_display', 'is_deleted', 'image_path',
            'has_saved_session'
        ]

    def get_has_saved_session(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, "user") and request.user.is_authenticated:
            user = request.user
            return StorymodeSession.objects.filter(story=obj, user=user).exists()
        return False