"""
수원시 도서관 캠핑장 예약 자동화 봇 — 진입점

기본 실행 (스케줄 모드):
  python -m src.main
  → 다음 달 1일 10:00 KST까지 대기 후 예약 시도

즉시 실행:
  python -m src.main --now
  → 대기 없이 지금 바로 예약 시도

Dry-run (테스트용):
  python -m src.main --now --dry-run
  → 로그인 + 예약 페이지 로드 + 폼 입력 확인만 수행 (제출 안 함)
  → 선택자 검증, 페이지 구조 확인에 활용
"""

import argparse
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

# Sleep tuning
COARSE_SLEEP_CHUNK_SECONDS = 1800   # 30-minute chunks for Phase 1
PRECISION_THRESHOLD_SECONDS = 5     # switch to tight-loop for the final N seconds
PRECISION_SLEEP_SECONDS = 0.01      # 10 ms tight-loop interval


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

    # Phase 1: coarse chunks (CPU-friendly for long waits)
    while True:
        remaining = (target - datetime.now(KST)).total_seconds()
        if remaining <= PRECISION_THRESHOLD_SECONDS:
            break
        chunk = min(COARSE_SLEEP_CHUNK_SECONDS, remaining - PRECISION_THRESHOLD_SECONDS)
        logger.debug(f"Coarse sleep {chunk:.0f}s  ({remaining:.0f}s remaining)")
        await asyncio.sleep(chunk)

    # Phase 2: tight-loop for the final seconds (±10 ms accuracy)
    logger.info(f"Precision timing loop started (final {PRECISION_THRESHOLD_SECONDS} s)...")
    while True:
        remaining = (target - datetime.now(KST)).total_seconds()
        if remaining <= 0:
            break
        await asyncio.sleep(min(PRECISION_SLEEP_SECONDS, remaining))

    logger.info(f"Target reached: {datetime.now(KST).strftime('%H:%M:%S.%f')}")


# ─── Reservation orchestration ────────────────────────────────────────────────


async def run_reservation(
    config: Config,
    notifier: TelegramNotifier,
    run_now: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Full reservation flow:
      login → pre_position → (wait until 10:00:00) → retry loop → notify

    run_now=True : 10:00 대기 없이 즉시 시도
    dry_run=True : 폼 입력까지만 확인하고 제출 버튼 클릭 생략
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

        # 3. Wait until exactly 10:00:00 (스케줄 모드에서만)
        if not run_now:
            open_time = datetime.now(KST).replace(
                hour=OPEN_HOUR, minute=OPEN_MINUTE, second=OPEN_SECOND, microsecond=0
            )
            if datetime.now(KST) < open_time:
                logger.info("Step 3 — Waiting for 10:00:00 KST...")
                await sleep_until(open_time)
            logger.info(f"10:00:00 KST reached — {datetime.now(KST).strftime('%H:%M:%S.%f')}")
        else:
            logger.info("Step 3 — Skipped (--now mode)")

        # 4. Retry loop
        mode_tag = "[DRY-RUN] " if dry_run else ""
        retries = 1 if dry_run else config.max_retries
        logger.info(f"Step 4 — {mode_tag}Starting reservation loop (max {retries} attempts)...")
        last_screenshot: str | None = None
        last_reason = "시도 없음"

        for attempt in range(1, retries + 1):
            logger.info(f"{mode_tag}Attempt {attempt}/{retries}")
            success, message = await bot.attempt_reservation(dry_run=dry_run)

            if success:
                ss = await bot.take_screenshot("dryrun_success" if dry_run else "success")
                if dry_run:
                    await notifier.notify_success(
                        f"[DRY-RUN] 페이지 구조 확인 완료\n{message}"
                    )
                else:
                    await notifier.notify_success(
                        f"시도: {attempt}/{retries}\n"
                        f"날짜: {config.camping_date}\n"
                        f"구역: {config.campsite_name}\n"
                        f"인원: {config.attendee_count}명\n"
                        f"메시지: {message}"
                    )
                logger.info(f"{'Dry-run check' if dry_run else 'Reservation'} succeeded on attempt {attempt}!")
                return

            logger.warning(f"Attempt {attempt} failed: {message}")
            last_reason = message
            last_screenshot = await bot.take_screenshot(f"attempt_{attempt}_failed")

            if attempt < retries:
                await asyncio.sleep(config.retry_delay_seconds)

        # All retries exhausted
        logger.error(f"All {retries} attempts failed.")
        await notifier.notify_failure(
            f"{'[DRY-RUN] ' if dry_run else ''}모든 시도 소진 ({retries}회)\n마지막 사유: {last_reason}",
            last_screenshot,
        )


# ─── Entry point ──────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="수원시 도서관 캠핑장 예약 자동화 봇",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python -m src.main                   # 스케줄 모드: 다음 달 1일 10:00까지 대기
  python -m src.main --now             # 즉시 실행: 대기 없이 지금 바로 예약 시도
  python -m src.main --now --dry-run   # 즉시 dry-run: 로그인+페이지 확인만 (제출 안 함)
        """,
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="예약 오픈 시각까지 대기하지 않고 즉시 실행",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="로그인 및 폼 입력만 확인하고 실제 제출은 하지 않음 (선택자 검증용)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    # Load and validate configuration — exits immediately on missing vars
    try:
        config = load_config()
    except ValueError as e:
        logger.critical(f"설정 오류: {e}")
        sys.exit(1)

    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    if args.now:
        mode = "[DRY-RUN] " if args.dry_run else ""
        logger.info(f"{mode}즉시 실행 모드 (--now)")
    else:
        # 스케줄 모드: 다음 1일 10:00까지 대기
        open_time = next_reservation_open()
        logger.info(f"다음 예약 오픈: {open_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        await notifier.notify_startup(open_time.strftime("%Y-%m-%d %H:%M:%S %Z"))

        pre_time = open_time - timedelta(seconds=config.pre_position_seconds)
        logger.info(f"브라우저 시작 예정: {pre_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        await sleep_until(pre_time)

    try:
        await run_reservation(
            config,
            notifier,
            run_now=args.now,
            dry_run=args.dry_run,
        )
    except Exception as e:
        logger.exception(f"예기치 않은 오류: {e}")
        await notifier.notify_failure(f"예기치 않은 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
