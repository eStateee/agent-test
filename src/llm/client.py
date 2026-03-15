"""
LLM Client — абстракция провайдеров с надёжным JSON-парсером.

Изменения:
- Robust JSON parser: снятие markdown-обёрток, trailing commas, одинарные кавычки
- Валидация структуры ответа (обязательные поля tool/params)
- Чёткое разделение transient/fatal ошибок API
"""

import json
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

import asyncio
import os

from openai import OpenAI
from anthropic import Anthropic

from src.utils.logger import setup_logger

logger = setup_logger("llm_client")


def _sanitize_text(s: Optional[str]) -> Optional[str]:
    """Удаляет/заменяет неподдерживаемые суррогатные символы."""
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    return s.encode("utf-8", "replace").decode("utf-8")


def _extract_json_from_response(content: str) -> Optional[Dict[str, Any]]:
    """
    Надёжное извлечение JSON из ответа LLM.

    Обрабатывает:
    - Чистый JSON
    - JSON в markdown-блоке ```json ... ```
    - Несколько JSON-объектов (берёт первый валидный с помощью raw_decode)
    """
    if not content or not content.strip():
        return None

    content = content.strip()

    # Сначала пытаемся найти ```json ... ```
    md_patterns = [
        r"```json\s*\n?(.*?)\n?\s*```",
        r"```\s*\n?(.*?)\n?\s*```",
    ]
    extracted_text = content
    for pattern in md_patterns:
        md_match = re.search(pattern, content, re.DOTALL)
        if md_match:
            extracted_text = md_match.group(1).strip()
            break

    # Ищем первый '{'
    start_idx = extracted_text.find('{')
    if start_idx == -1:
        # Если в markdown не нашлось, попробуем поискать во всем тексте (если markdown не было)
        start_idx = content.find('{')
        if start_idx == -1:
            return None
        text_to_parse = content[start_idx:]
    else:
        text_to_parse = extracted_text[start_idx:]

    decoder = json.JSONDecoder()
    
    # Попытка 1: raw_decode (идеально для склеенных {"tool":"A"}{"tool":"B"})
    try:
        parsed, idx = decoder.raw_decode(text_to_parse)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Попытка 2: очистка кавычек и trailing commas, если сырой JSON был поврежден
    # Берем кусок до первого балансирующего '}', но это сложно, попробуем просто regex
    json_match = re.search(r"\{.*\}", text_to_parse, re.DOTALL)
    if json_match:
        raw_json = json_match.group()
        fixed = raw_json.replace("'", '"')
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        try:
            parsed, _ = decoder.raw_decode(fixed)
            if isinstance(parsed, dict):
                logger.info("JSON исправлен автоматически (кавычки/trailing commas)")
                return parsed
        except json.JSONDecodeError:
            pass

        # Попытка 3: более агрессивная очистка
        aggressive = re.sub(r"//[^\n]*", "", fixed)
        try:
            parsed, _ = decoder.raw_decode(aggressive)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"Не удалось распарсить JSON от LLM: {e}. Сырой: {raw_json[:300]}")

    return None


