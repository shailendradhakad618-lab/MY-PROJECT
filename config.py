"""JARVIS configuration. Keep secrets in environment variables, never in source."""
import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "storage"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.getenv("JARVIS_DB", str(DATA_DIR / "jarvis.db")))
MAX_PLAN_STEPS = int(os.getenv("JARVIS_MAX_PLAN_STEPS", "12"))
CONFIRM_RISKY = os.getenv("JARVIS_CONFIRM_RISKY", "1") != "0"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
