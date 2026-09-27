import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "").strip()
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "").strip()
BIFROST_URL = (os.getenv("BIFROST_URL") or "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY") or "sk-sgstats-bifrost"
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
MCP_URL = (os.getenv("MCP_URL") or "").rstrip("/")
DATA_DIR = ROOT / "data"
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT") or "12")
PLANNER_TIMEOUT = float(os.getenv("PLANNER_TIMEOUT") or "45")


def chat_model_ids() -> list[str]:
    models = []
    if GEMINI_MODEL:
        models.append(f"gemini/{GEMINI_MODEL}")
    if GROQ_MODEL:
        models.append(f"groq/{GROQ_MODEL}")
    return models


def fast_chat_model_ids() -> list[str]:
    models = chat_model_ids()
    groq = [model for model in models if model.startswith("groq/")]
    others = [model for model in models if model not in groq]
    return groq + others
