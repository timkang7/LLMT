from __future__ import annotations

import re

from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
    QApplication,
)

from src.config import APP_NAME, ICON_PATH
from src.data.app_settings import AppSettings, SettingsStore
from src.data.repository import ReviewWord, WordbookRepository
from src.services.lmstudio_client import DirectionType, LMStudioClient, LMStudioError, TaskType
from src.services.pronunciation import PronunciationService
from src.ui.hotkey import GlobalHotkey
from src.ui.settings_dialog import SettingsDialog


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class ApiWorker(QRunnable):
    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn()
            self.signals.succeeded.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class LoadingSpinner(QWidget):
    def __init__(self, size: int = 20, parent=None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(60)
        self.setFixedSize(size, size)
        self.hide()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(QColor("#2563eb"), 3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        margin = 3
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        # Draw a 270-degree arc and rotate it over time to mimic a circular spinner.
        start_angle = self._angle * 16
        span_angle = 270 * 16
        painter.drawArc(rect, start_angle, span_angle)


class SubmitTextEdit(QTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        is_enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        no_modifier = event.modifiers() == Qt.NoModifier
        if is_enter and no_modifier:
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        repo: WordbookRepository,
        client: LMStudioClient,
        hotkey: GlobalHotkey,
        settings_store: SettingsStore,
        settings: AppSettings,
        pronunciation: PronunciationService,
    ) -> None:
        super().__init__()
        self.repo = repo
        self.client = client
        self.hotkey = hotkey
        self.settings_store = settings_store
        self.settings = settings
        self.pronunciation = pronunciation
        self.current_review_word: ReviewWord | None = None
        self.card_revealed = False
        self._is_quitting = False
        self._tray_hint_shown = False
        self._is_translating = False
        self._workers: list[ApiWorker] = []
        self._pool = QThreadPool.globalInstance()

        self.setWindowTitle(APP_NAME)
        self.resize(980, 320)
        self._build_ui()
        self._apply_style()
        self._setup_tray()
        self._setup_menu()

        self.hotkey.triggered.connect(self._toggle_visibility)
        self.hotkey.updated.connect(self._on_hotkey_updated)
        self.hotkey.update_failed.connect(self._on_hotkey_failed)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("LLMT")
        title_font = QFont("Segoe UI", 16)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_translate_tab(), "Translator")
        self.tabs.addTab(self._build_playground_tab(), "Playground")
        layout.addWidget(self.tabs)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.hide()

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.spinner = LoadingSpinner(18)
        self.loading_label = QLabel("Translating...")
        self.loading_label.hide()
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.loading_label)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        self.setCentralWidget(root)
        self._update_stats()

    def _setup_menu(self) -> None:
        menu = self.menuBar().addMenu("Settings")
        api_action = QAction("API Settings", self)
        api_action.triggered.connect(self._open_api_settings)
        menu.addAction(api_action)

    def _build_translate_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        controls = QHBoxLayout()
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Auto (自动检测)", "auto")
        self.direction_combo.addItem("中文 -> English", "zh_to_en")
        self.direction_combo.addItem("English -> 中文", "en_to_zh")
        self.direction_combo.setCurrentIndex(0)

        self.task_combo = QComboBox()
        self.task_combo.addItem("Translate", "translate")
        self.task_combo.addItem("Grammar", "grammar")
        self.task_combo.addItem("Polish", "polish")

        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._run_task)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_io)

        controls.addWidget(QLabel("Direction"))
        controls.addWidget(self.direction_combo)
        controls.addSpacing(10)
        controls.addWidget(QLabel("Mode"))
        controls.addWidget(self.task_combo)
        controls.addStretch()
        controls.addWidget(self.run_btn)
        controls.addWidget(clear_btn)

        io_row = QHBoxLayout()
        self.source_input = SubmitTextEdit()
        self.source_input.setPlaceholderText("Input text...")
        self.source_input.submit_requested.connect(self._run_task)
        self.result_output = QTextEdit()
        self.result_output.setPlaceholderText("Result...")

        io_row.addWidget(self._panel("Input", self.source_input))
        io_row.addWidget(self._panel("Output", self.result_output))

        pronounce_row = QHBoxLayout()
        self.output_phonetic_label = QLabel("Phonetic: -")
        self.output_phonetic_label.setObjectName("phoneticLabel")
        self.pronounce_input_btn = QPushButton("Speak Input")
        self.pronounce_input_btn.clicked.connect(self._pronounce_input_text)
        self.pronounce_output_btn = QPushButton("Speak Output")
        self.pronounce_output_btn.clicked.connect(self._pronounce_output_text)

        pronounce_row.addWidget(self.output_phonetic_label)
        pronounce_row.addStretch()
        pronounce_row.addWidget(self.pronounce_input_btn)
        pronounce_row.addWidget(self.pronounce_output_btn)

        layout.addLayout(controls)
        layout.addLayout(io_row)
        layout.addLayout(pronounce_row)
        return page

    def _build_playground_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.playground_word = QLabel("Press Next to start reviewing")
        self.playground_word.setAlignment(Qt.AlignCenter)
        self.playground_word.setObjectName("playgroundWord")

        self.playground_hint = QLabel("")
        self.playground_hint.setAlignment(Qt.AlignCenter)

        self.playground_phonetic = QLabel("")
        self.playground_phonetic.setAlignment(Qt.AlignCenter)
        self.playground_phonetic.setObjectName("playgroundPhonetic")

        self.playground_meaning = QTextEdit()
        self.playground_meaning.setReadOnly(True)
        self.playground_meaning.setPlaceholderText("Click Reveal to see meaning and examples")
        self.playground_meaning.setMaximumHeight(170)

        btn_row = QHBoxLayout()
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._load_next_review_word)

        self.reveal_btn = QPushButton("Reveal")
        self.reveal_btn.clicked.connect(self._reveal_current_word)

        self.pronounce_btn = QPushButton("Pronounce")
        self.pronounce_btn.clicked.connect(self._pronounce_current_word)

        self.yes_btn = QPushButton("Yes, I remember")
        self.yes_btn.clicked.connect(lambda: self._submit_review(True))
        self.no_btn = QPushButton("No, I forgot")
        self.no_btn.clicked.connect(lambda: self._submit_review(False))
        self.yes_btn.setEnabled(False)
        self.no_btn.setEnabled(False)

        btn_row.addStretch()
        btn_row.addWidget(self.next_btn)
        btn_row.addWidget(self.reveal_btn)
        btn_row.addWidget(self.pronounce_btn)
        btn_row.addWidget(self.yes_btn)
        btn_row.addWidget(self.no_btn)
        btn_row.addStretch()

        layout.addStretch()
        layout.addWidget(self.playground_word)
        layout.addWidget(self.playground_phonetic)
        layout.addWidget(self.playground_hint)
        layout.addWidget(self.playground_meaning)
        layout.addLayout(btn_row)
        layout.addStretch()

        return page

    def _panel(self, title: str, editor: QTextEdit) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel(title))
        layout.addWidget(editor)
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f3f4f6;
                color: #111827;
                font-family: Segoe UI;
                font-size: 14px;
            }
            QTabWidget::pane {
                border: 1px solid #d1d5db;
                background: #ffffff;
            }
            #card {
                border: 1px solid #d1d5db;
                border-radius: 10px;
                background: #ffffff;
                padding: 8px;
            }
            QTextEdit {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px;
                background: #ffffff;
                selection-background-color: #1d4ed8;
            }
            QPushButton {
                background: #1d4ed8;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                min-width: 90px;
            }
            QPushButton:hover { background: #1e40af; }
            QComboBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 6px;
                min-width: 150px;
            }
            #playgroundWord {
                font-size: 34px;
                font-weight: 700;
            }
            #playgroundPhonetic {
                font-size: 20px;
                color: #1e40af;
                margin-bottom: 2px;
            }
            #statusLabel {
                color: #374151;
            }
            #phoneticLabel {
                color: #1e40af;
                font-size: 15px;
                font-weight: 600;
            }
            """
        )

    def _run_task(self) -> None:
        if self._is_translating:
            self.playground_hint.setText("Translation is already running...")
            return

        source = self.source_input.toPlainText().strip()
        if not source:
            QMessageBox.warning(self, "Warning", "Please input text first.")
            return

        selected_direction = str(self.direction_combo.currentData())
        direction: DirectionType = self._resolve_direction(selected_direction, source)
        task: TaskType = self.task_combo.currentData()

        self._is_translating = True
        self.run_btn.setEnabled(False)
        self.source_input.setReadOnly(True)
        self.result_output.clear()
        self.output_phonetic_label.setText("Phonetic: -")
        self.spinner.start()
        self.loading_label.show()
        self.playground_hint.setText("Translating...")

        def do_call() -> tuple[str, str]:
            result = self.client.run_task(text=source, task=task, direction=direction)
            return source, result

        def on_success(payload: tuple[str, str]) -> None:
            self._is_translating = False
            self.run_btn.setEnabled(True)
            self.source_input.setReadOnly(False)
            self.spinner.stop()
            self.loading_label.hide()
            source_text, result_text = payload
            self.result_output.setPlainText(result_text)
            self._update_output_phonetic(result_text)
            self.repo.upsert_words_from_text(source_text, context=source_text)
            self.repo.upsert_words_from_text(result_text, context=source_text)
            self._update_stats()
            self.playground_hint.setText("")

        def on_error(message: str) -> None:
            self._is_translating = False
            self.run_btn.setEnabled(True)
            self.source_input.setReadOnly(False)
            self.spinner.stop()
            self.loading_label.hide()
            QMessageBox.critical(self, "API Error", message)

        self._start_worker(do_call, on_success, on_error)

    def _resolve_direction(self, selected: str, text: str) -> DirectionType:
        if selected != "auto":
            return "en_to_zh" if selected == "en_to_zh" else "zh_to_en"

        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        english_count = len(re.findall(r"[A-Za-z]", text))

        if english_count > chinese_count:
            return "en_to_zh"
        return "zh_to_en"

    def _clear_io(self) -> None:
        self.source_input.clear()
        self.result_output.clear()
        self.output_phonetic_label.setText("Phonetic: -")

    def _update_output_phonetic(self, text: str) -> None:
        pron = self.pronunciation.build_phonetic(text)
        if not pron.phonetic:
            self.output_phonetic_label.setText("Phonetic: -")
            return
        self.output_phonetic_label.setText(f"Phonetic: {pron.phonetic}")

    def _pronounce_input_text(self) -> None:
        text = self.source_input.toPlainText().strip()
        if not text:
            self.playground_hint.setText("Input is empty.")
            return
        self.pronunciation.speak_async(text)

    def _pronounce_output_text(self) -> None:
        text = self.result_output.toPlainText().strip()
        if not text:
            self.playground_hint.setText("Output is empty.")
            return
        self.pronunciation.speak_async(text)

    def _update_stats(self) -> None:
        self.status_label.setText("")

    def _load_next_review_word(self) -> None:
        word = self.repo.get_due_word()
        if word is None:
            self.current_review_word = None
            self.card_revealed = False
            self.playground_word.setText("No due words now")
            self.playground_phonetic.setText("")
            self.playground_hint.setText("Try again later, or add more text in Translator.")
            self.playground_meaning.clear()
            self.yes_btn.setEnabled(False)
            self.no_btn.setEnabled(False)
            self._update_stats()
            return

        self.current_review_word = word
        self.card_revealed = False
        self.playground_word.setText(word.word)
        pron = self.pronunciation.build_phonetic(word.word)
        self.playground_phonetic.setText(pron.phonetic)
        self.playground_hint.setText("Think first, then click Reveal.")
        self.playground_meaning.clear()
        self.yes_btn.setEnabled(False)
        self.no_btn.setEnabled(False)

    def _pronounce_current_word(self) -> None:
        if self.current_review_word is None:
            self.playground_hint.setText("Click Next first.")
            return
        self.pronunciation.speak_async(self.current_review_word.word)

    def _reveal_current_word(self) -> None:
        if self.current_review_word is None:
            self.playground_hint.setText("Click Next first.")
            return

        context = self.repo.get_word_context(self.current_review_word.id)
        self.reveal_btn.setEnabled(False)
        self.playground_hint.setText("Revealing...")

        def do_call() -> str:
            return self.client.explain_word(self.current_review_word.word, context=context)

        def on_success(meaning: str) -> None:
            self.reveal_btn.setEnabled(True)
            self.card_revealed = True
            self.playground_meaning.setPlainText(meaning)
            self.playground_hint.setText("Now choose Yes or No based on your memory.")
            self.yes_btn.setEnabled(True)
            self.no_btn.setEnabled(True)

        def on_error(message: str) -> None:
            self.reveal_btn.setEnabled(True)
            self.playground_hint.setText(message)

        self._start_worker(do_call, on_success, on_error)

    def _submit_review(self, remembered: bool) -> None:
        if self.current_review_word is None:
            self.playground_hint.setText("Click Next first.")
            return
        if not self.card_revealed:
            self.playground_hint.setText("Please click Reveal before answering.")
            return

        self.repo.record_review(self.current_review_word.id, remembered=remembered)
        self.playground_hint.setText("Saved. Loading next word...")
        self._update_stats()
        self._load_next_review_word()

    def _on_hotkey_updated(self, hotkey_text: str) -> None:
        self.settings.hotkey = hotkey_text
        self.settings_store.save(self.settings)
        self._update_stats()

    def _on_hotkey_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Hotkey", message)

    def _open_api_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != dialog.Accepted:
            return

        updated = dialog.to_settings(self.settings)

        ok, error = self.hotkey.update_hotkey(updated.hotkey)
        if not ok:
            QMessageBox.warning(self, "Hotkey", error)
            return

        try:
            self.client.configure(
                provider=updated.api_provider,
                base_url=updated.api_base_url,
                model=updated.api_model,
                api_key=updated.api_key,
                timeout=updated.request_timeout,
            )
        except LMStudioError as exc:
            QMessageBox.warning(self, "API Settings", str(exc))
            return

        self.settings.api_provider = updated.api_provider
        self.settings.api_base_url = updated.api_base_url
        self.settings.api_key = updated.api_key
        self.settings.api_model = updated.api_model
        self.settings.request_timeout = updated.request_timeout
        self.settings_store.save(self.settings)
        self._update_stats()
        QMessageBox.information(self, "Settings", "API and hotkey settings were saved and applied.")

    def _start_worker(self, fn, on_success, on_error) -> None:
        worker = ApiWorker(fn)
        self._workers.append(worker)

        def handle_success(result) -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            on_success(result)

        def handle_error(message: str) -> None:
            if worker in self._workers:
                self._workers.remove(worker)
            on_error(message)

        worker.signals.succeeded.connect(handle_success)
        worker.signals.failed.connect(handle_error)
        self._pool.start(worker)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        icon = QIcon(str(ICON_PATH)) if ICON_PATH.exists() else self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu(self)
        show_action = QAction("Show / Hide", self)
        show_action.triggered.connect(self._toggle_visibility)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visibility()

    def _quit_from_tray(self) -> None:
        self._is_quitting = True
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._is_quitting:
            event.accept()
            return

        event.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self.tray.showMessage(
                APP_NAME,
                "App is still running in tray. Use tray menu to quit.",
                QSystemTrayIcon.Information,
                2000,
            )
            self._tray_hint_shown = True

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
            return

        self.show()
        self.raise_()
        self.activateWindow()
