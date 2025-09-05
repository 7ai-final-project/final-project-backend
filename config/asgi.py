# config/asgi.py
import os
import django
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

# ✅ settings 먼저 로드
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# 이제 안전하게 import
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken

@database_sync_to_async
def _get_user(user_id: int):
    User = get_user_model()
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()

# ✅ NonceAuthMiddlewareStack으로 변경
from .middleware import NonceAuthMiddlewareStack
from . import routing

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AllowedHostsOriginValidator(
            NonceAuthMiddlewareStack( # ✅ JWTAuthMiddlewareStack 대신 NonceAuthMiddlewareStack 사용
                URLRouter(routing.websocket_urlpatterns)
            )
        ),
    }
)