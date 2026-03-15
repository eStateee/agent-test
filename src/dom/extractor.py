"""
DOM Extractor — сбор интерактивных элементов через JS-инъекцию.

Вся логика парсинга выполняется ОДНИМ вызовом page.evaluate(),
что сокращает время извлечения с ~3-5 секунд до <100 мс.
"""

import re
from typing import List, Dict, Any

from playwright.async_api import Page

from src.utils.logger import setup_logger
from src.utils.security import validate_selector

logger = setup_logger("dom_extractor")

# JavaScript-скрипт, инжектируемый в браузер.
# Собирает все интерактивные элементы и генерирует селекторы за один проход.
JS_EXTRACT_SCRIPT = """
() => {
    const MAX_TEXT_LEN = 80;
    const results = [];
    const seen = new Set();

    function safeText(el) {
        try {
            const t = (el.innerText || el.textContent || '').trim();
            return t.replace(/[\\n\\r]+/g, ' ').replace(/\\s+/g, ' ').slice(0, MAX_TEXT_LEN);
        } catch { return ''; }
    }

    function getSelector(el) {
        // 1. data-testid / data-qa
        const testId = el.getAttribute('data-testid');
        if (testId) return `[data-testid='${testId}']`;
        const qa = el.getAttribute('data-qa');
        if (qa) return `[data-qa='${qa}']`;

        // 2. id
        const id = el.getAttribute('id');
        if (id && id.trim()) return `#${id}`;

        // 3. name
        const name = el.getAttribute('name');
        if (name) return `[name='${name}']`;

        // 4. aria-label
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return `[aria-label='${ariaLabel}']`;

        // 5. text content для кликабельных элементов
        const tag = el.tagName.toLowerCase();
        if (['button', 'a', 'div', 'li', 'tr'].includes(tag)) {
            const text = safeText(el);
            if (text && text.length > 1 && text.length < 60) {
                const escaped = text.replace(/"/g, '\\\\"');
                return `${tag}:has-text("${escaped}")`;
            }
        }

        // 6. class + nth-of-type
        const cls = el.className;
        if (cls && typeof cls === 'string') {
            const firstClass = cls.trim().split(/\\s+/)[0];
            if (firstClass && !firstClass.includes('{')) {
                let nth = 1;
                let sib = el.previousElementSibling;
                while (sib) {
                    if (sib.className === el.className) nth++;
                    sib = sib.previousElementSibling;
                }
                return `${tag}.${firstClass}:nth-of-type(${nth})`;
            }
        }

        // 7. tag + nth-of-type
        let nth = 1;
        let sib = el.previousElementSibling;
        while (sib) {
            if (sib.tagName === el.tagName) nth++;
            sib = sib.previousElementSibling;
        }
        return `${tag}:nth-of-type(${nth})`;
    }

    function isVisible(el) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function addElement(el, type, extra) {
        const sel = getSelector(el);
        if (!sel || seen.has(sel)) return;
        seen.add(sel);
        const entry = { type, selector: sel, ...extra };
        results.push(entry);
    }

    // --- Кнопки ---
    document.querySelectorAll("button, input[type='button'], input[type='submit']").forEach(el => {
        if (!isVisible(el)) return;
        const text = safeText(el);
        if (text) addElement(el, 'button', { text });
    });

    // --- Ссылки (основной контент) ---
    document.querySelectorAll("main a, article a, [role='main'] a").forEach(el => {
        if (!isVisible(el)) return;
        const text = safeText(el);
        const href = el.getAttribute('href') || '';
        if (text) addElement(el, 'link', { text, href });
    });

    // --- Навигация ---
    document.querySelectorAll("nav a, aside a, [role='navigation'] a, [class*='folder'], [class*='menu']").forEach(el => {
        if (!isVisible(el)) return;
        const text = safeText(el);
        if (text) addElement(el, 'nav', { text });
    });

    // --- Поля ввода ---
    document.querySelectorAll("input[type='text'], input[type='email'], input[type='search'], input[type='password'], textarea").forEach(el => {
        if (!isVisible(el)) return;
        const placeholder = el.getAttribute('placeholder') || el.getAttribute('name') || 'text field';
        addElement(el, 'input', { placeholder: placeholder.slice(0, 50) });
    });

    // --- Чекбоксы и радио ---
    document.querySelectorAll("input[type='checkbox'], input[type='radio']").forEach(el => {
        if (!isVisible(el)) return;
        const cbType = (el.getAttribute('type') || '').toLowerCase();
        let labelText = '';

        const cbId = el.getAttribute('id');
        if (cbId) {
            const label = document.querySelector(`label[for='${cbId}']`);
            if (label) labelText = safeText(label);
        }
        if (!labelText) {
            const parentLabel = el.closest('label');
            if (parentLabel) labelText = safeText(parentLabel);
        }

        addElement(el, cbType === 'checkbox' ? 'checkbox' : 'radio', { label: labelText });
    });

    // --- Элементы списков ---
    document.querySelectorAll("div[role='listitem'], li, div[data-message-id], tr[data-message-id]").forEach(el => {
        if (!isVisible(el)) return;
        const text = safeText(el);
        if (!text) return;
        const child = el.querySelector('a, button');
        if (child) {
            addElement(child, 'listitem', { text: text.slice(0, 120) });
        } else {
            addElement(el, 'listitem', { text: text.slice(0, 120) });
        }
    });

    return results;
}
"""


class DOMExtractor:
    """Извлечение интерактивных элементов через JS-инъекцию (один IPC-вызов)."""

    def __init__(self, page: Page):
        self.page = page

    async def extract_interactive_elements(
        self, max_elements: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Извлекает кликабельные элементы, формы, ссылки.

        Весь парсинг выполняется в контексте браузера через page.evaluate(),
        что исключает N IPC-вызовов и снижает латентность до ~50-100 мс.
        """
        try:
            raw_elements = await self.page.evaluate(JS_EXTRACT_SCRIPT)
        except Exception as e:
            logger.error(f"JS DOM extraction failed: {e}")
            return []

        if not isinstance(raw_elements, list):
            logger.warning(f"JS extraction returned non-list: {type(raw_elements)}")
            return []

        # Серверная фильтрация: validate_selector + safe_text + лимит
        elements = []
        for elem in raw_elements:
            selector = elem.get("selector", "")
            if not selector or not validate_selector(selector):
                continue

            # Нормализация текстовых полей
            for key in ("text", "placeholder", "label"):
                if key in elem:
                    elem[key] = self._safe_text(elem[key])

            elements.append(elem)
            if len(elements) >= max_elements:
                break

        logger.info(f"Extracted {len(elements)} elements (raw: {len(raw_elements)})")
        return elements

    @staticmethod
    def _safe_text(text: Any) -> str:
        """Нормализация текста: заменяем некорректные суррогаты."""
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        return text.encode("utf-8", "replace").decode("utf-8")
