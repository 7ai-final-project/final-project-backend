from rest_framework import serializers
from storymode.models import Story, StorymodeMoment, StorymodeChoice


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
        fields = '__all__'