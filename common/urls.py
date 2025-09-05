# backend/common/urls.py

from django.urls import path
from common.views import WebSocketNonceAPIView

# accounts 앱의 기존 URL 패턴들
urlpatterns = [
    path("websocket-nonce/", WebSocketNonceAPIView.as_view(), name="websocket_nonce"),
]