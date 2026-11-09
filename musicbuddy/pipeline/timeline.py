"""Unified lesson timeline: phrases across recordings with stable ids and music markers."""


def fmt_ts(s: float) -> str:
    s = int(max(s, 0))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def build(recordings: list[dict], transcripts: dict[str, list[dict]],
          silences: dict[str, list[tuple[float, float]]]) -> list[dict]:
    """Return a flat list of timeline items ordered by recording then time.

    Speech items: {id, rec, start, end, speaker, text}
    Gap items (no id): {rec, start, end, gap: "playing"|"quiet"} for >= 5s without speech.
    """
    items: list[dict] = []
    pid = 0
    for rec in recordings:
        rid = rec["id"]
        sil = silences.get(rid, [])
        prev_end = 0.0
        for p in transcripts.get(rid, []):
            _add_gap(items, rid, prev_end, p["start"], sil)
            pid += 1
            items.append({"id": pid, "rec": rid, "start": p["start"], "end": p["end"],
                          "speaker": p["speaker"], "text": p["text"]})
            prev_end = max(prev_end, p["end"])
        _add_gap(items, rid, prev_end, rec["duration"], sil)
    return items


def _add_gap(items, rid, a, b, sil):
    if b - a < 5:
        return
    quiet = sum(max(0.0, min(b, e) - max(a, s)) for s, e in sil)
    items.append({"rec": rid, "start": round(a, 2), "end": round(b, 2),
                  "gap": "quiet" if quiet / (b - a) > 0.6 else "playing"})


def phrases(items: list[dict]) -> list[dict]:
    return [i for i in items if "id" in i]


def render(items: list[dict], speaker_names: dict | None = None,
           id_range: tuple[int, int] | None = None) -> str:
    """Compact text form for LLM prompts. speaker_names maps 'R1:S3' -> 'Teacher'."""
    lines = []
    lo, hi = id_range or (0, 10**9)
    last_id = 0
    for it in items:
        if "id" in it:
            last_id = it["id"]
            if not lo <= it["id"] <= hi:
                continue
            key = f"{it['rec']}:{it['speaker']}"
            who = (speaker_names or {}).get(key, it["speaker"])
            lines.append(f"#{it['id']} {it['rec']} {fmt_ts(it['start'])} {who}: {it['text']}")
        elif lo <= last_id + 1 and last_id <= hi:
            dur = it["end"] - it["start"]
            label = "♪ instrument playing / demo" if it["gap"] == "playing" else "… quiet"
            lines.append(f"    [{it['rec']} {fmt_ts(it['start'])}-{fmt_ts(it['end'])} {label}, {dur:.0f}s]")
    return "\n".join(lines)
