# config/middleware.py
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from django.core.cache import cache # ✅ Django 캐시 시스템 임포트

User = get_user_model()

class NonceJWTAuthMiddleware: # ✅ 클래스 이름 변경 (더 명확하게)
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope["query_string"].decode()
        query_params = parse_qs(query_string)
        nonce = query_params.get("nonce") # ✅ "token" 대신 "nonce"를 사용

        scope["user"] = AnonymousUser()

        if nonce:
            try:
                # ✅ Django 캐시에서 nonce와 매핑된 user_id를 가져옴
                user_id = cache.get(nonce[0])
                if user_id:
                    user = await self.get_user(user_id)
                    if user and not user.is_anonymous:
                        scope["user"] = user
                        print("✅ Nonce 인증 성공:", user.name)
                        # ✅ 일회성 인증이므로 사용 후 즉시 삭제
                        cache.delete(nonce[0]) 
                    else:
                        print("❌ Nonce에 해당하는 사용자 없음.")
                else:
                    print("❌ 유효하지 않거나 만료된 Nonce.")
            except Exception as e:
                print("❌ Nonce 인증 실패:", str(e))

        return await self.inner(scope, receive, send)

    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return AnonymousUser()


from channels.auth import AuthMiddlewareStack

# ✅ 미들웨어 스택에 새로운 미들웨어 적용
def NonceAuthMiddlewareStack(inner):
    return NonceJWTAuthMiddleware(AuthMiddlewareStack(inner))