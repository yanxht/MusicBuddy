"""On-demand Chinese version of a kid's lesson notes (cached in blob storage)."""
import copy
import json
import logging

from .. import config, llm, prompts, storage

log = logging.getLogger(__name__)
TEXT_KEYS = {"headline", "overview", "mood", "title", "detail", "material", "summary", "text",
             "item", "feedback", "task", "details", "step", "kid_recap", "meaning", "term"}
LIST_KEYS = {"parent_notes"}
BATCH = 120


def _collect(obj, out: list, setters: list) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TEXT_KEYS and isinstance(v, str) and v.strip():
                out.append(v)
                setters.append((obj, k))
            elif k in LIST_KEYS and isinstance(v, list):
                for i, s in enumerate(v):
                    if isinstance(s, str) and s.strip():
                        out.append(s)
                        setters.append((v, i))
            elif isinstance(v, (dict, list)) and k != "clip" and k != "clips":
                _collect(v, out, setters)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, out, setters)


def translate_summary(summary: dict) -> dict:
    zh = copy.deepcopy(summary)
    texts, setters = [], []
    _collect(zh, texts, setters)
    for start in range(0, len(texts), BATCH):
        chunk = texts[start:start + BATCH]
        res = llm.chat_json(prompts.TRANSLATE_SYSTEM, prompts.TRANSLATE_USER.format(
            n=len(chunk), payload=json.dumps({"items": chunk}, ensure_ascii=False)),
            model=config.VISION_MODEL, max_tokens=16000)
        items = res.get("items", [])
        if len(items) != len(chunk):
            raise RuntimeError(f"translation returned {len(items)} of {len(chunk)} strings")
        for (target, key), value in zip(setters[start:start + BATCH], items):
            if isinstance(value, str) and value.strip():
                target[key] = value
    return zh


def get_zh(date: str, kid: str) -> dict | None:
    doc = storage.get_json(config.DATA_CONTAINER, f"{date}/lesson.json")
    if not doc or kid not in doc.get("kids", {}):
        return None
    path = f"{date}/zh/{kid}.json"
    cached = storage.get_json(config.DATA_CONTAINER, path)
    if cached and cached.get("updated") == doc["updated"]:
        return cached["summary"]
    zh = translate_summary(doc["kids"][kid]["summary"])
    storage.put_json(config.DATA_CONTAINER, path, {"updated": doc["updated"], "summary": zh})
    return zh
