# game/management/commands/seed_from_json.py

import json
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from game.models import Story, StorymodeMoment, StorymodeChoice

class Command(BaseCommand):
    help = 'JSON 파일들로부터 여러 스토리 데이터를 자동으로 데이터베이스에 시딩합니다.'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('JSON 기반 스토리 데이터 시딩을 시작합니다...'))

        # 기존 데이터를 모두 삭제하여 중복을 방지합니다.
        self.stdout.write(self.style.WARNING('기존의 모든 Story, Scene, Choice 데이터를 삭제합니다.'))
        Story.objects.all().delete()
        StorymodeMoment.objects.all().delete()
        StorymodeChoice.objects.all().delete()

        stories_dir = os.path.join(settings.BASE_DIR, 'llm', 'stories', 'json')

        if not os.path.exists(stories_dir):
            self.stdout.write(self.style.ERROR(f"'{stories_dir}' 디렉토리를 찾을 수 없습니다."))
            return

        for file_name in os.listdir(stories_dir):
            if file_name.endswith('.json'):
                file_path = os.path.join(stories_dir, file_name)
                self.stdout.write(f"-> '{file_name}' 파일을 처리 중입니다...")

                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # 1. Story 객체 생성
                    story_title = data['id'].replace('_게임', '').replace('해와달', '해와 달')
                    story, created = Story.objects.update_or_create(
                        identifier=data['id'],
                        defaults={
                            'title': story_title,
                            'description': data['world'],
                            'start_scene_name': data['start_moment_id'],
                        }
                    )
                    self.stdout.write(self.style.SUCCESS(f"  > Story '{story.title}' 처리 완료."))

                    # 2. Scene 객체들 생성
                    scene_objects = {}
                    for scene_name, scene_data in data['moments'].items():
                        scene, _ = StorymodeMoment.objects.update_or_create(
                            story=story,
                            name=scene_name,
                            defaults={'description': scene_data['description']}
                        )
                        scene_objects[scene_name] = scene
                    self.stdout.write(f"  > {len(scene_objects)}개의 Scene 처리 완료.")

                    # 3. Choice 객체들 생성
                    choice_count = 0
                    for scene_name, scene_data in data['moments'].items():
                        if 'choices' in scene_data:
                            parent_scene = scene_objects[scene_name]
                            for choice_data in scene_data['choices']:
                                choice_text = choice_data.get('description') or choice_data.get('action_type', '계속')
                                
                                StorymodeChoice.objects.update_or_create(
                                    scene=parent_scene,
                                    next_scene_name=choice_data['next_moment_id'],
                                    text=choice_text, # text 필드는 중복될 수 있으므로 defaults가 아닌 식별자로 사용
                                    defaults={
                                        'adds_item': choice_data.get('effects', {}).get('acquire_item'),
                                        'required_item': choice_data.get('requirements', {}).get('has_item'),
                                    }
                                )
                                choice_count += 1
                    self.stdout.write(f"  > {choice_count}개의 Choice 처리 완료.")

        self.stdout.write(self.style.SUCCESS('모든 JSON 파일의 데이터베이스 시딩을 성공적으로 완료했습니다.'))