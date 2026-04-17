from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import eng_to_ipa as ipa  # type: ignore
import pyttsx3  # type: ignore
from pypinyin import Style, pinyin  # type: ignore

ENGLISH_PATTERN = re.compile(r"[A-Za-z]")
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class PronunciationResult:
    text: str
    phonetic: str
    language: str


class PronunciationService:
    def __init__(self) -> None:
        self._speaker_lock = threading.Lock()

    def build_phonetic(self, text: str) -> PronunciationResult:
        cleaned = text.strip()
        if not cleaned:
            return PronunciationResult(text="", phonetic="", language="unknown")

        if ENGLISH_PATTERN.search(cleaned):
            phonetic = ipa.convert(cleaned).replace("*", "").strip()
            return PronunciationResult(text=cleaned, phonetic=phonetic or "(no IPA found)", language="en")

        if CHINESE_PATTERN.search(cleaned):
            chunks = pinyin(cleaned, style=Style.TONE3, strict=False)
            phonetic = " ".join(item[0] for item in chunks if item)
            return PronunciationResult(text=cleaned, phonetic=phonetic or "(no pinyin found)", language="zh")

        return PronunciationResult(text=cleaned, phonetic="(unsupported text)", language="unknown")

    def speak_async(self, text: str) -> None:
        content = text.strip()
        if not content:
            return

        thread = threading.Thread(target=self._speak_blocking, args=(content,), daemon=True)
        thread.start()

    def _speak_blocking(self, text: str) -> None:
        with self._speaker_lock:
            engine = pyttsx3.init()
            # Keep default system voice for fully-local speech synthesis.
            engine.say(text)
            engine.runAndWait()
