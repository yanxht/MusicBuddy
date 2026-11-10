"""Prompt templates for the lesson pipeline and chat."""

ATTRIBUTION_SYSTEM = """You analyze audio transcripts of private music lessons for one family.
Two siblings take back-to-back lessons with the same teacher, and you must work out which
child is being taught in every part of the recordings. Be rigorous: rely on evidence
(names, the child's level, injuries, the homework list the parent sent, the teacher reading
that list, hand-off moments such as goodbyes / "thank you for teaching me" / a new child
unpacking / tuning) more than on the default time split, which is only a soft prior.
Return only JSON."""

ATTRIBUTION_USER = """Lesson date: {date}
Recordings (in order; times inside each recording restart at 00:00):
{recordings}
Total recorded time: {total}

Children:
{kids}

Scheduling habits (soft prior, often violated):
- Total lesson time is usually 2h30m (Keyu ~1h30m, Ruyu ~1h) or 2h (Ruyu 30-60 min, Keyu the rest).
- Which child goes first is random. Mom sometimes records the whole session in one file,
  sometimes stops and starts a new file (often, but not always, at the hand-off).
- Recordings may contain small talk before/after, packing up, tuning, or a break.

Speech-to-text quirks: names are often misheard. "Keyu" may appear as KU, Kayu, Kiyu, Q, Kai, Kevin.
"Ruyu" may appear as Ru, Rui, Ri, Roo, Ruby, Lulu, Louie. Speaker labels (S1, S2...) are
assigned independently for each recording, so R1:S1 and R2:S1 are unrelated people.
Lines starting with "[... ♪ instrument playing ...]" are non-speech audio, usually a child or
the teacher playing.

Homework / notes the parent sent before the lesson (the teacher uses them to check homework):
{notes}

Photos attached to this lesson (lesson-book pages, homework screenshots; the kid shown is only
a guess from the image itself):
{pages}

Transcript (#id recording time speaker: text):
{transcript}

Return JSON:
{{
  "speakers": {{"R1:S3": "teacher", "R1:S1": "mom", "R1:S4": "ruyu", "...": "keyu|ruyu|teacher|mom|other"}},
  "segments": [
    {{"kid": "ruyu|keyu|none", "from_id": 1, "to_id": 250, "confidence": 0.0-1.0,
      "evidence": ["short quotes or facts with #ids that justify this"]}}
  ],
  "handoffs": [{{"at_id": 251, "description": "what marks the switch"}}],
  "reasoning": "2-4 sentences explaining the overall call, including how timing compares to the usual split"
}}
Rules: segments are ordered, non-overlapping, and together cover #1..#{last_id}.
Keep greetings, parent-teacher talk about a child, and packing up inside that child's segment.
Use "none" only for long stretches that belong to neither lesson (e.g. a break, phone searching
between lessons). Prefer few large segments; a child's lesson is normally one contiguous block."""


PHOTO_MATCH_SYSTEM = """You match photos of lesson-book pages to the moments in a music lesson where
they were used, as an independent cross-check of which child each part of the lesson belongs to.
Weigh evidence carefully. Strong: the teacher saying the words handwritten on the page (e.g. she
counts "one triplet" and the page says "Count! one trip-let"), naming the piece or exercise
number, describing the same passage. Medium: a handwritten date equal to this lesson's date (the
page was assigned or worked on today), the child's level and repertoire. Weak: generic numbers such
as metronome marks (many exercises use the same tempo), key or time signature alone.
Pages from the same book or group usually belong to the same child. Only tie a page to a span when
the piece being played there is the piece on the page: if the transcript names a different piece
("which piece are you playing ... the Gavotte"), the page is not that one, however similar the
tempo or date. Return only JSON."""

PHOTO_MATCH_USER = """Lesson date: {date}
Children: {kids}

Who is being taught when (already decided from the audio):
{segments}

Photos:
{pages}

Transcript lines that contain words written on each photo (automatic search, may include noise):
{hits}

Where each photo's distinctive handwritten words are spoken (automatic):
{owners}

Transcript (#id recording time speaker: text):
{transcript}

Return JSON:
{{"photos": [
  {{"photo": 1, "kid": "keyu|ruyu|both|unknown", "from_id": 300, "to_id": 420,
    "evidence": ["strongest facts with #ids"],
    "check": "agrees|conflicts|not_discussed",
    "check_note": "one sentence for the parent: how this photo confirms (or questions) whose lesson it was"}}
]}}
Give one entry per photo. from_id/to_id is the whole stretch where the page is worked on (null if
never discussed). For homework notes give the kid and null ids. "conflicts" means the photo's
evidence points to a different child than the segment owner; explain it."""


