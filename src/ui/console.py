"""
Console UI — премиальный консольный интерфейс на базе rich.

Заменяет хаотичные print() на аккуратные панели, спиннеры и прогресс-бары.
"""

import sys

from src.utils.logger import setup_logger

logger = setup_logger("ui")

# Проверяем наличие rich
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.status import Status
    from rich import box

    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    logger.info("rich не установлен, используется plain-text UI")


class ConsoleUI:
    """Консольный интерфейс агента."""

    def __init__(self):
        if HAS_RICH:
            self.console = Console(force_terminal=True)
        else:
            self.console = None

    def task_header(self, task: str):
        """Заголовок задачи."""
        if self.console:
            self.console.print()
            self.console.print(
                Panel(
                    f"[bold white]{task}[/]",
                    title="[bold cyan]📋 ЗАДАЧА[/]",
                    border_style="cyan",
                    box=box.DOUBLE,
                    padding=(0, 2),
                )
            )
        else:
            print(f"\n{'=' * 70}")
            print(f"📋 ЗАДАЧА: {task}")
            print(f"{'=' * 70}")

    def plan_display(self, subtasks):
        """Отображение плана подзадач."""
        if not subtasks or len(subtasks) <= 1:
            return

        if self.console:
            table = Table(
                title="📝 План выполнения",
                box=box.ROUNDED,
                border_style="blue",
                show_header=True,
                header_style="bold blue",
            )
            table.add_column("#", style="dim", width=4)
            table.add_column("Подзадача", style="white")
            table.add_column("Статус", width=10, justify="center")

            for st in subtasks:
                status_icon = {
                    "pending": "⏳",
                    "in_progress": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                }.get(st.status.value, "⏳")
                table.add_row(st.id, st.description, status_icon)

            self.console.print(table)
        else:
            print(f"\n📝 План ({len(subtasks)} подзадач):")
            for st in subtasks:
                print(f"   {st.id}. {st.description}")

    def iteration_header(self, iteration: int, max_iter: int, completed: int, total: int, subtask_desc: str = ""):
        """Заголовок итерации."""
        if self.console:
            progress_bar = self._make_progress_bar(completed, total)
            header_text = (
                f"[bold]Итерация {iteration}/{max_iter}[/]  │  "
                f"Прогресс: {progress_bar} {completed}/{total}"
            )
            if subtask_desc:
                header_text += f"\n[dim]🎯 {subtask_desc}[/]"

            self.console.print()
            self.console.print(
                Panel(
                    header_text,
                    border_style="yellow",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )
        else:
            print(f"\n{'─' * 50}")
            print(f"🔄 Итерация {iteration}/{max_iter}  │  Прогресс: {completed}/{total}")
            if subtask_desc:
                print(f"🎯 Подзадача: {subtask_desc}")
            print(f"{'─' * 50}")

    def thinking(self):
        """Спиннер 'LLM думает'."""
        if self.console:
            return self.console.status("[bold yellow]🧠 LLM думает...[/]", spinner="dots")
        return _DummyContext()

    def action_display(self, tool: str, params_str: str):
        """Отображение выбранного действия."""
        if self.console:
            self.console.print(f"  [bold green]🛠️  {tool}[/]([dim]{params_str}[/])")
        else:
            print(f"🛠️  Действие: {tool}({params_str})")

    def success(self, message: str = "Успешно"):
        """Успех."""
        if self.console:
            self.console.print(f"  [green]✅ {message}[/]")
        else:
            print(f"✅ {message}")

    def error(self, message: str):
        """Ошибка."""
        if self.console:
            self.console.print(f"  [red]❌ {message}[/]")
        else:
            print(f"❌ Ошибка: {message}")

    def warning(self, message: str):
        """Предупреждение."""
        if self.console:
            self.console.print(f"  [yellow]⚠️  {message}[/]")
        else:
            print(f"⚠️  {message}")

    def info(self, message: str):
        """Информация."""
        if self.console:
            self.console.print(f"  [dim]{message}[/]")
        else:
            print(f"   {message}")

    def task_complete(self, summary: str):
        """Задача завершена."""
        if self.console:
            self.console.print()
            self.console.print(
                Panel(
                    f"[bold white]{summary}[/]",
                    title="[bold green]✅ ЗАДАЧА ЗАВЕРШЕНА[/]",
                    border_style="green",
                    box=box.DOUBLE,
                    padding=(0, 2),
                )
            )
        else:
            print(f"\n{'=' * 70}")
            print(f"✅ ЗАДАЧА ЗАВЕРШЕНА")
            print(f"📝 Итог: {summary}")
            print(f"{'=' * 70}\n")

    def limit_reached(self, max_iterations: int):
        """Лимит итераций."""
        if self.console:
            self.console.print()
            self.console.print(
                Panel(
                    f"Достигнут лимит в {max_iterations} итераций",
                    title="[bold yellow]⚠️  ЛИМИТ ИТЕРАЦИЙ[/]",
                    border_style="yellow",
                    box=box.DOUBLE,
                    padding=(0, 2),
                )
            )
        else:
            print(f"\n{'=' * 70}")
            print(f"⚠️  ЛИМИТ ИТЕРАЦИЙ ({max_iterations})")
            print(f"{'=' * 70}\n")

    def ask_user(self, question: str) -> str:
        """Запрос у пользователя."""
        if self.console:
            self.console.print()
            self.console.print(
                Panel(
                    f"[bold]{question}[/]",
                    title="[bold blue]🤔 Агент спрашивает[/]",
                    border_style="blue",
                    padding=(0, 2),
                )
            )
        else:
            print(f"\n🤔 Агент спрашивает: {question}")

        return input("Ваш ответ: ").strip()

    def retry_notice(self, attempt: int, tool: str, params_str: str):
        """Уведомление о повторе."""
        if self.console:
            self.console.print(f"  [yellow]🔄 Повтор ({attempt}): {tool}({params_str})[/]")
        else:
            print(f"   🔄 Повтор с обновлённым DOM: {tool}({params_str})")

    def extracted_text(self, text: str, max_len: int = 200):
        """Отображение извлечённого текста."""
        display = text[:max_len] + "..." if len(text) > max_len else text
        if self.console:
            self.console.print(f"  [dim]📄 {display}[/]")
        else:
            print(f"   📄 Текст: {display}")

    @staticmethod
    def _make_progress_bar(completed: int, total: int, width: int = 15) -> str:
        """Создаёт текстовый прогресс-бар."""
        if total == 0:
            return "░" * width
        filled = int(width * completed / total)
        return "█" * filled + "░" * (width - filled)


class _DummyContext:
    """Заглушка для контекстного менеджера когда rich недоступен."""

    def __enter__(self):
        print("🧠 Планирование...")
        return self

    def __exit__(self, *args):
        pass
