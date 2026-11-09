"""FastAPI web app: lesson notes, audio clips, chat, and uploads (passcode protected)."""
import hmac
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from .. import config, ingest, storage
from . import chat, translate

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
COOKIE = "mb_session"
SESSION_DAYS = 90
DATE_RE = re.compile(r"^\d{8}$")
REC_RE = re.compile(r"^R\d{1,2}$")
KEY_RE = re.compile(r"^[A-Za-z0-9]{1,20}$")
MAX_UPLOAD_BYTES = 600 * 1024 * 1024

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    if os.getenv("MB_RUN_WORKER", "0") == "1":
        from .. import worker
        worker.start_background()
    yield


app = FastAPI(title="MusicBuddy", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_signer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="mb-session")
_attempts: dict[str, deque] = defaultdict(deque)
_attempt_lock = threading.Lock()


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https://*.blob.core.windows.net; "
        "media-src 'self' https://*.blob.core.windows.net; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'")
    return resp


# ---------------------------------------------------------------- auth

def require_auth(request: Request) -> None:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "login required")
    try:
        _signer.loads(token, max_age=SESSION_DAYS * 86400)
    except BadSignature:
        raise HTTPException(401, "login required") from None


class Login(BaseModel):
    passcode: str


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    # The ingress proxy appends the real client address last; earlier entries are client-supplied.
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[-1].strip()
    with _attempt_lock:
        q = _attempts[ip]
        while q and q[0] < time.time() - 300:
            q.popleft()
        if len(q) >= 8:
            raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
        q.append(time.time())
    if not config.PASSCODE or not hmac.compare_digest(body.passcode.strip().lower(), config.PASSCODE.lower()):
        raise HTTPException(401, "Wrong passcode")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, _signer.dumps({"v": 1}), max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=secure, samesite="lax")
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me", dependencies=[Depends(require_auth)])
def me():
    return {"ok": True, "kids": {k: {"name": v["name"], "age": v["age"]} for k, v in config.KIDS.items()}}


# ---------------------------------------------------------------- lessons

def _check_date(date: str) -> str:
    if not DATE_RE.match(date):
        raise HTTPException(400, "bad date")
    return date


@app.get("/api/lessons", dependencies=[Depends(require_auth)])
def lessons():
    index = storage.get_json(config.DATA_CONTAINER, "index.json", {"lessons": []})
    statuses = {}
    for b in storage.container(config.DATA_CONTAINER).list_blobs():
        if b.name.endswith("/status.json") and DATE_RE.match(b.name.split("/")[0]):
            st = storage.get_json(config.DATA_CONTAINER, b.name) or {}
            if st.get("state") != "ready":
                statuses[st.get("date", b.name[:8])] = st
    return {"lessons": index["lessons"], "pending": sorted(statuses.values(), key=lambda s: s["date"], reverse=True)}


@app.get("/api/lessons/{date}", dependencies=[Depends(require_auth)])
def lesson(date: str):
    doc = storage.get_json(config.DATA_CONTAINER, f"{_check_date(date)}/lesson.json")
    if not doc:
        raise HTTPException(404, "lesson not found")
    doc["status"] = storage.get_json(config.DATA_CONTAINER, f"{date}/status.json")
    return doc


@app.get("/api/lessons/{date}/status", dependencies=[Depends(require_auth)])
def lesson_status(date: str):
    return storage.get_json(config.DATA_CONTAINER, f"{_check_date(date)}/status.json") or {}


@app.get("/api/lessons/{date}/timeline", dependencies=[Depends(require_auth)])
def lesson_timeline(date: str):
    items = storage.get_json(config.DATA_CONTAINER, f"{_check_date(date)}/timeline.json")
    if items is None:
        raise HTTPException(404, "timeline not found")
    return items


@app.get("/api/lessons/{date}/audio/{rid}", dependencies=[Depends(require_auth)])
def lesson_audio(date: str, rid: str):
    if not REC_RE.match(rid):
        raise HTTPException(400, "bad recording id")
    name = f"{_check_date(date)}/audio/{rid}.mp3"
    if not storage.exists(config.DATA_CONTAINER, name):
        raise HTTPException(404, "audio not found")
    return RedirectResponse(storage.sas_url(config.DATA_CONTAINER, name), status_code=307)


@app.get("/api/lessons/{date}/images/{key}", dependencies=[Depends(require_auth)])
def lesson_image(date: str, key: str):
    if not KEY_RE.match(key):
        raise HTTPException(400, "bad image id")
    name = f"{_check_date(date)}/images/{key}.jpg"
    if not storage.exists(config.DATA_CONTAINER, name):
        raise HTTPException(404, "image not found")
    return RedirectResponse(storage.sas_url(config.DATA_CONTAINER, name), status_code=307)


class Checks(BaseModel):
    done: list[int]


