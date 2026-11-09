# MusicBuddy

A family music-lesson companion. Drop a dated folder with lesson recordings, the homework note
screenshot and (optionally) lesson-book photos; MusicBuddy transcribes the lesson, works out which
child is being taught when, and writes per-child study notes where every point links to the exact
clip of the teacher explaining it. A chat assistant (DeepSeek V4) answers questions grounded in all
lesson transcripts.

## How it works

```
Google Drive/Music Lesson Recording/20261107/  ->  launchd watcher (Mac, every 5 min)
   *.m4a, homework *.PNG, book photos               uploads to blob raw/20261107/ + queues a job
                                                         |
Azure Container App (FastAPI + worker thread)  <---------+
   ffmpeg -> Azure Speech fast transcription (diarized, timestamped)
   timeline with global phrase ids + "♪ playing" gaps
   DeepSeek V4 Pro: who is being taught when -> per-kid notes with clip ids -> learning profiles
   web UI: notes, tap-to-listen clips, transcript, chat, upload
```

Design docs live in the Obsidian vault: `Project/Project MusicBuddy/`.

## Layout

```
musicbuddy/
  config.py           env + family profile (kids, teacher)
  ingest.py           folder scanning, upload to blob, enqueue
  storage.py          blob / queue helpers, SAS URLs
  llm.py              DeepSeek client (JSON mode, streaming, images)
  prompts.py          all prompts
  worker.py           queue consumer
  pipeline/
    audio.py          ffmpeg transcode, silence detection
    transcribe.py     Azure Speech fast transcription
    timeline.py       phrase ids, playing/quiet gaps, prompt rendering
    run.py            the end-to-end lesson pipeline
  web/
    app.py            FastAPI routes (auth, lessons, audio, upload, chat)
    chat.py           grounded chat context
    static/           index.html, app.js, style.css (no build step)
infra/deploy.sh       ACR cloud build + Container Apps deploy (idempotent)
watcher/              launchd agent for the Google Drive folder
tests/                pytest unit tests
```

## Local setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
brew install ffmpeg
cp .env.example .env   # fill in keys
pytest -q
```

## Commands

```bash
python -m musicbuddy watch [--force]    # scan input folder once, upload + enqueue new/changed dates
python -m musicbuddy process 20261107   # run the pipeline locally for one date (raw files must be in blob)
python -m musicbuddy enqueue 20261107   # ask the cloud worker to (re)process a date
python -m musicbuddy worker             # run the queue worker in the foreground
python -m musicbuddy serve --port 8000  # run the web app locally
```

## Deploy

```bash
./infra/deploy.sh          # builds in ACR and updates the Container App; prints the URL
./watcher/install.sh       # installs the Mac folder watcher (launchd)
```

## Input folder conventions
- One folder per lesson date: `YYYYMMDD` (or `YYYY-MM-DD`).
- Recordings: any of m4a/mp3/wav/aac/caf/mp4/mov. Name them so they sort in order, e.g. `20261107-violin-coleman-p1.m4a`, `...-p2.m4a`. The instrument and teacher are read from the name when present.
- Photos: png/jpg/heic. Homework screenshots and lesson-book pages are told apart automatically.
- Text notes: `.txt` / `.md`.
- The watcher waits until files have stopped changing for 3 minutes, and re-processes a date if its files change.
