import re
import json
from openai import AzureOpenAI
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from storymode.models import Story
from storymode.serializers import StorySerializer

AZURE_OPENAI_API_KEY = settings.AZURE_OPENAI_API_KEY
AZURE_OPENAI_ENDPOINT = settings.AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_VERSION = settings.AZURE_OPENAI_VERSION
AZURE_OPENAI_DEPLOYMENT = settings.AZURE_OPENAI_DEPLOYMENT

# Azure OpenAI 클라이언트 초기화
def get_azure_openai_client() :
    try :
        return AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_VERSION
        )
    except Exception as e :
        print(f'Azure OpenAI 클라이언트 초기화 실패 {e}')
        return None

# AI 응답 파싱
def parse_ai_response(llm_output):
    if not llm_output:
        print("파싱 오류: AI로부터 받은 내용이 비어있습니다(None).")
        return {"scene_text": "(AI로부터 응답을 받지 못했습니다. Azure 콘텐츠 필터 문제일 수 있습니다.)", "choices": []}
    
    try:
        cleaned = re.sub(r"```json|```", "", llm_output).strip()
        cleaned = cleaned.replace('\n', ' ').replace('\r', ' ')
                
        if cleaned.startswith("{{") and cleaned.endswith("}}"):
            cleaned = cleaned[1:-1]
            
        data = json.loads(cleaned)
        
        return {
            "scene_text": data.get("scene_text"), 
            "choices": data.get("choices", [])
        }
    except Exception as e:
        print(f"JSON 파싱 실패: {e}\n원본 출력: {llm_output}")
        return {
            "scene_text": f"(AI 응답 오류: {llm_output})", 
            "choices": []
        }