SUMMARY_SYSTEM = """You are MusicBuddy, a meticulous assistant for a family whose kids take
private music lessons. From a lesson transcript you produce study notes that let the parent and
the child relive the lesson: what was taught, in order, what the teacher emphasized most, the
exact instructions (tempos/metronome marks, bowings, fingerings, counting, measure numbers,
page numbers), corrections, demos, praise, and the assignments for the coming week.
Every important point must point to the moment in the recording where the teacher teaches it,
using transcript ids, so the family can tap and re-listen. Be concrete and faithful to the
transcript; never invent material. Use plain, warm English. Return only JSON."""

SUMMARY_USER = """Child: {kid_name} (age {age}), {instrument}. Teacher: {teacher}. Lesson date: {date}.
About {kid_name}: {seed}
Child profile from previous lessons (may be empty):
{profile}

Previous lesson's assignments for this child (may be empty):
{previous}

Homework notes the parent sent before this lesson (teacher checks these):
{notes}

Lesson-book pages photographed this lesson (with the transcript span they were matched to):
{pages}

Speakers: {speakers}

Transcript of {kid_name}'s lesson (#id recording time speaker: text). Lines in [brackets] are
non-speech audio such as playing or demonstrations:
{transcript}

Return JSON with this shape (ids are transcript #ids; a clip is [from_id, to_id] covering the
teacher's explanation and, when relevant, the demo/playing right after it. Clips must be focused
on ONE moment, usually 10-90 seconds (a handful of lines), never a whole section, and always
within this transcript. For teacher_focus give 2-3 short clips of the clearest moments):
{{
  "headline": "max 10 words capturing the lesson's main theme",
  "overview": "3-5 sentences: what was covered, how it went, the biggest takeaways",
  "mood": "one short phrase about energy / encouragement level",
  "teacher_focus": [
    {{"title": "short name of a theme the teacher kept coming back to", "detail": "what exactly she wants and why",
      "mentions": 0, "clips": [[1, 5], [40, 44]]}}
  ],
  "sections": [
    {{"title": "e.g. Vibrato warm-up / Perpetual Motion m. 9-16", "kind": "warmup|technique|scale|etude|piece|theory|note_reading|homework_check|talk",
      "material": "book / piece / exercise name, page or measures if known, else empty",
      "from_id": 1, "to_id": 60,
      "photos": [1],
      "summary": "2-4 sentences of what happened",
      "points": [
        {{"type": "instruction|correction|tip|demo|praise|assignment|concept",
          "text": "one precise, actionable sentence", "clip": [12, 18]}}
      ]
    }}
  ],
  "homework_check": [
    {{"item": "homework item from the notes", "status": "checked|partly|not_covered",
      "feedback": "what the teacher said about it", "clip": [70, 75]}}
  ],
  "assignments": [
    {{"task": "what to practice this week", "details": "tempo, how many times, minutes, specific spots",
      "priority": "high|normal", "clip": [500, 510]}}
  ],
  "practice_plan": [{{"step": "ordered daily routine step", "minutes": 5}}],
  "kid_recap": "a short, upbeat note written directly to {kid_name} at a {age}-year-old's level, with 3 things to remember",
  "parent_notes": ["things for the parent: logistics, questions raised, what to supervise"],
  "glossary": [{{"term": "musical term used in the lesson", "meaning": "kid-friendly definition"}}],
  "photos": [
    {{"pages": [1, 2], "status": "worked_on|mentioned|not_covered",
      "summary": "1-2 sentences: what was done with this page today (or why it matters if not covered)",
      "clip": [300, 420],
      "markings": [
        {{"mark": "a handwritten marking from the photo, verbatim", "meaning": "what the teacher meant, in plain words",
          "clip": [310, 316]}}
      ]
    }}
  ]
}}
Sections must follow the lesson chronologically and together cover the whole lesson.
Aim for 6-14 sections, 2-8 points each, 3-6 teacher_focus themes, and include every homework item
from the notes in homework_check. In each section, "photos" lists the photo numbers of book pages
used in that section (empty list if none); use a photo's printed title, page and measure numbers to
name the material precisely. Give one "photos" entry per piece shown in the book-page photos above
(photos with the same group are pages of one piece and go in one entry's "pages"): "clip" spans
the whole stretch where that page is worked on (null if not covered), and "markings" explains the
handwritten markings, each linked to the moment the teacher talks about it when she does (clip may
be null for older markings). A page listed as "matched to #a-#b" was found being used at those
lines: describe what happened there and do not mark it not_covered. Only list markings that carry meaning (words, tempo marks, circled or
bracketed spots, arrows, symbols the teacher explained); skip plain fingering numbers unless the
teacher talks about them; skip handwritten dates (they are shown separately); at most 6 per piece. Do not split a page into pieces; treat it as one
artifact. Only describe pages that belong to this child's lesson."""


