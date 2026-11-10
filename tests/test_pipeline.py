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


def test_resolve_clip_caps_long_point_clips():
    it = items()
    durs = {"R1": 100.0, "R2": 60.0}
    capped = run._resolve_clip([1, 3], it, durs, [(1, 5)], max_s=10)
    assert capped["to"] == 2  # phrase 3 ends 31s after phrase 1 starts
    whole = run._resolve_clip([1, 3], it, durs, [(1, 5)], max_s=None)
    assert whole["to"] == 3


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


def photos():
    return [
        {"kind": "homework_notes", "kid": "keyu", "blob": "d/images/img1.jpg", "title": "notes"},
        {"kind": "lesson_book_page", "kid": "unknown", "blob": "d/images/abc123.jpg", "title": "No. 10",
         "music": "Scherzando", "handwriting": ["Count! one trip-let"], "dates": ["11-7"]},
        {"kind": "lesson_book_page", "kid": "unknown", "blob": "d/images/def456.jpg", "title": "Perpetual Motion"},
    ]


SEGS = {"segments": [{"kid": "ruyu", "from_id": 1, "to_id": 3}, {"kid": "keyu", "from_id": 4, "to_id": 5}]}


def test_photo_attribution_uses_span_owner_and_keeps_check():
    imgs = photos()
    attr = {**SEGS, "photos": [
        {"photo": 2, "kid": "ruyu", "from_id": "5", "to_id": 4, "check": "agrees", "check_note": "dated 11-7"},
        {"photo": 3, "kid": "Keyu", "from_id": None, "to_id": None, "check": "not_discussed"},
        {"photo": 9, "kid": "keyu"},
    ]}
    run._apply_photo_attribution(imgs, attr, 5)
    assert imgs[1]["kid"] == "keyu" and imgs[1]["span"] == [4, 5]  # span owner beats the stated kid
    assert imgs[1]["check"] == "agrees"
    assert imgs[2]["kid"] == "keyu" and "span" not in imgs[2]


def test_fmt_pages_numbers_and_handwriting():
    txt = run._fmt_pages(photos(), books_only=True)
    assert "[photo 2]" in txt and "[photo 1]" not in txt
    assert "Count! one trip-let" in txt and "11-7" in txt


def test_attach_section_photos_maps_numbers_and_falls_back_to_overlap():
    imgs = photos()
    imgs[1].update(kid="keyu", span=[4, 5])
    imgs[2].update(kid="keyu", span=[1, 2])
    s = {"sections": [{"from_id": 1, "to_id": 3, "photos": ["3"]}, {"from_id": 4, "to_id": 5, "photos": []}]}
    run._attach_section_photos(s, imgs, "keyu")
    assert s["sections"][0]["photos"] == ["def456"]
    assert s["sections"][1]["photos"] == ["abc123"]


def test_resolve_photo_notes():
    it = items()
    durs = {"R1": 100.0, "R2": 60.0}
    s = {"photos": [{"photo": 2, "status": "worked_on", "clip": [1, 3],
                     "markings": [{"mark": "Count!", "meaning": "count aloud", "clip": [1, 1]}, {"mark": ""}]},
                    {"photo": 7}]}
    run._resolve_photo_notes(s, photos(), it, durs, [(1, 5)])
    assert len(s["photos"]) == 1
    p = s["photos"][0]
    assert p["key"] == "abc123" and p["clip"]["to"] == 3  # page clip is not capped
    assert [m["mark"] for m in p["markings"]] == ["Count!"]


def test_resolve_photo_notes_groups_pages():
    s = {"photos": [{"pages": [2, "3", 3, 99], "status": "not_covered", "clip": None}]}
    run._resolve_photo_notes(s, photos(), items(), {"R1": 100.0, "R2": 60.0}, [(1, 5)])
    assert s["photos"][0]["keys"] == ["abc123", "def456"] and s["photos"][0]["clip"] is None


