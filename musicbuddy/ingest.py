"""Watch the input folder for new date folders, upload raw files, enqueue processing."""
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, storage

log = logging.getLogger(__name__)

AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".flac", ".ogg", ".opus", ".mp4", ".mov", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp"}
TEXT_EXT = {".txt", ".md"}
DATE_DIR = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")
STABLE_AFTER_S = 180  # wait for cloud-drive sync to settle before uploading


def kind_of(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    return None


def date_id(folder_name: str) -> str | None:
    m = DATE_DIR.match(folder_name.strip())
    return "".join(m.groups()) if m else None


def lesson_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and not p.name.startswith(".") and kind_of(p.name))


def fingerprint(files: list[Path]) -> str:
    h = hashlib.sha1()
    for p in files:
        h.update(f"{p.name}:{p.stat().st_size};".encode())
    return h.hexdigest()


def sync_folder(folder: Path, force: bool = False) -> bool:
    """Upload a lesson folder if it is new or changed. Returns True if a job was enqueued."""
    did = date_id(folder.name)
    files = lesson_files(folder)
    if not did or not files:
        return False
    newest = max(p.stat().st_mtime for p in files)
    if not force and time.time() - newest < STABLE_AFTER_S:
        log.info("%s still changing; will retry later", folder.name)
        return False
    fp = fingerprint(files)
    manifest = storage.get_json(config.RAW_CONTAINER, f"{did}/manifest.json") or {}
    if manifest.get("fingerprint") == fp and not force:
        return False
    existing = {b.name: b.size for b in storage.list_blobs(config.RAW_CONTAINER, f"{did}/")}
    for p in files:
        blob = f"{did}/{p.name}"
        if existing.get(blob) != p.stat().st_size:
            log.info("uploading %s (%.1f MB)", p.name, p.stat().st_size / 1e6)
            storage.put_file(config.RAW_CONTAINER, blob, p)
    storage.put_json(config.RAW_CONTAINER, f"{did}/manifest.json", {
        "date": did, "fingerprint": fp, "source": str(folder),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"name": p.name, "kind": kind_of(p.name), "size": p.stat().st_size} for p in files],
    })
    storage.put_json(config.DATA_CONTAINER, f"{did}/status.json",
                     {"date": did, "state": "queued", "step": "uploaded raw files",
                      "updated": datetime.now(timezone.utc).isoformat()})
    storage.enqueue(did, "changed" if manifest else "new")
    return True


def scan(input_dir: str | None = None, force: bool = False) -> list[str]:
    root = Path(input_dir or config.INPUT_DIR or "")
    if not root.is_dir():
        raise SystemExit(f"Input folder not found: {root}")
    queued = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            if sync_folder(folder, force=force):
                queued.append(folder.name)
        except Exception:  # noqa: BLE001 - one bad folder must not block the others
            log.exception("failed to sync %s", folder)
    return queued
