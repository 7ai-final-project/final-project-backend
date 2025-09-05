from django.core.management.base import BaseCommand
from game.models import Story, Scene, Choice

class Command(BaseCommand):
    help = 'Seeds the database with story-based game data.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Deleting old story data...'))
        Choice.objects.all().delete()
        Scene.objects.all().delete()
        Story.objects.all().delete()

       # --- 1단계: 새로운 "스토리" 정보 추가 ---
        # 이 부분이 완전히 새로 추가되었습니다.
        self.stdout.write(self.style.SUCCESS('Creating stories...'))
        sun_moon_story = Story.objects.create(
            # identifier='sun_and_moon',
            title='해님달님: 운명의 동아줄',
            description='떡 장수 어머니를 잃은 오누이가, 꾀를 내어 호랑이로부터 벗어나 하늘의 해와 달이 되는 이야기',
            start_scene_name='home_alone' # 이 이야기의 시작 장면 이름을 명시합니다.
        )
        # (나중에 여기에 다른 이야기를 추가할 수 있습니다.)
        # kongjwi_story = Story.objects.create(...)

        
        # --- 2단계: 기존 "장면" 데이터에 "스토리" 연결 ---
        # 기존 scenes_data 코드에서 각 장면에 'story' 정보를 추가하도록 수정되었습니다.
        self.stdout.write(self.style.SUCCESS('Creating scenes for stories...'))
        scenes_data = [
            # 모든 장면에 'story': sun_moon_story 를 추가합니다.
            {'story': sun_moon_story, 'name': 'sun_and_moon_home_alone', 'description': "엄마는 떡을 팔러 고개 너머 마을에 가셨다.\n해가 저물도록 돌아오지 않으시자, 동생 달식이가 불안한 듯 말한다.\n\"누나, 엄마가 왜 이렇게 안 오시지? 무서워...\"", 'image_path': 'scene_home.png'},
            {'story': sun_moon_story, 'name': 'sun_and_moon_knock_sound', 'description': "그때, 밖에서 문을 쿵쿵 두드리는 소리가 들린다.\n\"얘들아, 엄마 왔다. 문 열어라.\"\n하지만 목소리가 낯설고 걸걸하다.", 'image_path': 'scene_door.png'},
            {'story': sun_moon_story, 'name': 'sun_and_moon_tiger_hand', 'description': "\"그럼 문틈으로 손을 내밀어 보세요.\" 달식이의 말에 문틈으로 털이 숭숭 난 손이 쑥 들어온다.\n\"엄마 손이 아니야! 이건 호랑이 손이야!\"", 'image_path': 'scene_tiger_hand.png'},
            {'story': sun_moon_story, 'name': 'sun_and_moon_escape_tree', 'description': "오누이는 호랑이라는 것을 깨닫고 뒷문으로 몰래 빠져나와 마당의 커다란 나무 위로 올라갔다.\n아래에서 호랑이가 나무를 흔들며 울부짖는다.\n\"내려오지 못할까!\"", 'image_path': 'scene_tree.png'},
            {'story': sun_moon_story, 'name': 'sun_and_moon_pray_to_sky', 'description': "절체절명의 순간, 해식이는 하늘에 간절히 기도하기 시작했다.", 'image_path': 'scene_sky.png'},
            {'story': sun_moon_story, 'name': 'sun_and_moon_good_ending', 'description': "튼튼한 동아줄이 내려와 오누이를 하늘로 이끌었다.\n하늘에 오른 해식이는 따스한 햇살로 세상을 비추는 해가 되었고, 용감한 달식이는 밤을 지키는 든든한 달이 되었다.", 'image_path': 'scene_sun_moon.png'},
            {'story': sun_moon_story, 'name': 'sun_and_moon_bad_ending', 'description': "안타깝게도, 오누이는 결국 호랑이에게 잡히고 말았다...", 'image_path': 'scene_bad_end.png'}
        ]
        # 생성된 Scene 객체들을 딕셔너리에 저장하는 방식이 조금 더 명확하게 변경되었습니다.
        scenes = {data['name']: Scene.objects.create(**data) for data in scenes_data}


        # --- 3단계: 기존 "선택지" 데이터가 올바른 "장면"을 참조하도록 수정 ---
        # 기존 choices_data 코드에서 참조하는 'scenes' 딕셔너리의 키 이름이 변경되었습니다.
        self.stdout.write(self.style.SUCCESS('Creating choices for scenes...'))
        choices_data = [
            {'scene': scenes['sun_and_moon_home_alone'], 'text': '"괜찮아, 곧 오실 거야." (달식이를 안심시킨다)', 'next_scene_name': 'sun_and_moon_knock_sound', 'wisdom_change': 1},
            {'scene': scenes['sun_and_moon_home_alone'], 'text': '"무서우니, 부엌에서 뭐라도 찾아보자."', 'next_scene_name': 'sun_and_moon_knock_sound', 'courage_change': 1, 'adds_item': '부엌칼'},

            {'scene': scenes['sun_and_moon_knock_sound'], 'text': '"목소리가 이상해요. 누구세요?" (지혜롭게 대처)', 'next_scene_name': 'sun_and_moon_tiger_hand', 'required_wisdom': 6, 'wisdom_change': 1},
            {'scene': scenes['sun_and_moon_knock_sound'], 'text': '"엄마! 어서 들어와요!" (성급하게 문을 연다)', 'next_scene_name': 'sun_and_moon_bad_ending', 'wisdom_change': -2, 'courage_change': -2},
            {'scene': scenes['sun_and_moon_knock_sound'], 'text': '"무서워... 그냥 조용히 있자." (두려워한다)', 'next_scene_name': 'sun_and_moon_tiger_hand', 'courage_change': -1},
            
            {'scene': scenes['sun_and_moon_tiger_hand'], 'text': '(달식이) "뒷문으로 도망가자!" (용감한 선택)', 'next_scene_name': 'sun_and_moon_escape_tree', 'required_courage': 6, 'courage_change': 1},
            {'scene': scenes['sun_and_moon_tiger_hand'], 'text': '(해식이) "장독대 뒤에 숨어있자." (어리석은 선택)', 'next_scene_name': 'sun_and_moon_bad_ending', 'wisdom_change': -1, 'courage_change': -1},

            {'scene': scenes['sun_and_moon_escape_tree'], 'text': '"참기름을 듬뿍 바르고 올라왔지!" (호랑이를 속인다)', 'next_scene_name': 'sun_and_moon_pray_to_sky', 'required_wisdom': 7, 'wisdom_change': 2},
            {'scene': scenes['sun_and_moon_escape_tree'], 'text': '"비녀로 호랑이 눈을 찌르자!" (공격한다)', 'next_scene_name': 'sun_and_moon_bad_ending', 'required_courage': 8, 'required_item': '어머니의 비녀', 'courage_change': -2},
            {'scene': scenes['sun_and_moon_escape_tree'], 'text': '"부엌칼로 맞서 싸우자!" (대담한 선택)', 'next_scene_name': 'sun_and_moon_bad_ending', 'required_courage': 9, 'required_item': '부엌칼', 'courage_change': -3},

            {'scene': scenes['sun_and_moon_pray_to_sky'], 'text': '"저희를 살려주시려면 튼튼한 동아줄을 내려주세요."', 'next_scene_name': 'sun_and_moon_good_ending', 'wisdom_change': 5, 'courage_change': 5},
            {'scene': scenes['sun_and_moon_pray_to_sky'], 'text': '"저희를 잡아먹으려는 호랑이에게 썩은 동아줄을 내려주세요!"', 'next_scene_name': 'sun_and_moon_good_ending', 'required_courage': 7, 'wisdom_change': 2, 'courage_change': 5}
        ]

        for data in choices_data:
            Choice.objects.create(**data)

        self.stdout.write(self.style.SUCCESS('Successfully seeded all story data!'))