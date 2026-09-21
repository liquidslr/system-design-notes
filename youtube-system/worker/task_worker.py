"""Task worker: ffmpeg encoding of one rendition (design doc: Task Workers).

Encoding failures are retried with exponential backoff and classified as
RecoverableError (transient, worth retrying) or UnrecoverableError
(permanent, e.g. missing codec support).
"""
import asyncio
import logging
import os
import subprocess

from worker.preprocessor import UnrecoverableError

logger = logging.getLogger(__name__)


class RecoverableError(Exception):
    """Transient failure - worth retrying with backoff."""


def _run(cmd: list[str], timeout: int = 1800) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RecoverableError(
            f"command failed ({proc.returncode}): {proc.stderr.strip()[-300:]}")


def _encode_once(src: str, out_root: str, rend: dict,
                 key_info_path: str | None = None) -> None:
    out_dir = os.path.join(out_root, rend["resolution"])
    os.makedirs(out_dir, exist_ok=True)
    playlist = os.path.join(out_dir, "playlist.m3u8")

    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vf", f"scale=-2:{rend['height']}",
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        # GOP alignment so master playlist level switching is seamless
        "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "128k",
        "-hls_time", "4", "-hls_playlist_type", "vod",
        "-hls_segment_filename", os.path.join(out_dir, "seg_%03d.ts"),
    ]
    if key_info_path:
        cmd += ["-hls_key_info_file", key_info_path]
    cmd.append(playlist)
    _run(cmd)


async def encode_rendition(src: str, out_root: str, rend: dict,
                           key_info_path: str | None = None,
                           max_retries: int = 3) -> dict:
    """Encode one rendition with retry/backoff. Returns the rendition result."""
    backoff = 2
    for attempt in range(1, max_retries + 1):
        try:
            await asyncio.to_thread(_encode_once, src, out_root, rend, key_info_path)
            return {
                "resolution": rend["resolution"],
                "playlist_path": f"{rend['resolution']}/playlist.m3u8",
                "bitrate_kbps": rend["bitrate_kbps"],
                "width": rend.get("width"),
                "height": rend.get("height"),
            }
        except RecoverableError as e:
            logger.warning("encode %s attempt %d/%d failed: %s",
                           rend["resolution"], attempt, max_retries, e)
            if attempt == max_retries:
                raise UnrecoverableError(
                    f"encode {rend['resolution']} failed after {max_retries} attempts"
                ) from e
            await asyncio.sleep(backoff)
            backoff *= 2


def make_thumbnail(src: str, out_root: str) -> str:
    """Extract a thumbnail; failure is non-fatal (returns '')."""
    out = os.path.join(out_root, "thumbnail.jpg")
    cmd = ["ffmpeg", "-y", "-ss", "0.5", "-i", src,
           "-vframes", "1", "-vf", "scale=640:-2", out]
    try:
        _run(cmd, timeout=120)
        return "thumbnail.jpg"
    except Exception as e:  # noqa: BLE001 - thumbnail is best-effort
        logger.warning("thumbnail generation failed (non-fatal): %s", e)
        return ""


def build_master_playlist(renditions: list[dict]) -> str:
    """Build master.m3u8 referencing per-rendition playlists (highest
    bandwidth first)."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    ordered = sorted(renditions, key=lambda r: r["bitrate_kbps"], reverse=True)
    for r in ordered:
        bandwidth = r["bitrate_kbps"] * 1000 + 128000  # audio + mux overhead
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
                     f"RESOLUTION={r['width']}x{r['height']}")
        lines.append(f"{r['resolution']}/playlist.m3u8")
    return "\n".join(lines) + "\n"
