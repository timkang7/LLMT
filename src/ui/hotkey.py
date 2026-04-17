from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from src.config import HOTKEY_ID, DEFAULT_HOTKEY

WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001

MODIFIERS = {
    "ALT": 0x0001,
    "CTRL": 0x0002,
    "SHIFT": 0x0004,
    "WIN": 0x0008,
}

KEYS = {
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "ESC": 0x1B,
}
for i in range(1, 13):
    KEYS[f"F{i}"] = 0x6F + i
for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEYS[ch] = ord(ch)
for digit in "0123456789":
    KEYS[digit] = ord(digit)


@dataclass
class HotkeyBinding:
    modifiers: int
    vk: int
    text: str


def parse_hotkey(hotkey_text: str) -> HotkeyBinding:
    raw = hotkey_text.strip()
    if not raw:
        raise ValueError("Hotkey cannot be empty")

    parts = [part.strip().upper() for part in raw.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("Use format like Ctrl+Shift+Space")

    modifiers = 0
    key_token = ""
    for token in parts:
        if token in MODIFIERS:
            modifiers |= MODIFIERS[token]
            continue
        if key_token:
            raise ValueError("Only one non-modifier key is allowed")
        key_token = token

    if modifiers == 0:
        raise ValueError("At least one modifier is required")
    if not key_token:
        raise ValueError("Missing key, for example Space or K")

    vk = KEYS.get(key_token)
    if vk is None:
        raise ValueError("Unsupported key. Use A-Z, 0-9, F1-F12, Space, Tab, Enter or Esc")

    return HotkeyBinding(modifiers=modifiers, vk=vk, text="+".join(parts))


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class GlobalHotkey(QObject):
    triggered = Signal()
    updated = Signal(str)
    update_failed = Signal(str)

    def __init__(self, hotkey_text: str = DEFAULT_HOTKEY) -> None:
        super().__init__()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._registered = False
        self._lock = threading.Lock()
        self._active: HotkeyBinding | None = None
        self._pending: HotkeyBinding | None = parse_hotkey(hotkey_text)
        self._hotkey_text = self._pending.text

    @property
    def hotkey_text(self) -> str:
        return self._hotkey_text

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def update_hotkey(self, hotkey_text: str) -> tuple[bool, str]:
        try:
            binding = parse_hotkey(hotkey_text)
        except ValueError as exc:
            return False, str(exc)

        with self._lock:
            self._pending = binding
        return True, ""

    def _register_binding(self, user32: ctypes.LibraryLoader, binding: HotkeyBinding) -> bool:
        ok = user32.RegisterHotKey(None, HOTKEY_ID, binding.modifiers, binding.vk)
        if ok:
            self._registered = True
            self._active = binding
            self._hotkey_text = binding.text
            self.updated.emit(binding.text)
            return True
        return False

    def _unregister(self, user32: ctypes.LibraryLoader) -> None:
        if self._registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
            self._active = None

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        msg = MSG()

        with self._lock:
            initial = self._pending
            self._pending = None

        if initial is not None and not self._register_binding(user32, initial):
            self.update_failed.emit(f"Unable to register hotkey: {initial.text}")

        while not self._stop_event.is_set():
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.triggered.emit()

            pending: HotkeyBinding | None = None
            with self._lock:
                if self._pending is not None:
                    pending = self._pending
                    self._pending = None

            if pending is not None:
                self._unregister(user32)
                if not self._register_binding(user32, pending):
                    self.update_failed.emit(f"Unable to register hotkey: {pending.text}")

            time.sleep(0.03)

        self._unregister(user32)
