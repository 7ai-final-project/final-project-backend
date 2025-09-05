from django.urls import path
from accounts.views import GoogleCallbackView, KakaoCallbackView, UserInfoView, CustomTokenRefreshView, LogoutView
from rest_framework_simplejwt.views import TokenObtainPairView

urlpatterns = [
    path('google/callback', GoogleCallbackView.as_view(), name="google_callback"),
    path('kakao/callback', KakaoCallbackView.as_view(), name="kakao_callback"),
    path('user/me', UserInfoView.as_view(), name="user_info"),
    path('token/', TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path('token/refresh', CustomTokenRefreshView.as_view(), name="token_refresh"),
    path('logout', LogoutView.as_view(), name="logout"),
]