import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import pytz
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async

from .config import Config

logger = logging.getLogger(__name__)

# ─── Site URLs ────────────────────────────────────────────────────────────────
# The library uses an ASP SSO login gateway that sets the session cookie used
# by the downstream Spring (.do) reservation pages.
LOGIN_URL = "https://www.suwonlib.go.kr/inc/sso_login_s.asp"
RESERVATION_URL = "https://www.suwonlib.go.kr/reserve/camping/campingApplySimple.do"

# ─── CSS Selectors ────────────────────────────────────────────────────────────
# These are educated guesses based on common Korean library site patterns.
# ⚠️  MUST be verified / updated against the live site using DevTools (F12)
#      before the first production run.
SELECTORS = {
    # Login form
    "login_id":     "input[name='mb_id'], #mb_id, input[name='userid']",
    "login_pw":     "input[name='mb_password'], #mb_password, input[type='password']",
    "login_submit": "input[type='submit'], button[type='submit'], .btn_login, a.login_btn",

    # Reservation form fields
    "camping_date": "input[name='campingDate'], #campingDate, input[name='resveDate']",
    "campsite_sel": "select[name='campsiteNo'], select[name='siteNo'], select[name='campNo']",
    "attendee_cnt": "input[name='personCnt'], input[name='attendeeCnt'], input[name='nop']",
    "apply_btn":    "input[type='submit'][value*='신청'], button.btn_apply, .reservation_submit, input[value*='예약']",

    # Result indicators (success / error)
    "success":      ".success_msg, #successMsg, .complete_msg, .resve_complete",
    "error":        ".error_msg, #errorMsg, .fail_msg, .already_full, .alert_msg",
}

# Keywords to look for in raw page HTML when CSS selectors are ambiguous
SUCCESS_KEYWORDS = ["예약완료", "신청완료", "접수완료", "예약이 완료"]
FAILURE_KEYWORDS = ["마감", "초과", "예약불가", "신청불가", "이미 예약", "접수불가"]


