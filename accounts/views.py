import os
import re
import requests
from django.utils import timezone
from dotenv import load_dotenv
from django.http import JsonResponse
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.views import TokenRefreshView as DRFTokenRefreshView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from accounts.services.achievement_service import AchievementService
from accounts.models import User
from accounts.serializers import UserSerializer

load_dotenv()

SOCIAL_AUTH_GOOGLE_CLIENT_ID = os.getenv('SOCIAL_AUTH_GOOGLE_CLIENT_ID')
SOCIAL_AUTH_GOOGLE_CLIENT_SECRET = os.getenv('SOCIAL_AUTH_GOOGLE_CLIENT_SECRET')
SOCIAL_AUTH_KAKAO_REST_API_KEY = os.getenv('SOCIAL_AUTH_KAKAO_REST_API_KEY')
SOCIAL_AUTH_MICROSOFT_TENANT_ID = os.getenv('SOCIAL_AUTH_MICROSOFT_TENANT_ID')
SOCIAL_AUTH_MICROSOFT_CLIENT_ID = os.getenv('SOCIAL_AUTH_MICROSOFT_CLIENT_ID')
SOCIAL_AUTH_MICROSOFT_CLIENT_SECRET = os.getenv('SOCIAL_AUTH_MICROSOFT_CLIENT_SECRET')


