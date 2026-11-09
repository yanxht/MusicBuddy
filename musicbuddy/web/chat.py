"""Chat grounded in lesson transcripts, notes and kid profiles."""
import json
import logging
import time
from pathlib import Path
from typing import Iterator

from .. import config, llm, prompts, storage
from ..pipeline import timeline

log = logging.getLogger(__name__)
_cache: dict[str, tuple[float, str]] = {}
CACHE_S = 600
OTHER_LESSONS = 8


def _ids(clip) -> list | None:
    return [clip["from"], clip["to"]] if isinstance(clip, dict) else None


def _slim_summary(s: dict) -> dict:
    """Summary with clips reduced to transcript id ranges (ids are what the model cites)."""
    out = {k: s.get(k) for k in ("headline", "overview", "parent_notes", "glossary", "practice_plan")}
    out["teacher_focus"] = [{**f, "clips": [_ids(c) for c in f.get("clips", [])]} for f in s.get("teacher_focus", [])]
    for key in ("homework_check", "assignments"):
        out[key] = [{**x, "clip": _ids(x.get("clip"))} for x in s.get(key, [])]
    out["sections"] = [{"title": sec.get("title"), "material": sec.get("material"),
                        "ids": [sec.get("from_id"), sec.get("to_id")], "summary": sec.get("summary"),
                        "points": [{**p, "clip": _ids(p.get("clip"))} for p in sec.get("points", [])]}
                       for sec in s.get("sections", [])]
    out["photos"] = [{"photo": p.get("key"), "status": p.get("status"), "summary": p.get("summary"),
                      "clip": _ids(p.get("clip")),
                      "markings": [{**m, "clip": _ids(m.get("clip"))} for m in p.get("markings", [])]}
                     for p in s.get("photos", [])]
    return out


def _lesson_block(date: str, full: bool) -> str:
    key = f"{date}:{full}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    doc = storage.get_json(config.DATA_CONTAINER, f"{date}/lesson.json")
    if not doc:
        return ""
    parts = [f"## Lesson {date} ({doc.get('instrument')}, teacher {doc.get('teacher') or config.TEACHER_NAME})"]
    for kid, k in doc.get("kids", {}).items():
        s = k["summary"]
        rng = ", ".join(f"#{a}-#{b}" for a, b in k["ranges"])
        if full:
            parts.append(f"### {config.KIDS[kid]['name']}'s lesson ({k['minutes']} min, transcript {rng}) notes:\n"
                         + json.dumps(_slim_summary(s), ensure_ascii=False))
        else:
            parts.append(f"### {config.KIDS[kid]['name']} ({k['minutes']} min): {s.get('headline')}\n"
                         f"{s.get('overview')}\nAssignments: "
                         + "; ".join(f"{a.get('task')} ({a.get('details', '')})" for a in s.get("assignments", [])))
    if full:
        for n in doc.get("notes", []):
            parts.append(f"### Homework notes sent before the lesson ({n['source']}):\n{n['text']}")
        for im in doc.get("images", []):
            if im.get("kind") == "lesson_book_page":
                parts.append(f"### Photo {Path(im.get('blob', '')).stem}: {im.get('title')} "
                             f"(for {im.get('kid')}): {im.get('music', '')}\n"
                             f"Handwritten: {'; '.join(map(str, im.get('handwriting') or []))}")
        items = storage.get_json(config.DATA_CONTAINER, f"{date}/timeline.json") or []
        speakers = (doc.get("attribution") or {}).get("speaker_names", {})
        who = {}
        for kid, k in doc.get("kids", {}).items():
            for a, b in k["ranges"]:
                who.update({i: config.KIDS[kid]["name"] for i in range(a, b + 1)})
        chunks, cur, buf = [], None, []
        for it in items:
            if "id" in it and who.get(it["id"]) != cur:
                if buf:
                    chunks.append((cur, buf))
                cur, buf = who.get(it["id"]), []
            buf.append(it)
        if buf:
            chunks.append((cur, buf))
        for name, chunk in chunks:
            parts.append(f"### Transcript ({name or 'not part of a lesson'}'s part)\n"
                         + timeline.render(chunk, speakers))
    text = "\n\n".join(parts)
    _cache[key] = (time.time(), text)
    return text


def build_context(date: str | None, kid: str | None) -> str:
    index = storage.get_json(config.DATA_CONTAINER, "index.json", {"lessons": []})
    dates = [l["date"] for l in index["lessons"]]
    focus = date if date in dates else (dates[0] if dates else None)
    blocks = []
    for k, v in config.KIDS.items():
        prof = storage.get_json(config.DATA_CONTAINER, f"profiles/{k}.json") or {}
        blocks.append(f"## {v['name']} (age {v['age']}) learning profile\n{json.dumps(prof, ensure_ascii=False)}")
    if focus:
        blocks.append("# Lesson in focus (full detail)\n" + _lesson_block(focus, True))
    others = [d for d in dates if d != focus][:OTHER_LESSONS]
    if others:
        blocks.append("# Other recent lessons (summaries)\n" + "\n\n".join(_lesson_block(d, False) for d in others))
    if kid:
        blocks.append(f"The person chatting is looking at {config.KIDS[kid]['name']}'s notes.")
    return "\n\n".join(blocks)


def answer(messages: list[dict], date: str | None, kid: str | None) -> Iterator[str]:
    try:
        system = prompts.CHAT_SYSTEM.format(context=build_context(date, kid))
        yield from llm.chat_stream([{"role": "system", "content": system}, *messages])
    except Exception:  # noqa: BLE001 - surface a friendly error inside the stream
        log.exception("chat failed")
        yield "\n\nSorry, I couldn't reach the AI service just now. Please try again."
