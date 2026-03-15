"""
Browser Controller — обёртка над Playwright с автовосстановлением.

Изменения:
- Автоматическое восстановление при краше процесса браузера
- Сохранение/восстановление cookies при пересоздании контекста
- Улучшенная _ensure_page_valid() с проверкой browser alive
"""

import json
from pathlib import Path
from typing import Optional, List, Dict

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from src.browser.actions import BrowserActions
from src.utils.logger import setup_logger
from config.settings import (
    BROWSER_SLOW_MO,
    BROWSER_VIEWPORT,
)

logger = setup_logger("browser_controller")


class MockBrowserActions:
    """Минимальная мок-реализация интерфейса действий для dry_run."""

    async def navigate(self, url: str):
        return {"success": True, "url": url, "title": "MOCK"}

    async def click(self, selector: str, wait_for_navigation: bool = False):
        return {"success": True, "selector": selector}

    async def type_text(self, selector: str, text: str, clear: bool = True):
        return {"success": True, "selector": selector, "text": text}

    async def extract_text(self, selector: str):
        return {"success": True, "selector": selector, "text": "MOCK_TEXT"}

    async def scroll_down(self):
        return {"success": True}

    async def scroll_up(self):
        return {"success": True}

    async def go_back(self):
        return {"success": True, "url": "mock://back", "title": "MOCK"}

    async def press_key(self, key: str):
        return {"success": True, "key": key}

    async def wait(self, seconds: float):
        return {"success": True, "seconds": seconds}

    async def screenshot(self, path: Optional[str] = None):
        return {"success": True, "path": path}


class BrowserController:
    """Обёртка над Playwright с поддержкой режимов и автовосстановления."""

    def __init__(
        self,
        headless: bool = False,
        dry_run: bool = False,
        cookies_file: str = "cookies.txt",
    ):
        self.headless = headless
        self.dry_run = dry_run
        self.cookies_file = Path(cookies_file)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.actions: Optional[BrowserActions] = None
        self._last_url: Optional[str] = None  # для восстановления

    def _load_cookies(self) -> Optional[List[Dict]]:
        """Загружает cookies из файла (формат Netscape/JSON)."""
        if not self.cookies_file.exists():
            logger.info(f"Файл cookies не найден: {self.cookies_file}")
            return None

        try:
            with open(self.cookies_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

                if content.startswith("["):
                    cookies = json.loads(content)
                    logger.info(f"Загружено {len(cookies)} cookies (JSON)")
                    return cookies

                cookies = []
                for line in content.split("\n"):
                    if not line or line.startswith("#"):
                        continue

                    parts = line.strip().split("\t")
                    if len(parts) < 7:
                        continue

                    domain, _, path, secure, expires, name, value = parts[:7]

                    cookies.append(
                        {
                            "name": name,
                            "value": value,
                            "domain": domain,
                            "path": path,
                            "expires": int(expires) if expires.isdigit() else -1,
                            "httpOnly": False,
                            "secure": secure.upper() == "TRUE",
                            "sameSite": "Lax",
                        }
                    )

                logger.info(f"Загружено {len(cookies)} cookies (Netscape)")
                return cookies if cookies else None

        except Exception as e:
            logger.error(f"Ошибка загрузки cookies: {e}")
            return None

    async def _save_cookies(self) -> None:
        """Сохраняет текущие cookies контекста в файл (для восстановления)."""
        if not self.context:
            return
        try:
            cookies = await self.context.cookies()
            if cookies:
                with open(self.cookies_file, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                logger.debug(f"Сохранено {len(cookies)} cookies")
        except Exception as e:
            logger.warning(f"Не удалось сохранить cookies: {e}")

    async def _is_browser_alive(self) -> bool:
        """Проверяет, жив ли процесс браузера."""
        if not self.browser:
            return False
        try:
            # Простая проверка — попытка получить список контекстов
            _ = self.browser.contexts
            return True
        except Exception:
            return False

    async def _ensure_page_valid(self) -> None:
        """Проверяет валидность страницы и восстанавливает при необходимости."""
        if self.dry_run:
            return

        # Проверяем, жив ли браузер
        if not await self._is_browser_alive():
            logger.warning("Процесс браузера упал, полное пересоздание...")
            await self._full_restart()
            return

        try:
            if not self.page or self.page.is_closed():
                logger.warning("Страница закрыта, создаём новую")
                await self._create_new_page()
                # Восстанавливаем последний URL
                if self._last_url and self._last_url != "about:blank":
                    try:
                        await self.page.goto(self._last_url, wait_until="domcontentloaded", timeout=15000)
                        logger.info(f"Восстановлен URL: {self._last_url}")
                    except Exception as nav_err:
                        logger.warning(f"Не удалось восстановить URL: {nav_err}")
                return
            # Проверяем доступность страницы
            url = self.page.url
            self._last_url = url
        except Exception as e:
            logger.warning(f"Страница недоступна ({e}), создаём новую")
            if self.page:
                try:
                    await self.page.close()
                except Exception:
                    pass
            await self._create_new_page()

    async def _full_restart(self) -> None:
        """Полное пересоздание браузера, контекста и страницы."""
        # Сохраняем URL для восстановления
        saved_url = self._last_url

        # Очистка старого
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

        self.browser = None
        self.context = None
        self.page = None
        self.actions = None

        # Пересоздание
        await self.start()

        # Восстановление URL
        if saved_url and saved_url != "about:blank" and self.page:
            try:
                await self.page.goto(saved_url, wait_until="domcontentloaded", timeout=15000)
                logger.info(f"Восстановлен URL после рестарта: {saved_url}")
            except Exception as e:
                logger.warning(f"Не удалось восстановить URL после рестарта: {e}")

    async def _create_new_page(self) -> None:
        """Создаёт новую страницу в существующем контексте."""
        if self.context:
            self.page = await self.context.new_page()
            self.actions = BrowserActions(self.page)
            logger.info("Создана новая страница")

    async def start(self) -> None:
        """Запускает браузер с загрузкой cookies."""

        if self.dry_run:
            logger.info("DRY RUN MODE: используется MockBrowserActions")
            self.actions = MockBrowserActions()
            return

        if self.browser:
            await self._ensure_page_valid()
            return

        logger.info(f"Запуск браузера (headless={self.headless})")

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.firefox.launch(
            headless=self.headless,
            slow_mo=BROWSER_SLOW_MO,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
            ],
        )

        self.context = await self.browser.new_context(
            viewport=BROWSER_VIEWPORT,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

        cookies = self._load_cookies()
        if cookies:
            await self.context.add_cookies(cookies)
            logger.info("Cookies добавлены в контекст")

        await self._create_new_page()
        logger.info("Браузер запущен")

    async def stop(self) -> None:
        """Останавливает браузер с сохранением cookies."""

        if self.dry_run:
            return

        logger.info("Остановка браузера")

        # Сохраняем cookies перед остановкой
        await self._save_cookies()

        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        logger.info("Браузер остановлен")

    def get_actions(self) -> BrowserActions:
        """Возвращает интерфейс действий."""

        if not self.actions:
            raise RuntimeError("Browser not started. Call await start() first")
        return self.actions
