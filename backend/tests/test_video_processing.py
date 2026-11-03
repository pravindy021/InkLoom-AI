import asyncio
import json
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from app.services import video_processing


@pytest.mark.parametrize(
    ("filename", "media_type", "extension"),
    [
        ("brand.mp4", "video/mp4", ".mp4"),
        ("brand.MOV", "video/quicktime", ".mov"),
        ("brand.webm", "video/webm", ".webm"),
    ],
)
def test_video_upload_type_requires_supported_extension_and_matching_mime(
    filename, media_type, extension
):
    assert video_processing._validate_video_type(filename, media_type) == extension


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("brand.mp4", "video/quicktime"),
        ("brand.exe", "video/mp4"),
        ("brand.webm", "application/octet-stream"),
    ],
)
def test_video_upload_type_rejects_mime_mismatch_or_unsupported_format(
    filename, media_type
):
    with pytest.raises(video_processing.VideoProcessingError):
        video_processing._validate_video_type(filename, media_type)


def test_video_metadata_requires_video_stream_and_duration_within_limit(monkeypatch):
    monkeypatch.setattr(video_processing, "MAX_VIDEO_DURATION_SECONDS", 15)
    monkeypatch.setattr(
        video_processing,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps(
                {
                    "format": {"duration": "12.5"},
                    "streams": [
                        {
                            "codec_type": "video",
                            "width": 1920,
                            "height": 1080,
                            "codec_name": "h264",
                        },
                        {"codec_type": "audio", "codec_name": "aac"},
                    ],
                }
            ).encode(),
            stderr=b"",
        ),
    )
    assert video_processing._probe_video(Path("sample.mp4")) == {
        "duration_seconds": 12.5,
        "has_audio": True,
        "width": 1920,
        "height": 1080,
        "video_codec": "h264",
        "audio_codec": "aac",
    }

    monkeypatch.setattr(
        video_processing,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps(
                {"format": {"duration": "16"}, "streams": [{"codec_type": "video"}]}
            ).encode(),
            stderr=b"",
        ),
    )
    with pytest.raises(video_processing.VideoProcessingError, match="duration"):
        video_processing._probe_video(Path("sample.mp4"))


def test_video_extraction_is_bounded_and_cleans_temporary_files(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"test")
    temporary_directories = []
    real_temp_directory = video_processing.tempfile.TemporaryDirectory

    def track_temp_directory(*args, **kwargs):
        directory = real_temp_directory(*args, **kwargs)
        temporary_directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(
        video_processing.tempfile, "TemporaryDirectory", track_temp_directory
    )
    monkeypatch.setattr(
        video_processing,
        "_probe_video",
        lambda _path: {"duration_seconds": 31.0, "has_audio": True},
    )
    monkeypatch.setattr(video_processing, "VIDEO_FRAME_INTERVAL_SECONDS", 15)
    monkeypatch.setattr(video_processing, "VIDEO_MAX_FRAMES", 2)
    monkeypatch.setattr(
        video_processing,
        "VIDEO_TRANSCRIPTION_ENABLED",
        False,
    )
    monkeypatch.setattr(
        video_processing,
        "_transcribe_audio",
        lambda _path: pytest.fail("Transcription must not run without consent."),
    )

    def fake_run(command, **_kwargs):
        destination = Path(command[-1])
        if destination.name == "frame-%03d.jpg":
            destination.with_name("frame-001.jpg").write_bytes(b"frame-one")
            destination.with_name("frame-002.jpg").write_bytes(b"frame-two")
            destination.with_name("frame-003.jpg").write_bytes(b"extra-frame")
        else:
            destination.write_bytes(b"audio")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(video_processing, "_run", fake_run)
    result = video_processing._process_video_file(source, allow_transcription=False)
    assert len(result["frames"]) == 2
    assert [frame["timestamp_seconds"] for frame in result["frames"]] == [0, 31]
    assert result["warnings"]
    assert temporary_directories
    assert all(not directory.exists() for directory in temporary_directories)


def test_upload_stream_rejects_oversize_and_cleans_upload_temp(monkeypatch):
    upload = UploadFile(
        filename="private.mp4",
        file=BytesIO(b"\x00\x00\x00\x18ftyp" + b"x" * 24),
        headers=Headers({"content-type": "video/mp4"}),
    )
    temporary_directories = []
    real_temp_directory = video_processing.tempfile.TemporaryDirectory

    def track_temp_directory(*args, **kwargs):
        directory = real_temp_directory(*args, **kwargs)
        temporary_directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(video_processing.tempfile, "TemporaryDirectory", track_temp_directory)
    monkeypatch.setattr(video_processing, "MAX_VIDEO_UPLOAD_SIZE", 16)
    with pytest.raises(video_processing.VideoProcessingError, match="upload limit"):
        asyncio.run(video_processing.process_video_upload(upload, False))
    assert temporary_directories
    assert all(not directory.exists() for directory in temporary_directories)


def test_upload_stream_rejects_corrupted_video_signature(monkeypatch):
    upload = UploadFile(
        filename="corrupted.mp4",
        file=BytesIO(b"not a video"),
        headers=Headers({"content-type": "video/mp4"}),
    )
    monkeypatch.setattr(
        video_processing,
        "_process_video_file",
        lambda *_args, **_kwargs: pytest.fail(
            "Corrupted uploads must be rejected before invoking media tools."
        ),
    )
    with pytest.raises(video_processing.VideoProcessingError, match="contents"):
        asyncio.run(video_processing.process_video_upload(upload, False))


def test_missing_ffmpeg_is_a_configuration_error(monkeypatch):
    def missing_binary(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(video_processing.subprocess, "run", missing_binary)
    with pytest.raises(
        video_processing.VideoProcessingConfigurationError,
        match="FFmpeg and ffprobe",
    ):
        video_processing._run(["ffmpeg", "-version"])


def test_configured_transcription_sends_audio_only_after_opt_in(
    monkeypatch, tmp_path
):
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    requests = []

    class Response:
        status_code = 200
        content = b'{"text":"Brand promise","segments":[{"start":2.5,"end":3,"text":"Brand promise"}]}'

        @staticmethod
        def json():
            return json.loads(Response.content)

    def fake_post(url, **kwargs):
        requests.append((url, kwargs))
        return Response()

    monkeypatch.setattr(video_processing, "VIDEO_TRANSCRIPTION_ENABLED", True)
    monkeypatch.setattr(
        video_processing, "VIDEO_TRANSCRIPTION_API_URL", "https://speech.example.test/v1/audio"
    )
    monkeypatch.setattr(video_processing, "VIDEO_TRANSCRIPTION_API_KEY", "local-test-key")
    monkeypatch.setattr(video_processing.httpx, "post", fake_post)
    result = video_processing._transcribe_audio(audio)
    assert result["segments"] == [
        {"start": 2.5, "end": 3.0, "text": "Brand promise"}
    ]
    assert requests[0][1]["headers"]["Authorization"] == "Bearer local-test-key"


def test_transcription_consent_without_provider_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(video_processing, "VIDEO_TRANSCRIPTION_ENABLED", False)
    monkeypatch.setattr(
        video_processing,
        "_probe_video",
        lambda _path: {
            "duration_seconds": 1,
            "has_audio": False,
            "width": 1,
            "height": 1,
            "video_codec": "h264",
            "audio_codec": None,
        },
    )
    with pytest.raises(
        video_processing.VideoProcessingConfigurationError,
        match="no transcription service is configured",
    ):
        video_processing._process_video_file(Path("unused.mp4"), allow_transcription=True)