def test_group_members_inherit_kid_and_other_kids_pages_are_hidden():
    imgs = photos()
    imgs[1]["group"] = imgs[2]["group"] = "mds"
    attr = {**SEGS, "photos": [{"photo": 2, "from_id": 4, "to_id": 5, "check": "agrees"},
                               {"photo": 3, "kid": "unknown", "check": "not_discussed"}]}
    run._apply_photo_attribution(imgs, attr, 5)
    assert imgs[2]["kid"] == "keyu"
    assert "[photo 2]" not in run._fmt_pages(imgs, "ruyu", books_only=True)
    s = {"photos": [{"pages": [2, 3]}]}
    run._resolve_photo_notes(s, imgs, items(), {"R1": 100.0, "R2": 60.0}, [(1, 3)], "ruyu")
    assert s["photos"] == []


def test_photo_keyword_hits_find_handwritten_words_in_transcript():
    imgs = [{"kind": "lesson_book_page", "handwriting": ["Count! one trip-let (top, orange ink)"], "piece": ""}]
    it = items()
    next(i for i in it if i.get("id") == 4)["text"] = "Count it: one triplet, two triplet."
    txt = run._photo_keyword_hits(imgs, it, SEGS["segments"])
    assert "'triplet' -> #4 (keyu)" in txt and "orange" not in txt


def test_keyword_owner_overrides_wrong_kid():
    imgs = [{"kind": "lesson_book_page", "handwriting": ["Count! one trip-let"]}]
    it = items()
    for pid in (3, 4, 5):
        next(i for i in it if i.get("id") == pid)["text"] = "one triplet two triplet"
    segs = [{"kid": "ruyu", "from_id": 1, "to_id": 2}, {"kid": "keyu", "from_id": 3, "to_id": 5}]
    owners = run._photo_keyword_owners(imgs, it, segs)
    assert owners[1]["kid"] == "keyu" and owners[1]["word"] == "triplet"
    photos = [{"photo": 1, "kid": "ruyu", "from_id": 1, "to_id": 2, "check": "agrees"}]
    run._enforce_keyword_owners(photos, owners)
    assert photos[0]["kid"] == "keyu" and (photos[0]["from_id"], photos[0]["to_id"]) == (3, 5)


def test_keyword_owner_needs_one_kid_and_three_lines():
    imgs = [{"kind": "lesson_book_page", "handwriting": ["triplet"]}]
    it = items()
    for pid in (2, 4, 5):
        next(i for i in it if i.get("id") == pid)["text"] = "one triplet"
    segs = [{"kid": "ruyu", "from_id": 1, "to_id": 3}, {"kid": "keyu", "from_id": 4, "to_id": 5}]
    assert run._photo_keyword_owners(imgs, it, segs) == {}


def test_matched_page_never_reported_untouched():
    imgs = photos()
    imgs[1].update(kid="keyu", span=[2, 3])
    s = {"photos": [{"pages": [2], "status": "not_covered", "clip": None}]}
    run._resolve_photo_notes(s, imgs, items(), {"R1": 100.0, "R2": 60.0}, [(1, 5)], "keyu")
    assert s["photos"][0]["status"] == "mentioned" and s["photos"][0]["clip"]["from"] == 2


def test_profile_before_ignores_this_lessons_own_output(monkeypatch):
    blobs = {"profiles/ruyu.json": {"updated": "20261107", "current_repertoire": ["wrong"]}}
    monkeypatch.setattr(run.storage, "get_json", lambda c, name, default=None: blobs.get(name, default))
    assert run.profile_before("ruyu", "20261107") == {}
    blobs["profiles/ruyu/before-20261107.json"] = {"current_repertoire": ["Gavotte"]}
    assert run.profile_before("ruyu", "20261107") == {"current_repertoire": ["Gavotte"]}
    assert run.profile_before("ruyu", "20261114")["current_repertoire"] == ["wrong"]
