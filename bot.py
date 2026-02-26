import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InputMediaVideo, InputMediaPhoto
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError

from downloader import extract_urls, download_media, cleanup

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")

# Webhook настройки
MODE = os.getenv("MODE", "polling").lower()          # "webhook" или "polling"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")           # https://yourdomain.com
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_LISTEN = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or secrets.token_hex(32)

# Максимальный размер файла для Telegram (50 МБ)
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Расширения для фото (всё остальное — видео)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик всех сообщений — ищет Instagram/Facebook ссылки."""
    message = update.message or update.channel_post
    if not message or not message.text:
        return

    text = message.text
    urls = extract_urls(text)

    if not urls:
        return

    logger.info(f"Найдено {len(urls)} ссылок в сообщении от {message.chat.title or message.chat.id}")

    for url in urls:
        await process_url(url, message, context)


async def process_url(url: str, message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Скачивает медиа по URL и отправляет в чат."""
    chat_id = message.chat_id
    reply_to = message.message_id

    logger.info(f"Скачиваю: {url}")

    # Статусное сообщение
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="⏬ Скачиваю...",
        reply_to_message_id=reply_to,
    )

    files = await download_media(url, COOKIES_FILE if os.path.exists(COOKIES_FILE) else None)

    if not files:
        await status_msg.edit_text("❌ Не удалось скачать. Возможно, контент приватный или ссылка недоступна.")
        return

    try:
        await _send_files(files, chat_id, reply_to, context)
        await status_msg.delete()
    except TelegramError as e:
        logger.error(f"Ошибка отправки: {e}")
        await status_msg.edit_text(f"❌ Ошибка при отправке: {e}")
    finally:
        cleanup(files)


async def _send_files(files: list[Path], chat_id: int, reply_to: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет скачанные файлы в Telegram."""
    valid_files = [f for f in files if f.exists() and f.stat().st_size <= MAX_FILE_SIZE_BYTES]
    oversized = [f for f in files if f.exists() and f.stat().st_size > MAX_FILE_SIZE_BYTES]

    if oversized:
        names = ", ".join(f.name for f in oversized)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Файлы слишком большие (>{MAX_FILE_SIZE_MB} МБ) и не могут быть отправлены: {names}",
            reply_to_message_id=reply_to,
        )

    if not valid_files:
        return

    if len(valid_files) == 1:
        await _send_single_file(valid_files[0], chat_id, reply_to, context)
    else:
        await _send_media_group(valid_files, chat_id, reply_to, context)


async def _send_single_file(file: Path, chat_id: int, reply_to: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет один файл."""
    with open(file, "rb") as f:
        if is_image(file):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                reply_to_message_id=reply_to,
            )
        else:
            await context.bot.send_video(
                chat_id=chat_id,
                video=f,
                reply_to_message_id=reply_to,
                supports_streaming=True,
            )
    logger.info(f"Отправлен файл: {file.name}")


async def _send_media_group(files: list[Path], chat_id: int, reply_to: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет несколько файлов как медиа-группу (альбом)."""
    media = []
    opened_files = []

    try:
        for file in files[:10]:  # Telegram позволяет max 10 в группе
            f = open(file, "rb")
            opened_files.append(f)
            if is_image(file):
                media.append(InputMediaPhoto(media=f))
            else:
                media.append(InputMediaVideo(media=f, supports_streaming=True))

        await context.bot.send_media_group(
            chat_id=chat_id,
            media=media,
            reply_to_message_id=reply_to,
        )
        logger.info(f"Отправлена медиа-группа из {len(media)} файлов")
    finally:
        for f in opened_files:
            f.close()

    # Если файлов больше 10 — отправляем остальные отдельно
    if len(files) > 10:
        await _send_media_group(files[10:], chat_id, reply_to, context)


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env файле!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    if MODE == "webhook":
        if not WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL не задан в .env файле (нужен для webhook режима)!")

        webhook_path = BOT_TOKEN
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{webhook_path}"

        logger.info(f"Запуск в режиме WEBHOOK: {full_webhook_url} (порт {WEBHOOK_PORT})")

        app.run_webhook(
            listen=WEBHOOK_LISTEN,
            port=WEBHOOK_PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        logger.info("Запуск в режиме POLLING...")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
