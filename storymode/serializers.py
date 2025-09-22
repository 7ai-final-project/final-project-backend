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
        # API 응답에 포함될 필드 목록입니다.
        fields = [
            'id', 'title', 'title_eng', 'description', 'description_eng', 
            'is_display', 'is_deleted', 'has_saved_session', 'image_path'
        ]

    def get_has_saved_session(self, obj):
        """
        이 스토리에 대해 현재 사용자가 '플레이 중'인 세션이 있는지 확인합니다.
        - self: Serializer 인스턴스
        - obj: 현재 처리 중인 Story 객체
        """
        # Serializer가 View로부터 context를 통해 request 객체를 전달받습니다.
        request = self.context.get('request')
        
        # request 객체가 있고, 사용자가 로그인한 상태인지 확인합니다.
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            # 🟢 핵심 수정: status가 'play'인 세션이 존재하는 경우에만 True를 반환합니다.
            return StorymodeSession.objects.filter(
                story=obj, 
                user=request.user, 
                status='play'
            ).exists()
            
        # 로그인하지 않았거나 request 정보가 없으면 False를 반환합니다.
        return False