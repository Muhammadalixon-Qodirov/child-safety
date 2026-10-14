"""Runtime configuration, read from environment variables or a local .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("GUARDIAN_DATA", ROOT / "data"))
SHOTS_DIR = DATA_DIR / "shots"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
# Model ids change over time; check https://console.groq.com/docs/models and override in .env.
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_SAFETY_MODEL = os.getenv("GROQ_SAFETY_MODEL", "openai/gpt-oss-safeguard-20b")
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000")

# Shared secret the agent sends in the X-Agent-Key header.
AGENT_KEY = os.getenv("AGENT_KEY", "demo-agent-key")

RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
OFFLINE_AFTER_SEC = int(os.getenv("OFFLINE_AFTER_SEC", "25"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
SHOTS_DIR.mkdir(parents=True, exist_ok=True)
