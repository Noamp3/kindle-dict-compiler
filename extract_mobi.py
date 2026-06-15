from pathlib import Path
import json
import sys

import mobi


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: extract_mobi.py <input.prc>")
        return 2

    src = Path(sys.argv[1]).resolve()
    if not src.exists():
        print(f"Input file not found: {src}")
        return 2

    result = mobi.extract(str(src))
    print(json.dumps({"result": result}, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
