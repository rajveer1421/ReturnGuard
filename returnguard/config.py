"""Central configuration. Every threshold lives here so the code, README and
website can't drift apart again. Values are chosen by scripts/evaluate.py."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ANGLES = ("front", "back", "side")

# ── Storage ────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("RG_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "returnguard.db"
IMAGE_DIR = DATA_DIR / "images"
CACHE_DIR = Path(os.getenv("RG_CACHE_DIR", ROOT / ".cache"))
RESULTS_PATH = ROOT / "results" / "eval_results.json"

# ── Models ─────────────────────────────────────────────────────────────────
BG_MODEL = os.getenv("RG_BG_MODEL", "u2net")
EMBED_MODEL = os.getenv("RG_EMBED_MODEL", "facebook/dinov2-base")
EMBED_SIZE = int(os.getenv("RG_EMBED_SIZE", "224"))      # input side; patch grid = size / 14
# gemini-2.5-flash is no longer offered to new API keys, so the default is a current model
LLM_MODEL = os.getenv("RG_LLM_MODEL", "gemini-3.8-flash")
# Google advises keeping Gemini 3 models at their default temperature (1.0); older models run at 0.
LLM_TEMPERATURE = float(os.environ["RG_LLM_TEMPERATURE"]) if os.getenv("RG_LLM_TEMPERATURE") else None
LLM_TIMEOUT_S = float(os.getenv("RG_LLM_TIMEOUT_S", "90"))
LLM_MAX_RETRIES = int(os.getenv("RG_LLM_MAX_RETRIES", "3"))
LLM_MIN_INTERVAL_S = float(os.getenv("RG_LLM_MIN_INTERVAL_S", "0"))   # client-side rate limit between calls
LLM_MAX_WAIT_S = float(os.getenv("RG_LLM_MAX_WAIT_S", "75"))           # never sleep longer than this between retries
LLM_CACHE = os.getenv("RG_LLM_CACHE", "0") == "1"         # on for evaluation runs only

# ── Upload limits ──────────────────────────────────────────────────────────
MAX_UPLOAD_MB = 15
# Public demo protection: deliveries + returns per IP per hour (0 = unlimited)
RATE_LIMIT_PER_HOUR = int(os.getenv("RG_RATE_LIMIT_PER_HOUR", "0"))
MAX_IMAGE_SIDE = 1024

# ── Capture quality gate ───────────────────────────────────────────────────
MIN_OBJECT_FRACTION = 0.02    # object must cover at least 2% of the frame
# Laplacian variance inside the object. Smooth steel or matte plastic is naturally
# low-texture (5-20), so only near-featureless captures are sent back for a retake.
MIN_SHARPNESS = 2.0

# ── Visual screen (local, no LLM) ──────────────────────────────────────────
# On the evaluation set, object-only DINOv2 similarity (mean of 3 views) is
# 0.37-0.53 for different products, 0.72-0.85 for another unit of the same or a
# similar model, and 0.89-0.99 for the same item photographed again.
# Fast reject: clearly a different product, no LLM needed.
FAST_REJECT_SHAPE = 0.60
# Fast accept: every view matches strongly in shape and colour, and the delivery
# fingerprint has no printed identifiers that still need reading.
FAST_ACCEPT_SHAPE = 0.92
FAST_ACCEPT_MIN_VIEW = 0.85
FAST_ACCEPT_MAX_COLOR_SHIFT = 3.0  # Delta E (a*b*) between median object colours

# ── Decision routing on the 0–100 evidence-weighted risk score ─────────────
ACCEPT_BELOW = 50
REJECT_FROM = 90
# Customer history makes the policy stricter: each prior flagged return lowers
# the acceptance cut-off by this much (capped).
HISTORY_PENALTY_PER_FLAG = 10
HISTORY_PENALTY_CAP = 25

# ── Return policy ──────────────────────────────────────────────────────────
RETURN_WINDOW_DAYS = {"electronics": 7, "apparel": 30, "home_kitchen": 10, "other": 10}
FUNCTIONAL_TEST_CATEGORIES = {"electronics"}
# Wear-and-return ("wardrobing") risk: a worn item is the same unit, so it passes the
# shape, colour and label checks. These categories always get a visual inspection.
WEAR_CHECK_CATEGORIES = {"apparel"}
RETURN_REASONS = {
    "changed_mind": "Changed my mind / no longer needed",
    "damaged": "Item arrived damaged",
    "defective": "Item is defective / not working",
    "wrong_item": "Received the wrong item",
    "not_as_described": "Not as described",
}
