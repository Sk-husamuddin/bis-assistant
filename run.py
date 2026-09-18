"""Works from EITHER C:\sih2026 or C:\sih2026\bis-assistant — no --app-dir guessing."""
import pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import uvicorn
if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
