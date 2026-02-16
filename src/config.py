import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# ─── Validation constants ─────────────────────────────────────────────────────
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_ATTENDEE = 1
MAX_ATTENDEE = 10


@dataclass(frozen=True)
class Config:
    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Suwon Library login
    suwon_username: str
    suwon_password: str

    # Reservation details
    camping_date: str       # "YYYY-MM-DD" — the date you want to camp
    campsite_name: str      # e.g. "A구역"
    attendee_count: int

    # Timing / retry
    max_retries: int
    retry_delay_seconds: float
    pre_position_seconds: int   # seconds before 10:00 to open browser & log in
    headless: bool

    # Paths
    screenshot_dir: str


def _validate_camping_date(date_str: str) -> None:
    """Validate that camping_date is in YYYY-MM-DD format."""
    if not _DATE_PATTERN.match(date_str):
        raise ValueError(
            f"CAMPING_DATE must be in YYYY-MM-DD format, got '{date_str}'"
        )


def _validate_attendee_count(count: int) -> None:
    """Validate that attendee_count is within the allowed range."""
    if not (MIN_ATTENDEE <= count <= MAX_ATTENDEE):
        raise ValueError(
            f"ATTENDEE_COUNT must be between {MIN_ATTENDEE} and {MAX_ATTENDEE}, got {count}"
        )


def load_config() -> Config:
    """
    Load configuration from environment variables.
    Raises ValueError immediately if a required variable is missing or invalid.
    """
    required = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SUWON_USERNAME",
        "SUWON_PASSWORD",
        "CAMPING_DATE",
        "CAMPSITE_NAME",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}")

    camping_date = os.environ["CAMPING_DATE"]
    _validate_camping_date(camping_date)

    attendee_count = int(os.getenv("ATTENDEE_COUNT", "2"))
    _validate_attendee_count(attendee_count)

    return Config(
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=os.environ["TELEGRAM_CHAT_ID"],
        suwon_username=os.environ["SUWON_USERNAME"],
        suwon_password=os.environ["SUWON_PASSWORD"],
        camping_date=camping_date,
        campsite_name=os.environ["CAMPSITE_NAME"],
        attendee_count=attendee_count,
        max_retries=int(os.getenv("MAX_RETRIES", "10")),
        retry_delay_seconds=float(os.getenv("RETRY_DELAY_SECONDS", "1.0")),
        pre_position_seconds=int(os.getenv("PRE_POSITION_SECONDS", "30")),
        headless=os.getenv("HEADLESS", "false").lower() == "true",
        screenshot_dir=os.getenv("SCREENSHOT_DIR", "/app/screenshots"),
    )
