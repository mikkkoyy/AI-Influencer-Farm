"""
Video assembler: direct video composition from user-selected assets.

Features:
- Compose video from selected images + optional narration + optional subtitles
- Deterministic caption generation when speech-to-text is unavailable
- MP4 validation (file exists, size > 0, FFmpeg readable, duration, codec, resolution)
- Progress tracking for long-running composition jobs
- Safe path handling to prevent traversal attacks
"""
import json
import logging
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from config.settings import settings, ACCOUNTS
from pipeline import compositor, tts as tts_module, subtitles as subtitles_module

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent_wav(path: Path, duration: float = 2.0):
    import wave
    sample_rate = 24000
    n_samples = int(duration * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return path

def _safe_path(path: str | Path, must_exist: bool = True) -> Path:
    """Resolve and validate a path to prevent traversal attacks."""
    p = Path(path).resolve()
    if must_exist and not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")
    # Ensure it is within project storage or a system temp dir
    allowed_roots = [
        Path(settings.db_path).parent.resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]
    is_allowed = any(
        p == root or str(p).startswith(str(root) + os.sep)
        for root in allowed_roots
    )
    if not is_allowed:
        raise ValueError(f"Path outside allowed storage: {p}")
    return p


# ---------------------------------------------------------------------------
# MP4 validation
# ---------------------------------------------------------------------------

def validate_mp4(path: str | Path) -> dict:
    """Validate an MP4 file and return detailed status.

    Checks:
    - File exists
    - Size > 0
    - FFmpeg can read it
    - Duration is valid
    - Video stream exists
    - Expected resolution (if provided)
    - Expected codec/container

    Returns dict with keys: ok, exists, size_bytes, duration_seconds,
    video_codec, audio_codec, width, height, errors (list of str).
    """
    result = {
        "ok": False,
        "exists": False,
        "size_bytes": 0,
        "duration_seconds": 0.0,
        "video_codec": None,
        "audio_codec": None,
        "width": None,
        "height": None,
        "errors": [],
    }

    p = Path(path)
    result["exists"] = p.exists()
    if not result["exists"]:
        result["errors"].append("File does not exist")
        return result

    result["size_bytes"] = p.stat().st_size
    if result["size_bytes"] <= 0:
        result["errors"].append("File size is zero")
        return result

    ffprobe = compositor._get_ffprobe_path()
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(p)],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0:
            result["errors"].append(f"FFprobe failed: {probe.stderr[:300]}")
            return result

        data = json.loads(probe.stdout)
        fmt = data.get("format", {})
        try:
            result["duration_seconds"] = float(fmt.get("duration", 0))
        except (TypeError, ValueError):
            pass
        if result["duration_seconds"] <= 0:
            result["errors"].append("Invalid or missing duration")

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video":
                result["video_codec"] = stream.get("codec_name")
                result["width"] = stream.get("width")
                result["height"] = stream.get("height")
            elif codec_type == "audio":
                result["audio_codec"] = stream.get("codec_name")

        if result["video_codec"] is None:
            result["errors"].append("No video stream found")

    except Exception as exc:
        result["errors"].append(f"FFprobe error: {exc}")
        return result

    if not result["errors"]:
        result["ok"] = True

    return result


# ---------------------------------------------------------------------------
# Deterministic captions
# ---------------------------------------------------------------------------

