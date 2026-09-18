import io
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _mock_groq(text: str = "What is IS 2347 and which products does it cover?"):
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.text = text
    mock_client.audio.transcriptions.create.return_value = mock_result
    return mock_client


def test_transcribe_success():
    mock_client = _mock_groq("What is IS 2347 and which products does it cover?")
    with patch("api.transcribe.Groq", return_value=mock_client):
        # need to set GROQ_API_KEY for the test to not return 500
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            fake_audio = io.BytesIO(b"fake webm audio bytes")
            r = client.post(
                "/transcribe",
                files={"file": ("audio.webm", fake_audio, "audio/webm")},
            )
            assert r.status_code == 200, r.text
            j = r.json()
            assert "text" in j
            assert j["text"] == "What is IS 2347 and which products does it cover?"
            # Verify Groq called with correct model and language
            mock_client.audio.transcriptions.create.assert_called_once()
            kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
            assert kwargs["model"] == "whisper-large-v3-turbo"
            assert kwargs["language"] == "en"


def test_transcribe_empty_file_400():
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        r = client.post(
            "/transcribe",
            files={"file": ("audio.webm", io.BytesIO(b""), "audio/webm")},
        )
        assert r.status_code == 400
        assert "empty" in r.json()["detail"].lower()


def test_transcribe_missing_file_422_or_400():
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        r = client.post("/transcribe", data={})
        # FastAPI returns 422 for missing required File(...)
        assert r.status_code in (400, 422)


def test_transcribe_no_speech_400():
    # Groq returns empty text -> should be mapped to 400 "no speech detected"
    mock_client = _mock_groq("")
    with patch("api.transcribe.Groq", return_value=mock_client):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            r = client.post(
                "/transcribe",
                files={"file": ("audio.webm", io.BytesIO(b"fake"), "audio/webm")},
            )
            assert r.status_code == 400
            assert "no speech" in r.json()["detail"].lower()


def test_transcribe_missing_api_key_500():
    # Ensure no GROQ_API_KEY triggers 500, not crash
    import os

    orig = os.environ.get("GROQ_API_KEY")
    # Clear env and prevent dotenv from reloading .env
    with patch.dict("os.environ", {}, clear=True):
        # also patch dotenv load to no-op so .env doesn't repopulate
        with patch("dotenv.load_dotenv"):
            with patch("api.transcribe.Groq") as mock_groq:
                r = client.post(
                    "/transcribe",
                    files={"file": ("audio.webm", io.BytesIO(b"fake"), "audio/webm")},
                )
                # Should be 500, not 200, and Groq not called
                assert r.status_code == 500
                assert "groq_api_key" in r.json()["detail"].lower()
                mock_groq.assert_not_called()
    # restore if needed (patch.dict with clear already restores, but ensure)
    if orig is not None:
        os.environ["GROQ_API_KEY"] = orig


def test_transcribe_invalid_mime_or_large_file():
    # Test large file 400
    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        large = b"x" * (10 * 1024 * 1024 + 1)
        r = client.post(
            "/transcribe",
            files={"file": ("audio.webm", io.BytesIO(large), "audio/webm")},
        )
        assert r.status_code == 400
        assert "too large" in r.json()["detail"].lower()
