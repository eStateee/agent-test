"""
Agent Orchestrator — основной цикл агента.

Использует ConsoleUI для премиального вывода.
Stale Element retry с пере-извлечением DOM.
Поддержка расширенного набора действий.
"""

from typing import Optional

from src.agent.state import TaskState, TaskStatus
from src.agent.history_manager import HistoryManager
from src.browser.controller import BrowserController
from src.agent.planner import Planner
from src.dom.extractor import DOMExtractor
from src.dom.summarizer import DOMSummarizer
from src.ui.console import ConsoleUI
from src.utils.logger import setup_logger
from src.utils.security import (
    is_destructive_action,
    ask_user_confirmation,
    validate_selector,
)
from config.settings import MAX_ITERATIONS

logger = setup_logger("orchestrator")

MAX_STALE_RETRIES = 2


class AgentOrchestrator:
    def __init__(
        self,
        llm_client,
        headless=False,
        dry_run=False,
        cookies_file: str = "cookies.txt",
    ):
        self.llm_client = llm_client
        self.browser = BrowserController(
            headless=headless, dry_run=dry_run, cookies_file=cookies_file
        )
        self.planner = Planner(llm_client)
        self.extractor = None
        self.summarizer = None
        self.history_manager = HistoryManager()
        self.dry_run = dry_run
        self.task_state: Optional[TaskState] = None
        self.ui = ConsoleUI()

    async def _ensure_ready(self):
        """Убеждаемся, что браузер и экстрактор готовы к работе."""
        if getattr(self.browser, "page", None) is None:
            await self.browser.start()
        else:
            await self.browser._ensure_page_valid()

        if not self.dry_run and self.browser.page:
            self.extractor = DOMExtractor(self.browser.page)

    async def _get_page_state(self) -> str:
        """Извлекает и сжимает состояние DOM."""
        if self.dry_run or not getattr(self.browser, "page", None):
            return "DRY RUN: нет реального DOM"

        if (
            not self.extractor
            or getattr(self.extractor, "page", None) != self.browser.page
        ):
            self.extractor = DOMExtractor(self.browser.page)

        try:
            elements = await self.extractor.extract_interactive_elements()
            compressed = self.summarizer.compress(elements)
            current_url = str(self.browser.page.url) if self.browser.page else "unknown"
            return f"URL: {current_url}\n{compressed}"
        except Exception as e:
            logger.warning(f"Не удалось извлечь DOM: {e}")
            try:
                await self.browser._ensure_page_valid()
                if self.browser.page:
                    self.extractor = DOMExtractor(self.browser.page)
                    return f"URL: {self.browser.page.url}\n(DOM недоступен после восстановления)"
            except Exception as recovery_err:
                logger.error(f"Не удалось восстановить страницу: {recovery_err}")
            return "Страница недоступна или была закрыта."

    async def execute_task(self, task: str):
        await self._ensure_ready()

        if not self.dry_run and self.browser.page:
            logger.info(f"Текущая страница: {self.browser.page.url}")

        self.summarizer = DOMSummarizer()

        # UI: заголовок задачи
        self.ui.task_header(task)

        self.task_state = await self.planner.decompose_task(task)

        # UI: план подзадач
        self.ui.plan_display(self.task_state.subtasks)

        for i in range(MAX_ITERATIONS):
            self.task_state.iteration = i + 1

            completed = sum(
                1
                for st in self.task_state.subtasks
                if st.status == TaskStatus.COMPLETED
            )
            total = len(self.task_state.subtasks)
            current_subtask = self.task_state.get_current_subtask()

            # UI: заголовок итерации
            self.ui.iteration_header(
                i + 1, MAX_ITERATIONS, completed, total,
                current_subtask.description if current_subtask else "",
            )

            # Получаем состояние страницы
            page_state = await self._get_page_state()

            # Планирование с LLM-спиннером
            with self.ui.thinking():
                action = await self.planner.next_action(
                    task_state=self.task_state,
                    current_page_state=page_state,
                    history=self.history_manager.history,
                )

            tool_name = action.get("tool", "unknown")
            params = action.get("params", {})

            # UI: отображение действия
            self.ui.action_display(tool_name, self._format_params(params))

            # --- task_complete ---
            if tool_name == "task_complete":
                current_subtask = self.task_state.get_current_subtask()
                if current_subtask and current_subtask.status == TaskStatus.IN_PROGRESS:
                    self.task_state.update_subtask(
                        current_subtask.id,
                        status=TaskStatus.COMPLETED,
                        result=params,
                    )

                summary = params.get("summary", "Задача завершена")
                self.ui.task_complete(summary)
                logger.info(f"Задача завершена: {summary}")
                return

            # --- ask_user ---
            if tool_name == "ask_user":
                question = params.get("question", "")
                user_answer = self.ui.ask_user(question)

                current_subtask = self.task_state.get_current_subtask()
                if current_subtask:
                    current_subtask.context["user_input"] = user_answer
                    self.task_state.collected_data[
                        f"user_answer_{current_subtask.id}"
                    ] = user_answer

                self.history_manager.add_user_interaction(question, user_answer)
                continue

            # --- Destructive actions ---
            if is_destructive_action(tool_name, params):
                confirmed = ask_user_confirmation(tool_name, params)
                if not confirmed:
                    logger.info(f"Пользователь отменил: {tool_name}")
                    self.ui.warning("Действие отменено пользователем")
                    continue

            # --- Выполнение с retry при Stale Element ---
            result = await self._execute_with_stale_retry(action)

            if result.get("success"):
                self.ui.success()

                subtask_id = action.get("_subtask_id")
                if subtask_id:
                    self.task_state.update_subtask(
                        subtask_id,
                        status=TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED,
                        result=result,
                    )

                if tool_name == "extract_text" and "text" in result:
                    extracted = result["text"]
                    self.ui.extracted_text(extracted)
                    key = params.get("selector", "unknown")
                    self.task_state.collected_data[key] = extracted
                    current_subtask = self.task_state.get_current_subtask()
                    if current_subtask:
                        current_subtask.context[f"extracted_{key}"] = extracted
            else:
                error_msg = result.get("error", "Неизвестная ошибка")
                self.ui.error(error_msg)
                logger.warning(f"Ошибка действия: {error_msg}")

            self.history_manager.add_action(action, result)

        self.ui.limit_reached(MAX_ITERATIONS)
        logger.warning("Достигнут лимит итераций")

    async def _execute_with_stale_retry(self, action: dict) -> dict:
        """Выполняет действие с retry при Stale Element."""
        for attempt in range(MAX_STALE_RETRIES + 1):
            result = await self._execute_action(action)

            if result.get("success"):
                return result

            error = result.get("error", "")
            is_stale = any(
                marker in error.lower()
                for marker in [
                    "element is not attached",
                    "element not found",
                    "timeout",
                    "waiting for selector",
                    "disposed",
                    "detached",
                ]
            )

            if not is_stale or attempt >= MAX_STALE_RETRIES:
                return result

            logger.warning(
                f"Stale element (попытка {attempt + 1}/{MAX_STALE_RETRIES}), "
                f"пере-извлекаем DOM..."
            )

            await self.browser._ensure_page_valid()
            if self.browser.page:
                self.extractor = DOMExtractor(self.browser.page)

            page_state = await self._get_page_state()
            new_action = await self.planner.next_action(
                task_state=self.task_state,
                current_page_state=page_state,
                history=self.history_manager.history,
            )

            new_tool = new_action.get("tool", "")
            if new_tool in ("task_complete", "ask_user"):
                return {"success": True, "tool": new_tool, "params": new_action.get("params", {})}

            action = new_action
            self.ui.retry_notice(
                attempt + 1,
                new_tool,
                self._format_params(new_action.get("params", {})),
            )

        return result

    async def _execute_action(self, action: dict) -> dict:
        """Выполняет действие и возвращает результат."""
        actions = self.browser.get_actions()
        tool = action.get("tool", "")
        params = action.get("params", {})

        required_params = {
            "navigate": ["url"],
            "click": ["selector"],
            "type_text": ["selector", "text"],
            "extract_text": ["selector"],
            "wait": ["seconds"],
            "task_complete": ["summary"],
        }

        if tool in required_params:
            missing = [p for p in required_params[tool] if p not in params]
            if missing:
                error_msg = (
                    f"Действие '{tool}' требует параметры: {missing}. "
                    f"Получены: {list(params.keys())}"
                )
                logger.warning(error_msg)
                return {"success": False, "error": error_msg}

        selector = params.get("selector")
        if selector and not validate_selector(selector):
            return {
                "success": False,
                "error": f"Небезопасный селектор: {selector}",
            }

        if tool == "navigate":
            return await actions.navigate(params["url"])
        elif tool == "click":
            wait_nav = params.get("wait_for_navigation", False)
            return await actions.click(params["selector"], wait_for_navigation=wait_nav)
        elif tool == "type_text":
            clear = params.get("clear", True)
            return await actions.type_text(
                params["selector"], params["text"], clear=clear
            )
        elif tool == "extract_text":
            return await actions.extract_text(params["selector"])
        elif tool == "scroll_down":
            return await actions.scroll_down()
        elif tool == "scroll_up":
            return await actions.scroll_up()
        elif tool == "go_back":
            return await actions.go_back()
        elif tool == "press_key":
            key = params.get("key", "Enter")
            return await actions.press_key(key)
        elif tool == "wait":
            return await actions.wait(params["seconds"])
        elif tool == "screenshot":
            path = params.get("path")
            return await actions.screenshot(path)
        elif tool == "task_complete":
            return {"success": True, "summary": params["summary"]}
        else:
            return {"success": False, "error": f"Неизвестный инструмент: {tool}"}

    @staticmethod
    def _format_params(params: dict) -> str:
        """Форматирует параметры для вывода в консоль (кратко)."""
        if not params:
            return ""
        parts = []
        for k, v in params.items():
            v_str = str(v)
            if len(v_str) > 60:
                v_str = v_str[:57] + "..."
            parts.append(f"{k}={v_str}")
        return ", ".join(parts)

    async def shutdown(self):
        await self.browser.stop()
