from typing import List, Dict, Any


class HistoryManager:
    """Централизованное управление историей действий."""

    def __init__(self, max_items: int = 20):
        self.history: List[Dict[str, Any]] = []
        self.max_items = max_items

    def add_action(self, action: Dict, result: Dict):
        """Добавляет выполненное действие."""
        self.history.append({"action": action, "result": result})
        self._trim()

    def add_user_interaction(self, question: str, answer: str):
        """Добавляет диалог с пользователем."""
        self.history.append({"role": "assistant", "content": f"Вопрос: {question}"})
        self.history.append({"role": "user", "content": f"Ответ: {answer}"})
        self._trim()

    def format_for_llm(self, max_recent: int = 5) -> List[Dict]:
        """Форматирует последние N записей для LLM."""
        recent = (
            self.history[-max_recent:]
            if len(self.history) > max_recent
            else self.history
        )
        formatted = []

        for item in recent:
            if "role" in item:
                formatted.append(item)
            elif "action" in item:
                action = item["action"]
                result = item["result"]
                status = "успех" if result.get("success") else "ошибка"
                formatted.append(
                    {
                        "role": "assistant",
                        "content": f"Действие: {action['tool']}({action.get('params', {})})\nРезультат: {status}",
                    }
                )

        return formatted

    def _trim(self):
        """Ограничивает размер истории."""
        if len(self.history) > self.max_items:
            self.history = self.history[-self.max_items :]
