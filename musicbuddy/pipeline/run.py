"""End-to-end processing of one lesson folder (raw blobs -> lesson.json)."""
import base64
import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .. import config, llm, prompts, storage
from ..ingest import kind_of
from . import audio, timeline, transcribe

log = logging.getLogger(__name__)
INSTRUMENTS = ("violin", "piano", "viola", "cello", "guitar", "flute")
KID_IDS = tuple(config.KIDS)
MAX_CLIP_S = 150


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_status(date: str, state: str, step: str, **extra) -> None:
    storage.put_json(config.DATA_CONTAINER, f"{date}/status.json",
                     {"date": date, "state": state, "step": step, "updated": now(), **extra})
    log.info("[%s] %s: %s", date, state, step)


def _natural(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _meta_from_names(names: list[str]) -> tuple[str, str]:
    instrument, teacher = "", ""
    for n in names:
        toks = re.split(r"[-_ .]+", Path(n).stem.lower())
        for i, t in enumerate(toks):
            if t in INSTRUMENTS:
                instrument = instrument or t
                nxt = toks[i + 1] if i + 1 < len(toks) else ""
                if nxt and not re.fullmatch(r"p?\d+", nxt):
                    teacher = teacher or nxt.title()
    return instrument or "violin", teacher


# ---------------------------------------------------------------- sources

def _download_raw(date: str, work: Path) -> list[Path]:
    paths = []
    for b in storage.list_blobs(config.RAW_CONTAINER, f"{date}/"):
        name = b.name.split("/", 1)[1]
        if "/" in name or not kind_of(name):
            continue
        dest = work / "raw" / name
        if not dest.exists() or dest.stat().st_size != b.size:
            storage.get_file(config.RAW_CONTAINER, b.name, dest)
        paths.append(dest)
    return sorted(paths, key=lambda p: _natural(p.name))


def _process_images(date: str, images: list[Path], work: Path) -> list[dict]:
    out = []
    for i, p in enumerate(images, 1):
        cached = storage.get_json(config.DATA_CONTAINER, f"{date}/images/{p.name}.json")
        if cached and cached.get("size") == p.stat().st_size:
            out.append(cached)
            continue
        jpg = work / "images" / f"img{i}.jpg"
        jpg.parent.mkdir(parents=True, exist_ok=True)
        part = llm.image_part(p, max_px=1600)
        jpg.write_bytes(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
        try:
            info = llm.chat_json(prompts.IMAGE_SYSTEM,
                                 [{"type": "text", "text": prompts.IMAGE_USER}, part],
                                 model=config.VISION_MODEL, max_tokens=6000)
        except Exception as e:  # noqa: BLE001 - an unreadable photo should not fail the lesson
            log.warning("image read failed for %s: %s", p.name, e)
            info = {"kind": "other", "kid": "unknown", "title": p.name, "text": "", "items": []}
        blob = f"{date}/images/img{i}.jpg"
        storage.put_file(config.DATA_CONTAINER, blob, jpg)
        rec = {"name": p.name, "size": p.stat().st_size, "blob": blob, **info}
        rec["kid"] = str(rec.get("kid") or "unknown").lower()
        storage.put_json(config.DATA_CONTAINER, f"{date}/images/{p.name}.json", rec)
        out.append(rec)
    return out


def _kid_in_text(text: str) -> str:
    t = text.lower()
    hits = [k for k in KID_IDS if k in t]
    return hits[0] if len(hits) == 1 else ("both" if hits else "unknown")


def _process_audio(date: str, audios: list[Path], work: Path) -> tuple[list, dict, dict]:
    recordings, transcripts, silences = [], {}, {}
    for i, p in enumerate(audios, 1):
        rid = f"R{i}"
        tblob = f"{date}/transcripts/{rid}.json"
        cached = storage.get_json(config.DATA_CONTAINER, tblob)
        if cached and cached.get("source") == p.name and cached.get("size") == p.stat().st_size:
            dur = cached["duration"]
            transcripts[rid], silences[rid] = cached["phrases"], [tuple(s) for s in cached["silences"]]
        else:
            set_status(date, "processing", f"transcribing recording {i} of {len(audios)}")
            dur = audio.duration_s(p)
            transcripts[rid] = transcribe.transcribe(p, work / "stt")
            silences[rid] = audio.silences(p)
            storage.put_json(config.DATA_CONTAINER, tblob, {
                "source": p.name, "size": p.stat().st_size, "duration": dur,
                "phrases": transcripts[rid], "silences": silences[rid]})
        ablob = f"{date}/audio/{rid}.mp3"
        if not (cached and cached.get("source") == p.name and storage.exists(config.DATA_CONTAINER, ablob)):
            set_status(date, "processing", f"preparing audio for playback ({i} of {len(audios)})")
            mp3 = audio.to_stream_mp3(p, work / "audio" / f"{rid}.mp3")
            storage.put_file(config.DATA_CONTAINER, ablob, mp3)
        recordings.append({"id": rid, "name": p.name, "duration": round(dur, 2), "audio_blob": ablob})
    return recordings, transcripts, silences


# ---------------------------------------------------------------- attribution

def _fmt_notes(notes: list[dict], kid: str | None = None) -> str:
    rows = []
    for n in notes:
        if kid and n["kid"] not in (kid, "both", "unknown"):
            continue
        owner = n["kid"] if n["kid"] != "unknown" else "unknown child"
        rows.append(f"- From {n['source']} (for {owner}):\n{n['text'].strip()}")
    return "\n".join(rows) or "(none provided)"


def _fmt_pages(images: list[dict], kid: str | None = None) -> str:
    rows = [f"- {i.get('title', '')}: {i.get('music') or i.get('text', '')[:800]}"
            for i in images if i.get("kind") == "lesson_book_page"
            and (not kid or i.get("kid") in (kid, "both", "unknown"))]
    return "\n".join(rows) or "(none)"


def _fmt_kids() -> str:
    rows = []
    for k, v in config.KIDS.items():
        prof = storage.get_json(config.DATA_CONTAINER, f"profiles/{k}.json") or {}
        brief = {x: prof.get(x) for x in ("current_repertoire", "scales_etudes", "health_or_context") if prof.get(x)}
        rows.append(f"- {v['name']} (id '{k}'), age {v['age']}. {v['seed']}"
                    + (f" Recent profile: {json.dumps(brief, ensure_ascii=False)}" if brief else ""))
    return "\n".join(rows)


def attribute(date: str, recordings: list[dict], items: list[dict], notes: list[dict],
              images: list[dict]) -> dict:
    phr = timeline.phrases(items)
    last_id = phr[-1]["id"]
    rec_lines = "\n".join(f"- {r['id']}: {r['name']} ({timeline.fmt_ts(r['duration'])})" for r in recordings)
    total = sum(r["duration"] for r in recordings)
    user = prompts.ATTRIBUTION_USER.format(
        date=date, recordings=rec_lines, total=timeline.fmt_ts(total), kids=_fmt_kids(),
        notes=_fmt_notes(notes), pages=_fmt_pages(images), transcript=timeline.render(items),
        last_id=last_id)
    result = llm.chat_json(prompts.ATTRIBUTION_SYSTEM, user, max_tokens=16000)
    result["segments"] = _clean_segments(result.get("segments", []), last_id)
    return result


def _clean_segments(segs: list[dict], last_id: int) -> list[dict]:
    """Make segments ordered, non-overlapping and covering 1..last_id."""
    clean = []
    for s in sorted(segs, key=lambda s: int(s.get("from_id", 0))):
        kid = s.get("kid") if s.get("kid") in KID_IDS else "none"
        a = max(1, int(s.get("from_id", 1)))
        b = min(last_id, int(s.get("to_id", last_id)))
        if clean and a <= clean[-1]["to_id"]:
            a = clean[-1]["to_id"] + 1
        if a > b:
            continue
        if clean and a > clean[-1]["to_id"] + 1:
            clean[-1]["to_id"] = a - 1  # close holes by extending the previous segment
        if clean and clean[-1]["kid"] == kid:
            clean[-1]["to_id"] = b
            clean[-1]["evidence"] += s.get("evidence", [])
            continue
        clean.append({"kid": kid, "from_id": a, "to_id": b,
                      "confidence": float(s.get("confidence", 0.5)), "evidence": list(s.get("evidence", []))})
    if not clean:
        return [{"kid": "none", "from_id": 1, "to_id": last_id, "confidence": 0.0, "evidence": []}]
    clean[0]["from_id"] = 1
    clean[-1]["to_id"] = last_id
    return clean


# ---------------------------------------------------------------- summaries

def _speaker_names(attr: dict) -> dict:
    names = {"teacher": "Teacher", "mom": "Mom", "other": "Other"}
    names.update({k: v["name"] for k, v in config.KIDS.items()})
    return {key: names.get(role, role) for key, role in (attr.get("speakers") or {}).items()}


def _span_seconds(items: list[dict], a: int, b: int) -> float:
    """Wall time covered by phrases a..b (per recording: first start to last end)."""
    spans: dict[str, list[float]] = {}
    for p in timeline.phrases(items):
        if a <= p["id"] <= b:
            s = spans.setdefault(p["rec"], [p["start"], p["end"]])
            s[1] = max(s[1], p["end"])
    return sum(e - s for s, e in spans.values())


def _resolve_clip(ref, items: list[dict], durations: dict, allowed: list[tuple[int, int]],
                  max_s: float | None = MAX_CLIP_S):
    """[from_id, to_id] -> playable clip {rec, start, end, from, to} or None.

    Point clips are capped at max_s (LLMs sometimes cite a whole section as a "clip")."""
    if not isinstance(ref, (list, tuple)) or len(ref) != 2:
        return None
    try:
        a, b = sorted(int(x) for x in ref)
    except (TypeError, ValueError):
        return None
    rng = next(((lo, hi) for lo, hi in allowed if lo <= a <= hi or lo <= b <= hi), None)
    if not rng:
        return None
    a, b = max(a, rng[0]), min(b, rng[1])
    idx = {it["id"]: n for n, it in enumerate(items) if "id" in it}
    if a not in idx or b not in idx:
        return None
    first = items[idx[a]]
    last = items[idx[b]]
    if last["rec"] != first["rec"]:
        last = max((it for it in items[idx[a]:idx[b] + 1] if "id" in it and it["rec"] == first["rec"]),
                   key=lambda it: it["id"])
        b = last["id"]
    if max_s and last["end"] - first["start"] > max_s:
        last = max((it for it in items[idx[a]:idx[b] + 1] if "id" in it and it["rec"] == first["rec"]
                    and it["end"] - first["start"] <= max_s), key=lambda it: it["id"], default=first)
        b = last["id"]
    end = last["end"]
    nxt = items[idx[b] + 1] if idx[b] + 1 < len(items) else None
    if nxt and nxt.get("gap") == "playing" and nxt["rec"] == first["rec"] and nxt["end"] - nxt["start"] <= 45:
        end = nxt["end"]  # include the demo/playing right after the explanation
    dur = durations[first["rec"]]
    return {"rec": first["rec"], "start": round(max(0.0, first["start"] - 1.5), 2),
            "end": round(min(dur, end + 1.0), 2), "from": a, "to": b}


def _resolve_summary(s: dict, items, durations, ranges) -> dict:
    def rc(ref):
        return _resolve_clip(ref, items, durations, ranges)

    for f in s.get("teacher_focus", []):
        f["clips"] = [c for c in (rc(r) for r in f.get("clips", [])) if c]
    for sec in s.get("sections", []):
        sec["clip"] = _resolve_clip([sec.get("from_id"), sec.get("to_id")], items, durations, ranges, None)
        for p in sec.get("points", []):
            p["clip"] = rc(p.get("clip"))
    for key in ("homework_check", "assignments"):
        for x in s.get(key, []):
            x["clip"] = None if x.get("status") == "not_covered" else rc(x.get("clip"))
    return s


def _previous_assignments(date: str, kid: str) -> str:
    index = storage.get_json(config.DATA_CONTAINER, "index.json", {"lessons": []})
    prev = sorted((l["date"] for l in index["lessons"]
                   if l["date"] < date and kid in (l.get("kids") or {})), reverse=True)
    if not prev:
        return "(none)"
    doc = storage.get_json(config.DATA_CONTAINER, f"{prev[0]}/lesson.json") or {}
    asg = ((doc.get("kids") or {}).get(kid) or {}).get("summary", {}).get("assignments", [])
    return f"Lesson {prev[0]}:\n" + "\n".join(f"- {a.get('task')}: {a.get('details', '')}" for a in asg)


def summarize_kid(date: str, kid: str, meta: dict, items: list[dict], ranges: list[tuple[int, int]],
                  notes, images, speakers: dict, durations: dict) -> dict:
    k = config.KIDS[kid]
    transcript = "\n".join(timeline.render(items, speakers, r) for r in ranges)
    profile = storage.get_json(config.DATA_CONTAINER, f"profiles/{kid}.json") or {}
    user = prompts.SUMMARY_USER.format(
        kid_name=k["name"], age=k["age"], seed=k["seed"], instrument=meta["instrument"],
        teacher=meta["teacher"] or config.TEACHER_NAME, date=date,
        profile=json.dumps(profile, ensure_ascii=False) if profile else "(none)",
        previous=_previous_assignments(date, kid), notes=_fmt_notes(notes, kid),
        pages=_fmt_pages(images, kid),
        speakers=", ".join(sorted(set(speakers.values()))) or "unknown", transcript=transcript)
    s = llm.chat_json(prompts.SUMMARY_SYSTEM, user, max_tokens=24000)
    return _resolve_summary(s, items, durations, ranges)


def update_profile(date: str, kid: str, summary: dict) -> None:
    path = f"profiles/{kid}.json"
    prof = storage.get_json(config.DATA_CONTAINER, path) or {}
    if prof.get("updated", "") > date:
        return  # never let an older lesson overwrite a newer profile
    slim = {k: summary.get(k) for k in ("headline", "overview", "teacher_focus", "assignments", "sections")}
    for sec in slim.get("sections") or []:
        sec.pop("clip", None)
        for p in sec.get("points", []):
            p.pop("clip", None)
    new = llm.chat_json(prompts.PROFILE_SYSTEM, prompts.PROFILE_USER.format(
        profile=json.dumps(prof, ensure_ascii=False) if prof else "(none)", date=date,
        summary=json.dumps(slim, ensure_ascii=False)), max_tokens=6000)
    new["updated"] = date
    storage.put_json(config.DATA_CONTAINER, path, new)


def _update_index(doc: dict) -> None:
    index = storage.get_json(config.DATA_CONTAINER, "index.json", {"lessons": []})
    entry = {"date": doc["date"], "instrument": doc["instrument"], "teacher": doc["teacher"],
             "updated": doc["updated"],
             "kids": {k: {"minutes": v["minutes"], "headline": v["summary"].get("headline", "")}
                      for k, v in doc["kids"].items()}}
    index["lessons"] = sorted([l for l in index["lessons"] if l["date"] != doc["date"]] + [entry],
                              key=lambda l: l["date"], reverse=True)
    storage.put_json(config.DATA_CONTAINER, "index.json", index)


# ---------------------------------------------------------------- orchestrator

def process(date: str, keep_work: bool = False) -> dict:
    work = config.WORK_DIR / date
    work.mkdir(parents=True, exist_ok=True)
    try:
        set_status(date, "processing", "downloading raw files")
        files = _download_raw(date, work)
        if not files:
            raise RuntimeError("no lesson files found in raw storage")
        audios = [p for p in files if kind_of(p.name) == "audio"]
        images = [p for p in files if kind_of(p.name) == "image"]
        texts = [p for p in files if kind_of(p.name) == "text"]
        if not audios:
            raise RuntimeError("no audio recordings in this lesson folder")
        instrument, teacher = _meta_from_names([p.name for p in files])
        meta = {"instrument": instrument, "teacher": teacher}

        set_status(date, "processing", "reading photos and notes")
        image_info = _process_images(date, images, work)
        notes = [{"source": i["name"], "kid": i.get("kid", "unknown"),
                  "text": i.get("text", ""), "items": i.get("items", [])}
                 for i in image_info if i.get("kind") == "homework_notes"]
        for t in texts:
            body = t.read_text(errors="ignore")
            notes.append({"source": t.name, "kid": _kid_in_text(body), "text": body, "items": []})

        recordings, transcripts, silences = _process_audio(date, audios, work)
        items = timeline.build(recordings, transcripts, silences)
        if not timeline.phrases(items):
            raise RuntimeError("no speech recognized in the recordings")
        storage.put_json(config.DATA_CONTAINER, f"{date}/timeline.json", items)

        set_status(date, "processing", "figuring out whose lesson is when")
        attr = attribute(date, recordings, items, notes, image_info)
        speakers = _speaker_names(attr)
        durations = {r["id"]: r["duration"] for r in recordings}

        kid_ranges: dict[str, list[tuple[int, int]]] = {}
        for s in attr["segments"]:
            if s["kid"] in KID_IDS:
                kid_ranges.setdefault(s["kid"], []).append((s["from_id"], s["to_id"]))

        set_status(date, "processing", "writing lesson notes for " +
                   " and ".join(config.KIDS[k]["name"] for k in kid_ranges))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = {k: pool.submit(summarize_kid, date, k, meta, items, r, notes, image_info,
                                   speakers, durations) for k, r in kid_ranges.items()}
            summaries = {k: f.result() for k, f in futs.items()}

        kids = {}
        for k, ranges in kid_ranges.items():
            secs = sum(_span_seconds(items, a, b) for a, b in ranges)
            kids[k] = {"minutes": round(secs / 60), "ranges": ranges, "summary": summaries[k]}

        doc = {"date": date, **meta, "updated": now(), "model": config.LLM_MODEL,
               "recordings": recordings, "images": image_info, "notes": notes,
               "attribution": {**attr, "speaker_names": speakers}, "kids": kids}
        storage.put_json(config.DATA_CONTAINER, f"{date}/lesson.json", doc)
        _update_index(doc)

        set_status(date, "processing", "updating learning profiles")
        for k in kids:
            try:
                update_profile(date, k, summaries[k])
            except Exception:  # noqa: BLE001 - profile is a nice-to-have
                log.exception("profile update failed for %s", k)
        set_status(date, "ready", "done")
        return doc
    except Exception as e:
        set_status(date, "error", str(e)[:500])
        raise
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
