"""Azure Blob + Queue helpers. All lesson state lives in blob storage as JSON."""
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, ContentSettings, generate_blob_sas
from azure.storage.queue import QueueClient, TextBase64EncodePolicy, TextBase64DecodePolicy

from . import config

log = logging.getLogger(__name__)


@lru_cache
def blob_service() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(config.AZURE_STORAGE_CONNECTION_STRING)


@lru_cache
def container(name: str):
    c = blob_service().get_container_client(name)
    try:
        c.create_container()
    except ResourceExistsError:
        pass
    return c


@lru_cache
def queue() -> QueueClient:
    q = QueueClient.from_connection_string(
        config.AZURE_STORAGE_CONNECTION_STRING, config.JOB_QUEUE,
        message_encode_policy=TextBase64EncodePolicy(),
        message_decode_policy=TextBase64DecodePolicy())
    try:
        q.create_queue()
    except ResourceExistsError:
        pass
    return q


_TYPES = {".json": "application/json", ".mp3": "audio/mpeg", ".jpg": "image/jpeg",
          ".jpeg": "image/jpeg", ".png": "image/png", ".m4a": "audio/mp4", ".txt": "text/plain",
          ".md": "text/markdown"}


def _ctype(name: str) -> str:
    return _TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def put_json(cname: str, name: str, data) -> None:
    container(cname).upload_blob(
        name, json.dumps(data, ensure_ascii=False, indent=1).encode(), overwrite=True,
        content_settings=ContentSettings(content_type="application/json"))


def get_json(cname: str, name: str, default=None):
    try:
        return json.loads(container(cname).download_blob(name).readall())
    except ResourceNotFoundError:
        return default


def put_file(cname: str, name: str, path: Path) -> None:
    with open(path, "rb") as f:
        container(cname).upload_blob(name, f, overwrite=True, max_concurrency=4,
                                     content_settings=ContentSettings(content_type=_ctype(name)))


def get_file(cname: str, name: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        container(cname).download_blob(name, max_concurrency=4).readinto(f)
    return dest


def list_blobs(cname: str, prefix: str) -> list:
    return list(container(cname).list_blobs(name_starts_with=prefix))


def exists(cname: str, name: str) -> bool:
    return container(cname).get_blob_client(name).exists()


def sas_url(cname: str, name: str, hours: int = 6) -> str:
    svc = blob_service()
    token = generate_blob_sas(
        account_name=svc.account_name, container_name=cname, blob_name=name,
        account_key=svc.credential.account_key, permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=hours))
    return f"{svc.url}{cname}/{name}?{token}"


def enqueue(date_id: str, reason: str = "new") -> None:
    queue().send_message(json.dumps({"date": date_id, "reason": reason}))
    log.info("enqueued %s (%s)", date_id, reason)
