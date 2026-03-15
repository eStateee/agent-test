"""
Browser Actions — базовые действия браузера с умными ожиданиями.

Изменения:
- Заменены хардкод wait_for_timeout на wait_for_load_state
- Добавлен scroll_down / scroll_up / go_back
- Richer event logging
"""

from pathlib import Path
from typing import Optional, Dict, Any

from playwright.async_api import Page

from src.utils.logger import setup_logger

LOG_PATH = Path("logs") / "actions.ndjson"
LOG_PATH.parent.mkdir(exist_ok=True, parents=True)

logger = setup_logger("actions")


def _emit_event(event: Dict[str, Any]) -> None:
    """Логирование событий действий браузера."""
    logger.debug(f"Event: {event}")


class BrowserActions:
    """Базовые действия браузера с умными ожиданиями Playwright."""

    def __init__(self, page: Page):
        self.page = page

    async def navigate(self, url: str) -> Dict[str, Any]:
        """Переход по URL."""
        _emit_event({"type": "navigate:start", "url": url})
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Ожидаем стабилизации сети вместо хардкод задержки
            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # networkidle таймаут — не критично, страница уже загружена
            result = {
                "success": True,
                "url": str(self.page.url),
                "title": await self.page.title(),
            }
            _emit_event({"type": "navigate:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            _emit_event({"type": "navigate:error", **result})
            return result

    async def click(
        self, selector: str, wait_for_navigation: bool = False
    ) -> Dict[str, Any]:
        """Клик по элементу с умным ожиданием."""
        _emit_event({"type": "click:start", "selector": selector})
        try:
            url_before = self.page.url

            await self.page.click(selector, timeout=10000)

            if wait_for_navigation:
                try:
                    await self.page.wait_for_url(
                        lambda url: url != url_before, timeout=5000
                    )
                except Exception:
                    # URL не изменился — возможно AJAX-навигация
                    try:
                        await self.page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass
            else:
                # Вместо wait_for_timeout(500) — ждём стабилизации DOM
                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass

            result = {"success": True, "selector": selector}
            _emit_event({"type": "click:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "selector": selector, "error": str(e)}
            _emit_event({"type": "click:error", **result})
            return result

    async def type_text(
        self, selector: str, text: str, clear: bool = True
    ) -> Dict[str, Any]:
        """Ввод текста в поле."""
        _emit_event({"type": "type:start", "selector": selector, "text": text})
        try:
            if clear:
                await self.page.fill(selector, text)
            else:
                await self.page.type(selector, text, delay=50)
            result = {"success": True, "selector": selector, "text": text}
            _emit_event({"type": "type:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "selector": selector, "error": str(e)}
            _emit_event({"type": "type:error", **result})
            return result

    async def extract_text(self, selector: str) -> Dict[str, Any]:
        """Извлечение текста из элемента."""
        _emit_event({"type": "extract:start", "selector": selector})
        try:
            text = await self.page.text_content(selector, timeout=5000)
            result = {"success": True, "selector": selector, "text": text}
            _emit_event({"type": "extract:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "selector": selector, "error": str(e)}
            _emit_event({"type": "extract:error", **result})
            return result

    async def scroll_down(self) -> Dict[str, Any]:
        """Скролл вниз на один viewport."""
        _emit_event({"type": "scroll_down:start"})
        try:
            await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            result = {"success": True}
            _emit_event({"type": "scroll_down:done"})
            return result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            _emit_event({"type": "scroll_down:error", **result})
            return result

    async def scroll_up(self) -> Dict[str, Any]:
        """Скролл вверх на один viewport."""
        _emit_event({"type": "scroll_up:start"})
        try:
            await self.page.evaluate("window.scrollBy(0, -window.innerHeight)")
            result = {"success": True}
            _emit_event({"type": "scroll_up:done"})
            return result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            _emit_event({"type": "scroll_up:error", **result})
            return result

    async def go_back(self) -> Dict[str, Any]:
        """Переход назад в истории браузера."""
        _emit_event({"type": "go_back:start"})
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=10000)
            result = {
                "success": True,
                "url": str(self.page.url),
                "title": await self.page.title(),
            }
            _emit_event({"type": "go_back:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            _emit_event({"type": "go_back:error", **result})
            return result

    async def press_key(self, key: str) -> Dict[str, Any]:
        """Нажатие клавиши (Enter, Escape, Tab и т.д.)."""
        _emit_event({"type": "press_key:start", "key": key})
        try:
            await self.page.keyboard.press(key)
            result = {"success": True, "key": key}
            _emit_event({"type": "press_key:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "key": key, "error": str(e)}
            _emit_event({"type": "press_key:error", **result})
            return result

    async def wait(self, seconds: float) -> Dict[str, Any]:
        """Ожидание."""
        _emit_event({"type": "wait:start", "seconds": seconds})
        await self.page.wait_for_timeout(int(seconds * 1000))
        result = {"success": True, "seconds": seconds}
        _emit_event({"type": "wait:done", **result})
        return result

    async def screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Скриншот страницы."""
        _emit_event({"type": "screenshot:start", "path": path})
        try:
            if path:
                await self.page.screenshot(path=path, full_page=False)
            result = {"success": True, "path": path}
            _emit_event({"type": "screenshot:done", **result})
            return result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            _emit_event({"type": "screenshot:error", **result})
            return result
