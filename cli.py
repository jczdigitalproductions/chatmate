import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from reviewer import review

load_dotenv(Path(__file__).with_name(".env"))
parser = argparse.ArgumentParser(description="Chatmate: review AI-generated source without executing it")
parser.add_argument("file", type=Path)
parser.add_argument("--language", default="python")
parser.add_argument("--question", default="Review correctness and security.")
parser.add_argument("--local-only", action="store_true")
if __name__ == "__main__":
    args = parser.parse_args()
    try:
        report = review({"code": args.file.read_text(encoding="utf-8"), "language": args.language,
                         "question": args.question}, use_meta=not args.local_only)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(report, indent=2))
