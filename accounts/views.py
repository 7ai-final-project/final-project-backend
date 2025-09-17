import os
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
from accounts.models import User
from accounts.serializers import UserSerializer

load_dotenv()

SOCIAL_AUTH_GOOGLE_CLIENT_ID = os.getenv('SOCIAL_AUTH_GOOGLE_CLIENT_ID')
SOCIAL_AUTH_GOOGLE_CLIENT_SECRET = os.getenv('SOCIAL_AUTH_GOOGLE_CLIENT_SECRET')
SOCIAL_AUTH_KAKAO_REST_API_KEY = os.getenv('SOCIAL_AUTH_KAKAO_REST_API_KEY')

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
                    'name' : name
                }
            )

            print('user', user)
            print('created', created)

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
                    'email' : '',
                    'name' : nickname
                }
            )

            print('user', user)
            print('created', created)

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


# 사용자 정보 조회
class UserInfoView(APIView) :
    permission_classes = [IsAuthenticated]
    print('permission_classes', permission_classes)
    
    authentication_classes = [JWTAuthentication]
    print('authentication_classes', authentication_classes)

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
        