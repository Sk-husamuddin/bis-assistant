import os
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

try:
    from groq import Groq
except Exception:
    Groq = None  # type: ignore

router = APIRouter()

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIMES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-wav",
    "audio/webm;codecs=opus",
    "audio/ogg;codecs=opus",
    "video/webm",
    "audio/mp4;codecs=mp4a.40.2",
}
ALLOWED_EXTS = (".webm", ".wav", ".ogg", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga")
ALLOWED_TRANSCRIBE_LANGS = {"en", "hi", "te", "ta"}

@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form(default="en")):
    # Validate presence
    if not file or not file.filename:
        # FastAPI will have already raised 422 if File(...) missing, but handle empty filename
        raise HTTPException(status_code=400, detail="missing audio file — field 'file' required")
    data = await file.read()
    if not data or len(data) == 0:
        raise HTTPException(status_code=400, detail="empty audio file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="file too large (max 10MB)")

    ctype = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    if ctype not in ALLOWED_MIMES and not fname.endswith(ALLOWED_EXTS):
        # Be lenient: allow anything audio/video/* but warn if completely unknown
        if not ctype.startswith("audio/") and not ctype.startswith("video/"):
            raise HTTPException(status_code=400, detail=f"unsupported audio type '{ctype or 'unknown'}'")

    api_key = os.getenv("GROQ_API_KEY", "")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY", api_key)
    except Exception:
        pass
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured — transcription unavailable")

    # Manual language selection for Telugu/Hindi/Tamil/English via Groq Whisper
    lang = (language or "en").strip().lower()
    if lang not in ALLOWED_TRANSCRIBE_LANGS:
        raise HTTPException(status_code=400, detail=f"unsupported language '{lang}' — allowed: {sorted(ALLOWED_TRANSCRIBE_LANGS)}")

    if Groq is None:
        raise HTTPException(status_code=500, detail="Groq SDK not available")
    try:
        client = Groq(api_key=api_key)
        # Groq Whisper expects file tuple (filename, bytes)
        # language is explicit per manual selector (hi/te/ta/en)
        result = client.audio.transcriptions.create(
            file=(file.filename or "audio.webm", data),
            model="whisper-large-v3-turbo",
            language=lang,
        )
        text = (getattr(result, "text", "") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="no speech detected — try again, speak clearly")
        return {"text": text, "language": lang}
    except HTTPException:
        raise
    except Exception as e:
        # Groq errors (network, auth, etc.)
        msg = str(e)
        # Map common Groq auth error to 500 with clear message
        if "api_key" in msg.lower() or "authentication" in msg.lower():
            raise HTTPException(status_code=500, detail=f"GROQ_API_KEY invalid: {msg}")
        raise HTTPException(status_code=502, detail=f"Transcription failed: {msg}")
