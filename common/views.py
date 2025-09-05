# common/views.py

import uuid # ✅ UUID 생성을 위해 추가
from django.core.cache import cache # ✅ Django 캐시 시스템을 위해 추가
from rest_framework.views import APIView # ✅ API 뷰를 위해 추가
from rest_framework.response import Response # ✅ API 응답을 위해 추가
from rest_framework.permissions import IsAuthenticated

class WebSocketNonceAPIView(APIView):
    # 이 뷰는 인증된 사용자만 접근 가능하도록 설정
    permission_classes = [IsAuthenticated] 

    def post(self, request, *args, **kwargs):
        # 1. IsAuthenticated 퍼미션에 의해 인증된 사용자 정보에 접근
        user = request.user
        
        # 2. 웹소켓 인증을 위한 일회성 고유 키(nonce) 생성
        nonce = str(uuid.uuid4())
        
        # 3. 생성된 nonce를 사용자의 ID와 함께 Django 캐시에 저장
        # nonce의 유효 시간을 짧게(예: 30초) 설정하여 보안 강화
        # settings.py에 CACHES 설정이 되어 있어야 함
        cache.set(nonce, user.id, timeout=30)
        
        # 4. 생성된 nonce를 클라이언트에게 반환
        return Response({"nonce": nonce})