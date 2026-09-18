import os
import pathlib

# bis-assistant project root (one level up from agent/)
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
# also support running from C:\sih2026 with --app-dir bis-assistant
_CANDIDATE_ENVS = [
    _PROJECT_ROOT / ".env",  # C:\sih2026\bis-assistant\.env (primary)
    pathlib.Path.cwd() / ".env",  # CWD .env (e.g. C:\sih2026\.env)
    pathlib.Path.cwd() / "bis-assistant" / ".env",  # C:\sih2026\bis-assistant\.env when CWD is C:\sih2026
]

def _load():
    try:
        from dotenv import load_dotenv
        # Load the correct .env with override so edits after process start are picked up,
        # and when running from repo root with --app-dir
        for p in _CANDIDATE_ENVS:
            if p.exists():
                load_dotenv(dotenv_path=p, override=True)
                break
        else:
            load_dotenv(override=True)
    except Exception:
        pass

def is_verbose() -> bool:
    _load()
    return os.getenv("DEBUG_VERBOSE", "false").lower() == "true"

# Also expose as constant for import-time checks (re-evaluated via function)
DEBUG_VERBOSE = is_verbose()
