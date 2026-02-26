import os
import re
import asyncio
import logging
from pathlib import Path
from typing import Optional

import yt_dlp

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

INSTAGRAM_PATTERNS = [
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|stories|tv)/[\w-]+",
    r"https?://(?:www\.)?instagram\.com/[\w.]+/(?:p|reel|tv)/[\w-]+",
    r"https?://instagr\.am/(?:p|reel)/[\w-]+",
]

FACEBOOK_PATTERNS = [
    r"https?://(?:www\.)?facebook\.com/(?:watch|video|reel)s?(?:/\?v=\d+|/[\w.-]+/videos/\d+|/\d+)",
    r"https?://(?:www\.)?facebook\.com/[\w.]+/(?:videos|reels)/[\w-]+",
    r"https?://(?:www\.)?facebook\.com/share/[rv]/[\w-]+",
    r"https?://fb\.watch/[\w-]+",
    r"https?://m\.facebook\.com/(?:watch|story\.php)",
]

ALL_PATTERNS = INSTAGRAM_PATTERNS + FACEBOOK_PATTERNS


def extract_urls(text: str) -> list[str]:
    """Извлекает все Instagram и Facebook ссылки из текста."""
    urls = []
    for pattern in ALL_PATTERNS:
        found = re.findall(pattern, text)
        urls.extend(found)
    return list(dict.fromkeys(urls))  # убираем дубликаты


def _get_ydl_opts(output_path: str, cookies_file: Optional[str] = None) -> dict:
    opts = {
        "outtmpl": output_path,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )
        },
    }
    if cookies_file and os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
    return opts


async def download_media(url: str, cookies_file: Optional[str] = None) -> list[Path]:
    """
    Скачивает медиа по URL.
    Возвращает список скачанных файлов (видео или картинки).
    """
    safe_name = re.sub(r"[^\w]", "_", url[-30:])
    output_template = str(DOWNLOAD_DIR / f"{safe_name}_%(autonumber)s.%(ext)s")

    ydl_opts = _get_ydl_opts(output_template, cookies_file)

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info

    try:
        info = await loop.run_in_executor(None, _download)
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp ошибка для {url}: {e}")
        return []
    except Exception as e:
        logger.error(f"Неожиданная ошибка при скачивании {url}: {e}")
        return []

    downloaded = []

    if info is None:
        return downloaded

    # Обработка плейлиста (например, альбомы или несколько историй)
    entries = info.get("entries") if "entries" in info else [info]

    for entry in entries:
        if entry is None:
            continue
        filepath = entry.get("requested_downloads", [{}])[0].get("filepath")
        if filepath and Path(filepath).exists():
            downloaded.append(Path(filepath))
        else:
            # Попробуем найти файл по шаблону
            ext = entry.get("ext", "mp4")
            autonumber = entry.get("autonumber", 1)
            candidate = DOWNLOAD_DIR / f"{safe_name}_{autonumber:05d}.{ext}"
            if candidate.exists():
                downloaded.append(candidate)

    if not downloaded:
        # Последняя попытка — ищем любые новые файлы в папке
        for f in DOWNLOAD_DIR.iterdir():
            if f.name.startswith(safe_name):
                downloaded.append(f)

    return downloaded


def cleanup(files: list[Path]) -> None:
    """Удаляет временные файлы после отправки."""
    for f in files:
        try:
            if f.exists():
                f.unlink()
                logger.debug(f"Удалён файл: {f}")
        except Exception as e:
            logger.warning(f"Не удалось удалить {f}: {e}")
