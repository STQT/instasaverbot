"""
Playwright-based session manager for Instagram/Facebook.

Responsibilities:
- Login to Instagram with username/password
- Maintain a persistent browser session on disk
- Export cookies in Netscape format so yt-dlp can use them
- Auto re-login when the session expires
"""

import asyncio
import logging
import os
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger(__name__)

IG_USERNAME = os.getenv("IG_USERNAME", "")
IG_PASSWORD = os.getenv("IG_PASSWORD", "")

SESSION_DIR = Path(".session")
SESSION_DIR.mkdir(exist_ok=True)
SESSION_FILE = SESSION_DIR / "instagram_session.json"
COOKIES_FILE = Path(os.getenv("COOKIES_FILE", "cookies.txt"))

INSTAGRAM_DOMAINS = [
    "https://www.instagram.com",
    "https://i.instagram.com",
    "https://graph.instagram.com",
]
FACEBOOK_DOMAINS = [
    "https://www.facebook.com",
    "https://m.facebook.com",
    "https://graph.facebook.com",
]


# ──────────────────────────────────────────────────────────────
# Browser / Context helpers
# ──────────────────────────────────────────────────────────────

def _browser_args() -> dict:
    return {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    }


def _context_kwargs() -> dict:
    return {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "locale": "en-US",
        "timezone_id": "Asia/Tashkent",
    }


async def _dismiss_popups(page: Page) -> None:
    """Dismisses common Instagram/browser popups."""
    selectors = [
        "text=Allow all cookies",
        "text=Accept all",
        "text=Only allow essential cookies",
        "text=Not Now",
        "text=Not now",
        "text=Не сейчас",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# Instagram login
# ──────────────────────────────────────────────────────────────

async def _do_login(page: Page, context: BrowserContext) -> bool:
    """Performs Instagram login. Returns True on success."""
    logger.info("Авторизация в Instagram через Playwright...")

    await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await _dismiss_popups(page)

    # Instagram removed name attributes — use type selectors
    username_selectors = [
        'input[name="username"]',
        'input[type="text"]',
        'input[aria-label*="username" i]',
        'input[aria-label*="phone" i]',
    ]
    password_selectors = [
        'input[name="password"]',
        'input[type="password"]',
    ]
    submit_selectors = [
        'button[type="submit"]',
        'div[role="button"]:has-text("Log in")',
        'button:has-text("Log in")',
        'button:has-text("Log In")',
    ]

    # Fill username
    filled_user = False
    for sel in username_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.fill(IG_USERNAME)
                filled_user = True
                break
        except Exception:
            pass

    if not filled_user:
        logger.error("Поле username не найдено — Instagram мог изменить структуру страницы")
        return False

    await page.wait_for_timeout(300)

    # Fill password
    for sel in password_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.fill(IG_PASSWORD)
                break
        except Exception:
            pass

    await page.wait_for_timeout(300)

    # Click submit
    clicked = False
    for sel in submit_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        logger.error("Кнопка входа не найдена")
        return False

    # Wait for redirect away from login page
    try:
        await page.wait_for_url(
            lambda url: "login" not in url and "challenge" not in url,
            timeout=15000,
        )
    except Exception:
        logger.warning("Редирект после логина не произошёл — проверьте credentials")

    await page.wait_for_timeout(2000)

    # Dismiss "Save login info" / "onetap" / notifications prompts
    onetap_selectors = [
        'button:has-text("Not Now")',
        'button:has-text("Not now")',
        'button:has-text("Skip")',
        'div[role="button"]:has-text("Not Now")',
        'div[role="button"]:has-text("Not now")',
    ]
    for sel in onetap_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

    if "login" in page.url and "onetap" not in page.url:
        logger.error("Авторизация не удалась — неверный логин/пароль или требуется 2FA")
        return False

    await context.storage_state(path=str(SESSION_FILE))
    logger.info(f"Сессия Instagram сохранена. URL: {page.url}")
    return True


async def _is_session_valid(page: Page) -> bool:
    """Navigates to Instagram and checks if we're still logged in."""
    try:
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        return "login" not in page.url
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Cookie export (Netscape format for yt-dlp)
# ──────────────────────────────────────────────────────────────

def _write_netscape_cookies(cookies: list[dict], path: Path) -> None:
    """Writes cookies in Netscape/Mozilla format that yt-dlp understands."""
    lines = ["# Netscape HTTP Cookie File\n", "# https://curl.se/docs/http-cookies.html\n\n"]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path_val = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = str(int(c.get("expires", 0) or 0))
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(f"{domain}\t{flag}\t{path_val}\t{secure}\t{expires}\t{name}\t{value}\n")

    path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Куки сохранены в {path} ({len(cookies)} шт.)")


async def _export_cookies(context: BrowserContext) -> None:
    all_domains = INSTAGRAM_DOMAINS + FACEBOOK_DOMAINS
    cookies = await context.cookies(all_domains)
    _write_netscape_cookies(cookies, COOKIES_FILE)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

async def refresh_session() -> bool:
    """
    Main entry point.
    Logs in (or reuses existing session) and exports fresh cookies for yt-dlp.
    Returns True if cookies were successfully written.
    """
    if not IG_USERNAME or not IG_PASSWORD:
        logger.warning("IG_USERNAME / IG_PASSWORD не заданы — Playwright авторизация отключена")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_browser_args())

        kwargs = _context_kwargs()
        if SESSION_FILE.exists():
            kwargs["storage_state"] = str(SESSION_FILE)

        context = await browser.new_context(**kwargs)
        page = await context.new_page()

        try:
            if SESSION_FILE.exists():
                valid = await _is_session_valid(page)
                if not valid:
                    logger.info("Сессия устарела — повторный логин...")
                    SESSION_FILE.unlink(missing_ok=True)
                    await context.close()
                    # Re-create context without stale session
                    context = await browser.new_context(**_context_kwargs())
                    page = await context.new_page()
                    success = await _do_login(page, context)
                    if not success:
                        return False
                else:
                    logger.info("Сессия Instagram активна.")
            else:
                success = await _do_login(page, context)
                if not success:
                    return False

            await _export_cookies(context)
            return True

        except Exception as e:
            logger.error(f"Playwright ошибка: {e}")
            return False
        finally:
            await context.close()
            await browser.close()


def refresh_session_sync() -> bool:
    """Синхронная обёртка для вызова из не-async кода."""
    return asyncio.run(refresh_session())
