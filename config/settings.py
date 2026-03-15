import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Пути
PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Ключи API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AGENTROUTER_API_KEY = os.getenv("AGENTROUTER_API_KEY", "")

# Настройки браузера
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_SLOW_MO = int(os.getenv("BROWSER_SLOW_MO", "100"))
BROWSER_VIEWPORT = {"width": 1280, "height": 720}
BROWSER_TIMEOUT = 30000  # ms

# Настройки агента
MAX_ITERATIONS = 20
MAX_RETRIES = 3
RETRY_DELAY = 10  # секунды

# Настройки DOM
MAX_DOM_ELEMENTS = 100
MAX_STATE_TOKENS = 5000
