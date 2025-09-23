from django.db.models import Count
from storymode.models import Story, StorymodeMoment, StorymodeSession
from game.models import GameRoom, GameJoin, SinglemodeSession, MultimodeSession, Difficulty

class AchievementService:
    def __init__(self, user):
        self.user = user

        # 업적 정의
        self.achievement_definitions = {
            # 스토리 모드 업적들
            'story_first_play': {
                'name': '첫 이야기 시작',
                'description': '스토리 모드의 첫 에피소드를 플레이했습니다.',
                'icon': 'book',
                'mode': 'story',
                'target': 1 # 최소 1회 플레이
            },
            'story_complete_all_endings': {
                'name': '모든 스토리 엔딩 클리어',
                'description': '모든 스토리의 모든 엔딩을 보았습니다.',
                'icon': 'book',
                'mode': 'story',
                'target': 'all' # 모든 스토리의 모든 엔딩
            },
            'story_hidden_ending': {
                'name': '숨겨진 이야기',
                'description': '특정 스토리의 숨겨진 엔딩을 발견했습니다.',
                'icon': 'bookmark',
                'mode': 'story',
                'target': 'specific_ending_id' # 특정 엔딩 ID (예: "엔딩 A")
            },
            'story_complete_one_story': {
                'name': '하나의 이야기 완료',
                'description': '하나의 스토리 모드를 완료했습니다.',
                'icon': 'book-open',
                'mode': 'story',
                'target': 1 # 하나의 스토리 완료
            },

            # 싱글 모드 업적들
            'single_play_10': {
                'name': '싱글 플레이어',
                'description': '싱글 모드 게임을 10회 플레이했습니다.',
                'icon': 'person',
                'mode': 'single',
                'target': 10
            },
            'single_master_all_difficulties': {
                'name': '싱글 모드 마스터 (모든 난이도)',
                'description': '싱글 모드의 모든 난이도를 클리어했습니다.',
                'icon': 'star',
                'mode': 'single',
                'target': 'all' # 모든 난이도
            },
            'single_master_hard_difficulty': {
                'name': '싱글 모드 마스터 (상급)',
                'description': '싱글 모드 상급 난이도를 클리어했습니다.',
                'icon': 'star-half',
                'mode': 'single',
                'target': '상급' # 상급 난이도 이름
            },

            # 멀티 모드 업적들
            'multi_first_play': {
                'name': '첫 멀티 플레이',
                'description': '멀티 모드 게임을 처음 플레이했습니다.',
                'icon': 'people',
                'mode': 'multi',
                'target': 1
            },
            'multi_team_play_5': {
                'name': '협동의 달인',
                'description': '멀티 모드에서 팀원과 5회 게임을 진행했습니다.',
                'icon': 'hand-left',
                'mode': 'multi',
                'target': 5 # 5회 플레이
            },
            'multi_room_owner_3': {
                'name': '방장',
                'description': '멀티 모드 게임방을 3회 생성했습니다.',
                'icon': 'key',
                'mode': 'multi',
                'target': 3 # 3회 방 생성
            },
            'multi_large_game_6_players': {
                'name': '대규모 멀티 플레이',
                'description': '멀티 모드에서 6인 이상 게임에 참여하여 완료했습니다.',
                'icon': 'group',
                'mode': 'multi',
                'target': 1 # 1회 참여
            },
        }

    # 모든 업적과 유저 달성 상태
    def get_all_achievements_with_status(self):
        achievements_data = []

        for achievement_id, achievement_info in self.achievement_definitions.items():
            is_unlocked = self._check_achievement_status(achievement_id)

            achievements_data.append({
                'id': achievement_id,
                'name': achievement_info['name'],
                'description': achievement_info['description'],
                'icon': achievement_info['icon'],
                'isUnlocked': is_unlocked,
                'mode': achievement_info['mode']
            })

        return achievements_data

    # 개별 업적의 달성 조건 확인
    def _check_achievement_status(self, achievement_id):
        try:
            # 스토리 모드 업적들
            if achievement_id == 'story_first_play':
                return self._check_story_first_play()

            elif achievement_id == 'story_complete_all_endings':
                return self._check_story_complete_all_endings()

            elif achievement_id == 'story_hidden_ending':
                return self._check_story_hidden_ending()

            elif achievement_id == 'story_complete_one_story':
                return self._check_story_complete_one_story()

            # 싱글 모드 업적들
            elif achievement_id == 'single_play_10':
                return self._check_single_play_count()

            elif achievement_id == 'single_master_all_difficulties':
                return self._check_single_master_all_difficulties()

            elif achievement_id == 'single_master_hard_difficulty':
                return self._check_single_master_hard_difficulty()

            # 멀티 모드 업적들
            elif achievement_id == 'multi_first_play':
                return self._check_multi_first_play()

            elif achievement_id == 'multi_team_play_5':
                return self._check_multi_team_play()

            elif achievement_id == 'multi_large_game_6_players':
                return self._check_multi_large_game()

            elif achievement_id == 'multi_room_owner_3':
                return self._check_multi_room_owner_count()

            return False

        except Exception as e:
            print(f"업적 체크 중 오류 발생 ({achievement_id}): {str(e)}")
            return False

    # === 스토리 모드 업적 체크 ===
    # 스토리 모드 첫 플레이 체크 (최소 1개의 StorymodeSession 존재 여부)
    def _check_story_first_play(self):
        return StorymodeSession.objects.filter(user=self.user).exists()

    # 모든 스토리의 모든 엔딩 완료 체크
    def _check_story_complete_all_endings(self):
        all_stories = Story.objects.filter(is_display=True, is_deleted=False)

        if not all_stories.exists():
            return False

        for story in all_stories:
            total_endings_for_story = StorymodeMoment.objects.filter(story=story).annotate(
                num_choices=Count('choices')
            ).filter(num_choices=0).count()

            if total_endings_for_story == 0:
                continue

            user_sessions_for_story = StorymodeSession.objects.filter(
                user=self.user, 
                story=story, 
                status='finish'
            )

            reached_ending_moments_ids = set()
            for session in user_sessions_for_story:
                if session.current_moment and session.current_moment.is_ending():
                    reached_ending_moments_ids.add(str(session.current_moment.id))

                for hist_entry in session.history:
                    moment_id = hist_entry.get('moment_id')
                    if moment_id:
                        try:
                            moment = StorymodeMoment.objects.get(id=moment_id, story=story)
                            if moment.is_ending():
                                reached_ending_moments_ids.add(str(moment.id))
                        except StorymodeMoment.DoesNotExist:
                            continue

            if len(reached_ending_moments_ids) < total_endings_for_story:
                return False 

        return True 

    # 숨겨진 엔딩 발견 체크
    def _check_story_hidden_ending(self):
        hidden_ending_moment_identifier = 'HIDDEN_ENDING' 
        # 숨겨진 엔딩 식별자가 정의되지 않음
        if hidden_ending_moment_identifier == 'HIDDEN_ENDING':
            return False 

        try:
            hidden_ending_moment = StorymodeMoment.objects.get(name=hidden_ending_moment_identifier)
        except StorymodeMoment.DoesNotExist:
            return False 

        return StorymodeSession.objects.filter(
            user=self.user,
            story=hidden_ending_moment.story, 
            current_moment=hidden_ending_moment,
            status='finish'
        ).exists()

    # 하나의 스토리 모드를 완료했는지 체크 (status가 'finish'인 StorymodeSession이 1개라도 있는지 확인)
    def _check_story_complete_one_story(self):
        return StorymodeSession.objects.filter(user=self.user, status='finish').exists()

    # === 싱글 모드 업적 체크 ===
    # 싱글 모드 10회 플레이 체크
    def _check_single_play_count(self):
        play_count = SinglemodeSession.objects.filter(user=self.user, status='finish').count()
        return play_count >= self.achievement_definitions['single_play_10']['target']

    # 싱글 모드 모든 난이도 마스터 체크
    def _check_single_master_all_difficulties(self):
        all_difficulties = Difficulty.objects.filter(is_display=True, is_deleted=False)

        if not all_difficulties.exists():
            return False 

        for difficulty in all_difficulties:
            if not SinglemodeSession.objects.filter(
                user=self.user,
                difficulty=difficulty,
                status='finish'
            ).exists():
                return False 

        return True 

    # 싱글 모드 상급 난이도 마스터 체크
    def _check_single_master_hard_difficulty(self):
        try:
            hard_difficulty = Difficulty.objects.get(name='상급')
        except Difficulty.DoesNotExist:
            return False 

        return SinglemodeSession.objects.filter(
            user=self.user,
            difficulty=hard_difficulty,
            status='finish'
        ).exists()

    # === 멀티 모드 업적 체크 ===
    # 멀티 모드 첫 플레이 체크 (최소 1개의 MultimodeSession 존재 여부)
    def _check_multi_first_play(self):
        return MultimodeSession.objects.filter(user=self.user).exists()

    # 6인 이상 멀티 모드 참여 체크
    # 사용자가 완료한 게임룸 중, 해당 게임룸에 6인 이상이 참여한 경우가 있는지 확인
    def _check_multi_large_game(self):
        completed_gameroom_ids = MultimodeSession.objects.filter(
            user=self.user,
            status='finish'
        ).values_list('gameroom_id', flat=True).distinct()

        if not completed_gameroom_ids:
            return False

        for room_id in completed_gameroom_ids:
            # 해당 게임룸에 참여한 고유 유저 수를 카운트, 게임룸이 'finish' 상태로 완료된 경우만 고려
            participating_players_count = GameJoin.objects.filter(
                gameroom_id=room_id,
                gameroom__status='finish'
            ).values('user').distinct().count()

            if participating_players_count >= 6:
                return True
        return False

    # 멀티 모드에서 팀원과 함께 진행한 게임 횟수를 계산하는 헬퍼 함수
    def _get_multi_team_play_count(self):
        completed_sessions_by_user = MultimodeSession.objects.filter(user=self.user, status='finish')

        team_play_count = 0
        counted_gamerooms = set() # 중복 카운트 방지

        for session in completed_sessions_by_user:
            gameroom = session.gameroom

            if gameroom.id in counted_gamerooms:
                continue

            if gameroom.status == 'finish':
                participating_players_count = GameJoin.objects.filter(
                    gameroom=gameroom
                ).values('user').distinct().count()

                # 본인 외에 최소 1명 이상의 다른 플레이어가 있었다면 팀 플레이로 간주 (즉, 최소 2명)
                if participating_players_count > 1:
                    team_play_count += 1
                    counted_gamerooms.add(gameroom.id) 
        return team_play_count

    # 멀티 모드에서 팀원과 5회 게임을 진행했는지 체크
    def _check_multi_team_play(self):
        team_play_count = self._get_multi_team_play_count()
        target = self.achievement_definitions['multi_team_play_5']['target']
        return team_play_count >= target

    # 멀티 모드 게임방 3회 생성 체크
    def _check_multi_room_owner_count(self):
        room_count = GameRoom.objects.filter(
            owner=self.user,
            is_deleted=False,
            deleted_at__isnull=True
        ).count()
        return room_count >= self.achievement_definitions['multi_room_owner_3']['target']

    # === 유틸리티 ===
    # 특정 업적의 진행 상황 정보
    def get_achievement_progress_info(self, achievement_id):
        if achievement_id == 'single_play_10':
            current_count = SinglemodeSession.objects.filter(user=self.user, status='finish').count()
            target = self.achievement_definitions['single_play_10']['target']
            return {
                'current': current_count,
                'target': target
            }

        elif achievement_id == 'multi_room_owner_3':
            current_count = GameRoom.objects.filter(
                owner=self.user,
                is_deleted=False,
                deleted_at__isnull=True
            ).count()
            target = self.achievement_definitions['multi_room_owner_3']['target']
            return {
                'current': current_count,
                'target': target
            }

        elif achievement_id == 'multi_team_play_5':
            current_count = self._get_multi_team_play_count() # 헬퍼 함수 재사용
            target = self.achievement_definitions['multi_team_play_5']['target']
            return {
                'current': current_count,
                'target': target
            }

        # 진행 상황이 수치로 표시되지 않는 업적 (예: 첫 플레이, 모든 엔딩 클리어)
        return None