from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import requests
from requests import ReadTimeout

from src.config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_MODEL,
    DEFAULT_API_PROVIDER,
    GRAMMAR_MAX_TOKENS,
    MAX_OUTPUT_TOKENS,
    POLISH_MAX_TOKENS,
    REQUEST_TIMEOUT,
    TRANSLATE_MAX_TOKENS,
    WORD_EXPLAIN_MAX_TOKENS,
)


TaskType = Literal["translate", "grammar", "polish"]
DirectionType = Literal["en_to_zh", "zh_to_en"]
ProviderType = Literal["lmstudio", "openai", "anthropic"]


class LMStudioError(RuntimeError):
    pass


@dataclass
class LMStudioClient:
    provider: ProviderType = DEFAULT_API_PROVIDER
    base_url: str = DEFAULT_API_BASE_URL
    default_model: str = DEFAULT_API_MODEL
    api_key: str = ""
    timeout: int = REQUEST_TIMEOUT
    _cached_detected_model: str | None = None

    def configure(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
    ) -> None:
        provider_norm = (provider or DEFAULT_API_PROVIDER).strip().lower()
        if provider_norm not in {"lmstudio", "openai", "anthropic"}:
            raise LMStudioError("Unsupported provider. Use lmstudio/openai/anthropic.")
        self.provider = provider_norm
        self.base_url = self._normalize_base_url(base_url)
        self.default_model = (model or DEFAULT_API_MODEL).strip()
        self.api_key = api_key.strip()
        self.timeout = max(15, int(timeout))
        self._cached_detected_model = None

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        url = (base_url or DEFAULT_API_BASE_URL).strip().rstrip("/")
        if not url:
            return DEFAULT_API_BASE_URL
        return url

    @staticmethod
    def supported_providers() -> list[tuple[str, str]]:
        return [
            ("lmstudio", "LMStudio (local OpenAI-compatible)"),
            ("openai", "OpenAI"),
            ("anthropic", "Anthropic Claude"),
        ]

    def _require_key_if_needed(self) -> None:
        if self.provider in {"openai", "anthropic"} and not self.api_key:
            raise LMStudioError("This provider requires API key. Please configure it in Settings.")

    def _post_openai_chat(self, payload: dict) -> dict:
        endpoint = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except ReadTimeout:
            # Retry once with shorter output for slow model responses.
            retry_payload = dict(payload)
            retry_payload["max_tokens"] = min(256, int(payload.get("max_tokens", MAX_OUTPUT_TOKENS)))
            response = requests.post(
                endpoint,
                json=retry_payload,
                headers=headers,
                timeout=max(120, self.timeout),
            )
            response.raise_for_status()
            return response.json()

    def _post_lmstudio_completion(self, payload: dict) -> dict:
        endpoint = f"{self.base_url}/completions"
        headers = {"Content-Type": "application/json"}
        response = requests.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_openai_content(data: dict) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = (message.get("content") or "").strip()
        return content

    @staticmethod
    def _extract_openai_reasoning(data: dict) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return (message.get("reasoning_content") or "").strip()

    @staticmethod
    def _clean_completion_output(text: str) -> str:
        cleaned = re.sub(r"</?think>", "", text, flags=re.I).strip()
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return ""

        # Some models duplicate the same short answer twice.
        dup_match = re.match(r"^(.{2,120}?)\s+\1$", cleaned)
        if dup_match:
            return dup_match.group(1).strip()

        half = len(cleaned) // 2
        if len(cleaned) >= 8 and len(cleaned) % 2 == 0:
            left = cleaned[:half].strip()
            right = cleaned[half:].strip()
            if left and left == right:
                return left
        return cleaned

    def _run_lmstudio_fast_translate(self, text: str, direction: DirectionType, model: str) -> str:
        if direction == "en_to_zh":
            prompt = (
                "Translate the following English text to natural Simplified Chinese. "
                "Output translation only.\n"
                f"Text: {text}\n"
                "<think>\n</think>"
            )
        else:
            prompt = (
                "Translate the following Simplified Chinese text to natural English. "
                "Output translation only.\n"
                f"Text: {text}\n"
                "<think>\n</think>"
            )

        payload = {
            "model": model,
            "prompt": prompt,
            "temperature": 0.0,
            "max_tokens": TRANSLATE_MAX_TOKENS,
        }
        data = self._post_lmstudio_completion(payload)
        choices = data.get("choices", [])
        if not choices:
            return ""
        raw = choices[0].get("text") or ""
        return self._clean_completion_output(raw)

    @staticmethod
    def _extract_translation_from_reasoning(reasoning: str) -> str:
        if not reasoning:
            return ""

        normalized = reasoning.replace("\r", "")
        pattern = re.compile(
            r"(?im)^(?:final\s*answer|answer|translation|译文|最终答案)\s*[:：]\s*(.+)$"
        )
        match = pattern.search(normalized)
        if match:
            return match.group(1).strip().strip('"')

        lines = [line.strip() for line in normalized.split("\n") if line.strip()]
        for line in reversed(lines):
            low = line.lower()
            if low.startswith("thinking") or low.startswith("analyze"):
                continue
            if line.startswith(("*", "-", ">")):
                continue
            if re.match(r"^\d+[\.)]", line):
                continue
            candidate = line.strip('"')
            if re.fullmatch(r"[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff ,.!?\-'\"]{1,79}", candidate):
                return candidate
        return ""

    @staticmethod
    def _max_tokens_for_task(task: TaskType) -> int:
        if task == "translate":
            return TRANSLATE_MAX_TOKENS
        if task == "grammar":
            return GRAMMAR_MAX_TOKENS
        return POLISH_MAX_TOKENS

    def _post_anthropic_chat(self, system_prompt: str, user_prompt: str, model: str) -> dict:
        endpoint = f"{self.base_url}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        }
        response = requests.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def detect_model(self) -> str:
        if self.provider == "anthropic":
            return self.default_model or "claude-3-5-sonnet-latest"

        # If user explicitly selected a model, trust it and skip model-list probing.
        if self.default_model and self.default_model != DEFAULT_API_MODEL:
            return self.default_model

        if self._cached_detected_model:
            return self._cached_detected_model

        endpoint = f"{self.base_url}/models"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = requests.get(endpoint, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", [])
            if not models:
                return self.default_model
            chosen = models[0].get("id", self.default_model)
            self._cached_detected_model = chosen
            return chosen
        except requests.RequestException:
            return self.default_model

    def run_task(self, text: str, task: TaskType, direction: DirectionType) -> str:
        if not text.strip():
            raise LMStudioError("输入文本为空。")

        self._require_key_if_needed()
        model = self.detect_model()
        prompt = self._build_prompt(text=text, task=task, direction=direction)
        system_prompt = (
            "You are a reliable bilingual assistant focused on English/Chinese tasks. "
            "Keep answers concise and do not reveal internal reasoning."
        )

        try:
            if self.provider == "lmstudio" and task == "translate":
                fast_output = self._run_lmstudio_fast_translate(text=text, direction=direction, model=model)
                if fast_output:
                    return fast_output

            if self.provider == "anthropic":
                data = self._post_anthropic_chat(system_prompt=system_prompt, user_prompt=prompt, model=model)
                blocks = data.get("content", [])
                text_blocks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                output = "\n".join(part for part in text_blocks if part).strip()
                if not output:
                    raise LMStudioError("模型未返回结果。")
                return output

            payload = {
                "model": model,
                "temperature": 0.2,
                "max_tokens": self._max_tokens_for_task(task),
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            }
            data = self._post_openai_chat(payload)
            output = self._extract_openai_content(data)
            if output:
                return output

            reasoning = self._extract_openai_reasoning(data)
            fallback = self._extract_translation_from_reasoning(reasoning)
            if fallback:
                return fallback

            raise LMStudioError(
                "模型进入了长推理但未产出最终答案。"
                "请在 Settings 里选择非推理模型，或在 LMStudio 中关闭推理模式。"
            )
        except requests.RequestException as exc:
            raise LMStudioError(f"调用 API 失败: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise LMStudioError("模型返回格式异常。") from exc

    def explain_word(self, word: str, context: str | None = None) -> str:
        if not word.strip():
            raise LMStudioError("单词为空，无法释义。")

        self._require_key_if_needed()
        model = self.detect_model()
        context_block = context.strip() if context else "(no context available)"
        prompt = (
            "You are an English vocabulary coach for Chinese learners. "
            "Given one English word, provide a concise explanation in Simplified Chinese. "
            "Output strictly in this format:\n"
            "词性: ...\n"
            "中文释义: ...\n"
            "英文例句: ...\n"
            "例句翻译: ...\n\n"
            f"Word: {word}\n"
            f"Context: {context_block}"
        )
        system_prompt = (
            "You provide concise and correct bilingual vocabulary explanations. "
            "Keep answers short and do not reveal internal reasoning."
        )

        try:
            if self.provider == "anthropic":
                data = self._post_anthropic_chat(system_prompt=system_prompt, user_prompt=prompt, model=model)
                blocks = data.get("content", [])
                text_blocks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                output = "\n".join(part for part in text_blocks if part).strip()
                if not output:
                    raise LMStudioError("模型未返回释义结果。")
                return output

            payload = {
                "model": model,
                "temperature": 0.3,
                "max_tokens": WORD_EXPLAIN_MAX_TOKENS,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            }
            data = self._post_openai_chat(payload)
            output = self._extract_openai_content(data)
            if not output:
                raise LMStudioError("模型未返回释义结果。")
            return output
        except requests.RequestException as exc:
            raise LMStudioError(f"调用 API 释义失败: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise LMStudioError("模型释义返回格式异常。") from exc

    def _build_prompt(self, text: str, task: TaskType, direction: DirectionType) -> str:
        if task == "translate":
            if direction == "en_to_zh":
                return (
                    "Translate the following English text into natural and accurate Simplified Chinese. "
                    "Only return the translated text.\n\n"
                    f"Text:\n{text}"
                )
            return (
                "Translate the following Simplified Chinese text into natural and accurate English. "
                "Only return the translated text.\n\n"
                f"Text:\n{text}"
            )

        if task == "grammar":
            if direction == "en_to_zh":
                return (
                    "Correct grammar and improve clarity for this English text, then provide a concise Chinese explanation "
                    "of major corrections. Format as:\n1) Corrected Text\n2) Explanation(中文).\n\n"
                    f"Text:\n{text}"
                )
            return (
                "润色并纠正这段中文的语法与表达，然后给出一版自然英文翻译。"
                "输出格式:\n1) 修正后中文\n2) English Version。\n\n"
                f"文本:\n{text}"
            )

        if direction == "en_to_zh":
            return (
                "Polish this English text to be fluent and professional. Then provide a Chinese translation. "
                "Format as:\n1) Polished English\n2) 中文翻译。\n\n"
                f"Text:\n{text}"
            )

        return (
            "润色这段中文，使其更自然、简洁、专业。然后提供自然英文版本。"
            "输出格式:\n1) 润色后中文\n2) English Version。\n\n"
            f"文本:\n{text}"
        )
