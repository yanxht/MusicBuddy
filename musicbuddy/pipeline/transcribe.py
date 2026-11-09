"""Azure Speech fast transcription (REST) with diarization and word timestamps."""
import json
import logging
import time
from pathlib import Path

import httpx

from .. import config
from . import audio

log = logging.getLogger(__name__)

API_VERSION = "2024-11-15"
MAX_CHUNK_S = 100 * 60  # stay well under the service's per-file duration limit


def _call(path: Path) -> dict:
    url = (f"https://{config.AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/"
           f"speechtotext/transcriptions:transcribe?api-version={API_VERSION}")
    definition = {
        "locales": config.SPEECH_LOCALES,
        "diarization": {"enabled": True, "maxSpeakers": 4},
        "profanityFilterMode": "None",
    }
    for attempt in range(4):
        with open(path, "rb") as f:
            resp = httpx.post(
                url,
                headers={"Ocp-Apim-Subscription-Key": config.AZURE_SPEECH_KEY},
                files={"audio": (path.name, f, "audio/mpeg"),
                       "definition": (None, json.dumps(definition), "application/json")},
                timeout=httpx.Timeout(1800.0, connect=30.0),
            )
        if resp.status_code == 200:
            return resp.json()
        log.warning("transcribe %s failed (%s): %s", path.name, resp.status_code, resp.text[:300])
        if resp.status_code < 500 and resp.status_code != 429:
            resp.raise_for_status()
        time.sleep(10 * (attempt + 1))
    resp.raise_for_status()
    return {}


def transcribe(src: Path, work: Path) -> list[dict]:
    """Return phrases: {start, end, speaker, text, conf} with seconds relative to `src`."""
    total = audio.duration_s(src)
    phrases: list[dict] = []
    offset = 0.0
    idx = 0
    while offset < total - 0.5:
        length = min(MAX_CHUNK_S, total - offset)
        chunk = audio.to_stt_audio(src, work / f"{src.stem}.stt{idx}.mp3", offset, length)
        log.info("transcribing %s chunk %d (%.0fs @ %.0fs)", src.name, idx, length, offset)
        data = _call(chunk)
        for p in data.get("phrases", []):
            start = offset + p["offsetMilliseconds"] / 1000
            phrases.append({
                "start": round(start, 2),
                "end": round(start + p["durationMilliseconds"] / 1000, 2),
                # Diarization ids are per chunk; prefix keeps them distinct across chunks.
                "speaker": f"S{idx}{p['speaker']}" if idx and "speaker" in p else f"S{p.get('speaker', 0)}",
                "text": p["text"].strip(),
                "conf": round(p.get("confidence", 0), 3),
            })
        offset += length
        idx += 1
    phrases.sort(key=lambda p: p["start"])
    return phrases