# 구글 리다이렉션 콜백
class GoogleCallbackView(APIView) :
    def post(self, request) :
        try :
            code = request.data.get('code')
            print('코드', code)

            redirect_uri = request.data.get('redirect_uri')
            print('리디렉션 uri', redirect_uri)

            code_verifier = request.data.get('code_verifier')
            print('code_verifier', code_verifier)

            # 구글 액세스 token 얻기
            client_id = SOCIAL_AUTH_GOOGLE_CLIENT_ID
            client_secret = SOCIAL_AUTH_GOOGLE_CLIENT_SECRET
            token_response = requests.post('https://oauth2.googleapis.com/token',
                data = {
                    'code' : code,
                    'client_id' : client_id,
                    'client_secret' : client_secret,
                    'redirect_uri' : redirect_uri,
                    'grant_type' : 'authorization_code',
                    'code_verifier' : code_verifier
                }
            )

            token_json = token_response.json()
            print('토큰', token_json)

            # 사용자 정보 가져오기
            id_token = token_json.get('id_token')
            user_response = requests.get(f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}')
            if user_response.status_code != 200 :
                return JsonResponse({
                    'error' : '구글 사용자 정보 조회 실패'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user_data = user_response.json()
            print('구글 사용자 정보', user_data)

            # 필요한 데이터 추출
            email = user_data.get('email')
            name = user_data.get('name')
            social_id = user_data.get('sub')

            # 새로운 유저 생성 및 기존 유저 조회
            user, created = User.objects.get_or_create(
                social_type='google',
                social_id=social_id,
                defaults={
                    'email' : email,
                    'name' : name,
                }
            )

            # 로그인 시마다 last_login 업데이트
            user.last_login = timezone.now()
            user.save()

            # 로그인
            token = RefreshToken.for_user(user)
            print('google token', token)

            # 사용자 정보 직렬화
            serializer = UserSerializer(user)

            return JsonResponse({
                'message' : '성공',
                'access_token' : str(token.access_token),
                'refresh_token' : str(token),
                'user' : serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e :
            return JsonResponse({
                'error': '서버 에러'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 카카오 리다이렉션 콜백
class KakaoCallbackView(APIView) :
    def post(self, request) :
        try :
            code = request.data.get('code')
            print('코드', code)

            redirect_uri = request.data.get('redirect_uri')
            print('리디렉션 uri', redirect_uri)

            # 카카오 액세스 token 얻기
            client_id = SOCIAL_AUTH_KAKAO_REST_API_KEY
            token_response = requests.post('https://kauth.kakao.com/oauth/token',
                headers = {
                    'Content-Type' : 'application/x-www-form-urlencoded;charset=utf-8'
                },
                data = {
                    'code' : code,
                    'client_id' : client_id,
                    'redirect_uri' : redirect_uri,
                    'grant_type' : 'authorization_code',
                }
            )

            token_json = token_response.json()
            print('토큰', token_json)

            # 사용자 정보 가져오기
            access_token = token_json.get('access_token')
            user_response = requests.get('https://kapi.kakao.com/v2/user/me',
                headers = {
                    'Authorization' : f'Bearer {access_token}',
                    'Content-Type' : 'application/x-www-form-urlencoded;charset=utf-8'
                }
            )
            if not user_response.ok :
                return JsonResponse({
                    'error' : '카카오 사용자 정보 조회 실패'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user_data = user_response.json()
            print('카카오 사용자 정보', user_data)

            # 필요한 데이터 추출
            social_id = user_data.get('id')
            kakao_account = user_data.get('kakao_account')
            profile = kakao_account.get('profile')
            nickname = profile.get('nickname')

            # 새로운 유저 생성 및 기존 유저 조회
            user, created = User.objects.get_or_create(
                social_type='kakao',
                social_id=social_id,
                defaults={
                    'email' : None,
                    'name' : nickname
                }
            )

            # 로그인 시마다 last_login 업데이트
            user.last_login = timezone.now()
            user.save()

            # 로그인
            token = RefreshToken.for_user(user)
            print('kakao token',token)

            # 사용자 정보 직렬화
            serializer = UserSerializer(user)

            return JsonResponse({
                'message' : '성공',
                'access_token' : str(token.access_token),
                'refresh_token' : str(token),
                'user' : serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e :
            return JsonResponse({
                'error': '서버 에러'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 마이크로소프트 리다이렉션 콜백
class MicrosoftCallbackView(APIView) :
    def post(self, request) :
        try :
            code = request.data.get('code')
            print('코드', code)

            redirect_uri = request.data.get('redirect_uri')
            print('리디렉션 uri', redirect_uri)

            code_verifier = request.data.get('code_verifier')
            print('code_verifier', code_verifier)

            # 마이크로소프트 액세스 token 얻기
            tenant_id = SOCIAL_AUTH_MICROSOFT_TENANT_ID
            client_id = SOCIAL_AUTH_MICROSOFT_CLIENT_ID
            client_secret = SOCIAL_AUTH_MICROSOFT_CLIENT_SECRET
            token_response = requests.post(f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token',
                headers = {
                    'Content-Type' : 'application/x-www-form-urlencoded;charset=utf-8'
                },
                data = {
                    'code' : code,
                    'client_id' : client_id,
                    'redirect_uri' : redirect_uri,
                    'grant_type' : 'authorization_code',
                    'code_verifier' : code_verifier,
                    'client_secret' : client_secret
                }
            )

            token_json = token_response.json()
            print('토큰', token_json)

            # 사용자 정보 가져오기
            access_token = token_json.get('access_token')
            user_response = requests.get(
                'https://graph.microsoft.com/oidc/userinfo',
                headers = {
                    'Authorization' : f'Bearer {access_token}'
                }
            )
            if user_response.status_code != 200 :
                return JsonResponse({
                    'error' : '마이크로소프트 사용자 정보 조회 실패'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user_data = user_response.json()
            print('마이크로소프트 사용자 정보', user_data)

            # 필요한 데이터 추출
            email = user_data.get('email', None)
            name = user_data.get('name')
            social_id = user_data.get('sub')

            # 새로운 유저 생성 및 기존 유저 조회
            user, created = User.objects.get_or_create(
                social_type='microsoft',
                social_id=social_id,
                defaults={
                    'email' : email,
                    'name' : name,
                }
            )

            # 로그인 시마다 last_login 업데이트
            user.last_login = timezone.now()
            user.save()

            # 로그인
            token = RefreshToken.for_user(user)
            print('microsoft token', token)

            # 사용자 정보 직렬화
            serializer = UserSerializer(user)

            return JsonResponse({
                'message' : '성공',
                'access_token' : str(token.access_token),
                'refresh_token' : str(token),
                'user' : serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e :
            return JsonResponse({
                'error': '서버 에러'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 사용자 정보 조회
class UserInfoView(APIView) :
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        user = request.user
        if user.is_authenticated:
            serializer = UserSerializer(user)
            return JsonResponse({
                'user' : serializer.data
            }, status=status.HTTP_200_OK)
        
        return JsonResponse({
            'error': 'Unauthorized'
        }, status=status.HTTP_401_UNAUTHORIZED)

# 사용자 정보 업데이트
class UserInfoUpdateView(APIView) :
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication] 

    def put(self, request):
        user = request.user

        nickname = request.data.get('nickname')

        if not nickname:
            return JsonResponse({
                'message': '닉네임을 입력해주세요.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 닉네임 유효성 검사
        nickname = nickname.strip()

        if not (2 <= len(nickname) <= 10):
            return JsonResponse({
                'message': '닉네임은 2자 이상 10자 이하로 입력해주세요.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 한글, 영문, 숫자만 허용하는 정규식 검사
        if not re.fullmatch(r'^[a-zA-Z0-9가-힣ㄱ-ㅎㅏ-ㅣ]*$', nickname):
            return JsonResponse({
                'message': '닉네임은 한글, 영문, 숫자만 사용할 수 있습니다.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 닉네임 중복 확인
        if User.objects.filter(nickname=nickname).exclude(id=user.id).exists():
            return JsonResponse({
                'message': '이미 사용 중인 닉네임입니다. 다른 닉네임을 사용해주세요.'
            }, status=status.HTTP_409_CONFLICT)

        # 닉네임 저장
        try :
            user.nickname = nickname
            user.save()
            serializer = UserSerializer(user)
            return JsonResponse({
                'message': '닉네임이 성공적으로 업데이트되었습니다.',
                'user': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e :
            return JsonResponse(
                {'message': f'닉네임 업데이트 중 알 수 없는 오류 발생: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# 액세스 토큰 재발급
class CustomTokenRefreshView(DRFTokenRefreshView) :
    def post(self, request, *args, **kwargs) :
        try :
            response = super().post(request, *args, **kwargs)
            return response
        except (InvalidToken, TokenError) as e :
            return JsonResponse({
                'detail' : str(e)
            }, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e :
            return JsonResponse({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

# 로그아웃
class LogoutView(APIView) :
    permission_classes = [IsAuthenticated]

    def post(self, request) :
        try :
            # Refresh token 을 블랙리스트에 추가
            refresh_token = request.data.get('refresh_token')
            token = RefreshToken(refresh_token)
            token.blacklist()

            return JsonResponse({
                'message' : '로그인 성공'
            }, status=status.HTTP_200_OK)
        except (KeyError, TokenError) :
            return JsonResponse({
                'error' : '유효하지 않은 토큰'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e :
            return JsonResponse({
                'error' : str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserAchievementsView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            service = AchievementService(request.user)
            all_achievements = service.get_all_achievements_with_status()
            
            for ach in all_achievements:
                progress_info = service.get_achievement_progress_info(ach['id'])
                if progress_info:
                    ach['progress'] = progress_info
                else:
                    ach['progress'] = None

            grouped_achievements = {
                'story': [ach for ach in all_achievements if ach['mode'] == 'story'],
                'single': [ach for ach in all_achievements if ach['mode'] == 'single'],
                'multi': [ach for ach in all_achievements if ach['mode'] == 'multi'],
            }
            return JsonResponse({
                'success': True,
                'message': '업적이 성공적으로 조회되었습니다.',
                'data': grouped_achievements
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"UserAchievementsView 에러: {e}")
            return JsonResponse({
                'success': False,
                'message': '업적 조회 중 서버 오류가 발생했습니다.',
                'error_detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
