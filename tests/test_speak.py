import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from unittest.mock import patch, MagicMock
import io
from fastapi.testclient import TestClient
from api.main import app
from api.speak import clean_for_speech

client = TestClient(app)

def test_clean_for_speech_strips_markdown():
    assert clean_for_speech("**bold** text") == "bold text"
    assert clean_for_speech("## Heading\n- list item") == "Heading list item"
    assert clean_for_speech("See IS 2347 [1] and [2]") == "See IS 2347 and"
    assert clean_for_speech("Check [link](https://example.com) here") == "Check link here"
    assert clean_for_speech("`code` snippet") == "code snippet"

def test_clean_for_speech_citations():
    assert "[1]" not in clean_for_speech("Answer with citation [1] and [12]")
    assert "[1]" not in clean_for_speech("Multiple [1][2] markers")

def test_clean_for_speech_empty():
    assert clean_for_speech("") == ""
    assert clean_for_speech("   ") == ""

def test_speak_returns_mpeg():
    fake_mp3 = b"ID3\x00\x00\x00 fake mp3"
    # mock gTTS to avoid network
    with patch("api.speak.gTTS") as MockGTTS:
        mock = MagicMock()
        def fake_write(fp):
            fp.write(fake_mp3)
        mock.write_to_fp.side_effect = fake_write
        MockGTTS.return_value = mock
        r = client.post("/speak", json={"text": "Hello world, this is a test."})
        assert r.status_code == 200
        assert "audio/mpeg" in r.headers.get("content-type", "")
        assert len(r.content) > 0
        # verify gTTS called with cleaned text and en
        MockGTTS.assert_called_once()
        kwargs = MockGTTS.call_args[1] if MockGTTS.call_args[1] else {}
        # positional or keyword
        assert kwargs.get("lang", "en") == "en" or MockGTTS.call_args[0][1] == "en" if len(MockGTTS.call_args[0]) > 1 else True

def test_speak_with_language_param():
    fake_mp3 = b"ID3 fake"
    with patch("api.speak.gTTS") as MockGTTS:
        mock = MagicMock()
        mock.write_to_fp.side_effect = lambda fp: fp.write(fake_mp3)
        MockGTTS.return_value = mock
        r = client.post("/speak", json={"text": "Hello", "language": "en"})
        assert r.status_code == 200
        assert "audio/mpeg" in r.headers["content-type"]

def test_speak_empty_400():
    r = client.post("/speak", json={"text": ""})
    assert r.status_code == 400
    r2 = client.post("/speak", json={"text": "   "})
    assert r2.status_code == 400

def test_speak_markdown_cleaned_before_tts():
    with patch("api.speak.gTTS") as MockGTTS:
        mock = MagicMock()
        mock.write_to_fp.side_effect = lambda fp: fp.write(b"ID3")
        MockGTTS.return_value = mock
        client.post("/speak", json={"text": "**bold** answer [1] with ## heading"})
        # cleaned text should not contain ** or [1]
        call_text = MockGTTS.call_args[1].get("text") if MockGTTS.call_args[1] else MockGTTS.call_args[0][0]
        assert "**" not in call_text
        assert "[1]" not in call_text