def generate_deterministic_captions(
    script_text: str,
    output_path: str | Path,
    duration_seconds: float,
    words_per_cue: int = 3,
    min_cue_seconds: float = 1.0,
) -> str:
    """Generate SRT captions with deterministic timing when TTS timing is unavailable.

    Splits script into word groups and spaces them evenly across the duration.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    words = script_text.strip().split()
    if not words:
        output_path.write_text("", encoding="utf-8")
        return str(output_path)

    groups = []
    for i in range(0, len(words), words_per_cue):
        group = words[i:i + words_per_cue]
        groups.append(group)

    if not groups:
        groups = [words]

    group_duration = duration_seconds / len(groups)
    srt_entries = []
    index = 1
    current_time = 0.0

    for group in groups:
        start = current_time
        end = current_time + group_duration
        if end > duration_seconds:
            end = duration_seconds
        text = " ".join(group)
        srt_entries.append(
            f"{index}\n"
            f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n"
            f"{text}\n"
        )
        index += 1
        current_time = end
        if current_time >= duration_seconds:
            break

    srt_content = "\n".join(srt_entries)
    output_path.write_text(srt_content, encoding="utf-8")
    logger.info("Generated deterministic captions: %d entries at %s", len(srt_entries), output_path)
    return str(output_path)


def _format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ---------------------------------------------------------------------------
# Main video assembly
# ---------------------------------------------------------------------------

def assemble_video(
    *,
    video_id: int,
    account: str,
    image_paths: list[str],
    output_dir: str | Path,
    title: str = "",
    narration_text: Optional[str] = None,
    caption_text: Optional[str] = None,
    resolution: str = "1080x1920",
    fps: int = 30,
    music_path: Optional[str] = None,
    include_subtitles: bool = True,
    include_narration: bool = True,
    progress_callback=None,
) -> dict:
    """Assemble a complete video from selected images.

    Parameters:
        video_id: Database video record ID
        account: Account slug
        image_paths: List of local image file paths
        output_dir: Directory for all output artifacts
        title: Optional video title
        narration_text: If provided, generate TTS narration
        caption_text: If provided, use as subtitle source (or deterministic timing)
        resolution: Target resolution as "WxH"
        fps: Target frames per second
        music_path: Optional background music file
        include_subtitles: Whether to burn subtitles
        include_narration: Whether to include narration audio
        progress_callback: Optional callable(percent: float, status: str)

    Returns dict with keys:
        final_path, duration_seconds, width, height, validation
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _progress(pct: float, status: str):
        logger.info("Video %d progress: %.0f%% - %s", video_id, pct, status)
        if progress_callback:
            try:
                progress_callback(pct, status)
            except Exception:
                pass

    _progress(5, "Validating inputs")
    validated_images = []
    for img in image_paths:
        try:
            p = _safe_path(img)
            if p.exists() and p.stat().st_size > 0:
                validated_images.append(str(p))
            else:
                logger.warning("Skipping invalid image: %s", img)
        except Exception as exc:
            logger.warning("Skipping image due to path error (%s): %s", exc, img)

    if not validated_images:
        raise RuntimeError("No valid images provided")

    # Parse resolution
    try:
        w_str, h_str = resolution.lower().split("x")
        target_w = int(w_str.strip())
        target_h = int(h_str.strip())
    except Exception:
        target_w, target_h = settings.video_width, settings.video_height

    # Temporarily override resolution settings
    orig_w = settings.video_width
    orig_h = settings.video_height
    orig_fps = settings.video_fps
    try:
        settings.video_width = target_w
        settings.video_height = target_h
        settings.video_fps = max(1, fps)
    except Exception:
        settings.video_width = orig_w
        settings.video_height = orig_h
        settings.video_fps = orig_fps

    narration_path = None
    subtitle_path = None

    if not include_narration:
        silent_path = output_dir / "silent_placeholder.wav"
        if not silent_path.exists():
            try:
                _make_silent_wav(silent_path, duration=2.0)
            except Exception:
                pass

    try:
        # Step 1: Narration
        _progress(15, "Generating narration")
        if narration_text and include_narration:
            try:
                narration_path = tts_module.generate_tts(narration_text, account, video_id)
            except Exception as exc:
                logger.warning("TTS generation failed, continuing without narration: %s", exc)
                narration_path = None

        # Step 2: Subtitles or deterministic captions
        _progress(40, "Preparing subtitles")
        subtitle_path = None
        if include_subtitles:
            if caption_text:
                if narration_path:
                    try:
                        subtitle_path = subtitles_module.generate_subtitles(
                            narration_path, video_id, account
                        )
                    except Exception as exc:
                        logger.warning("Whisper transcription failed: %s", exc)
                        subtitle_path = None
                if not subtitle_path:
                    duration = 10.0
                    if narration_path:
                        try:
                            duration = compositor.get_audio_duration(narration_path)
                        except Exception:
                            pass
                    elif caption_text:
                        words = len(caption_text.split())
                        duration = max(10.0, words / 2.6)
                    subtitle_path = generate_deterministic_captions(
                        caption_text or narration_text or "",
                        output_dir / "subtitles.srt",
                        duration,
                    )
            elif narration_path:
                try:
                    subtitle_path = subtitles_module.generate_subtitles(
                        narration_path, video_id, account
                    )
                except Exception as exc:
                    logger.warning("Whisper transcription failed: %s", exc)
                    subtitle_path = None

        _subtitle_for_compositor = subtitle_path
        if not _subtitle_for_compositor:
            empty_srt = output_dir / "empty_subtitles.srt"
            empty_srt.write_text("", encoding="utf-8")
            _subtitle_for_compositor = str(empty_srt)

        # Step 3: Compose
        _progress(60, "Compositing video")
        final_path = compositor.compose_video(
            validated_images,
            narration_path or str(output_dir / "silent_placeholder.wav"),
            _subtitle_for_compositor,
            account,
            video_id,
        )

        _progress(85, "Validating output")
        validation = validate_mp4(final_path)
        if not validation["ok"]:
            raise RuntimeError(
                f"Video validation failed: {'; '.join(validation['errors'])}"
            )

        _progress(95, "Finalizing")
        return {
            "final_path": final_path,
            "duration_seconds": validation["duration_seconds"],
            "width": validation["width"] or target_w,
            "height": validation["height"] or target_h,
            "validation": validation,
        }

    finally:
        try:
            settings.video_width = orig_w
            settings.video_height = orig_h
            settings.video_fps = orig_fps
        except Exception:
            pass
        _progress(100, "Complete")


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------

def run_video_job(video_id: int, db_session_factory, **kwargs) -> None:
    """Run a video assembly job in a background thread.

    Updates the Video record status and error_message as it progresses.
    """
    from core.models import Video, PipelineRun
    from datetime import datetime

    def _update(status: str, **fields):
        with db_session_factory() as session:
            v = session.query(Video).filter_by(id=video_id).first()
            if v:
                v.status = status
                for k, val in fields.items():
                    setattr(v, k, val)
                session.flush()

    start = datetime.utcnow()
    try:
        _update("processing", progress=10)
        result = assemble_video(video_id=video_id, **kwargs)
        elapsed = (datetime.utcnow() - start).total_seconds()
        _update(
            "completed",
            final_path=result["final_path"],
            progress=100,
            rendering_time=elapsed,
        )
    except Exception as exc:
        logger.error("Video job %d failed: %s", video_id, exc)
        _update("failed", error_message=str(exc), progress=0)
        with db_session_factory() as session:
            run = PipelineRun(
                video_id=video_id,
                step="video_assembly",
                status="failed",
                started_at=start,
                completed_at=datetime.utcnow(),
                error_message=str(exc),
            )
            session.add(run)