class ReservationBot:
    """
    Playwright-based automation for Suwon Library camping reservation.

    Usage:
        async with ReservationBot(config) as bot:
            await bot.login()
            await bot.pre_position()
            # ... wait until 10:00:00 ...
            success, msg = await bot.attempt_reservation()
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ─── Context manager ──────────────────────────────────────────────────────

    async def __aenter__(self) -> "ReservationBot":
        await self._launch_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._close_browser()

    # ─── Browser lifecycle ────────────────────────────────────────────────────

    async def _launch_browser(self) -> None:
        logger.info("Launching Chromium browser...")
        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=50,  # 50 ms between actions — more human-like pacing
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--no-first-run",
                "--disable-default-apps",
                "--window-size=1280,900",
            ],
        )

        self._context = await self._browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        self._page = await self._context.new_page()
        # Patch navigator.webdriver and CDP markers to help bypass WAF detection
        await stealth_async(self._page)
        logger.info("Browser ready with stealth settings applied.")

    async def _close_browser(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Browser cleanup error (non-fatal): {e}")

    # ─── Screenshot ───────────────────────────────────────────────────────────

    async def take_screenshot(self, prefix: str = "screenshot") -> str:
        """Save a full-page PNG screenshot. Returns the file path."""
        os.makedirs(self.config.screenshot_dir, exist_ok=True)
        ts = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
        path = str(Path(self.config.screenshot_dir) / f"{prefix}_{ts}.png")
        try:
            await self._page.screenshot(path=path, full_page=True)
            logger.info(f"Screenshot saved: {path}")
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
        return path

    # ─── Login ────────────────────────────────────────────────────────────────

    async def login(self) -> bool:
        """
        Navigate to the SSO login page and authenticate.
        Returns True if the login redirect confirms success.
        """
        logger.info(f"Navigating to login page: {LOGIN_URL}")
        try:
            await self._page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._page.wait_for_load_state("networkidle", timeout=15_000)

            await self._page.fill(SELECTORS["login_id"], self.config.suwon_username)
            await asyncio.sleep(0.3)
            await self._page.fill(SELECTORS["login_pw"], self.config.suwon_password)
            await asyncio.sleep(0.3)
            await self._page.click(SELECTORS["login_submit"])
            await self._page.wait_for_load_state("networkidle", timeout=15_000)

            if "login" in self._page.url.lower():
                logger.error("Login failed — still on the login page after submit.")
                return False

            logger.info("Login successful.")
            return True

        except PlaywrightTimeoutError as e:
            logger.error(f"Login timed out: {e}")
            return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    # ─── Pre-position ─────────────────────────────────────────────────────────

    async def pre_position(self) -> bool:
        """
        Navigate to the reservation page before 10 AM so it is already loaded
        and in a "hot" state when we attempt to submit at exactly 10:00:00.
        """
        logger.info(f"Pre-positioning on reservation page: {RESERVATION_URL}")
        try:
            await self._page.goto(RESERVATION_URL, wait_until="domcontentloaded", timeout=30_000)
            await self._page.wait_for_load_state("networkidle", timeout=15_000)
            logger.info("Reservation page loaded and ready.")
            return True
        except Exception as e:
            logger.error(f"Pre-positioning failed: {e}")
            return False

    # ─── Reservation attempt ──────────────────────────────────────────────────

    async def attempt_reservation(self, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Perform one full reservation attempt:
          1. Hard-reload the page (get fresh state at 10:00)
          2. Fill date, campsite, attendee count
          3. Submit (skipped when dry_run=True)
          4. Detect result

        dry_run=True: 폼 입력까지만 수행하고 제출 버튼을 누르지 않음.
                      페이지 구조 확인 및 선택자 검증 목적.

        Returns (success, message).
        """
        try:
            await self._page.reload(wait_until="domcontentloaded", timeout=20_000)
            await self._page.wait_for_load_state("networkidle", timeout=10_000)

            # Fill date field if present
            date_found = await self._page.locator(SELECTORS["camping_date"]).count() > 0
            if date_found:
                await self._page.fill(SELECTORS["camping_date"], self.config.camping_date)
                await asyncio.sleep(0.2)

            # Select campsite if a <select> is present
            site_found = await self._page.locator(SELECTORS["campsite_sel"]).count() > 0
            if site_found:
                await self._page.select_option(
                    SELECTORS["campsite_sel"],
                    label=self.config.campsite_name,
                )
                await asyncio.sleep(0.3)

            # Fill attendee count if the input is present
            cnt_found = await self._page.locator(SELECTORS["attendee_cnt"]).count() > 0
            if cnt_found:
                await self._page.fill(
                    SELECTORS["attendee_cnt"],
                    str(self.config.attendee_count),
                )
                await asyncio.sleep(0.2)

            # ── Dry-run: 폼 입력 확인 후 제출 없이 반환 ──────────────────────
            if dry_run:
                btn_found = await self._page.locator(SELECTORS["apply_btn"]).count() > 0
                fields = {
                    "날짜 필드": date_found,
                    "구역 선택": site_found,
                    "인원 입력": cnt_found,
                    "제출 버튼": btn_found,
                }
                found = [name for name, ok in fields.items() if ok]
                missing = [name for name, ok in fields.items() if not ok]
                msg = (
                    f"[DRY-RUN] 제출 생략\n"
                    f"  감지된 필드: {', '.join(found) if found else '없음'}\n"
                    f"  미감지 필드: {', '.join(missing) if missing else '없음'}"
                )
                logger.info(msg)
                return True, msg

            # ── 실제 제출 ─────────────────────────────────────────────────────
            await self._page.click(SELECTORS["apply_btn"])
            await self._page.wait_for_load_state("networkidle", timeout=15_000)

            # ── Detect result ─────────────────────────────────────────────────

            # Layer 1: explicit CSS selectors
            if await self._page.locator(SELECTORS["success"]).count() > 0:
                text = await self._page.locator(SELECTORS["success"]).first.inner_text()
                return True, f"예약 확인: {text.strip()}"

            if await self._page.locator(SELECTORS["error"]).count() > 0:
                text = await self._page.locator(SELECTORS["error"]).first.inner_text()
                return False, f"사이트 오류: {text.strip()}"

            # Layer 2: Korean keyword matching in raw HTML
            html = await self._page.content()
            if any(kw in html for kw in SUCCESS_KEYWORDS):
                return True, "예약 완료 (키워드 감지)"
            if any(kw in html for kw in FAILURE_KEYWORDS):
                return False, "예약 마감 또는 불가 (키워드 감지)"

            # Layer 3: unknown — caller will take a screenshot
            return False, "결과 불명확 — 스크린샷을 확인하세요."

        except PlaywrightTimeoutError as e:
            return False, f"타임아웃: {e}"
        except Exception as e:
            return False, f"예기치 않은 오류: {e}"
