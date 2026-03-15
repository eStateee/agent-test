TOOLS_SCHEMA = [
    {
        "name": "navigate",
        "description": "Перейти по URL. Используй для открытия новых страниц.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Полный URL для перехода (например, https://example.com)",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Кликнуть на элемент. Используй селектор из DOM state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS-селектор элемента из списка доступных элементов",
                },
                "wait_for_navigation": {
                    "type": "boolean",
                    "description": "Ждать загрузки страницы после клика (по умолчанию false)",
                },
            },
            "required": ["selector"],
        },
    },
    {
        "name": "type_text",
        "description": "Ввести текст в поле ввода.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS-селектор поля ввода",
                },
                "text": {"type": "string", "description": "Текст для ввода"},
                "clear": {
                    "type": "boolean",
                    "description": "Очистить поле перед вводом (по умолчанию true)",
                },
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "extract_text",
        "description": "Извлечь текст из элемента для анализа.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS-селектор элемента"}
            },
            "required": ["selector"],
        },
    },
    {
        "name": "scroll_down",
        "description": "Скролл вниз на один экран. Используй для загрузки контента ниже видимой области.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "scroll_up",
        "description": "Скролл вверх на один экран.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "go_back",
        "description": "Перейти назад в истории браузера.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "press_key",
        "description": "Нажать клавишу (Enter, Escape, Tab, ArrowDown, ArrowUp и т.д.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Название клавиши (например, Enter, Escape, Tab)",
                }
            },
            "required": ["key"],
        },
    },
    {
        "name": "wait",
        "description": "Подождать N секунд. Используй если нужно дождаться загрузки динамического контента.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "Количество секунд ожидания (например, 2.5)",
                }
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "screenshot",
        "description": "Сделать скриншот страницы для отладки.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Путь для сохранения скриншота (опционально)",
                }
            },
        },
    },
    {
        "name": "task_complete",
        "description": "Задача выполнена. Используй когда цель достигнута.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Краткое описание результата выполнения задачи",
                }
            },
            "required": ["summary"],
        },
    },
    {
        "name": "ask_user",
        "description": "Запросить дополнительную информацию у пользователя, если не хватает данных для продолжения.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Вопрос пользователю"}
            },
            "required": ["question"],
        },
    },
]
