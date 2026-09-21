"""Preprocessor stage (design doc: split/dedup, check video correctness).

Runs ffprobe to validate the source and select rendition targets based on
the source resolution, mirroring the design-doc DAG metadata step.
"""
import json
import subprocess


class UnrecoverableError(Exception):
    """Bad input (corrupt file, no video stream) - do not retry."""


# Target renditions by source height (design doc assumption: 3 formats)
RENDITION_TARGETS = {
    "1080p": {"height": 1080, "bitrate_kbps": 5000},
    "720p": {"height": 720, "bitrate_kbps": 2800},
    "480p": {"height": 480, "bitrate_kbps": 1400},
}


def probe(path: str) -> dict:
    """Return ffprobe stream info. Raises UnrecoverableError on bad input."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-print_format", "json", path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise UnrecoverableError(f"ffprobe failed: {proc.stderr.strip()[:300]}")
    info = json.loads(proc.stdout)
    streams = info.get("streams") or []
    if not streams:
        raise UnrecoverableError("no video stream found")
    duration = streams[0].get("duration") or info.get("format", {}).get("duration")
    return {
        "width": int(streams[0]["width"]),
        "height": int(streams[0]["height"]),
        "duration_sec": float(duration) if duration else None,
    }


def select_renditions(width: int, height: int) -> list[dict]:
    """Choose renditions capped by the source resolution, largest first."""
    if height >= 1080:
        chosen = ["1080p", "720p", "480p"]
    elif height >= 720:
        chosen = ["720p", "480p"]
    else:
        chosen = ["480p"]

    renditions = []
    for res in chosen:
        target = RENDITION_TARGETS[res]
        out_w = max(2, round(width * target["height"] / height / 2) * 2)
        renditions.append({
            "resolution": res,
            "height": target["height"],
            "width": out_w,
            "bitrate_kbps": target["bitrate_kbps"],
        })
    return renditions
