from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from openai import AzureOpenAI
from dotenv import load_dotenv
import json
import os
import traceback
import time
import requests

# [수정 1] ContentSettings를 import 목록에 추가합니다.
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceExistsError

# .env 파일 로드
load_dotenv()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class GenerateSceneImageView(APIView):
    # 이 API는 프로젝트 전체 인증 설정을 무시하고 누구나 접근 가능하도록 설정
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            story_identifier = request.data.get("story_id")
            scene_name = request.data.get("scene_name") 

            if not story_identifier or not scene_name:
                return Response({"error": "'story_id'와 'scene_name'이 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

            container_name = story_identifier.lower()

            connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            if not connection_string:
                return Response({"error": "Azure Blob Storage 연결 문자열(.env) 설정이 누락되었습니다."}, status=500)

            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            
            try:
                container_client = blob_service_client.create_container(container_name)
                container_client.set_container_access_policy(signed_identifiers={}, public_access='blob')
                print(f"\n>> 신규 컨테이너 '{container_name}' 생성 및 공개 설정 완료.\n")
            except ResourceExistsError:
                pass

            blob_name = f"{scene_name}.png"
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

            if blob_client.exists():
                print(f"\n>> 이미지가 이미 존재합니다. 생성을 건너뜁니다. URL: {blob_client.url}\n")
                return Response({"message": "이미지가 이미 존재합니다.", "image_url": blob_client.url}, status=status.HTTP_200_OK)

            stories_dir = os.path.join(BASE_DIR, 'llm', 'stories', 'json')
            story_data = None
            if os.path.exists(stories_dir):
                for file in os.listdir(stories_dir):
                    if file.endswith(".json"):
                        with open(os.path.join(stories_dir, file), "r", encoding="utf-8") as f:
                            story_content = json.load(f)
                            if story_content.get('id_eng') == story_identifier:
                                story_data = story_content
                                break
            
            if not story_data:
                 return Response({"error": f"ID '{story_identifier}'에 해당하는 스토리를 찾을 수 없습니다."}, status=404)

            print(">> GPT-4를 호출하여 DALL-E 프롬프트를 생성합니다...")
            
            gpt_api_key = os.getenv("AZURE_OPENAI_API_KEY")
            gpt_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            gpt_api_version = os.getenv("AZURE_OPENAI_VERSION")

            gpt_client = AzureOpenAI(api_key=gpt_api_key, azure_endpoint=gpt_endpoint, api_version=gpt_api_version)

            description = story_data['moments'][scene_name]['description']
            characters_info = "Haesik (a girl in traditional yellow and red Hanbok), Dalsik (her younger brother in white and gray Hanbok), and a large, slightly foolish Tiger. Or a woodcutter and a ghost from a well."
            style_description = "Simple and clean 8-bit pixel art, minimalist, retro video game asset, clear outlines, Korean fairy tale theme. No Japanese or Chinese elements."

            gpt_prompt = f"""
            You are an expert prompt writer for an 8-bit pixel art image generator. Your task is to convert a scene description into a single, visually detailed paragraph for the DALL-E model.
            **Consistent Rules (Apply to all images):**
            - **Art Style:** {style_description}
            - **Relevant Characters:** {characters_info}
            **Current Scene Description to Convert:**
            - "{description}"
            Combine all of this information into a single descriptive paragraph. Focus on visual details like character actions, expressions, and background elements. Do not use markdown or lists.
            """

            gpt_response = gpt_client.chat.completions.create(
                model=gpt_deployment,
                messages=[{"role": "user", "content": gpt_prompt}],
                temperature=0.7,
                max_tokens=250
            )
            dalle_prompt = gpt_response.choices[0].message.content.strip()
            print(f">> 생성된 DALL-E 프롬프트: {dalle_prompt}")

            dalle_api_key = os.getenv("AZURE_OPENAI_DALLE_APIKEY")
            dalle_endpoint = os.getenv("AZURE_OPENAI_DALLE_ENDPOINT")
            dalle_deployment = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT")
            dalle_api_version = os.getenv("AZURE_OPENAI_DALLE_VERSION")

            dalle_client = AzureOpenAI(api_key=dalle_api_key, azure_endpoint=dalle_endpoint, api_version=dalle_api_version)
            
            start_time = time.perf_counter()
            dalle_response = dalle_client.images.generate(model=dalle_deployment, prompt=dalle_prompt, n=1, size="1024x1024", style="vivid", quality="standard")
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            temp_image_url = dalle_response.data[0].url if dalle_response.data else None
            
            if not temp_image_url:
                return Response({"error": "DALL-E 3 이미지 생성에 실패했습니다."}, 500)

            print(f"\n>> 이미지 생성 성공! 소요 시간: {duration:.2f}초.")
            
            print(f">> 이미지를 Blob Storage에 업로드합니다. (컨테이너: {container_name}, Blob: {blob_name})")
            image_response = requests.get(temp_image_url)
            if image_response.status_code == 200:
                # [수정 2] 딕셔너리 대신 ContentSettings 객체를 생성하여 전달합니다.
                content_settings_obj = ContentSettings(content_type='image/png')
                blob_client.upload_blob(image_response.content, overwrite=True, content_settings=content_settings_obj)
                final_image_url = blob_client.url
                print(f">> 업로드 성공! 최종 URL: {final_image_url}\n")
            else:
                return Response({"error": "생성된 이미지 다운로드에 실패했습니다."}, 500)

            return Response({"message": "이미지 생성 및 업로드 성공", "image_url": final_image_url, "duration": f"{duration:.2f}"}, status=201)

        except KeyError:
            traceback.print_exc()
            return Response({"error": f"'{scene_name}'에 해당하는 장면을 찾을 수 없습니다."}, 404)
        except Exception as e:
            traceback.print_exc()
            return Response({"error": f"서버 내부 오류 발생: {str(e)}"}, status=500)