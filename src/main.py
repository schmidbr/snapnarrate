import argparse
from pathlib import Path

import pyttsx3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple screen reader starter")
    parser.add_argument("--text", help="Text to read aloud")
    parser.add_argument("--file", type=Path, help="Path to text file to read")
    parser.add_argument("--rate", type=int, default=200, help="Speech rate (default: 200)")
    parser.add_argument("--volume", type=float, default=1.0, help="Volume 0.0 to 1.0")
    parser.add_argument("--voice-index", type=int, default=0, help="Voice index from --list-voices")
    parser.add_argument("--list-voices", action="store_true", help="List available voices and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = pyttsx3.init()

    voices = engine.getProperty("voices")

    if args.list_voices:
        for i, voice in enumerate(voices):
            print(f"[{i}] {voice.name} ({voice.id})")
        return

    if not (0 <= args.voice_index < len(voices)):
        raise ValueError(f"voice-index must be between 0 and {len(voices) - 1}")

    engine.setProperty("voice", voices[args.voice_index].id)
    engine.setProperty("rate", args.rate)
    engine.setProperty("volume", max(0.0, min(1.0, args.volume)))

    text = args.text
    if text is None and args.file:
        text = args.file.read_text(encoding="utf-8")

    if not text:
        raise ValueError("Provide --text or --file")

    engine.say(text)
    engine.runAndWait()


if __name__ == "__main__":
    main()
