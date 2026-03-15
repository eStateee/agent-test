"""
Planner — планирование и декомпозиция задач с LLM.

Изменения:
- Реальный decompose_task через LLM-вызов
- Verification step: LLM анализирует изменения после действия
"""

import json
import re
from typing import List, Dict, Any

from src.agent.state import TaskState, SubTask, TaskStatus
from src.agent.tools import TOOLS_SCHEMA
from src.llm.prompts import SYSTEM_PROMPT, DECOMPOSE_PROMPT
from src.utils.logger import setup_logger

logger = setup_logger("planner")


class Planner:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def decompose_task(self, main_task: str) -> TaskState:
        """
        Декомпозиция задачи через LLM.

        Для простых задач (одно действие) вернёт одну подзадачу.
        Для сложных (бронирование, многошаговые) — несколько.
        """
        # Сначала спрашиваем LLM, нужна ли декомпозиция
        decompose_prompt = DECOMPOSE_PROMPT.format(task=main_task)

        messages = [{"role": "user", "content": decompose_prompt}]

        try:
            response = await self.llm_client.generate_json(
                messages=messages,
                system_prompt=(
                    "Ты — планировщик задач для браузерного агента. "
                    "Отвечай СТРОГО в формате JSON."
                ),
            )

            # Если вернулась строка-обманка или ask_user - пытаемся извлечь как есть
            content = json.dumps(response) if isinstance(response, dict) else str(response)

            subtasks = self._parse_subtasks(content, main_task)
            if subtasks:
                logger.info(f"Декомпозиция: {len(subtasks)} подзадач")
                return TaskState(main_task=main_task, subtasks=subtasks)

        except Exception as e:
            logger.warning(f"Декомпозиция не удалась, используем простой режим: {e}")

        # Fallback: одна задача = одна подзадача
        return TaskState(
            main_task=main_task,
            subtasks=[SubTask(id="1", description=main_task)],
        )

    def _parse_subtasks(self, content: str, main_task: str) -> List[SubTask]:
        """Парсит ответ LLM в список подзадач."""
        if not content:
            return []

        # Пытаемся извлечь JSON
        try:
            # Снимаем markdown
            clean = content.strip()
            md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", clean, re.DOTALL)
            if md_match:
                clean = md_match.group(1).strip()

            data = json.loads(clean)

            # Формат: {"subtasks": ["step1", "step2"]} или {"subtasks": [{"description": "step1"}]}
            raw_subtasks = data if isinstance(data, list) else data.get("subtasks", [])

            subtasks = []
            for i, item in enumerate(raw_subtasks, 1):
                if isinstance(item, str):
                    desc = item
                elif isinstance(item, dict):
                    desc = item.get("description") or item.get("step") or item.get("task") or str(item)
                else:
                    desc = str(item)

                subtasks.append(SubTask(id=str(i), description=desc.strip()))

            # Если парсинг дал слишком много или ноль подзадач — fallback
            if 1 <= len(subtasks) <= 10:
                return subtasks

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"Не удалось спарсить подзадачи из JSON: {e}")

        return []

    async def next_action(
        self, task_state: TaskState, current_page_state: str, history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Определяет следующее действие с учётом текущей подзадачи."""

        current_subtask = task_state.get_current_subtask()

        if not current_subtask:
            current_subtask = task_state.get_next_pending_subtask()
            if current_subtask:
                task_state.current_subtask_id = current_subtask.id
                current_subtask.status = TaskStatus.IN_PROGRESS
                logger.info(f"Начало подзадачи: {current_subtask.description}")
            else:
                return {
                    "tool": "task_complete",
                    "params": {"summary": self._generate_summary(task_state)},
                }

        collected_data_text = self._format_collected_data(task_state.collected_data)
        subtask_context = ""
        if current_subtask.context:
            subtask_context = "\n**Контекст подзадачи:**\n"
            for key, value in current_subtask.context.items():
                subtask_context += f"- {key}: {value}\n"

        context = f"""
**Основная задача:** {task_state.main_task}
**Текущая подзадача ({current_subtask.id}):** {current_subtask.description}{subtask_context}
**Выполненные подзадачи:**
{self._format_completed_subtasks(task_state)}
**Собранные данные:**
{collected_data_text}
**Состояние страницы:**
{current_page_state}
        """

        llm_history = self._format_history_for_llm(history)

        messages = [{"role": "user", "content": context}] + llm_history

        tools = self._get_tools_schema()

        logger.debug(f"Запрос LLM для подзадачи: {current_subtask.description}")

        MAX_SELF_CORRECT = 3
        response = None
        for attempt in range(MAX_SELF_CORRECT):
            response = await self.llm_client.generate_tool_call(
                messages=messages, tools=tools, system_prompt=SYSTEM_PROMPT
            )
            
            if response.get("tool") == "system_error":
                err = response.get("params", {}).get("error", "Unknown format error")
                logger.warning(f"Self-correction вызван. Ошибка: {err}. Попытка: {attempt+1}/{MAX_SELF_CORRECT}")
                
                # Добавляем в историю (контекст текущего запроса) сообщение об ошибке
                messages.append({"role": "assistant", "content": json.dumps(response)})
                messages.append({
                    "role": "user", 
                    "content": "ВНИМАНИЕ: Твой предыдущий ответ был невалидным или содержал несколько действий. ВЕРНИ СТРОГО ОДИН JSON-ОБЪЕКТ."
                })
                continue
            break
            
        if response is None:
            # Fallback на случай пустого исхода (что маловероятно)
            response = {"tool": "system_error", "params": {"error": "All self-correction attempts failed"}}

        response["_subtask_id"] = current_subtask.id

        logger.debug(f"Получен ответ: {response}")
        return response

    def _format_collected_data(self, data: Dict[str, Any]) -> str:
        """Форматирует собранные данные для LLM."""
        if not data:
            return "Нет"

        lines = []
        for key, value in data.items():
            value_str = str(value)[:200]
            lines.append(f"- {key}: {value_str}")

        return "\n".join(lines)

    def _format_history_for_llm(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Конвертирует историю в формат LLM."""
        formatted = []

        for item in history:
            if "role" in item:
                formatted.append(item)
            elif "action" in item:
                action = item["action"]
                result = item["result"]

                action_text = f"Действие: {action['tool']}({action.get('params', {})})"
                result_text = (
                    f"Результат: {'успех' if result.get('success') else 'ошибка'}"
                )

                if result.get("error"):
                    result_text += f" - {result['error']}"

                formatted.append(
                    {"role": "assistant", "content": f"{action_text}\n{result_text}"}
                )

        return formatted

    def _format_completed_subtasks(self, task_state: TaskState) -> str:
        """Форматирует выполненные подзадачи."""
        completed = [
            st for st in task_state.subtasks if st.status == TaskStatus.COMPLETED
        ]
        if not completed:
            return "Нет"

        result = []
        for st in completed:
            result.append(f"✓ {st.id}. {st.description}")
            if st.result:
                result.append(f"   Результат: {st.result}")
        return "\n".join(result)

    def _generate_summary(self, task_state: TaskState) -> str:
        """Генерирует итоговый отчёт."""
        summary_parts = [f"Выполнена задача: {task_state.main_task}", ""]

        for st in task_state.subtasks:
            if st.status == TaskStatus.COMPLETED:
                summary_parts.append(f"✓ {st.description}")
                if st.result and "data" in st.result:
                    summary_parts.append(f"  → {st.result['data']}")

        if task_state.collected_data:
            summary_parts.append("\nСобранные данные:")
            for key, value in task_state.collected_data.items():
                summary_parts.append(f"- {key}: {value}")

        return "\n".join(summary_parts)

    def _get_tools_schema(self):
        return TOOLS_SCHEMA
