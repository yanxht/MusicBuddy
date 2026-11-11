"""Cloud-side Google Drive poller: picks up lesson folders added from a phone, no laptop needed.

Uses a Google service account that has been given Viewer access to the
"Music Lesson Recording" folder. Same fingerprint as the Mac watcher, so whichever
sees a folder first uploads it and the other one skips it.
"""
import json
import logging
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from . import config, ingest, storage

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"


def enabled() -> bool:
    return bool(config.GOOGLE_SA_JSON and config.DRIVE_FOLDER_ID)


def _session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        json.loads(config.GOOGLE_SA_JSON), scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return AuthorizedSession(creds)


def _children(s, folder_id: str) -> list[dict]:
    files, token = [], None
    while True:
        r = s.get(API, params={
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            "pageSize": 1000, "pageToken": token,
            "supportsAllDrives": True, "includeItemsFromAllDrives": True}, timeout=60)
        r.raise_for_status()
        data = r.json()
        files += data.get("files", [])
        token = data.get("nextPageToken")
        if not token:
            return files


def _downloader(s, file_id: str):
    def upload(blob: str) -> None:
        with tempfile.NamedTemporaryFile(dir=config.WORK_DIR, delete=True) as tmp:
            with s.get(f"{API}/{file_id}", params={"alt": "media", "supportsAllDrives": True},
                       stream=True, timeout=600) as r:
                r.raise_for_status()
                for chunk in r.iter_content(4 << 20):
                    tmp.write(chunk)
            tmp.flush()
            storage.put_file(config.RAW_CONTAINER, blob, Path(tmp.name))
    return upload


def _mtime(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def scan() -> list[str]:
    """Check every dated sub-folder of the Drive lesson folder; upload + queue new/changed ones."""
    s = _session()
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    queued = []
    for folder in _children(s, config.DRIVE_FOLDER_ID):
        did = ingest.date_id(folder["name"])
        if folder.get("mimeType") != FOLDER_MIME or not did:
            continue
        try:
            entries = [ingest.Entry(f["name"], int(f.get("size", 0)), _mtime(f["modifiedTime"]),
                                    _downloader(s, f["id"]))
                       for f in _children(s, folder["id"])
                       if f.get("mimeType") != FOLDER_MIME and f.get("size")]
            if ingest.sync_lesson(did, entries, f"gdrive:{folder['name']}"):
                queued.append(did)
        except Exception:  # noqa: BLE001 - one bad folder must not block the others
            log.exception("drive sync failed for %s", folder["name"])
    return queued


def loop(stop: threading.Event) -> None:
    log.info("Google Drive poller watching folder %s every %ss", config.DRIVE_FOLDER_ID, config.DRIVE_POLL_S)
    while not stop.is_set():
        try:
            if queued := scan():
                log.info("drive: queued %s", queued)
        except Exception:  # noqa: BLE001 - transient API errors: try again next round
            log.exception("drive scan failed")
        stop.wait(config.DRIVE_POLL_S)


def start_background() -> threading.Event | None:
    if not enabled():
        log.info("Google Drive poller disabled (no service account configured)")
        return None
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop,), daemon=True, name="drive-poller").start()
    return stop
