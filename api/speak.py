import hashlib
import io
import pathlib
import re
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

try:
    from gtts import gTTS
except Exception:
    gTTS = None  # type: ignore

router = APIRouter()

# Forward-compatible: Phase 1 enforces "en", Phase 2 will allow hi/te/ta
ALLOWED_LANGS = {"en", "hi", "te", "ta"}

# Cache dir for precached demo audio — /speak will serve from here if hash matches
AUDIO_CACHE_DIR = pathlib.Path(__file__).parent.parent / "static" / "audio_cache"

class SpeakRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    language: str = Field(default="en", pattern="^(en|hi|te|ta)$", description="gTTS language code")

def clean_for_speech(text: str) -> str:
    """Strip markdown so gTTS doesn't read symbols aloud. Silently drops [1] markers per spec."""
    if not text:
        return ""
    t = text
    # Remove citation markers [1], [2], 【1】, etc.
    t = re.sub(r'\[\s*\d+\s*\]', ' ', t)
    t = re.sub(r'【\s*\d+\s*】', ' ', t)
    # Remove markdown headings: ## Heading -> Heading
    t = re.sub(r'^\s{0,3}#{1,6}\s*', '', t, flags=re.MULTILINE)
    # Bold/italic: **bold** -> bold, *italic* -> italic, __bold__, _italic_
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'__(.+?)__', r'\1', t)
    t = re.sub(r'\*(.+?)\*', r'\1', t)
    t = re.sub(r'_(.+?)_', r'\1', t)
    # Inline code `code` -> code
    t = re.sub(r'`([^`]+)`', r'\1', t)
    # Links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', t)
    # Bullet markers at line start: - , * , •
    t = re.sub(r'^\s*[-*•]\s+', '', t, flags=re.MULTILINE)
    # Numbered lists "1. " keep content but strip marker? keep number spoken? strip for cleanliness
    # We'll keep numbers as they are useful, just clean extra
    # Horizontal rules --- etc.
    t = re.sub(r'^\s*[-*_]{3,}\s*$', ' ', t, flags=re.MULTILINE)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t

@router.post("/speak")
async def speak(req: SpeakRequest):
    raw = (req.text or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="text must be non-empty")
    lang = (req.language or "en").strip().lower()
    if lang not in ALLOWED_LANGS:
        raise HTTPException(status_code=400, detail=f"unsupported language '{lang}' — allowed: {sorted(ALLOWED_LANGS)}")
    cleaned = clean_for_speech(raw)
    if not cleaned:
        raise HTTPException(status_code=400, detail="text empty after cleaning markdown")
    # Cache-first: if precached file for this cleaned text+lang exists, serve it (demo reliability when wifi is down)
    try:
        h = hashlib.md5(cleaned.encode()).hexdigest()[:12]
        cached = AUDIO_CACHE_DIR / f"hash_{h}_{lang}.mp3"
        if cached.exists():
            return FileResponse(str(cached), media_type="audio/mpeg", headers={"Content-Disposition": 'inline; filename="speech.mp3"', "X-Cache": "HIT"})
    except Exception:
        pass
    if gTTS is None:
        raise HTTPException(status_code=500, detail="gTTS not available")
    try:
        buf = io.BytesIO()
        tts = gTTS(text=cleaned, lang=lang)
        tts.write_to_fp(buf)
        buf.seek(0)
        headers = {"Content-Disposition": 'inline; filename="speech.mp3"', "X-Cache": "MISS"}
        return StreamingResponse(buf, media_type="audio/mpeg", headers=headers)
    except Exception as e:
        # gTTS raises gTTSError on network failure etc.
        raise HTTPException(status_code=502, detail=f"TTS generation failed: {e}")
