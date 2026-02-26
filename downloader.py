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

# Ключевые слова, которые указывают на необходимость авторизации
AUTH_ERROR_KEYWORDS = (
    "login required",
    "rate-limit",
    "not available",
    "cookies",
    "authentication",
    "sign in",
)


def extract_urls(text: str) -> list[str]:
    """Извлекает все Instagram и Facebook ссылки из текста."""
    urls = []
    for pattern in ALL_PATTERNS:
        found = re.findall(pattern, text)
        urls.extend(found)
    return list(dict.fromkeys(urls))


def _is_auth_error(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(kw in msg for kw in AUTH_ERROR_KEYWORDS)


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


def _run_ydl(url: str, output_template: str, cookies_file: Optional[str]) -> tuple[dict | None, str | None]:
    """
    Runs yt-dlp synchronously.
    Returns (info_dict, error_message). One of them will be None.
    """
    opts = _get_ydl_opts(output_template, cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info, None
    except yt_dlp.utils.DownloadError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def _collect_files(info: dict, safe_name: str) -> list[Path]:
    """Collects downloaded file paths from yt-dlp info dict."""
    downloaded = []
    entries = info.get("entries") if "entries" in info else [info]

    for entry in (entries or []):
        if entry is None:
            continue
        filepath = entry.get("requested_downloads", [{}])[0].get("filepath")
        if filepath and Path(filepath).exists():
            downloaded.append(Path(filepath))
        else:
            ext = entry.get("ext", "mp4")
            autonumber = entry.get("autonumber", 1)
            candidate = DOWNLOAD_DIR / f"{safe_name}_{autonumber:05d}.{ext}"
            if candidate.exists():
                downloaded.append(candidate)

    if not downloaded:
        for f in DOWNLOAD_DIR.iterdir():
            if f.name.startswith(safe_name):
                downloaded.append(f)

    return downloaded


async def download_media(url: str, cookies_file: Optional[str] = None) -> list[Path]:
    """
    Downloads media from URL using yt-dlp.
    If the download fails with an auth error AND Playwright credentials are
    configured, automatically refreshes cookies and retries once.
    """
    safe_name = re.sub(r"[^\w]", "_", url[-30:])
    output_template = str(DOWNLOAD_DIR / f"{safe_name}_%(autonumber)s.%(ext)s")
    loop = asyncio.get_event_loop()

    # ── First attempt ────────────────────────────────────────────
    info, error = await loop.run_in_executor(
        None, _run_ydl, url, output_template, cookies_file
    )

    if info is not None:
        return _collect_files(info, safe_name)

    logger.error(f"yt-dlp ошибка для {url}: {error}")

    # ── Auto-refresh cookies via Playwright and retry ─────────────
    if error and _is_auth_error(error):
        refreshed = await _try_refresh_cookies()
        if refreshed and cookies_file:
            logger.info("Куки обновлены — повторная попытка скачивания...")
            info, error2 = await loop.run_in_executor(
                None, _run_ydl, url, output_template, cookies_file
            )
            if info is not None:
                return _collect_files(info, safe_name)
            logger.error(f"Повторная попытка также не удалась: {error2}")

    return []


async def _try_refresh_cookies() -> bool:
    """Tries to refresh cookies using Playwright. Returns True on success."""
    try:
        from downloader_playwright import refresh_session
        logger.info("Обновляю сессию через Playwright...")
        return await refresh_session()
    except ImportError:
        logger.warning("downloader_playwright не найден — авто-рефреш недоступен")
        return False
    except Exception as e:
        logger.error(f"Ошибка обновления сессии: {e}")
        return False


def cleanup(files: list[Path]) -> None:
    """Deletes temporary files after sending."""
    for f in files:
        try:
            if f.exists():
                f.unlink()
                logger.debug(f"Удалён файл: {f}")
        except Exception as e:
            logger.warning(f"Не удалось удалить {f}: {e}")
