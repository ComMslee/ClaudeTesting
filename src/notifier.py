import logging
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Sends success/failure notifications to a Telegram chat.
    Uses python-telegram-bot v20+ async API (outbound-only, no polling).
    All public methods never raise — notification failures must not stop the main flow.
    """

    def __init__(self, token: str, chat_id: str) -> None:
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def send_message(self, text: str) -> bool:
        """Send a plain HTML-formatted text message. Returns True on success."""
        try:
            async with self.bot:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode="HTML",
                )
            return True
        except TelegramError as e:
            logger.error(f"Telegram send_message failed: {e}")
            return False

    async def send_photo(self, caption: str, screenshot_path: str) -> bool:
        """
        Send a screenshot as a photo with an HTML caption.
        Falls back to text-only message if the file is not found.
        Returns True on success.
        """
        if not Path(screenshot_path).exists():
            logger.warning(f"Screenshot not found: {screenshot_path} — sending text only")
            return await self.send_message(caption)
        try:
            async with self.bot:
                with open(screenshot_path, "rb") as f:
                    await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=f,
                        caption=caption,
                        parse_mode="HTML",
                    )
            return True
        except TelegramError as e:
            logger.error(f"Telegram send_photo failed: {e}")
            return await self.send_message(f"{caption}\n(스크린샷 전송 실패)")

    async def notify_startup(self, target_time_str: str) -> None:
        """Notify that the bot has started and is waiting for the reservation window."""
        await self.send_message(
            f"🏕 <b>캠핑 예약 봇 시작</b>\n"
            f"대기 중 → <b>{target_time_str} KST</b>\n"
            f"해당 시각에 자동 예약을 시도합니다."
        )

    async def notify_success(self, message: str) -> None:
        """Send a success notification."""
        await self.send_message(f"✅ <b>예약 성공!</b>\n\n{message}")

    async def notify_failure(self, reason: str, screenshot_path: str | None = None) -> None:
        """Send a failure notification, optionally with a screenshot attached."""
        text = f"❌ <b>예약 실패</b>\n\n사유: {reason}"
        if screenshot_path:
            await self.send_photo(caption=text, screenshot_path=screenshot_path)
        else:
            await self.send_message(text)
