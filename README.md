# Screen Reader

A simple Python-based screen reader starter project.

## Features

- Read plain text aloud
- Read text from a file aloud
- Adjustable speech rate and volume
- Optional voice selection

## Quick Start

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run:

```powershell
python src/main.py --text "Hello from your screen reader project"
```

Or read from file:

```powershell
python src/main.py --file .\sample.txt
```

## Usage

```text
python src/main.py [--text "text to read"] [--file path] [--rate 200] [--volume 1.0] [--voice-index 0] [--list-voices]
```

## Notes

- If both `--text` and `--file` are provided, `--text` is used.
- This is a starter project; you can extend it with OCR, live window reading, hotkeys, and UI.
