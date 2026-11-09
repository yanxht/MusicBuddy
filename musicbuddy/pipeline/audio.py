"""ffmpeg helpers: probing, transcoding, and silence detection."""
import json
import re
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def duration_s(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(path)]).stdout
    return float(json.loads(out)["format"]["duration"])


def to_stream_mp3(src: Path, dst: Path) -> Path:
    """Loudness-normalized CBR mp3 for the web player (CBR keeps seeking accurate)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "44100",
          "-af", "loudnorm=I=-18:TP=-2:LRA=11", "-c:a", "libmp3lame", "-b:a", "64k", str(dst)])
    return dst


def to_stt_audio(src: Path, dst: Path, start_s: float | None = None,
                 length_s: float | None = None) -> Path:
    """16 kHz mono mp3, small enough for the Speech fast-transcription upload limit."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start_s is not None:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-i", str(src)]
    if length_s is not None:
        cmd += ["-t", f"{length_s:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", str(dst)]
    _run(cmd)
    return dst


_SIL_START = re.compile(r"silence_start: ([\d.]+)")
_SIL_END = re.compile(r"silence_end: ([\d.]+)")


def silences(path: Path, noise_db: int = -38, min_s: float = 1.5) -> list[tuple[float, float]]:
    """Return [(start, end)] seconds of near-silence. Gaps in speech that are NOT silent
    are almost always someone playing an instrument."""
    proc = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af",
                           f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"],
                          capture_output=True, text=True)
    out: list[tuple[float, float]] = []
    start = None
    for line in proc.stderr.splitlines():
        if m := _SIL_START.search(line):
            start = float(m.group(1))
        elif (m := _SIL_END.search(line)) and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out
