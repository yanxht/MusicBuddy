"""DeepSeek client (OpenAI-compatible API)."""
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Iterator

from openai import OpenAI

from . import config

log = logging.getLogger(__name__)
_client: OpenAI | None = None

try:  # iPhone photos are often HEIC
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL,
                         timeout=900, max_retries=2)
    return _client


def image_part(path: Path, max_px: int = 1600) -> dict:
    from io import BytesIO

    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_px, max_px * 2))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str | list, model: str | None = None,
              max_tokens: int = 32000, effort: str | None = None) -> dict:
    """One-shot call that must return a JSON object. Retries on malformed output."""
    model = model or config.LLM_MODEL
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    extra = {"reasoning_effort": effort} if effort else None
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            # Streaming keeps long reasoning calls alive (no single long-held read).
            stream = client().chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, stream=True,
                stream_options={"include_usage": True},
                response_format={"type": "json_object"}, extra_body=extra)
            parts, usage, t0 = [], None, time.time()
            for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage
                if chunk.choices and chunk.choices[0].delta.content:
                    parts.append(chunk.choices[0].delta.content)
            log.info("llm %s: in=%s out=%s %.0fs", model, getattr(usage, "prompt_tokens", "?"),
                     getattr(usage, "completion_tokens", "?"), time.time() - t0)
            return _parse_json("".join(parts))
        except Exception as e:  # noqa: BLE001 - retry any transport/parse failure
            last_err = e
            log.warning("chat_json attempt %d failed: %s", attempt + 1, e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"LLM JSON call failed: {last_err}")


def chat_stream(messages: list[dict], model: str | None = None,
                max_tokens: int = 16000) -> Iterator[str]:
    stream = client().chat.completions.create(
        model=model or config.LLM_MODEL, messages=messages, max_tokens=max_tokens, stream=True)
    for chunk in stream:
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            yield delta
