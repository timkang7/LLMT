from __future__ import annotations

from pathlib import Path

APP_NAME = "LLMT"
LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL = "local-model"
REQUEST_TIMEOUT = 180
MAX_OUTPUT_TOKENS = 512
TRANSLATE_MAX_TOKENS = 96
GRAMMAR_MAX_TOKENS = 280
POLISH_MAX_TOKENS = 280
WORD_EXPLAIN_MAX_TOKENS = 220
DEFAULT_API_PROVIDER = "lmstudio"
DEFAULT_API_BASE_URL = LMSTUDIO_BASE_URL
DEFAULT_API_MODEL = DEFAULT_MODEL

DEFAULT_HOTKEY = "Ctrl+Shift+Space"
HOTKEY_ID = 1

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
ICON_PATH = ASSETS_DIR / "llmt_logo.svg"
DATA_DIR = BASE_DIR / "storage"
DB_PATH = DATA_DIR / "wordbook.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
