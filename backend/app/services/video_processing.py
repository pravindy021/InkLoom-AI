import json
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.config import (
    MAX_VIDEO_DURATION_SECONDS,
    MAX_VIDEO_UPLOAD_SIZE,
    VIDEO_FFMPEG_BINARY,
    VIDEO_FFPROBE_BINARY,
    VIDEO_FRAME_INTERVAL_SECONDS,
    VIDEO_MAX_FRAMES,
    VIDEO_TRANSCRIPTION_API_KEY,
    VIDEO_TRANSCRIPTION_API_URL,
    VIDEO_TRANSCRIPTION_ENABLED,
    VIDEO_TRANSCRIPTION_MODEL,
)

VIDEO_MIME_TYPES = {
    ".mp4": {"video/mp4"},
    ".mov": {"video/quicktime"},
    ".webm": {"video/webm"},
}
VIDEO_SIGNATURES = {
    ".mp4": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
    ".mov": lambda data: len(data) >= 12 and data[4:8] == b"ftyp",
    ".webm": lambda data: data.startswith(bytes.fromhex("1A45DFA3")),
}
UPLOAD_CHUNK_SIZE = 64 * 1024
MAX_TRANSCRIPTION_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TRANSCRIPT_CHARACTERS = 200_000


class VideoProcessingConfigurationError(RuntimeError):
    pass


class VideoProcessingError(ValueError):
    pass


def _validate_video_type(filename: str, media_type: Optional[str]) -> str:
    extension = Path(filename).suffix.lower()
    accepted_mimes = VIDEO_MIME_TYPES.get(extension)
    if accepted_mimes is None:
        raise VideoProcessingError("Only MP4, MOV, and WEBM videos are supported.")
    if media_type not in accepted_mimes:
        raise VideoProcessingError(
            "The video extension does not match its declared MIME type."
        )
    return extension


