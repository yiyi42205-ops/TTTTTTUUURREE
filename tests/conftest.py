import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "review_scraper"))
sys.path.insert(0, str(ROOT))  # so tests can `import evaluate_v2`

# server.py raises RuntimeError at import time if GEMINI_API_KEY is missing;
# tests never call the real Gemini API, so a placeholder key is enough.
os.environ.setdefault("GEMINI_API_KEY", "test-key-for-pytest")