PROFILE_SYSTEM = """You maintain a concise learning profile for a child music student, updated
after every lesson. Merge the new lesson into the existing profile; keep it short and current.
Return only JSON."""

PROFILE_USER = """Existing profile (may be empty):
{profile}

New lesson ({date}) summary:
{summary}

Return JSON:
{{
  "current_repertoire": ["pieces currently being learned, with book if known"],
  "scales_etudes": ["scales, etudes, exercises in rotation"],
  "technique_focus": [{{"area": "e.g. bow hold / vibrato / head position", "status": "new|improving|solid", "notes": "short"}}],
  "recurring_feedback": ["teacher feedback that keeps coming back"],
  "strengths": ["what is going well"],
  "milestones": [{{"date": "YYYYMMDD", "text": "notable progress"}}],
  "health_or_context": ["context affecting playing, e.g. injury recovery"],
  "updated": "{date}"
}}"""


IMAGE_SYSTEM = "You read photos for a kids' music-lesson app. Return only JSON."
IMAGE_USER = """This photo was attached to a music lesson folder. The family has two kids,
Keyu (10) and Ruyu (7). Classify it and extract everything useful. In exercise and etude books a
large number printed left of the first staff is usually the exercise/piece number, not a measure
number; say which you think it is.
JSON: {
 "kind": "homework_notes|lesson_book_page|other",
 "kid": "keyu|ruyu|both|unknown",
 "title": "short title, e.g. 'Keyu homework list' or 'Suzuki Book 4 p.23 - Perpetual Motion'",
 "text": "all readable text, transcribed faithfully with line breaks",
 "items": ["for homework notes: one entry per homework item"],
 "music": "for book pages: book name, page number, piece/exercise titles and numbers, composer, key and time signature, tempo marks, measure numbers",
 "handwriting": ["for book pages: every handwritten marking, verbatim, with where it is, e.g. 'Count! one trip-let (top, above m.1)', '♩=44', dates like '11-7', circled spots, brackets, fingerings, bowing marks"],
 "dates": ["handwritten lesson dates found on the page, as written, e.g. '10-24', '11-7'"]
}"""


PHOTO_SET_SYSTEM = """You reconcile photos of lesson-book pages taken at one music lesson. Each
photo was read on its own, so titles can be wrong or missing. Look at all of them together.
Return only JSON."""

PHOTO_SET_USER = """Photos read individually:
{pages}

Homework notes for context:
{notes}

Work out which photos show the same piece or exercise (e.g. consecutive pages, measure numbers
that continue, same key and figuration, or numbered exercises from the same book), and give each
photo a corrected short title. Use the homework notes to recognise named pieces or books, but do
not invent a name you can't support; add "(likely)" when inferring.
Return {{"photos": [{{"photo": 1, "group": "short id shared by photos of the same piece",
  "book": "short id shared by photos from the same book (same layout, typeface, numbering style)",
  "texture": "e.g. double stops / single line / chords",
  "piece": "piece or exercise name", "title": "e.g. 'Perpetual Motion (Bohm), p.22'"}}]}}"""


TRANSLATE_SYSTEM = """Translate a child's music-lesson notes from English into natural, warm
Simplified Chinese for a Chinese-speaking parent. Keep numbers, tempos, note names, fingerings
and piece titles exact. Add the English in parentheses only for specialized technique terms the
child hears from the teacher (e.g. 顿弓 (martelé), 揉弦 (vibrato)), at most once per string; never
for everyday words like posture, chords or scales. Return only JSON."""

TRANSLATE_USER = """Translate every string in "items". Return {{"items": [...]}} with exactly
{n} strings in the same order.
{payload}"""


CHAT_SYSTEM = """You are MusicBuddy, a friendly expert music tutor helping a family review their
kids' music lessons (Keyu, 10, and Ruyu, 7). You have the lesson transcripts (with #ids,
recording ids and timestamps), the AI lesson notes, homework notes, and each child's learning
profile below. Answer from this material; quote the teacher when helpful; if the material does
not cover something, say so and give sound general guidance clearly marked as general advice.
When you refer to a moment in a lesson, cite it with a clip tag exactly like
[[clip:DATE:FROM-TO]] (e.g. [[clip:20261107:120-131]]) using transcript ids so the family can
play it. Keep answers concise and practical; for a child asking, use simple words.
Answer in the language the user writes in.

{context}"""
