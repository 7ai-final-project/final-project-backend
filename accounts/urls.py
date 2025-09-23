from django.urls import path
from accounts.views import GoogleCallbackView, KakaoCallbackView, MicrosoftCallbackView, UserInfoView, UserInfoUpdateView, CustomTokenRefreshView, LogoutView, UserAchievementsView
from rest_framework_simplejwt.views import TokenObtainPairView

urlpatterns = [
    path('google/callback', GoogleCallbackView.as_view(), name="google_callback"),
    path('kakao/callback', KakaoCallbackView.as_view(), name="kakao_callback"),
    path('microsoft/callback', MicrosoftCallbackView.as_view(), name="microsoft_callback"),
    path('user/me', UserInfoView.as_view(), name="user_info"),
    path('user/update', UserInfoUpdateView.as_view(), name="user_info_update"),
    path('token/', TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path('token/refresh', CustomTokenRefreshView.as_view(), name="token_refresh"),
    path('logout', LogoutView.as_view(), name="logout"),
    path('achievements/', UserAchievementsView.as_view(), name='user-achievements'),
]