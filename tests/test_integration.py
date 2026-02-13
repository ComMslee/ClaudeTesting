"""
통합 테스트 — 실제 Chromium 브라우저로 사이트에 접속

테스트 항목:
  1. 로그인 성공 여부 (실제 자격증명)
  2. 로그인 후 예약 페이지 로드 여부
  3. Dry-run 전체 흐름 (로그인 → 폼 입력 확인 → 제출 안 함)

실행 조건:
  - .env 파일에 SUWON_USERNAME, SUWON_PASSWORD 가 설정되어 있어야 함
  - playwright install chromium 이 완료된 환경 (Docker 내부 권장)
  - 누락 시 전체 스킵

실행:
  python -m pytest tests/test_integration.py -v
  python tests/test_integration.py          # 직접 실행 (리포트 출력)

주의:
  --dry-run 이므로 실제 예약 신청은 절대 하지 않습니다.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from io import StringIO

import pytz

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KST = pytz.timezone("Asia/Seoul")

# ─── 건너뛰기 조건 ─────────────────────────────────────────────────────────────

def _credentials_available() -> bool:
    """SUWON_USERNAME, SUWON_PASSWORD 가 .env 또는 환경에 설정되었는지 확인."""
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.getenv("SUWON_USERNAME") and os.getenv("SUWON_PASSWORD"))


def _playwright_available() -> bool:
    """playwright + chromium 이 사용 가능한지 확인."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


SKIP_REASON_CREDS = "SUWON_USERNAME / SUWON_PASSWORD 미설정 — .env 파일을 확인하세요."
SKIP_REASON_PW    = "playwright 패키지 없음 — pip install playwright 후 playwright install chromium 실행"

_creds_ok = _credentials_available()
_pw_ok    = _playwright_available()
_can_run  = _creds_ok and _pw_ok


def _make_test_config():
    """통합 테스트용 Config 객체 생성 (실제 자격증명 사용)."""
    from src.config import load_config
    from dotenv import load_dotenv
    load_dotenv()
    # TELEGRAM_* 이 없어도 테스트는 진행할 수 있도록 더미 값 주입
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "000:DUMMY")
    os.environ.setdefault("TELEGRAM_CHAT_ID",   "0")
    os.environ.setdefault("CAMPING_DATE",        "2099-01-01")  # 먼 미래 날짜
    os.environ.setdefault("CAMPSITE_NAME",       "A구역")
    return load_config()