def _checks_path(date: str, kid: str) -> str:
    if kid not in config.KIDS:
        raise HTTPException(404, "unknown kid")
    return f"{_check_date(date)}/checks/{kid}.json"


@app.get("/api/lessons/{date}/kids/{kid}/checks", dependencies=[Depends(require_auth)])
def get_checks(date: str, kid: str):
    return storage.get_json(config.DATA_CONTAINER, _checks_path(date, kid)) or {"done": []}


@app.put("/api/lessons/{date}/kids/{kid}/checks", dependencies=[Depends(require_auth)])
def put_checks(date: str, kid: str, body: Checks):
    done = sorted({i for i in body.done if 0 <= i < 100})
    data = {"done": done, "updated": datetime.now(timezone.utc).isoformat()}
    storage.put_json(config.DATA_CONTAINER, _checks_path(date, kid), data)
    return data


@app.get("/api/lessons/{date}/kids/{kid}/zh", dependencies=[Depends(require_auth)])
def lesson_zh(date: str, kid: str):
    if kid not in config.KIDS:
        raise HTTPException(404, "unknown kid")
    try:
        zh = translate.get_zh(_check_date(date), kid)
    except Exception as e:  # noqa: BLE001
        log.exception("translation failed")
        raise HTTPException(502, "translation failed, please retry") from e
    if zh is None:
        raise HTTPException(404, "lesson not found")
    return zh


@app.post("/api/lessons/{date}/reprocess", dependencies=[Depends(require_auth)])
def reprocess(date: str):
    _check_date(date)
    if not storage.exists(config.RAW_CONTAINER, f"{date}/manifest.json"):
        raise HTTPException(404, "no raw files for this date")
    storage.put_json(config.DATA_CONTAINER, f"{date}/status.json",
                     {"date": date, "state": "queued", "step": "waiting for worker",
                      "updated": datetime.now(timezone.utc).isoformat()})
    storage.enqueue(date, "reprocess")
    return {"ok": True}


@app.get("/api/profiles/{kid}", dependencies=[Depends(require_auth)])
def profile(kid: str):
    if kid not in config.KIDS:
        raise HTTPException(404, "unknown kid")
    return storage.get_json(config.DATA_CONTAINER, f"profiles/{kid}.json") or {}


# ---------------------------------------------------------------- upload

@app.post("/api/upload", dependencies=[Depends(require_auth)])
async def upload(date: str = Form(...), files: list[UploadFile] = File(...), notes: str = Form("")):
    did = ingest.date_id(date)
    if not did:
        raise HTTPException(400, "date must look like 2026-11-07")
    saved = []
    for f in files:
        name = Path(f.filename or "").name
        if not name or name.startswith(".") or not ingest.kind_of(name):
            raise HTTPException(400, f"unsupported file: {name or '?'}")
        storage.container(config.RAW_CONTAINER).upload_blob(
            f"{did}/{name}", f.file, overwrite=True, max_concurrency=4)
        saved.append(name)
    if notes.strip():
        name = "homework-notes.txt"
        storage.container(config.RAW_CONTAINER).upload_blob(f"{did}/{name}", notes.encode(), overwrite=True)
        saved.append(name)
    blobs = [b for b in storage.list_blobs(config.RAW_CONTAINER, f"{did}/") if ingest.kind_of(b.name)]
    if any(b.size > MAX_UPLOAD_BYTES for b in blobs):
        raise HTTPException(413, "file too large")
    storage.put_json(config.RAW_CONTAINER, f"{did}/manifest.json", {
        "date": did, "fingerprint": "web-" + datetime.now(timezone.utc).isoformat(), "source": "web upload",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"name": b.name.split("/", 1)[1], "kind": ingest.kind_of(b.name), "size": b.size} for b in blobs]})
    storage.put_json(config.DATA_CONTAINER, f"{did}/status.json",
                     {"date": did, "state": "queued", "step": "uploaded, waiting for worker",
                      "updated": datetime.now(timezone.utc).isoformat()})
    storage.enqueue(did, "web-upload")
    return {"ok": True, "date": did, "files": saved}


# ---------------------------------------------------------------- chat

class ChatMsg(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    messages: list[ChatMsg]
    date: str | None = None
    kid: str | None = None


@app.post("/api/chat", dependencies=[Depends(require_auth)])
def chat_endpoint(req: ChatReq):
    if req.date:
        _check_date(req.date)
    if req.kid and req.kid not in config.KIDS:
        raise HTTPException(400, "unknown kid")
    msgs = [{"role": m.role, "content": m.content[:4000]} for m in req.messages[-20:]
            if m.role in ("user", "assistant") and m.content.strip()]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "last message must be from the user")
    return StreamingResponse(chat.answer(msgs, req.date, req.kid), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- pages

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
