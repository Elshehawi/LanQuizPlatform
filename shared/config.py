"""Shared configuration constants for server and client."""

from pathlib import Path
import re

# ── Network ──────────────────────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000
UDP_BROADCAST_PORT = 37020
UDP_BROADCAST_INTERVAL = 3  # seconds
UDP_LISTEN_TIMEOUT = 4  # seconds
UDP_MAGIC = "QUIZ_LAN_HOST"

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "quiz_platform.db"
GRADEBOOK_PATH = DATA_DIR / "gradebook.xlsx"
TUTOR_CODE_PATH = DATA_DIR / "tutor_access_code.txt"
RECOVERY_DIR = DATA_DIR / "recovery"

# ── Auth ─────────────────────────────────────────────────────────────────────
JWT_SECRET_KEY = "lan-quiz-platform-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12

# ── Validation ───────────────────────────────────────────────────────────────
EMAIL_DOMAIN_SUFFIX = "@nmu.edu.eg"  # Configurable university domain
STUDENT_ID_REGEX = re.compile(r"(\d{6,12})")

# ── Quiz ─────────────────────────────────────────────────────────────────────
TIMER_GRACE_SECONDS = 5
AUTO_SAVE_INTERVAL_SECONDS = 10

# ── Default course seed ─────────────────────────────────────────────────────
DEFAULT_COURSE_ID = 1
DEFAULT_COURSE_CODE = "CS101"
DEFAULT_COURSE_TITLE = "Default Course"
