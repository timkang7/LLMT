from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.config import DB_PATH, SETTINGS_PATH
from src.data.app_settings import SettingsStore
from src.data.repository import WordbookRepository
from src.services.lmstudio_client import LMStudioClient
from src.services.pronunciation import PronunciationService
from src.ui.hotkey import GlobalHotkey
from src.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    settings_store = SettingsStore(SETTINGS_PATH)
    settings = settings_store.load()

    repo = WordbookRepository(DB_PATH)
    client = LMStudioClient()
    pronunciation = PronunciationService()
    client.configure(
        provider=settings.api_provider,
        base_url=settings.api_base_url,
        model=settings.api_model,
        api_key=settings.api_key,
        timeout=settings.request_timeout,
    )
    hotkey = GlobalHotkey(settings.hotkey)

    window = MainWindow(
        repo=repo,
        client=client,
        hotkey=hotkey,
        settings_store=settings_store,
        settings=settings,
        pronunciation=pronunciation,
    )
    window.show()

    hotkey.start()

    exit_code = app.exec()
    hotkey.stop()
    repo.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