def _run(command: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise VideoProcessingConfigurationError(
            "Video processing requires FFmpeg and ffprobe on the application host."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError(
            "Video processing exceeded its configured time limit."
        ) from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace")[:500]
        raise VideoProcessingError(
            "The uploaded video could not be decoded. {}".format(message).strip()
        ) from exc


def _probe_video(path: Path) -> Dict[str, Any]:
    result = _run(
        [
            VIDEO_FFPROBE_BINARY,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,codec_name",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
    )
    try:
        metadata = json.loads(result.stdout.decode("utf-8"))
        duration = float(metadata["format"]["duration"])
        streams = metadata.get("streams", [])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise VideoProcessingError(
            "The uploaded video has invalid or unreadable metadata."
        ) from exc
    if not duration or duration <= 0:
        raise VideoProcessingError("The uploaded video has no valid duration.")
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise VideoProcessingError(
            "Video duration exceeds the configured {} second limit.".format(
                MAX_VIDEO_DURATION_SECONDS
            )
        )
    video_stream = next(
        (item for item in streams if item.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise VideoProcessingError("The uploaded file contains no video stream.")
    audio_stream = next(
        (item for item in streams if item.get("codec_type") == "audio"), None
    )
    return {
        "duration_seconds": round(duration, 3),
        "has_audio": audio_stream is not None,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
    }


def _transcribe_audio(audio_path: Path) -> Dict[str, Any]:
    if not VIDEO_TRANSCRIPTION_ENABLED:
        return {"text": "", "segments": [], "configured": False}
    headers = {}
    if VIDEO_TRANSCRIPTION_API_KEY:
        token = VIDEO_TRANSCRIPTION_API_KEY
        headers.update({"Authorization": "Bearer " + token})
    try:
        with audio_path.open("rb") as audio_file:
            response = httpx.post(
                VIDEO_TRANSCRIPTION_API_URL,
                headers=headers,
                data={"model": VIDEO_TRANSCRIPTION_MODEL, "response_format": "verbose_json"},
                files={"file": (audio_path.name, audio_file, "audio/mpeg")},
                timeout=httpx.Timeout(120, connect=10),
                follow_redirects=False,
            )
    except httpx.HTTPError as exc:
        raise VideoProcessingError(
            "The configured speech-to-text service could not be reached."
        ) from exc
    if len(response.content) > MAX_TRANSCRIPTION_RESPONSE_BYTES:
        raise VideoProcessingError(
            "The speech-to-text response exceeded the configured response limit."
        )
    if response.status_code < 200 or response.status_code >= 300:
        raise VideoProcessingError(
            "The configured speech-to-text service returned HTTP {}.".format(
                response.status_code
            )
        )
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise VideoProcessingError(
            "The configured speech-to-text service returned invalid JSON."
        ) from exc
    text = str(payload.get("text") or "").strip()
    if len(text) > MAX_TRANSCRIPT_CHARACTERS:
        raise VideoProcessingError(
            "The video transcript exceeded the configured text analysis limit."
        )
    segments = []
    for item in payload.get("segments") or []:
        try:
            start = float(item["start"])
            end = float(item.get("end", start))
            segment_text = str(item.get("text") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
        if start < 0 or end < start or not segment_text:
            continue
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": segment_text})
    return {
        "text": text,
        "segments": segments,
        "configured": True,
        "provider": "configured speech-to-text service",
    }


def _process_video_file(path: Path, allow_transcription: bool) -> Dict[str, Any]:
    metadata = _probe_video(path)
    if allow_transcription and not VIDEO_TRANSCRIPTION_ENABLED:
        raise VideoProcessingConfigurationError(
            "Speech-to-text consent was given, but no transcription service is configured."
        )
    frame_interval = max(
        VIDEO_FRAME_INTERVAL_SECONDS,
        metadata["duration_seconds"] / max(1, VIDEO_MAX_FRAMES - 1),
    )
    with tempfile.TemporaryDirectory(prefix="inkloom-video-") as directory:
        workdir = Path(directory)
        frame_pattern = workdir / "frame-%03d.jpg"
        _run(
            [
                VIDEO_FFMPEG_BINARY,
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-vf",
                "fps=1/{:.6f},scale=1280:720:force_original_aspect_ratio=decrease".format(
                    frame_interval
                ),
                "-frames:v",
                str(VIDEO_MAX_FRAMES),
                "-q:v",
                "5",
                str(frame_pattern),
            ],
            timeout=180,
        )
        frames = []
        for index, frame_path in enumerate(sorted(workdir.glob("frame-*.jpg"))):
            if index >= VIDEO_MAX_FRAMES:
                break
            timestamp = min(
                float(index * frame_interval),
                metadata["duration_seconds"],
            )
            frame_data = frame_path.read_bytes()
            if frame_data:
                frames.append(
                    {
                        "frame_index": index,
                        "timestamp_seconds": timestamp,
                        "file_data": frame_data,
                        "media_type": "image/jpeg",
                    }
                )
        if not frames:
            raise VideoProcessingError(
                "FFmpeg could not extract a representative video frame."
            )

        transcription = {
            "text": "",
            "segments": [],
            "configured": VIDEO_TRANSCRIPTION_ENABLED,
        }
        warnings = []
        if not metadata["has_audio"]:
            warnings.append("No audio track was found; speech transcription is unavailable.")
        else:
            audio_path = workdir / "audio.mp3"
            try:
                _run(
                    [
                        VIDEO_FFMPEG_BINARY,
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        str(path),
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-b:a",
                        "64k",
                        "-t",
                        str(MAX_VIDEO_DURATION_SECONDS),
                        str(audio_path),
                    ],
                    timeout=180,
                )
                if allow_transcription:
                    transcription = _transcribe_audio(audio_path)
                    if not transcription["text"]:
                        warnings.append(
                            "The transcription service returned no recognizable speech."
                        )
                else:
                    warnings.append(
                        "Audio was extracted locally but not sent for transcription because explicit consent was not given."
                    )
            except VideoProcessingError as exc:
                warnings.append("Speech transcription was unavailable: {}".format(exc))

        return {
            "duration_seconds": metadata["duration_seconds"],
            "metadata": {
                key: value
                for key, value in metadata.items()
                if key != "has_audio"
            },
            "frame_interval_seconds": round(frame_interval, 3),
            "frames": frames,
            "transcript": transcription,
            "warnings": warnings,
        }


async def process_video_upload(
    upload: UploadFile,
    allow_transcription: bool,
) -> Tuple[bytes, Dict[str, Any]]:
    filename = Path(upload.filename or "").name
    media_type = upload.content_type
    extension = _validate_video_type(filename, media_type)
    temp_dir = tempfile.TemporaryDirectory(prefix="inkloom-upload-")
    try:
        video_path = Path(temp_dir.name) / ("upload" + extension)
        size = 0
        with video_path.open("wb") as target:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_VIDEO_UPLOAD_SIZE:
                    raise VideoProcessingError(
                        "Video exceeds the configured {} MB upload limit.".format(
                            MAX_VIDEO_UPLOAD_SIZE // (1024 * 1024)
                        )
                    )
                target.write(chunk)
        if size == 0:
            raise VideoProcessingError("Uploaded video is empty.")
        with video_path.open("rb") as source:
            signature = source.read(16)
        if not VIDEO_SIGNATURES[extension](signature):
            raise VideoProcessingError(
                "The uploaded file contents do not match a supported video format."
            )
        processing = await run_in_threadpool(
            _process_video_file, video_path, allow_transcription
        )
        processing["filename"] = filename
        processing["media_type"] = media_type or mimetypes.guess_type(filename)[0]
        processing["size_bytes"] = size
        return video_path.read_bytes(), processing
    finally:
        temp_dir.cleanup()
