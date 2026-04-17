# LLMT

A local translation desktop app for Windows, powered by LMStudio OpenAI-compatible API.

## Features

- English <-> Chinese translation.
- Grammar correction and polishing modes.
- Clean two-panel UI for input/output.
- Tray resident mode (close window to tray, not exit).
- Configurable global hotkey to show/hide window (default: `Ctrl+Shift+Space`).
- Settings menu for API configuration (Provider/Base URL/Model/API Key/Timeout).
- Wordbook (RAG memory): all queried English words are cached.
- Playground flashcard mode: first see the word, then click `Reveal` for meaning, then answer `Yes` / `No`.
- Fully-local pronunciation support in Playground: phonetic display (English IPA / Chinese pinyin) + offline speak button.

## Supported API Providers

- LMStudio (OpenAI-compatible local API)
- OpenAI (official API)
- Anthropic Claude API

## API Configuration

Open `Settings -> API Settings` in app menu, then set provider-specific fields.

- LMStudio example:
	- Provider: `LMStudio`
	- Base URL: `http://127.0.0.1:1234/v1`
	- Model: leave default or fill your local model id
	- API Key: empty

- OpenAI example:
	- Provider: `OpenAI`
	- Base URL: `https://api.openai.com/v1`
	- Model: `gpt-4.1-mini`
	- API Key: your OpenAI key

- Anthropic example:
	- Provider: `Anthropic`
	- Base URL: `https://api.anthropic.com/v1`
	- Model: `claude-3-5-sonnet-latest`
	- API Key: your Anthropic key

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Build EXE (PyInstaller)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name LLMT main.py
```

Output EXE path:

- `dist\LLMT\LLMT.exe`

## Project Structure

- `main.py`: app entry
- `src/services/lmstudio_client.py`: LMStudio API client
- `src/data/repository.py`: SQLite wordbook + review algorithm
- `src/ui/main_window.py`: translator/playground UI
- `src/ui/hotkey.py`: Windows global hotkey
- `src/config.py`: app config

## Notes

- Data is stored in `storage/wordbook.db`.
- App settings are stored in `storage/settings.json`.
- If the global hotkey cannot be registered, app still works normally.
