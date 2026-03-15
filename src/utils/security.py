DESTRUCTIVE_ACTIONS = {
    "delete",
    "remove",
    "clear",
    "pay",
    "purchase",
    "buy",
    "confirm_order",
    "submit_payment",
    "checkout",
    "send",
    "post",
    "publish",
    "approve",
    "reject",
}


def validate_selector(selector: str) -> bool:
    """Проверяет, что селектор безопасен."""
    dangerous_patterns = ["javascript:", "eval(", "document.write"]
    return not any(pattern in selector.lower() for pattern in dangerous_patterns)


def is_destructive_action(action_name: str, params: dict) -> bool:
    """Определяет, является ли действие деструктивным."""

    action_lower = action_name.lower()

    if any(keyword in action_lower for keyword in DESTRUCTIVE_ACTIONS):
        return True

    if "selector" in params:
        selector = params["selector"].lower()
        if any(
            keyword in selector
            for keyword in ["delete", "remove", "pay", "confirm", "submit"]
        ):
            return True

    if "text" in params:
        text = params["text"].lower()
        if any(keyword in text for keyword in ["delete", "confirm", "pay", "remove"]):
            return True

    return False


def ask_user_confirmation(action_name: str, params: dict) -> bool:
    """Запрашивает подтверждение у пользователя."""

    print(f"\n⚠️  ДЕСТРУКТИВНОЕ ДЕЙСТВИЕ")
    print(f"Действие: {action_name}")
    print(f"Параметры: {params}")

    while True:
        response = input("\nПродолжить? (y/n): ").strip().lower()
        if response in ["y", "yes", "да", "д"]:
            return True
        elif response in ["n", "no", "нет", "н"]:
            return False
        else:
            print("Пожалуйста, введите 'y' или 'n'")
