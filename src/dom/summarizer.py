"""
DOM Summarizer — сжатие состояния DOM с учётом лимита токенов.

Изменения:
- Ленивая загрузка tiktoken без thread (кэширование после первого вызова)
- Упрощённый fallback для подсчёта токенов
"""

from typing import List, Dict, Any

from config.settings import MAX_STATE_TOKENS
from src.utils.logger import setup_logger

logger = setup_logger("dom_summarizer")

# Кэш энкодера — загружается один раз при первом вызове
_tiktoken_encoding = None
_tiktoken_loaded = False


def _get_encoding():
    """Ленивая загрузка tiktoken-энкодера (один раз за процесс)."""
    global _tiktoken_encoding, _tiktoken_loaded
    if _tiktoken_loaded:
        return _tiktoken_encoding
    _tiktoken_loaded = True
    try:
        import tiktoken
        _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        logger.info("tiktoken encoder loaded successfully")
    except Exception as e:
        logger.warning(f"tiktoken unavailable, using word-based counting: {e}")
        _tiktoken_encoding = None
    return _tiktoken_encoding


class DOMSummarizer:
    """Сжатие состояния DOM с учётом лимита токенов."""

    def compress(
        self, elements: List[Dict[str, Any]], max_tokens: int = MAX_STATE_TOKENS
    ) -> str:
        """Сжимает список элементов в строку, укладываясь в лимит токенов."""

        if not elements:
            return "Страница пуста или элементы не найдены."

        grouped = {"button": [], "link": [], "input": [], "nav": [], "listitem": []}
        for elem in elements:
            elem_type = elem.get("type", "unknown")
            if elem_type in grouped:
                grouped[elem_type].append(elem)

        def _build_text(groups: Dict[str, List]) -> str:
            parts: List[str] = []
            total = sum(len(v) for v in groups.values())
            parts.append(
                f"Элементы: {total} (кнопки={len(groups['button'])}, "
                f"ссылки={len(groups['link'])}, поля={len(groups['input'])}, "
                f"навигация={len(groups['nav'])}, списки={len(groups['listitem'])})"
            )
            parts.append("")

            formatters = {
                "button": ("Кнопки", 50, lambda b: f"- [{b.get('text','').strip()[:60]}] `{b.get('selector','')}`"),
                "link": ("Ссылки", 50, lambda l: f"- [{l.get('text','').strip()[:60]}]({l.get('href','')}) `{l.get('selector','')}`"),
                "input": ("Поля ввода", 50, lambda i: f"- {i.get('placeholder', 'text field')[:60]} `{i.get('selector','')}`"),
                "nav": ("Навигация", 40, lambda n: f"- [{n.get('text','').strip()[:60]}] `{n.get('selector','')}`"),
                "listitem": ("Пункты списка", 80, lambda li: f"- {li.get('text','').strip()[:120]} `{li.get('selector','')}`"),
            }

            for key, (title, limit, fmt) in formatters.items():
                items = groups[key][:limit]
                if items:
                    parts.append(f"**{title}:**")
                    for it in items:
                        parts.append(fmt(it))
                    parts.append("")

            return "\n".join(parts).strip()

        state_text = _build_text(grouped)

        # Обрезка по токенам
        if self.count_tokens(state_text) > max_tokens:
            priorities = ["listitem", "nav", "link", "button", "input"]
            total_before = sum(len(v) for v in grouped.values())

            while self.count_tokens(state_text) > max_tokens:
                is_reduced = False
                for p in priorities:
                    if grouped.get(p) and len(grouped[p]) > 0:
                        grouped[p].pop()
                        is_reduced = True
                        break
                if not is_reduced:
                    break
                state_text = _build_text(grouped)

            total_after = sum(len(v) for v in grouped.values())
            if total_after < total_before:
                state_text += "\n\n...(список элементов обрезан)"

        return state_text

    @staticmethod
    def count_tokens(text: str) -> int:
        """Подсчитывает количество токенов в тексте."""
        enc = _get_encoding()
        if enc:
            return len(enc.encode(text))
        # fallback: ~4 символа ≈ 1 токен
        return len(text) // 4
