"""Central configuration. Values come from environment (or a local .env file)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


DEEPSEEK_API_KEY = env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# Pro model for reasoning-heavy work (attribution, summaries, chat); flash for vision.
LLM_MODEL = env("MB_LLM_MODEL", "deepseek-v4-pro")
VISION_MODEL = env("MB_VISION_MODEL", "deepseek-flash")

AZURE_SPEECH_KEY = env("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = env("AZURE_SPEECH_REGION", "eastus")
SPEECH_LOCALES = [s.strip() for s in env("MB_SPEECH_LOCALES", "en-US").split(",") if s.strip()]

AZURE_STORAGE_CONNECTION_STRING = env("AZURE_STORAGE_CONNECTION_STRING")
RAW_CONTAINER = env("MB_RAW_CONTAINER", "raw")
DATA_CONTAINER = env("MB_DATA_CONTAINER", "lessons")
JOB_QUEUE = env("MB_JOB_QUEUE", "lesson-jobs")

INPUT_DIR = env("MB_INPUT_DIR")
WORK_DIR = Path(env("MB_WORK_DIR", str(ROOT / "work")))

# Google Drive poller (cloud): service-account JSON and the "Music Lesson Recording" folder id.
GOOGLE_SA_JSON = env("MB_GOOGLE_SA_JSON")
if not GOOGLE_SA_JSON and (ROOT / ".secrets" / "google-sa.json").exists():
    GOOGLE_SA_JSON = (ROOT / ".secrets" / "google-sa.json").read_text()
DRIVE_FOLDER_ID = env("MB_DRIVE_FOLDER_ID")
DRIVE_POLL_S = int(env("MB_DRIVE_POLL_S", "180"))

SESSION_SECRET = env("MB_SESSION_SECRET", "dev-only-secret")
PASSCODE = env("MB_PASSCODE")

# Family profile used by the attribution + summary prompts.
KIDS = {
    "keyu": {"name": "Keyu", "age": 10, "instruments": "violin, piano",
             "seed": "Older sister (she/her), advanced for age: three-octave scales in many keys, etudes, "
                     "concerto-level repertoire, youth-symphony auditions. Usually the longer lesson."},
    "ruyu": {"name": "Ruyu", "age": 7, "instruments": "violin, piano",
             "seed": "Younger sister (she/her), earlier repertoire and note reading. Had elbow surgery in "
                     "Oct 2026 (arm was in a cast), so bow-arm range may be limited while recovering."},
}
TEACHER_NAME = env("MB_TEACHER_NAME", "Ms. Coleman")
