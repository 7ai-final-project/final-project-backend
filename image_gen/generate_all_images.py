import os
import json
import requests
import sys

# --- 자동 경로 설정 ---
# 이 스크립트 파일(generate_all_images.py)이 있는 폴더의 경로
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# backend 폴더의 경로 (SCRIPT_DIR의 부모 폴더)
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
# 최종적으로 찾으려는 stories json 폴더의 경로
STORIES_JSON_DIR = os.path.join(BACKEND_DIR, "llm", "stories", "json")
# --- 설정 끝 ---


# 서버 주소
BASE_URL = "http://127.0.0.1:8000"
IMAGE_GEN_URL = f"{BASE_URL}/image-gen/api/generate-scene-image/"

def generate_images_for_story(file_path):
    """하나의 스토리 파일에 포함된 모든 장면에 대한 이미지 생성을 요청합니다."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            story = json.load(f)
        
        story_id = story.get("id_eng")
        if not story_id:
            print(f"오류: {os.path.basename(file_path)} 파일에 'id_eng'가 없습니다. 건너뜁니다.")
            return

        print(f"\n--- '{story_id}' 스토리의 이미지 생성을 시작합니다. ---")
        
        moment_ids = story.get("moments", {}).keys()
        if not moment_ids:
            print(f"경고: '{story_id}' 스토리에 'moments'가 없습니다.")
            return

        for moment_id in moment_ids:
            print(f"'{moment_id}' 장면의 이미지 생성을 요청합니다...")
            
            payload = {
                "story_id": story_id,
                "scene_name": moment_id
            }
            
            try:
                # DALL-E 생성 시간이 길 수 있으므로 타임아웃을 5분으로 넉넉하게 설정
                response = requests.post(IMAGE_GEN_URL, json=payload, timeout=300) 
                
                if response.status_code >= 400:
                    print(f"-> 실패: HTTP {response.status_code} - {response.text}")
                else:
                    print(f"-> 성공: {response.json().get('message', 'OK')}")

            except requests.exceptions.RequestException as e:
                print(f"-> 실패: 요청 중 오류 발생 - {e}")

    except Exception as e:
        print(f"파일 처리 중 오류 발생 ({os.path.basename(file_path)}): {e}")


if __name__ == "__main__":
    if not os.path.exists(STORIES_JSON_DIR):
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! 오류: 스토리 폴더를 찾을 수 없습니다.            !!!")
        print(f"!!! 예상 경로: {STORIES_JSON_DIR} !!!")
        print("!!! 경로가 올바른지 확인해주세요.                      !!!")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        sys.exit(1) # 오류 발생 시 스크립트 종료

    print("===== 전체 스토리 이미지 생성 스크립트를 시작합니다. =====")
    print(f"대상 폴더: {STORIES_JSON_DIR}")
    
    # 폴더 내의 모든 json 파일에 대해 실행
    for filename in os.listdir(STORIES_JSON_DIR):
        if filename.endswith(".json"):
            generate_images_for_story(os.path.join(STORIES_JSON_DIR, filename))
    
    print("\n===== 모든 작업이 완료되었습니다. =====")