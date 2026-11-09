from musicbuddy import ingest
from musicbuddy.pipeline import run, timeline

RECS = [{"id": "R1", "duration": 100.0}, {"id": "R2", "duration": 60.0}]
TRANSCRIPTS = {
    "R1": [{"start": 1, "end": 3, "speaker": "S1", "text": "hi"},
           {"start": 4, "end": 6, "speaker": "S1", "text": "play it"},
           {"start": 30, "end": 32, "speaker": "S1", "text": "good"}],
    "R2": [{"start": 2, "end": 4, "speaker": "S1", "text": "your turn"},
           {"start": 5, "end": 7, "speaker": "S2", "text": "ok"}],
}


def items(silences=None):
    return timeline.build(RECS, TRANSCRIPTS, silences or {})


def test_build_assigns_global_ids_and_gaps():
    it = items({"R1": [(6.0, 10.0)]})
    ids = [i["id"] for i in it if "id" in i]
    assert ids == [1, 2, 3, 4, 5]
    gaps = [i for i in it if "gap" in i]
    # 6..30 mostly not silent -> playing; tail 32..100 -> playing (no silences given)
    assert gaps[0]["gap"] == "playing" and gaps[0]["start"] == 6
    assert any(g["rec"] == "R2" for g in gaps)


def test_quiet_gap_detection():
    it = items({"R1": [(6.0, 30.0)]})
    assert next(i for i in it if "gap" in i)["gap"] == "quiet"


def test_render_range_and_names():
    txt = timeline.render(items(), {"R1:S1": "Teacher"}, (2, 3))
    assert "#1 " not in txt and "#2 R1 00:04 Teacher: play it" in txt and "#4" not in txt


def test_clean_segments_fills_and_merges():
    segs = run._clean_segments([
        {"kid": "ruyu", "from_id": 1, "to_id": 2},
        {"kid": "ruyu", "from_id": 3, "to_id": 3},
        {"kid": "keyu", "from_id": 5, "to_id": 9},
        {"kid": "bogus", "from_id": 4, "to_id": 4},
    ], 10)
    assert [(s["kid"], s["from_id"], s["to_id"]) for s in segs] == [
        ("ruyu", 1, 3), ("none", 4, 4), ("keyu", 5, 10)]


def test_clean_segments_overlap():
    segs = run._clean_segments([{"kid": "ruyu", "from_id": 1, "to_id": 6},
                                {"kid": "keyu", "from_id": 4, "to_id": 9}], 9)
    assert [(s["from_id"], s["to_id"]) for s in segs] == [(1, 6), (7, 9)]


def test_resolve_clip_pads_and_includes_short_demo():
    it = items()
    durs = {"R1": 100.0, "R2": 60.0}
    c = run._resolve_clip([2, 2], it, durs, [(1, 5)])
    # gap 6..30 is 24s of playing -> included
    assert c == {"rec": "R1", "start": 2.5, "end": 31.0, "from": 2, "to": 2}


def test_resolve_clip_stays_in_one_recording_and_range():
    it = items()
    durs = {"R1": 100.0, "R2": 60.0}
    c = run._resolve_clip([3, 5], it, durs, [(1, 5)])
    assert c["rec"] == "R1" and c["to"] == 3
    assert run._resolve_clip([4, 5], it, durs, [(1, 3)]) is None
    assert run._resolve_clip("bad", it, durs, [(1, 5)]) is None


def test_span_seconds():
    assert run._span_seconds(items(), 1, 3) == 31
    assert run._span_seconds(items(), 3, 5) == (32 - 30) + (7 - 2)


def test_ingest_helpers():
    assert ingest.date_id("20261107") == "20261107"
    assert ingest.date_id("2026-11-07") == "20261107"
    assert ingest.date_id("notes") is None
    assert ingest.kind_of("a.M4A") == "audio" and ingest.kind_of("b.PNG") == "image"
    assert ingest.kind_of("c.pdf") is None


def test_meta_from_names():
    assert run._meta_from_names(["20261107-violin-coleman-p1.m4a"]) == ("violin", "Coleman")
    assert run._meta_from_names(["x.m4a"]) == ("violin", "")
