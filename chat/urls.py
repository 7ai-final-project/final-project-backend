# backend\chat\urls.py
from django.urls import path
from django.http import JsonResponse

def ping(request):
    return JsonResponse({"message": "accounts ok"})

urlpatterns = [
    path("ping/", ping),
]
