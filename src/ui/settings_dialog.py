from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from src.data.app_settings import AppSettings
from src.services.lmstudio_client import LMStudioClient


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("App Settings")
        self.resize(520, 280)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.provider_combo = QComboBox()
        for value, label in LMStudioClient.supported_providers():
            self.provider_combo.addItem(label, value)
        provider_index = max(0, self.provider_combo.findData(settings.api_provider))
        self.provider_combo.setCurrentIndex(provider_index)

        self.base_url_input = QLineEdit(settings.api_base_url)
        self.base_url_input.setPlaceholderText("https://api.openai.com/v1")

        self.model_input = QLineEdit(settings.api_model)
        self.model_input.setPlaceholderText("gpt-4.1-mini / claude-3-5-sonnet-latest / qwen/qwen3.5-9b")

        self.api_key_input = QLineEdit(settings.api_key)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("sk-... or anthropic key")

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setMinimum(15)
        self.timeout_spin.setMaximum(600)
        self.timeout_spin.setValue(settings.request_timeout)


        self.hotkey_input = QLineEdit(settings.hotkey)
        self.hotkey_input.setPlaceholderText("Ctrl+Shift+Space")
        self.help_label = QLabel(
            "Tips: LMStudio use local URL like http://127.0.0.1:1234/v1 ; "
            "OpenAI use https://api.openai.com/v1 ; Anthropic use https://api.anthropic.com/v1"
            " ; Hotkey example: Ctrl+Shift+Space"
        )
        self.help_label.setWordWrap(True)

        form.addRow("Provider", self.provider_combo)
        form.addRow("Base URL", self.base_url_input)
        form.addRow("Model", self.model_input)
        form.addRow("API Key", self.api_key_input)
        form.addRow("Timeout (sec)", self.timeout_spin)
        form.addRow("Global Hotkey", self.hotkey_input)

        root.addLayout(form)
        root.addWidget(self.help_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def to_settings(self, current: AppSettings) -> AppSettings:
        return AppSettings(
            hotkey=self.hotkey_input.text().strip(),
            api_provider=str(self.provider_combo.currentData()),
            api_base_url=self.base_url_input.text().strip(),
            api_key=self.api_key_input.text().strip(),
            api_model=self.model_input.text().strip(),
            request_timeout=int(self.timeout_spin.value()),
        )
