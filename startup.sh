#!/bin/bash

# 서버에서 생성된 가상 환경을 활성화합니다.
source /home/site/wwwroot/antenv/bin/activate

# 데이터베이스 마이그레이션 및 정적 파일 수집
# python manage.py migrate
# python manage.py collectstatic --noinput

# [새로 추가된 라인] 모든 API 엔드포인트를 로그에 출력합니다.
# python manage.py show_my_urls

# ASGI 애플리케이션 실행
gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker --chdir /home/site/wwwroot