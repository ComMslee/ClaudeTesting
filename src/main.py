"""
수원시 도서관 캠핑장 예약 자동화 봇 — 진입점

실행 흐름:
  1. 환경변수 로드 및 검증
  2. 다음 예약 오픈 시각(매월 1일 10:00 KST) 계산
  3. Telegram으로 시작 알림 전송
  4. 오픈 30초 전까지 절전 대기 (coarse sleep)
  5. 브라우저 시작 → 로그인 → 예약 페이지 사전 로드
  6. 정확히 10:00:00까지 정밀 대기 (10 ms tight-loop)
  7. MAX_RETRIES 횟수만큼 예약 시도
  8. 결과를 Telegram으로 알림 후 종료
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta

import pytz

from .config import Config, load_config
from .notifier import TelegramNotifier
from .reservation import ReservationBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

OPEN_HOUR = 10
OPEN_MINUTE = 0
OPEN_SECOND = 0


# ─── Timing utilities ─────────────────────────────────────────────────────────


def next_reservation_open() -> datetime:
    """
    Return the next datetime when the reservation opens (1st of month, 10:00 KST).
    - If today is the 1st and it is before 10:00, return today 10:00.
    - Otherwise, return the 1st of next month at 10:00.
    """
    now = datetime.now(KST)
    if now.day == 1 and now.hour < OPEN_HOUR:
        return now.replace(hour=OPEN_HOUR, minute=OPEN_MINUTE, second=OPEN_SECOND, microsecond=0)

    # Advance to the first of next month
    if now.month == 12:
        first = now.replace(year=now.year + 1, month=1, day=1)
    else:
        first = now.replace(month=now.month + 1, day=1)
    return first.replace(hour=OPEN_HOUR, minute=OPEN_MINUTE, second=OPEN_SECOND, microsecond=0)


async def sleep_until(target: datetime) -> None:
    """
    Async sleep until *target* (timezone-aware datetime).

    Two-phase approach:
      Phase 1 — 30-minute coarse chunks (CPU-friendly for long waits)
      Phase 2 — 10 ms tight-loop for the final 5 seconds (±10 ms accuracy)
    """
    now = datetime.now(KST)
    total = (target - now).total_seconds()
    if total <= 0:
        return

    logger.info(f"Waiting {total:.0f}s until {target.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Phase 1: coarse 30-min chunks
    CHUNK = 1800  # 30 minutes
    while True:
        remaining = (target - datetime.now(KST)).total_seconds()
        if remaining <= 5:
            break
        chunk = min(CHUNK, remaining - 5)
        logger.debug(f"Coarse sleep {chunk:.0f}s  ({remaining:.0f}s remaining)")
        await asyncio.sleep(chunk)

    # Phase 2: 10 ms precision loop
    logger.info("Precision timing loop started (final 5 s)...")
    while True:
        remaining = (target - datetime.now(KST)).total_seconds()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.01, remaining))

    logger.info(f"Target reached: {datetime.now(KST).strftime('%H:%M:%S.%f')}")


# ─── Reservation orchestration ────────────────────────────────────────────────


async def run_reservation(config: Config, notifier: TelegramNotifier) -> None:
    """
    Full reservation flow inside an already-launched browser context:
      login → pre_position → wait until 10:00:00 → retry loop → notify
    """
    async with ReservationBot(config) as bot:

        # 1. Login
        logger.info("Step 1 — Logging in...")
        if not await bot.login():
            ss = await bot.take_screenshot("login_failed")
            await notifier.notify_failure("로그인 실패 — 자격증명을 확인하세요.", ss)
            return

        # 2. Pre-position on the reservation page
        logger.info("Step 2 — Loading reservation page...")
        if not await bot.pre_position():
            ss = await bot.take_screenshot("preposition_failed")
            await notifier.notify_failure("예약 페이지 로드 실패", ss)
            return

        # 3. Wait until exactly 10:00:00
        open_time = datetime.now(KST).replace(
            hour=OPEN_HOUR, minute=OPEN_MINUTE, second=OPEN_SECOND, microsecond=0
        )
        if datetime.now(KST) < open_time:
            logger.info("Step 3 — Waiting for 10:00:00 KST...")
            await sleep_until(open_time)
        logger.info(f"10:00:00 KST reached — {datetime.now(KST).strftime('%H:%M:%S.%f')}")

        # 4. Retry loop
        logger.info(f"Step 4 — Starting reservation loop (max {config.max_retries} attempts)...")
        last_screenshot: str | None = None
        last_reason = "시도 없음"

        for attempt in range(1, config.max_retries + 1):
            logger.info(f"Attempt {attempt}/{config.max_retries}")
            success, message = await bot.attempt_reservation()

            if success:
                ss = await bot.take_screenshot("success")
                await notifier.notify_success(
                    f"시도: {attempt}/{config.max_retries}\n"
                    f"날짜: {config.camping_date}\n"
                    f"구역: {config.campsite_name}\n"
                    f"인원: {config.attendee_count}명\n"
                    f"메시지: {message}"
                )
                logger.info(f"Reservation succeeded on attempt {attempt}!")
                return

            logger.warning(f"Attempt {attempt} failed: {message}")
            last_reason = message
            last_screenshot = await bot.take_screenshot(f"attempt_{attempt}_failed")

            if attempt < config.max_retries:
                await asyncio.sleep(config.retry_delay_seconds)

        # All retries exhausted
        logger.error(f"All {config.max_retries} attempts failed.")
        await notifier.notify_failure(
            f"모든 시도 소진 ({config.max_retries}회)\n마지막 사유: {last_reason}",
            last_screenshot,
        )


# ─── Entry point ──────────────────────────────────────────────────────────────


async def main() -> None:
    # Load and validate configuration — exits immediately on missing vars
    try:
        config = load_config()
    except ValueError as e:
        logger.critical(f"설정 오류: {e}")
        sys.exit(1)

    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    # Calculate next reservation open time
    open_time = next_reservation_open()
    logger.info(f"다음 예약 오픈: {open_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    await notifier.notify_startup(open_time.strftime("%Y-%m-%d %H:%M:%S %Z"))

    # Sleep until (open_time - pre_position_seconds) to give time to log in
    pre_time = open_time - timedelta(seconds=config.pre_position_seconds)
    logger.info(f"브라우저 시작 예정: {pre_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    await sleep_until(pre_time)

    try:
        await run_reservation(config, notifier)
    except Exception as e:
        logger.exception(f"예기치 않은 오류: {e}")
        await notifier.notify_failure(f"예기치 않은 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