def _validate_tool_response(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Валидация и нормализация ответа LLM.

    Гарантирует наличие полей 'tool' и 'params'.
    Обрабатывает альтернативные имена полей (action, arguments и т.д.).
    """
    # Нормализация имени инструмента
    tool = parsed.get("tool") or parsed.get("action") or parsed.get("function")
    if not tool:
        raise ValueError(f"Ответ LLM не содержит поле 'tool': {parsed}")

    # Нормализация параметров
    params = parsed.get("params") or parsed.get("arguments") or parsed.get("parameters") or {}
    if not isinstance(params, dict):
        params = {}

    return {"tool": str(tool), "params": params}


class LLMClient(ABC):
    """Абстрактный интерфейс для LLM провайдеров."""

    @abstractmethod
    async def generate_tool_call(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Генерирует tool_call на основе контекста."""
        pass

    @abstractmethod
    async def generate_json(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Генерирует произвольный валидный JSON на основе контекста."""
        pass


class MockLLMClient(LLMClient):
    """Мок-реализация для разработки без ключа."""

    def __init__(self):
        self.completed = False
        self.call_count = 0
        logger.info("Инициализирован MockLLMClient")

    async def generate_tool_call(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Возвращает предопределённые действия для тестирования."""
        if self.completed:
            return {"tool": "task_complete", "params": {"summary": "Already completed"}}

        self.call_count += 1
        logger.info(f"MockLLMClient call #{self.call_count}")

        mock_responses = [
            {"tool": "navigate", "params": {"url": "https://example.com"}},
            {"tool": "click", "params": {"selector": "button.login"}},
            {
                "tool": "type_text",
                "params": {
                    "selector": "input[name='email']",
                    "text": "test@example.com",
                },
            },
            {
                "tool": "task_complete",
                "params": {"summary": "Mock task completed successfully"},
            },
        ]

        idx = (self.call_count - 1) % len(mock_responses)
        response = mock_responses[idx]

        logger.info(f"Mock response: {response}")

    async def generate_json(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Для декомпозиции."""
        return {"subtasks": ["Mock task one", "Mock task two"]}


class RoutewayClient(LLMClient):  # ЮЗАЕМ ЕГО
    """Клиент для Routeway.ai API (OpenAI-совместимый)."""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, base_url="https://api.routeway.ai/v1")
        self.model = os.getenv("ROUTEWAY_MODEL", "gpt-oss-120b:free")
        logger.info(f"Инициализирован RoutewayClient с моделью {self.model}")

    async def generate_tool_call(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Эмулирует function calling через промпт с retry для transient ошибок."""
        max_retries = 3
        retry_delay = 2.0

        loop = asyncio.get_running_loop()

        system_prompt = _sanitize_text(system_prompt)
        sanitized_messages = []
        for m in messages:
            sanitized = dict(m)
            if "content" in sanitized:
                sanitized["content"] = _sanitize_text(sanitized.get("content"))
            sanitized_messages.append(sanitized)

        enhanced_prompt = _sanitize_text(f"""{system_prompt or ""}""")

        api_messages = [{"role": "system", "content": enhanced_prompt}]
        api_messages.extend(sanitized_messages)

        def sync_call():
            return self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                temperature=0.7,
            )

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await loop.run_in_executor(None, sync_call)

                if not response.choices:
                    msg = (
                        f"Routeway API вернул пустой ответ (choices=None). "
                        f"Модель: {self.model}. Попытка {attempt}/{max_retries}."
                    )
                    logger.warning(msg)
                    last_error = msg
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * attempt)
                        continue
                    raise ValueError(msg)

                content = response.choices[0].message.content

                if not content:
                    finish_reason = getattr(response.choices[0], "finish_reason", "unknown")
                    msg = (
                        f"Routeway API вернул пустой content. "
                        f"finish_reason={finish_reason}, модель: {self.model}. "
                        f"Попытка {attempt}/{max_retries}."
                    )
                    logger.warning(msg)
                    last_error = msg
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * attempt)
                        continue
                    raise ValueError(msg)

                # Robust JSON parser
                parsed = _extract_json_from_response(content)

                if parsed:
                    validated = _validate_tool_response(parsed)
                    return validated

                # Не удалось извлечь JSON — LLM ответила текстом
                logger.warning(f"LLM ответ без JSON, пробуем повтор. Ответ: {content[:200]}")

                if attempt < max_retries:
                    await asyncio.sleep(retry_delay * attempt)
                    continue

                # Последняя попытка — возвращаем system_error вместо ask_user
                return {
                    "tool": "system_error",
                    "params": {"error": f"JSON parse failed | Сырой текст: {content}"},
                }

            except (ValueError, KeyError) as e:
                logger.warning(f"Ошибка валидации ответа LLM (попытка {attempt}/{max_retries}): {e}")
                last_error = str(e)
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay * attempt)
                    continue
                return {
                    "tool": "system_error",
                    "params": {"error": f"Validation failed: {e}"},
                }
            except Exception as e:
                logger.error(f"Routeway API error (попытка {attempt}/{max_retries}): {e}")
                raise

        raise ValueError(last_error)

    async def generate_json(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Возвращает произвольный распарсенный JSON без tool/params валидации."""
        max_retries = 3
        retry_delay = 2.0
        loop = asyncio.get_running_loop()

        system_prompt = _sanitize_text(system_prompt)
        sanitized_messages = []
        for m in messages:
            sanitized = dict(m)
            if "content" in sanitized:
                sanitized["content"] = _sanitize_text(sanitized.get("content"))
            sanitized_messages.append(sanitized)

        enhanced_prompt = _sanitize_text(f"""{system_prompt or ""}""")
        api_messages = [{"role": "system", "content": enhanced_prompt}]
        api_messages.extend(sanitized_messages)

        def sync_call():
            return self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                temperature=0.7,
            )

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await loop.run_in_executor(None, sync_call)
                if not response.choices:
                    raise ValueError("Routeway API вернул пустой ответ")
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Routeway API вернул пустой content")

                parsed = _extract_json_from_response(content)
                if parsed:
                    return parsed
                    
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay * attempt)
                    continue
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay * attempt)
                    continue

        return {"error": last_error or "Не удалось распарсить JSON для генерации структуры"}


class OpenAIClient(LLMClient):  # НЕ ДОПИСАН ДО ПОСЛЕДНЕЙ РЕАЛИЗАЦИИ
    """Клиент для OpenAI API."""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        logger.info(f"Инициализирован OpenAIClient с моделью {self.model}")

    async def generate_tool_call(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Отправляет запрос к OpenAI API."""
        loop = asyncio.get_running_loop()

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in tools
        ]

        def sync_call():
            return self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                tools=openai_tools,
                tool_choice="auto",
            )

        try:
            response = await loop.run_in_executor(None, sync_call)

            if response.choices[0].message.tool_calls:
                tool_call = response.choices[0].message.tool_calls[0]
                return {
                    "tool": tool_call.function.name,
                    "params": json.loads(tool_call.function.arguments),
                }

            return {
                "tool": "system_error",
                "params": {
                    "error": response.choices[0].message.content or "No response"
                },
            }

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    async def generate_json(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Не реализовано полноценно, заглушка."""
        return {}


class ClaudeClient(LLMClient):  # НЕ ДОПИСАН ДО ПОСЛЕДНЕЙ РЕАЛИЗАЦИИ
    """Реальный клиент для Claude API."""

    def __init__(self, api_key: str, use_agentrouter: bool = True):
        if use_agentrouter:
            self.client = Anthropic(
                api_key=api_key, base_url="https://agentrouter.org/"
            )
            logger.info("Инициализирован ClaudeClient через AgentRouter")
        else:
            self.client = Anthropic(api_key=api_key)
            logger.info("Инициализирован ClaudeClient (прямой)")

        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-1")
        logger.info("Инициализирован ClaudeClient")

    async def generate_tool_call(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Отправляет запрос к Claude API без блокировки event loop."""
        loop = asyncio.get_running_loop()

        def sync_call():
            return self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt or "You are a browser automation agent.",
                messages=messages,
                tools=tools,
            )

        try:
            response = await loop.run_in_executor(None, sync_call)

            if getattr(response, "stop_reason", None) == "tool_use":
                tool_use = next(
                    (
                        block
                        for block in getattr(response, "content", [])
                        if getattr(block, "type", None) == "tool_use"
                    ),
                    None,
                )
                if tool_use:
                    return {"tool": tool_use.name, "params": tool_use.input}

            text_block = next(
                (
                    block
                    for block in getattr(response, "content", [])
                    if hasattr(block, "text")
                ),
                None,
            )
            return {
                "tool": "system_error",
                "params": {
                    "error": text_block.text if text_block else "No response"
                },
            }

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

    async def generate_json(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Не реализовано полноценно, заглушка."""
        return {}


def create_llm_client(
    provider: str = "mock", api_key: Optional[str] = None
) -> LLMClient:
    """Фабрика для создания LLM клиента."""

    if provider == "mock":
        return MockLLMClient()

    elif provider == "claude":
        if not api_key:
            api_key = os.getenv("AGENTROUTER_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
            use_agentrouter = bool(os.getenv("AGENTROUTER_API_KEY"))
        if not api_key:
            raise ValueError("Claude API KEY not provided")
        return ClaudeClient(api_key, use_agentrouter)

    elif provider == "openai":
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API KEY not provided")
        return OpenAIClient(api_key)

    elif provider == "routeway":
        if not api_key:
            api_key = os.getenv("ROUTEWAY_API_KEY")
        if not api_key:
            raise ValueError("Routeway API KEY not provided")
        return RoutewayClient(api_key)

    else:
        raise ValueError(f"Unknown provider: {provider}")