# 전체 스토리 DB 조회
class StoryListView(APIView) :
    def get(self, request) :
        try :
            stories = Story.objects.filter(is_display=True, is_deleted=False)
            serializer = StorySerializer(stories, many=True)
            return Response({
                'message' : '스토리 목록 조회 성공',
                'stories' : serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e :
            print(f"🛑 오류: 스토리 목록을 조회하는 데 실패했습니다. 오류: {e}")
            return Response({
                'message' : '스토리 목록 조회 실패'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 공통 로직 APIView
class BaseStoryModeView(APIView) :
    # 스토리 조회
    def _get_story_data(self, story_title) :
        try :
            story = Story.objects.filter(
                title=story_title,
                is_display=True,
                is_deleted=False
            ).prefetch_related('moments__choices').first()

            if not story :
                return Response({
                    'message' : '선택된 스토리를 찾을 수 없습니다.'
                }, status=status.HTTP_404_NOT_FOUND)

            moments_data = {}
            for moment in story.moments.all() :
                choices_data = []
                for choice in moment.choices.all() :
                    # 선택지 정보
                    choices_data.append({
                        'action_type' : choice.action_type,
                        'next_moment_id' : str(choice.next_moment.id) if choice.next_moment else None
                    })
                
                # 분기점 정보
                moments_data[str(moment.id)] = {
                    'title' : moment.title,
                    'description' : moment.description,
                    'choices' : choices_data,
                    'image_path' : moment.image_path
                }

            # 스토리 정보
            story_data  = {
                'id' : str(story.id),
                'title' : story.title,
                'title_eng' : story.title_eng,
                'description' : story.description,
                'content' : {
                    'start_moment_id' : str(story.start_moment.id) if story.start_moment else None,
                    'start_moment_title' : story.start_moment.title if story.start_moment else None,
                    'moments' : moments_data
                },
                'is_display' : story.is_display,
                'is_deleted' : story.is_deleted
            }

            return story_data, None
        except Exception as e :
            print(f"🛑 오류: 스토리 목록을 조회하는 데 실패했습니다. 오류: {e}")
            return None, Response({
                'message' : '스토리 목록 조회 실패'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    # AI 프롬프트 생성
    def _generate_story_prompt(self, story_title, player_action_text, moment_description, choice_instructions, is_ending, num_choices_available=0) :
        mission_part = ''
        response_format_part = ''

        if is_ending :
            mission_part = """
            2.  **이야기 마무리:** 이 장면은 이야기의 끝입니다. 아이가 동화 속에서 얻은 교훈이나 감동을 느낄 수 있도록, 3~4 문장으로 아름답게 이야기를 마무리해주세요. **선택지는 절대로 만들지 마세요.**
            """

            response_format_part = """
            [응답 형식]
            반드시 다음 JSON 형식으로만 응답해야 합니다. **choices는 빈 배열([])**이어야 합니다.
            {{
                "scene_text": "AI가 '장면 생성'과 '이야기 마무리' 임무에 따라 창작한 감동적인 이야기 내용.",
                "choices": []
            }}
            """
        else :
            mission_part = f"""
            2.  **선택지 생성:** 위에서 만든 장면에 이어서, 아이에게 **{num_choices_available}개의 선택지**를 제시하세요.
                *   **선택지 형식:** 주인공이 하려는 **'행동'을 직접 나타내는 짧은 문장** 형식이어야 합니다. 아이가 직접 주인공의 행동을 고르는 느낌을 주세요.
                    *   **(좋은 예시 - 다양한 상황에 적용 가능):**
                        *   **(모험적인 행동):** "용감하게 동굴로 들어간다."
                        *   **(대화/관계 행동):** "슬퍼하는 친구를 위로해준다."
                        *   **(소극적인 행동):** "무서워서 그냥 집으로 돌아간다."
                    *   **(나쁜 예시 - 스포일러):** "용을 물리치게 될까?", "보물을 찾게 될까?" 와 같이 **결과를 암시하거나 질문하는 형식은 절대 사용하지 마세요.**
                *   **선택지 내용:** **아래 '선택지 생성 가이드'에 명시된 각 결과로 이어지는 행동을 정확히 반영해야 합니다.** 예를 들어, 가이드가 '[배드 엔딩] 지쳐 쓰러진다'로 이어지라고 지시했다면, 선택지는 반드시 '계속 혼자 벼를 옮긴다' 또는 '무리한다' 와 같은 원인 행동이어야 합니다. **'대화한다'처럼 긍정적인 행동을 배드 엔딩에 연결하면 절대 안 됩니다.**
                *   **선택지 생성 가이드:** {choice_instructions}
            """

            response_format_part = """
            [응답 형식]
            반드시 다음 JSON 형식으로만 응답해야 합니다:
            {{
                "scene_text": "AI가 '장면 생성' 임무에 따라 창작한 이야기 내용.",
                "choices": ["첫 번째 행동 선택지", "두 번째 행동 선택지", "..."]
            }}
            """

        # 최종 프롬프트 템플릿
        prompt = f"""
        당신은 아이들에게 동화를 들려주는 다정한 '이야기 요정'입니다. 당신의 임무는 아이의 선택을 반영하여 이야기를 만들면서도, 정해진 핵심 줄거리대로 이야기가 흘러가도록 자연스럽게 유도하는 것입니다.

        [이야기 요정의 규칙]
        *   항상 다정한 말투를 사용하고, 아이의 눈높이에 맞춰 설명합니다.
        *   장면을 묘사할 때는 아이가 무엇을 보고, 듣고, 느끼는지에 집중합니다.
        *   장면의 감각을 극대화하기 위해 의성어와 의태어를 사용합니다. ... (중략) ...
            *   (원칙 1) 소리를 생생하게: ...
            *   (원칙 2) 모습과 움직임을 그림처럼: ...
            *   (원칙 3) 마음과 느낌을 실감 나게: ...
        *   ★★ (새로 추가할 규칙) ★★ 의성어/의태어는 문장을 생생하게 만들 수 있을 때만 자연스럽게 사용하고, **벼가 익어가는 것처럼 어울리는 표현이 없는 조용한 장면에서는 억지로 사용하지 않아도 괜찮아요.**
        *   (주의!) 이 모든 표현은 반드시 그 장면에 자연스럽게 어울려야 합니다. '벼가 쿵쾅쿵쾅 익는다'처럼 어색한 표현은 사용하지 않도록 항상 주의해주세요.

        [현재 상황]
        *   현재 동화: {story_title}
        *   아이의 행동: {player_action_text}

        [당신의 임무]
        1.  **장면 생성:** 아래 '이번 장면의 핵심 목표'를 달성하는 다음 장면을 3~4개의 문장으로 흥미롭게 묘사하세요.
            *   이번 장면의 핵심 목표: {moment_description}
        {mission_part}
        {response_format_part}
        """

        return prompt
    
    # OpenAI API 호출
    def _call_openai_api(self, prompt) :
        client = get_azure_openai_client()
        if not client :
            print(f'Azure OpenAI 클라이언트 초기화 실패')
            return None, Response({
                'message' : 'AI 서비스 연결 실패'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        try :
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            ai_response_content = parse_ai_response(response.choices[0].message.content)
            return ai_response_content, None
        except Exception as e :
            print(f'🛑 오류: OpenAI API 호출 또는 응답 처리 실패. 오류: {e}')
            return None, Response({
                'message' : 'AI 응답 생성 실패'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 선택된 스토리 DB 조회 (첫 페이지)
class StartGameView(BaseStoryModeView) :
    def post(self, request) :
        story_title = request.data.get('story_title')

        if not story_title :
            return Response({
                'message' : '스토리 선택이 필요합니다.'
            }, status=status.HTTP_400_BAD_REQUEST)

        story_data, error_response = self._get_story_data(story_title)
        if error_response :
            return error_response

        id = story_data.get('id')
        title = story_data.get('title')
        content = story_data.get('content')
        all_moments = content.get('moments')

        current_moment_id = content.get('start_moment_id')
        current_moments = all_moments.get(current_moment_id)
        current_moment_title = current_moments.get('title', '')
        current_moment_description = current_moments.get('description', '')
        current_moment_image = current_moments.get('image_path', '')

        choices = current_moments.get('choices', [])
        is_ending = not bool(choices)
        num_choices_available = len(choices)

        choice_instructions = ''
        if not is_ending :
            choice_instructions += '다음 선택지들은 아래 목표들로 이어지도록 만들어줘:\n'
        
        for i, choice_info in enumerate(choices):
            target_moment_id = choice_info.get('next_moment_id')
            target_moment_desc = all_moments.get(target_moment_id, {}).get('description', '')
            action_type = choice_info.get('action_type', '보통')
            choice_instructions += f'- 선택지 {i+1}: ({action_type} 결과) {target_moment_desc}\n'

        player_action_text = '이제 이야기가 시작되었어.' 
        
        prompt = self._generate_story_prompt(
            story_title=title,
            player_action_text=player_action_text,
            moment_description=current_moment_description,
            choice_instructions=choice_instructions,
            is_ending=is_ending,
            num_choices_available=num_choices_available
        )

        ai_response_content, error_response = self._call_openai_api(prompt)
        if error_response :
            return error_response

        return Response({
            "scene": ai_response_content.get("scene_text"),
            "choices": ai_response_content.get("choices"),
            "story_id": id,
            "story_title": title,
            "current_moment_id": current_moment_id,
            "current_moment_title": current_moment_title,
            "image_path" : current_moment_image
        }, status=status.HTTP_200_OK)        

# 선택된 스토리 DB 조회 (선택지 선택 후, 진행)
class MakeChoiceView(BaseStoryModeView):
    def post(self, request) :
        story_title = request.data.get('story_title')
        choice_index = request.data.get('choice_index')
        current_moment_id = request.data.get('current_moment_id')

        if not story_title or current_moment_id is None :
            return Response({
                'message' : 'story_title 혹은 current_moment_id 누락'
            }, status=status.HTTP_400_BAD_REQUEST)

        if choice_index is None :
            return Response({
                'message' : 'choice_index 누락'
            }, status=status.HTTP_400_BAD_REQUEST)

        story_data, error_response = self._get_story_data(story_title)
        if error_response :
            return error_response
        
        id = story_data.get('id')
        title = story_data.get('title')
        content = story_data.get('content')
        all_moments = content.get('moments')

        # 다음 장면 ID 결정
        current_moments = all_moments.get(current_moment_id)
        if not current_moments :
            return Response({
                'message' : '현재 장면 정보를 찾을 수 없습니다.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        choices_map = current_moments.get('choices')
        next_moment_id = current_moment_id
        if 0 <= choice_index < len(choices_map) :
            next_moment_id = choices_map[choice_index].get('next_moment_id')
        else :
            return Response({
                'message' : '유효하지 않은 선택입니다.'
            }, status=status.HTTP_400_BAD_REQUEST)

        next_moments = all_moments.get(next_moment_id)
        if not next_moments :
            return Response({
                'message' : '다음 장면 정보를 찾을 수 없습니다.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        next_moment_title = next_moments.get('title', '')
        next_moment_description = next_moments.get('description', '')
        next_moment_image = next_moments.get('image_path', '')

        choices = next_moments.get('choices', [])
        is_ending = not bool(choices)
        num_choices_available = len(choices)

        choice_instructions = ''
        if not is_ending :
            choice_instructions += '다음 선택지들은 아래 목표들로 이어지도록 만들어줘:\n'

            for i, choice_info in enumerate(choices):
                target_moment_id = choice_info.get('next_moment_id')
                target_moment_desc = all_moments.get(target_moment_id, {}).get('description', '')
                action_type = choice_info.get('action_type', '보통')
                choice_instructions += f'- 선택지 {i+1}: ({action_type} 결과) {target_moment_desc}\n'
        else:
            choice_instructions = "이야기의 끝입니다. 선택지가 필요 없습니다."

        player_action_text = f"플레이어가 {choice_index + 1}번째 선택지를 골랐어."
        
        prompt = self._generate_story_prompt(
            story_title=title,
            player_action_text=player_action_text,
            moment_description=next_moment_description,
            choice_instructions=choice_instructions,
            is_ending=is_ending,
            num_choices_available=num_choices_available
        )

        ai_response_content, error_response = self._call_openai_api(prompt)
        if error_response :
            return error_response

        return Response({
            "scene": ai_response_content.get("scene_text"),
            "choices": ai_response_content.get("choices"),
            "story_id": id,
            "story_title": title,
            "current_moment_id": next_moment_id,
            "current_moment_title": next_moment_title,
            "image_path" : next_moment_image
        }, status=status.HTTP_200_OK)