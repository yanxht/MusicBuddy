"""Watch the input folder for new date folders, upload raw files, enqueue processing."""
import hashlib
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config, storage

log = logging.getLogger(__name__)

AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".flac", ".ogg", ".opus", ".mp4", ".mov", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp"}
TEXT_EXT = {".txt", ".md"}
DATE_DIR = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")
STABLE_AFTER_S = 180  # wait for cloud-drive sync to settle before uploading


def allow_cloud_file_download() -> None:
    """Background (launchd) processes get EDEADLK reading cloud-only Drive files unless they opt in."""
    if sys.platform != "darwin":
        return
    import ctypes
    libc = ctypes.CDLL("libc.dylib", use_errno=True)
    # setiopolicy_np(IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS, ..._ON)
    if libc.setiopolicy_np(3, 0, 2) != 0:
        log.warning("could not enable dataless file materialization (errno %s)", ctypes.get_errno())


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


@dataclass
class Entry:
    """One lesson file from any source (local folder or Google Drive)."""
    name: str
    size: int
    mtime: float
    upload: Callable[[str], None]  # uploads the file to the given raw blob name


def fingerprint(entries: list[Entry]) -> str:
    # Names + sizes only, so the Mac watcher and the cloud Drive poller agree on "unchanged".
    h = hashlib.sha1()
    for e in sorted(entries, key=lambda e: e.name):
        h.update(f"{e.name}:{e.size};".encode())
    return h.hexdigest()


def sync_lesson(did: str, entries: list[Entry], source: str, force: bool = False) -> bool:
    """Upload a lesson's files if new or changed and queue processing. True if a job was queued."""
    entries = [e for e in entries if kind_of(e.name) and not e.name.startswith(".")]
    if not entries:
        return False
    if not force and time.time() - max(e.mtime for e in entries) < STABLE_AFTER_S:
        log.info("%s still changing; will retry later", did)
        return False
    fp = fingerprint(entries)
    manifest = storage.get_json(config.RAW_CONTAINER, f"{did}/manifest.json") or {}
    if manifest.get("fingerprint") == fp and not force:
        return False
    existing = {b.name: b.size for b in storage.list_blobs(config.RAW_CONTAINER, f"{did}/")}
    for e in entries:
        blob = f"{did}/{e.name}"
        if existing.get(blob) != e.size:
            log.info("uploading %s (%.1f MB) from %s", e.name, e.size / 1e6, source)
            e.upload(blob)
    storage.put_json(config.RAW_CONTAINER, f"{did}/manifest.json", {
        "date": did, "fingerprint": fp, "source": source,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"name": e.name, "kind": kind_of(e.name), "size": e.size} for e in entries],
    })
    storage.put_json(config.DATA_CONTAINER, f"{did}/status.json",
                     {"date": did, "state": "queued", "step": "uploaded raw files",
                      "updated": datetime.now(timezone.utc).isoformat()})
    storage.enqueue(did, "changed" if manifest else "new")
    return True


def sync_folder(folder: Path, force: bool = False) -> bool:
    did = date_id(folder.name)
    if not did:
        return False
    entries = [Entry(p.name, p.stat().st_size, p.stat().st_mtime,
                     lambda blob, p=p: storage.put_file(config.RAW_CONTAINER, blob, p))
               for p in lesson_files(folder)]
    return sync_lesson(did, entries, str(folder), force)


def scan(input_dir: str | None = None, force: bool = False) -> list[str]:
    root = Path(input_dir or config.INPUT_DIR or "")
    if not root.is_dir():
        raise SystemExit(f"Input folder not found: {root}")
    allow_cloud_file_download()
    queued = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            if sync_folder(folder, force=force):
                queued.append(folder.name)
        except Exception:  # noqa: BLE001 - one bad folder must not block the others
            log.exception("failed to sync %s", folder)
    return queued
