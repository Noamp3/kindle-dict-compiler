from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path

# Add parent directory to sys.path to load config
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config_helper import config

TAG_RE = re.compile(r"<[^>]+>")
BLOCK_RE = re.compile(r"(?is)<blockquote>(.*?)</blockquote>")
BREAK_RE = re.compile(r"(?i)<br\s*/?>")
WHITESPACE_RE = re.compile(r"\s+")
EXAMPLE_SPLIT_RE = re.compile(r"\bEx:\s*", re.IGNORECASE)


def clean_html_text(value: str) -> str:
    value = BREAK_RE.sub("\n", value)
    value = TAG_RE.sub(" ", value)
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    value = WHITESPACE_RE.sub(" ", value)
    return value.strip(" \t\r\n.")


def split_block_text(block_html: str) -> tuple[str, list[str], str]:
    text = clean_html_text(block_html)
    if text.startswith("="):
        text = text[1:].strip()

    parts = EXAMPLE_SPLIT_RE.split(text)
    definition = parts[0].strip(" ;") if parts else ""
    examples = [part.strip() for part in parts[1:] if part.strip()]
    return definition, examples, text


def decode_html(data: bytes, preferred_encoding: str) -> str:
    if preferred_encoding:
        return data.decode(preferred_encoding, errors="replace")

    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def iter_entries(body_html: str):
    prev_end = 0
    entry_id = 0
    for match in BLOCK_RE.finditer(body_html):
        raw_head = body_html[prev_end:match.start()]
        raw_block = match.group(1)
        prev_end = match.end()

        headword = clean_html_text(raw_head)
        if not headword:
            continue

        definition, examples, text = split_block_text(raw_block)
        entry_id += 1
        
        entry = {
            "entry_id": entry_id,
            config.headword_field: headword,
            config.definition_source_field: definition,
        }
        if examples:
            entry[config.examples_source_field] = " || ".join(examples)
            
        entry["entry_text_en"] = text
        yield entry


def extract_entries(input_path: Path, encoding: str) -> list[dict[str, str]]:
    source = decode_html(input_path.read_bytes(), encoding)
    body_start = source.find("<body>")
    body_end = source.rfind("</body>")
    if body_start == -1 or body_end == -1 or body_end <= body_start:
        raise ValueError("Could not locate <body>...</body> in extracted HTML")

    body_html = source[body_start + len("<body>") : body_end]
    return list(iter_entries(body_html))


def write_csv(entries: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["entry_id", config.headword_field, config.definition_source_field]
    if any(config.examples_source_field in entry for entry in entries):
        fieldnames.append(config.examples_source_field)
    fieldnames.append("entry_text_en")

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(entries)


def write_jsonl(entries: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse extracted PRC/MOBI dictionary HTML into structured rows."
    )
    parser.add_argument("input_html", type=Path)
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=Path("work/dictionary_entries.csv"),
    )
    parser.add_argument(
        "--jsonl",
        dest="jsonl_path",
        type=Path,
        default=Path("work/dictionary_entries.jsonl"),
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Source HTML encoding. Defaults to utf-8 for this extracted dictionary.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of entries to export for testing.",
    )
    args = parser.parse_args()

    entries = extract_entries(args.input_html, args.encoding)
    if args.limit > 0:
        entries = entries[: args.limit]

    write_csv(entries, args.csv_path)
    write_jsonl(entries, args.jsonl_path)

    sample = entries[:5]
    print(
        json.dumps(
            {
                "entries": len(entries),
                "csv": str(args.csv_path),
                "jsonl": str(args.jsonl_path),
                "sample": sample,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
