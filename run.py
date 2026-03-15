import asyncio
from pathlib import Path
from src.agent.orchestrator import AgentOrchestrator
from src.llm.client import create_llm_client
from src.utils.logger import setup_logger
import os

from src.ui.console import ConsoleUI

logger = setup_logger("main")


async def main():
    provider = os.getenv("LLM_PROVIDER", "mock")
    llm_client = create_llm_client(provider)

    # Путь к cookies.txt рядом с run.py
    cookies_path = Path(__file__).parent / "cookies.txt"

    orchestrator = AgentOrchestrator(
        llm_client=llm_client,
        headless=False,
        dry_run=False,
        cookies_file=str(cookies_path),
    )

    await orchestrator.browser.start()

    ui = ConsoleUI()

    try:
        while True:
            ui.console.print("\n[bold cyan]🤖 Введите задачу для агента (или `exit` для выхода): [/]", end="" if ui.console else "\n")
            if not ui.console:
                task = input("🤖 Введите задачу для агента (или `exit` для выхода): ").strip()
            else:
                task = input().strip()

            if not task:
                continue
            if task.lower() in ("exit", "quit", "q"):
                ui.info("Завершение сессии...")
                break
            await orchestrator.execute_task(task)
    finally:
        await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
