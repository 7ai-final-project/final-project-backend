# -*- coding: utf-8 -*-
# game/azure_image.py
import os, time, json, re
from typing import Optional, Dict, Any
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from httpx import Timeout
import logging
logger = logging.getLogger(__name__)

# ---- Style (영어) ----
STYLE_DESCRIPTION = (
    "Simple and clean 8-bit pixel art, minimalist, retro video game asset, "
    "clear outlines, Korean fairy tale theme. No Japanese or Chinese elements."
)
STYLE_TEXT = os.getenv("AZURE_IMAGE_STYLE", STYLE_DESCRIPTION)

# ---- DALL·E(Images API) 설정 ----
DEFAULT_MODEL_DEPLOYMENT = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT") or ""
DEFAULT_API_VERSION     = os.getenv("AZURE_OPENAI_DALLE_VERSION", "2024-04-01-preview")
DEFAULT_ENDPOINT        = os.getenv("AZURE_OPENAI_DALLE_ENDPOINT", "")
REQUEST_TIMEOUT         = float(os.getenv("AZURE_OPENAI_TIMEOUT_SEC", "60"))

# ---- (선택) 번역 설정 ----
# 1이면 번역 시도. 실패하면 원문 그대로 사용
TRANSLATE_TO_EN = (os.getenv("AZURE_IMAGE_TRANSLATE", "1").lower() in ("1","true","yes"))
CHAT_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", DEFAULT_ENDPOINT)  # 일반 챗 엔드포인트
CHAT_VERSION    = os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview")
CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")              # 번역용 챗 배포명

def _make_images_client() -> AzureOpenAI:
    if not DEFAULT_ENDPOINT:
        logger.error("[IMG] AZURE_OPENAI_DALLE_ENDPOINT is empty")
    if not DEFAULT_MODEL_DEPLOYMENT:
        logger.error("[IMG] AZURE_OPENAI_DALLE_DEPLOYMENT is empty (404 risk)")

    api_key = os.getenv("AZURE_OPENAI_DALLE_APIKEY")
    if api_key:
        logger.info(f"[IMG] KEY auth | endpoint={DEFAULT_ENDPOINT} | version={DEFAULT_API_VERSION} | deployment={DEFAULT_MODEL_DEPLOYMENT}")
        return AzureOpenAI(
            api_key=api_key,
            api_version=DEFAULT_API_VERSION,
            azure_endpoint=DEFAULT_ENDPOINT,
            timeout=Timeout(REQUEST_TIMEOUT),
        )
    logger.info(f"[IMG] AAD auth | endpoint={DEFAULT_ENDPOINT} | version={DEFAULT_API_VERSION} | deployment={DEFAULT_MODEL_DEPLOYMENT}")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        api_version=DEFAULT_API_VERSION,
        azure_endpoint=DEFAULT_ENDPOINT,
        azure_ad_token_provider=token_provider,
        timeout=Timeout(REQUEST_TIMEOUT),
    )

def _make_chat_client() -> Optional[AzureOpenAI]:
    """번역용. 설정이 없으면 None 반환."""
    if not TRANSLATE_TO_EN:
        return None
    if not CHAT_ENDPOINT or not CHAT_DEPLOYMENT:
        logger.warning("[IMG-TX] translate off (endpoint or deployment missing)")
        return None

    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_DALLE_APIKEY")
    try:
        if api_key:
            return AzureOpenAI(
                api_key=api_key,
                api_version=CHAT_VERSION,
                azure_endpoint=CHAT_ENDPOINT,
                timeout=Timeout(REQUEST_TIMEOUT),
            )
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        return AzureOpenAI(
            api_version=CHAT_VERSION,
            azure_endpoint=CHAT_ENDPOINT,
            azure_ad_token_provider=token_provider,
            timeout=Timeout(REQUEST_TIMEOUT),
        )
    except Exception as e:
        logger.warning(f"[IMG-TX] chat client init failed: {e}")
        return None

_CODEFENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_JSONBLOCK = re.compile(r"\{[^{}]{200,}\}", re.DOTALL)  # 큰 JSON 제거
_WS        = re.compile(r"[ \t]+")
_KO_CHARS  = re.compile(r"[가-힣]")

def _sanitize_prompt(raw: str, max_len: int = 950) -> str:
    if not isinstance(raw, str):
        raw = "" if raw is None else str(raw)
    s = _CODEFENCE.sub("", raw)
    s = _JSONBLOCK.sub("", s)
    s = s.replace("\r", "")
    s = "\n".join(line.strip() for line in s.split("\n") if line.strip())
    s = _WS.sub(" ", s)
    if len(s) > max_len:
        s = s[:max_len].rstrip() + " ..."
    return s

def _translate_to_english(text: str) -> str:
    """한국어가 포함되면 Chat Completions로 간단 번역. 실패 시 원문 반환."""
    if not _KO_CHARS.search(text):
        return text  # 한글 없음
    client = _make_chat_client()
    if not client:
        return text
    try:
        resp = client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "Translate the following content into concise, natural English suitable for an image generation prompt. Do not add quotes. Keep details, remove meta words like 'instruction'."},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            top_p=0.9,
            max_tokens=800,
        )
        out = (resp.choices[0].message.content or "").strip()
        if out:
            return out
    except Exception as e:
        logger.warning(f"[IMG-TX] translate failed: {e}")
    return text

def _compose_prompt(raw: str) -> str:
    base = _sanitize_prompt(raw)
    # 1) 필요하면 영어로 번역
    base = _translate_to_english(base)
    # 2) 스타일(영어) 붙이기
    style = _sanitize_prompt(STYLE_TEXT, max_len=300)
    final = f"{base}\n\n{style}".strip()
    return final

def generate_scene_image(
    prompt: str,
    *,
    model: Optional[str] = None,
    size: str = "512x512",
    n: int = 1,
    quality: str = "standard",
    style: str = "vivid",
    max_retries: int = 2,
    return_base64: bool = False
) -> Dict[str, Any]:
    client = _make_images_client()
    model = (model or DEFAULT_MODEL_DEPLOYMENT).strip()
    styled_prompt = _compose_prompt(prompt)
    last_err = None

    if not model:
        msg = "AZURE_OPENAI_DALLE_DEPLOYMENT is empty."
        logger.error(f"[IMG] {msg}")
        return {"ok": False, "error": msg, "prompt": styled_prompt}
    if not DEFAULT_ENDPOINT:
        msg = "AZURE_OPENAI_DALLE_ENDPOINT is empty."
        logger.error(f"[IMG] {msg}")
        return {"ok": False, "error": msg, "prompt": styled_prompt}
    if not styled_prompt:
        msg = "prompt became empty after sanitization."
        logger.error(f"[IMG] {msg}")
        return {"ok": False, "error": msg, "prompt": styled_prompt}

    logger.debug(f"[IMG] prompt_len={len(styled_prompt)} | preview={styled_prompt[:120]!r}")
    for attempt in range(max_retries + 1):
        try:
            result = client.images.generate(
                model=model,
                prompt=styled_prompt,
                n=n,
                size=size,
                quality=quality,
                style=style,
                response_format="b64_json" if return_base64 else "url",
            )
            payload = json.loads(result.model_dump_json())
            return {"ok": True, "result": payload, "prompt": styled_prompt}
        except Exception as e:
            last_err = e
            logger.warning(
                f"[IMG] generate failed (try {attempt+1}/{max_retries+1}) "
                f"| deployment={model} | endpoint={DEFAULT_ENDPOINT} | v={DEFAULT_API_VERSION} "
                f"| prompt_len={len(styled_prompt)} | err={e}"
            )
            time.sleep(0.8 * (attempt + 1))

    return {"ok": False, "error": str(last_err), "prompt": styled_prompt}
