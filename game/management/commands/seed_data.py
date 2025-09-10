from django.core.management.base import BaseCommand
from game.models import Scenario, Difficulty, Mode, Genre

class Command(BaseCommand):
    help = '초기 게임 옵션 데이터(시나리오, 난이도 등)를 생성합니다.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('초기 데이터 생성을 시작합니다...'))

        # # get_or_create를 사용하여 중복 생성을 방지합니다.
        # Scenario.objects.get_or_create(
        #     title="해와달",
        #     defaults={'description': '호랑이에게서 살아남아 하늘의 해와 달이 된 남매 이야기'}
        # )
        # Scenario.objects.get_or_create(
        #     title="구운몽",
        #     defaults={'description': '성진의 꿈을 통해 인생무상을 깨닫는 이야기'}
        # )
        # Scenario.objects.get_or_create(
        #     title="날개",
        #     defaults={'description': '박제가 되어버린 천재를 아시오?'}
        # )

        Genre.objects.get_or_create(name="전래동화")
        Genre.objects.get_or_create(name="고전소설")
        
        Difficulty.objects.get_or_create(name="초급")
        Difficulty.objects.get_or_create(name="중급")
        Difficulty.objects.get_or_create(name="상급")

        Mode.objects.get_or_create(name="동시 선택")
        Mode.objects.get_or_create(name="턴제")

        self.stdout.write(self.style.SUCCESS('초기 데이터 생성이 완료되었습니다.'))