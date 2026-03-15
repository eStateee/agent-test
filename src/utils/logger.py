"""
Logger — разделение консольного и файлового логирования.

Технические детали (DOM extraction, HTTP requests, debug) → файл.
Бизнес-логика (действия агента, ошибки) → консоль (только WARNING+).
"""

import logging
import sys
from config.settings import LOGS_DIR

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


def setup_logger(name: str) -> logging.Logger:
    """
    Настройка логгера с чистым разделением потоков.

    Консоль: только WARNING и выше (ошибки, критичные предупреждения).
    Файл: DEBUG и выше (полная трассировка для отладки).
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Консоль — только предупреждения и ошибки (чистый вывод)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)

    # Файл — полная детализация
    file_handler = logging.FileHandler(
        LOGS_DIR / f"{name}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_format)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