# ══════════════════════════════════════════════════════════════════════════════
# 통합 테스트 클래스
# ══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_can_run, SKIP_REASON_CREDS if not _creds_ok else SKIP_REASON_PW)
class TestIntegration(unittest.IsolatedAsyncioTestCase):
    """
    실제 Playwright Chromium 을 사용한 통합 테스트.
    모든 테스트는 dry-run 이므로 실제 예약 제출은 발생하지 않습니다.
    """

    @classmethod
    def setUpClass(cls):
        cls.config = _make_test_config()

    # ─── 테스트 1: 로그인 ──────────────────────────────────────────────────────

    async def test_01_login_success(self):
        """
        실제 자격증명으로 로그인 후 로그인 페이지가 아닌 다른 URL로
        리다이렉트되는지 확인합니다.
        """
        from src.reservation import ReservationBot, LOGIN_URL

        async with ReservationBot(self.config) as bot:
            result = await bot.login()
            screenshot = await bot.take_screenshot("integration_login")

        with self.subTest("로그인 반환값"):
            self.assertTrue(
                result,
                msg=f"login() 이 False 를 반환했습니다.\n"
                    f"스크린샷: {screenshot}\n"
                    f"자격증명과 선택자(SELECTORS['login_id'] 등)를 확인하세요."
            )

    # ─── 테스트 2: 예약 페이지 로드 ───────────────────────────────────────────

    async def test_02_reservation_page_loads(self):
        """
        로그인 후 예약 페이지(campingApplySimple.do)가 정상 로드되는지 확인합니다.
        페이지 타이틀 또는 URL 에 'camping' 이 포함되어야 합니다.
        """
        from src.reservation import ReservationBot, RESERVATION_URL

        async with ReservationBot(self.config) as bot:
            login_ok = await bot.login()
            self.assertTrue(login_ok, "로그인 실패 — 이 테스트를 진행할 수 없습니다.")

            prepos_ok = await bot.pre_position()
            current_url = bot._page.url
            page_title  = await bot._page.title()
            screenshot  = await bot.take_screenshot("integration_reservation_page")

        with self.subTest("pre_position 반환값"):
            self.assertTrue(
                prepos_ok,
                msg=f"pre_position() 이 False 를 반환했습니다.\n"
                    f"URL: {current_url}\n스크린샷: {screenshot}"
            )

        with self.subTest("URL 확인"):
            self.assertIn(
                "camping", current_url.lower(),
                msg=f"예약 페이지 URL 에 'camping' 이 없습니다: {current_url}"
            )

    # ─── 테스트 3: Dry-run 전체 흐름 ──────────────────────────────────────────

    async def test_03_dry_run_full_flow(self):
        """
        dry_run=True 로 attempt_reservation() 을 호출합니다.
        - 실제 제출은 하지 않습니다.
        - 감지된 폼 필드 목록이 반환되어야 합니다.
        - 스크린샷이 저장되어야 합니다.
        """
        import os
        from pathlib import Path
        from src.reservation import ReservationBot

        async with ReservationBot(self.config) as bot:
            login_ok = await bot.login()
            self.assertTrue(login_ok, "로그인 실패 — 이 테스트를 진행할 수 없습니다.")

            prepos_ok = await bot.pre_position()
            self.assertTrue(prepos_ok, "예약 페이지 로드 실패")

            success, message = await bot.attempt_reservation(dry_run=True)
            screenshot = await bot.take_screenshot("integration_dryrun")

        with self.subTest("dry-run 반환값"):
            self.assertTrue(
                success,
                msg=f"dry_run attempt_reservation() 이 실패했습니다.\n사유: {message}"
            )

        with self.subTest("DRY-RUN 태그 확인"):
            self.assertIn(
                "DRY-RUN", message,
                msg=f"dry-run 메시지에 'DRY-RUN' 태그가 없습니다: {message}"
            )

        with self.subTest("스크린샷 저장 확인"):
            self.assertTrue(
                Path(screenshot).exists(),
                msg=f"스크린샷 파일이 없습니다: {screenshot}"
            )

        # 감지된 필드 정보를 출력 (참고용)
        print(f"\n  [dry-run 결과]\n  {message.replace(chr(10), chr(10) + '  ')}")


# ══════════════════════════════════════════════════════════════════════════════
# 커스텀 리포트 출력 (직접 실행 시)
# ══════════════════════════════════════════════════════════════════════════════

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def run_and_report() -> int:
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromTestCase(TestIntegration)
    buf    = StringIO()

    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)

    passed  = result.testsRun - len(result.failures) - len(result.errors)
    skipped = len(result.skipped)
    failed  = len(result.failures) + len(result.errors)

    sep = "=" * 60
    print(f"\n{BOLD}{sep}{RESET}")
    print(f"{BOLD}  캠핑 예약 봇 — 통합 테스트 결과{RESET}")
    print(f"{BOLD}{sep}{RESET}\n")
    print(buf.getvalue())
    print(f"{BOLD}{sep}{RESET}")

    if not _creds_ok:
        print(f"  {YELLOW}SKIPPED{RESET}  자격증명 미설정 — {SKIP_REASON_CREDS}")
    elif not _pw_ok:
        print(f"  {YELLOW}SKIPPED{RESET}  Playwright 없음 — {SKIP_REASON_PW}")
    else:
        status = f"{GREEN}PASSED{RESET}" if failed == 0 else f"{RED}FAILED{RESET}"
        print(f"  결과:   {status}")
        print(f"  합계:   {result.testsRun}개")
        print(f"  {GREEN}통과{RESET}:   {passed}개")
        if skipped:
            print(f"  {YELLOW}스킵{RESET}:   {skipped}개")
        if failed:
            print(f"  {RED}실패{RESET}:   {failed}개")

    print(f"{BOLD}{sep}{RESET}\n")

    # 파일 저장
    report_path = os.path.join(os.path.dirname(__file__), "report_integration.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("캠핑 예약 봇 통합 테스트 결과\n")
        f.write(f"실행: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}\n")
        f.write(f"자격증명: {'설정됨' if _creds_ok else '미설정'}\n")
        f.write(f"Playwright: {'사용가능' if _pw_ok else '없음'}\n")
        f.write(sep + "\n")
        f.write(buf.getvalue())
        f.write(sep + "\n")
        f.write(f"합계: {result.testsRun}  통과: {passed}  실패: {failed}  스킵: {skipped}\n")
    print(f"  리포트 저장: {report_path}\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_and_report())
