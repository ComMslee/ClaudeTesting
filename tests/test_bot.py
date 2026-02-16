"""
캠핑 예약 봇 테스트 스위트

테스트 가능 범위:
  1. 모듈 임포트 및 구조 검증
  2. Config — 필수 변수 검증, 타입 캐스팅, 기본값
  3. 타이밍 로직 — next_reservation_open(), sleep_until()
  4. Notifier — 클래스 초기화, 메서드 시그니처 (Telegram API mock)
  5. ReservationBot — 클래스 초기화, 선택자 상수 존재 여부 (브라우저 mock)
  6. 결과: 콘솔 + report.txt 출력
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytz

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KST = pytz.timezone("Asia/Seoul")

# ─── ANSI 색상 ────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


# ══════════════════════════════════════════════════════════════════════════════
# 1. 모듈 임포트 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestImports(unittest.TestCase):
    """모든 src 모듈이 오류 없이 임포트되는지 확인."""

    def test_import_config(self):
        from src import config
        self.assertTrue(hasattr(config, "Config"))
        self.assertTrue(hasattr(config, "load_config"))

    def test_import_notifier(self):
        from src import notifier
        self.assertTrue(hasattr(notifier, "TelegramNotifier"))

    def test_import_reservation(self):
        from src import reservation
        self.assertTrue(hasattr(reservation, "ReservationBot"))
        self.assertTrue(hasattr(reservation, "SELECTORS"))
        self.assertTrue(hasattr(reservation, "LOGIN_URL"))
        self.assertTrue(hasattr(reservation, "RESERVATION_URL"))

    def test_import_main(self):
        from src import main
        self.assertTrue(hasattr(main, "main"))
        self.assertTrue(hasattr(main, "next_reservation_open"))
        self.assertTrue(hasattr(main, "sleep_until"))
        self.assertTrue(hasattr(main, "run_reservation"))


# ══════════════════════════════════════════════════════════════════════════════
# 2. Config 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestConfig(unittest.TestCase):
    """Config 로드, 검증, 기본값 동작 확인."""

    VALID_ENV = {
        "TELEGRAM_BOT_TOKEN": "123:ABC",
        "TELEGRAM_CHAT_ID":   "999",
        "SUWON_USERNAME":     "test_user",
        "SUWON_PASSWORD":     "test_pass",
        "CAMPING_DATE":       "2026-03-01",
        "CAMPSITE_NAME":      "A구역",
    }

    def test_load_success_with_all_required(self):
        """필수 변수가 모두 있으면 Config 객체 반환."""
        from src.config import load_config
        with patch.dict(os.environ, self.VALID_ENV, clear=False):
            cfg = load_config()
        self.assertEqual(cfg.telegram_bot_token, "123:ABC")
        self.assertEqual(cfg.suwon_username, "test_user")
        self.assertEqual(cfg.camping_date, "2026-03-01")
        self.assertEqual(cfg.campsite_name, "A구역")

    def test_default_values(self):
        """선택 변수는 기본값이 적용되어야 함."""
        from src.config import load_config
        env = {**self.VALID_ENV}
        # 선택 변수 제거
        for k in ["ATTENDEE_COUNT", "MAX_RETRIES", "RETRY_DELAY_SECONDS",
                  "PRE_POSITION_SECONDS", "HEADLESS", "SCREENSHOT_DIR"]:
            env.pop(k, None)
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config()
        self.assertEqual(cfg.attendee_count, 2)
        self.assertEqual(cfg.max_retries, 10)
        self.assertAlmostEqual(cfg.retry_delay_seconds, 1.0)
        self.assertEqual(cfg.pre_position_seconds, 30)
        self.assertFalse(cfg.headless)
        self.assertEqual(cfg.screenshot_dir, "/app/screenshots")

    def test_type_casting(self):
        """숫자/불리언 변수가 올바른 타입으로 변환되어야 함."""
        from src.config import load_config
        env = {**self.VALID_ENV,
               "ATTENDEE_COUNT": "4",
               "MAX_RETRIES": "5",
               "RETRY_DELAY_SECONDS": "2.5",
               "HEADLESS": "true"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config()
        self.assertIsInstance(cfg.attendee_count, int)
        self.assertEqual(cfg.attendee_count, 4)
        self.assertIsInstance(cfg.max_retries, int)
        self.assertEqual(cfg.max_retries, 5)
        self.assertIsInstance(cfg.retry_delay_seconds, float)
        self.assertAlmostEqual(cfg.retry_delay_seconds, 2.5)
        self.assertTrue(cfg.headless)

    def test_missing_required_raises(self):
        """필수 변수 누락 시 ValueError 발생."""
        from src.config import load_config
        # 필수 변수를 하나씩 빼서 테스트
        required_keys = [
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "SUWON_USERNAME", "SUWON_PASSWORD",
            "CAMPING_DATE", "CAMPSITE_NAME",
        ]
        for key in required_keys:
            env = {k: v for k, v in self.VALID_ENV.items() if k != key}
            # 환경에 존재하는 키라면 빈 값으로 오버라이드
            env[key] = ""
            with self.subTest(missing=key):
                with patch.dict(os.environ, env, clear=False):
                    with self.assertRaises(ValueError):
                        load_config()

    def test_invalid_camping_date_format_raises(self):
        """CAMPING_DATE가 YYYY-MM-DD 형식이 아니면 ValueError 발생."""
        from src.config import load_config
        invalid_dates = ["03-01-2026", "2026/03/01", "20260301", "invalid"]
        for bad_date in invalid_dates:
            env = {**self.VALID_ENV, "CAMPING_DATE": bad_date}
            with self.subTest(date=bad_date):
                with patch.dict(os.environ, env, clear=False):
                    with self.assertRaises(ValueError):
                        load_config()

    def test_valid_camping_date_accepted(self):
        """유효한 YYYY-MM-DD 형식은 정상 통과."""
        from src.config import load_config
        env = {**self.VALID_ENV, "CAMPING_DATE": "2026-03-01"}
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config()
        self.assertEqual(cfg.camping_date, "2026-03-01")

    def test_attendee_count_out_of_range_raises(self):
        """ATTENDEE_COUNT가 1~10 범위 밖이면 ValueError 발생."""
        from src.config import load_config
        for bad_count in ["0", "11", "999", "-1"]:
            env = {**self.VALID_ENV, "ATTENDEE_COUNT": bad_count}
            with self.subTest(count=bad_count):
                with patch.dict(os.environ, env, clear=False):
                    with self.assertRaises(ValueError):
                        load_config()

    def test_attendee_count_in_range_accepted(self):
        """ATTENDEE_COUNT가 1~10 범위 내이면 정상 통과."""
        from src.config import load_config
        for valid_count in ["1", "5", "10"]:
            env = {**self.VALID_ENV, "ATTENDEE_COUNT": valid_count}
            with self.subTest(count=valid_count):
                with patch.dict(os.environ, env, clear=False):
                    cfg = load_config()
                self.assertEqual(cfg.attendee_count, int(valid_count))

    def test_config_is_immutable(self):
        """frozen=True 데이터클래스이므로 속성 변경 불가."""
        from src.config import load_config
        with patch.dict(os.environ, self.VALID_ENV, clear=False):
            cfg = load_config()
        with self.assertRaises(Exception):
            cfg.max_retries = 999  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# 3. 타이밍 로직 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestTimingLogic(unittest.TestCase):
    """next_reservation_open() 및 sleep_until() 동작 확인."""

    def _now_kst(self, **kwargs) -> datetime:
        return datetime.now(KST).replace(**kwargs)

    def test_first_of_month_before_10am(self):
        """1일 오전 10시 이전이면 오늘 10:00 반환."""
        from src.main import next_reservation_open
        fake_now = datetime(2026, 3, 1, 9, 30, 0, tzinfo=KST)
        with patch("src.main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = next_reservation_open()
        self.assertEqual(result.day, 1)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.hour, 10)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.second, 0)

    def test_first_of_month_after_10am(self):
        """1일 오전 10시 이후면 다음 달 1일 10:00 반환."""
        from src.main import next_reservation_open
        fake_now = datetime(2026, 3, 1, 10, 5, 0, tzinfo=KST)
        with patch("src.main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = next_reservation_open()
        self.assertEqual(result.month, 4)
        self.assertEqual(result.day, 1)
        self.assertEqual(result.hour, 10)

    def test_mid_month_returns_next_first(self):
        """월 중간이면 다음 달 1일 10:00 반환."""
        from src.main import next_reservation_open
        fake_now = datetime(2026, 3, 15, 14, 0, 0, tzinfo=KST)
        with patch("src.main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = next_reservation_open()
        self.assertEqual(result.month, 4)
        self.assertEqual(result.day, 1)

    def test_december_rolls_to_january(self):
        """12월이면 다음 해 1월 1일 10:00 반환."""
        from src.main import next_reservation_open
        fake_now = datetime(2026, 12, 15, 14, 0, 0, tzinfo=KST)
        with patch("src.main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = next_reservation_open()
        self.assertEqual(result.year, 2027)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 1)

    def test_sleep_until_past_returns_immediately(self):
        """과거 시각에 sleep_until 호출 시 즉시 반환."""
        from src.main import sleep_until
        past = datetime.now(KST) - timedelta(seconds=10)
        asyncio.run(sleep_until(past))  # 타임아웃 없이 즉시 완료되어야 함

    def test_sleep_until_near_future(self):
        """0.1초 후 시각에 sleep_until 호출 시 ~0.1초 대기."""
        from src.main import sleep_until
        future = datetime.now(KST) + timedelta(seconds=0.1)
        start = datetime.now(KST)
        asyncio.run(sleep_until(future))
        elapsed = (datetime.now(KST) - start).total_seconds()
        self.assertGreaterEqual(elapsed, 0.09)
        self.assertLess(elapsed, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Notifier 테스트 (Telegram API mock)
# ══════════════════════════════════════════════════════════════════════════════

class TestTelegramNotifier(unittest.TestCase):
    """TelegramNotifier — 초기화 및 메서드 동작 확인 (실제 API 호출 없음)."""

    def _make_notifier(self):
        from src.notifier import TelegramNotifier
        return TelegramNotifier(token="123:TEST", chat_id="456")

    def test_init(self):
        n = self._make_notifier()
        self.assertEqual(n.chat_id, "456")

    def _async_run(self, coro):
        return asyncio.run(coro)

    def test_send_message_success(self):
        """send_message가 True를 반환하고 예외 없이 종료."""
        from src.notifier import TelegramNotifier
        n = TelegramNotifier(token="123:TEST", chat_id="456")
        mock_bot = MagicMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message = AsyncMock(return_value=True)
        with patch.object(n, "bot", mock_bot):
            result = self._async_run(n.send_message("테스트 메시지"))
        self.assertTrue(result)

    def test_send_message_telegram_error_returns_false(self):
        """TelegramError 발생 시 예외 없이 False 반환."""
        from telegram.error import TelegramError
        from src.notifier import TelegramNotifier
        n = TelegramNotifier(token="123:TEST", chat_id="456")
        mock_bot = MagicMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("network error"))
        with patch.object(n, "bot", mock_bot):
            result = self._async_run(n.send_message("테스트"))
        self.assertFalse(result)  # 예외가 아닌 False 반환 확인

    def test_send_photo_fallback_when_file_missing(self):
        """스크린샷 파일 없으면 send_message로 폴백."""
        from src.notifier import TelegramNotifier
        n = TelegramNotifier(token="123:TEST", chat_id="456")
        mock_bot = MagicMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message = AsyncMock(return_value=True)
        with patch.object(n, "bot", mock_bot):
            result = self._async_run(
                n.send_photo("캡션", "/nonexistent/screenshot.png")
            )
        # 파일이 없어도 예외 없이 결과 반환
        self.assertIsNotNone(result)

    def test_notify_success_calls_send_message(self):
        """notify_success가 send_message를 호출하는지 확인."""
        from src.notifier import TelegramNotifier
        n = TelegramNotifier(token="123:TEST", chat_id="456")
        with patch.object(n, "send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            self._async_run(n.notify_success("예약 완료!"))
        mock_send.assert_called_once()
        call_text = mock_send.call_args[0][0]
        self.assertIn("성공", call_text)

    def test_notify_failure_without_screenshot(self):
        """스크린샷 없이 notify_failure 호출 시 send_message 사용."""
        from src.notifier import TelegramNotifier
        n = TelegramNotifier(token="123:TEST", chat_id="456")
        with patch.object(n, "send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            self._async_run(n.notify_failure("오류 발생"))
        mock_send.assert_called_once()

    def test_notify_failure_with_screenshot_calls_send_photo(self):
        """스크린샷 경로 있으면 send_photo 사용."""
        from src.notifier import TelegramNotifier
        n = TelegramNotifier(token="123:TEST", chat_id="456")
        with patch.object(n, "send_photo", new_callable=AsyncMock) as mock_photo:
            mock_photo.return_value = True
            self._async_run(n.notify_failure("오류", "/some/path.png"))
        mock_photo.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# 5. ReservationBot 구조 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestReservationBotStructure(unittest.TestCase):
    """ReservationBot — 클래스 구조, 선택자, 상수 검증 (브라우저 실행 없음)."""

    def _make_config(self):
        from src.config import Config
        return Config(
            telegram_bot_token="tok", telegram_chat_id="cid",
            suwon_username="user", suwon_password="pass",
            camping_date="2026-03-01", campsite_name="A구역",
            attendee_count=2, max_retries=3, retry_delay_seconds=1.0,
            pre_position_seconds=30, headless=True,
            screenshot_dir="/tmp/screenshots",
        )

    def test_selectors_all_keys_present(self):
        """SELECTORS 딕셔너리에 필수 키가 모두 있어야 함."""
        from src.reservation import SELECTORS
        required = [
            "login_id", "login_pw", "login_submit",
            "camping_date", "campsite_sel", "attendee_cnt",
            "apply_btn", "success", "error",
        ]
        for key in required:
            with self.subTest(key=key):
                self.assertIn(key, SELECTORS)
                self.assertTrue(SELECTORS[key], f"SELECTORS['{key}'] is empty")

    def test_urls_are_https(self):
        """LOGIN_URL, RESERVATION_URL이 HTTPS이어야 함."""
        from src.reservation import LOGIN_URL, RESERVATION_URL
        self.assertTrue(LOGIN_URL.startswith("https://"))
        self.assertTrue(RESERVATION_URL.startswith("https://"))

    def test_keyword_lists_not_empty(self):
        """SUCCESS/FAILURE 키워드 리스트가 비어있지 않아야 함."""
        from src.reservation import SUCCESS_KEYWORDS, FAILURE_KEYWORDS
        self.assertGreater(len(SUCCESS_KEYWORDS), 0)
        self.assertGreater(len(FAILURE_KEYWORDS), 0)

    def test_timeout_constants_are_positive(self):
        """타임아웃 상수가 양수여야 함."""
        from src.reservation import (
            PAGE_LOAD_TIMEOUT_MS, NETWORK_IDLE_TIMEOUT_MS,
            RELOAD_TIMEOUT_MS, RELOAD_IDLE_TIMEOUT_MS,
            SUBMIT_IDLE_TIMEOUT_MS, SLOW_MO_MS,
        )
        for name, val in [
            ("PAGE_LOAD_TIMEOUT_MS", PAGE_LOAD_TIMEOUT_MS),
            ("NETWORK_IDLE_TIMEOUT_MS", NETWORK_IDLE_TIMEOUT_MS),
            ("RELOAD_TIMEOUT_MS", RELOAD_TIMEOUT_MS),
            ("RELOAD_IDLE_TIMEOUT_MS", RELOAD_IDLE_TIMEOUT_MS),
            ("SUBMIT_IDLE_TIMEOUT_MS", SUBMIT_IDLE_TIMEOUT_MS),
            ("SLOW_MO_MS", SLOW_MO_MS),
        ]:
            with self.subTest(constant=name):
                self.assertGreater(val, 0, f"{name} must be positive")

    def test_bot_has_required_methods(self):
        """ReservationBot에 필수 메서드가 정의되어 있어야 함."""
        from src.reservation import ReservationBot
        for method in [
            "login", "pre_position", "attempt_reservation", "take_screenshot",
            "_fill_form", "_validate_dry_run", "_detect_result",
        ]:
            with self.subTest(method=method):
                self.assertTrue(hasattr(ReservationBot, method))

    def test_bot_init(self):
        """ReservationBot 인스턴스 생성 시 config가 설정되어야 함."""
        from src.reservation import ReservationBot
        cfg = self._make_config()
        bot = ReservationBot(cfg)
        self.assertEqual(bot.config, cfg)
        self.assertIsNone(bot._browser)
        self.assertIsNone(bot._page)


# ══════════════════════════════════════════════════════════════════════════════
# 커스텀 리포트 출력
# ══════════════════════════════════════════════════════════════════════════════

class ColorTextTestResult(unittest.TextTestResult):
    """테스트 결과를 색상으로 출력."""

    def addSuccess(self, test):
        super().addSuccess(test)
        if self.showAll:
            self.stream.writeln(f"{GREEN}  PASS{RESET}")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        if self.showAll:
            self.stream.writeln(f"{RED}  FAIL{RESET}")

    def addError(self, test, err):
        super().addError(test, err)
        if self.showAll:
            self.stream.writeln(f"{RED}  ERROR{RESET}")


def run_tests() -> dict:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestImports,
        TestConfig,
        TestTimingLogic,
        TestTelegramNotifier,
        TestReservationBotStructure,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    buf = StringIO()
    runner = unittest.TextTestRunner(
        stream=buf,
        verbosity=2,
        resultclass=ColorTextTestResult,
    )
    result = runner.run(suite)

    return {
        "output": buf.getvalue(),
        "total":   result.testsRun,
        "passed":  result.testsRun - len(result.failures) - len(result.errors),
        "failed":  len(result.failures),
        "errors":  len(result.errors),
        "failures_detail": result.failures + result.errors,
    }


def print_report(r: dict) -> None:
    sep = "=" * 60
    print(f"\n{BOLD}{sep}{RESET}")
    print(f"{BOLD}  캠핑 예약 봇 — 테스트 결과 리포트{RESET}")
    print(f"{BOLD}{sep}{RESET}\n")
    print(r["output"])
    print(f"{BOLD}{sep}{RESET}")

    status = f"{GREEN}PASSED{RESET}" if r["failed"] == 0 and r["errors"] == 0 else f"{RED}FAILED{RESET}"
    print(f"  결과:   {status}")
    print(f"  합계:   {r['total']}개")
    print(f"  {GREEN}통과{RESET}:   {r['passed']}개")
    if r["failed"]:
        print(f"  {RED}실패{RESET}:   {r['failed']}개")
    if r["errors"]:
        print(f"  {RED}오류{RESET}:   {r['errors']}개")
    print(f"{BOLD}{sep}{RESET}\n")

    if r["failures_detail"]:
        print(f"{BOLD}실패/오류 상세:{RESET}")
        for test, trace in r["failures_detail"]:
            print(f"\n  {RED}▸ {test}{RESET}")
            for line in trace.strip().split("\n")[-4:]:
                print(f"    {line}")

    # 파일로도 저장
    report_path = os.path.join(os.path.dirname(__file__), "report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("캠핑 예약 봇 테스트 결과 리포트\n")
        f.write(f"실행: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}\n")
        f.write("=" * 60 + "\n")
        f.write(r["output"])
        f.write("=" * 60 + "\n")
        f.write(f"합계: {r['total']}  통과: {r['passed']}  실패: {r['failed']}  오류: {r['errors']}\n")
        if r["failures_detail"]:
            f.write("\n실패/오류 상세:\n")
            for test, trace in r["failures_detail"]:
                f.write(f"\n▸ {test}\n{trace}\n")
    print(f"  리포트 저장: {report_path}\n")


if __name__ == "__main__":
    results = run_tests()
    print_report(results)
    sys.exit(0 if results["failed"] == 0 and results["errors"] == 0 else 1)
