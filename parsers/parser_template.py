#!/usr/bin/env python3
"""
Custom Dictionary Parser Template
---------------------------------
Copy this template to write a parser for any new dictionary structure.
Only edit the `parse_entry` and entry extraction logic to fit your specific dictionary raw file.
"""
from __future__ import annotations

import argparse
import csv
import html as htmllib
import json
import re
import sys
from pathlib import Path

# Add parent directory to sys.path so config_helper can be imported
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config_helper import config

# Standard clean helpers
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_html_text(value: str) -> str:
    """Strip all HTML tags, unescape HTML entities, and collapse white space."""
    value = TAG_RE.sub(" ", value)
    value = htmllib.unescape(value)
    value = value.replace("\xa0", " ")
    value = WHITESPACE_RE.sub(" ", value)
    return value.strip(" \t\r\n.")


def parse_entry(entry_id: int, raw_head: str, raw_body: str) -> dict | None:
    """
    CUSTOMIZABLE: Parse a single raw entry block into a structured dictionary.
    
    Args:
        entry_id: Incremental counter of the entry.
        raw_head: The raw string of the headword area.
        raw_body: The raw string of the definition/examples area.
        
    Returns:
        A dict matching the configured field schema, or None if the entry is invalid or skipped.
    """
    # 1. Clean headword
    headword = clean_html_text(raw_head)
    if not headword:
        return None

    # 2. Extract definition and optional examples (Customize this section based on dictionary format!)
    # Example: If examples are split by "Ex:"
    body_text = clean_html_text(raw_body)
    parts = re.split(r"\bEx:\s*", body_text, flags=re.IGNORECASE)
    definition = parts[0].strip(" ;") if parts else ""
    examples = [part.strip() for part in parts[1:] if part.strip()]

    # 3. Build structured record mapping keys to config
    # This automatically matches whatever keys are configured in config.json!
    record = {
        "entry_id": entry_id,
        config.headword_field: headword,
        config.definition_source_field: definition,
    }
    
    if examples:
        record[config.examples_source_field] = " || ".join(examples)
        
    record["entry_text_en"] = body_text
    
    return record


def decode_html(data: bytes, preferred_encoding: str) -> str:
    """Safely decode binary data to string trying multiple encodings."""
    if preferred_encoding:
        return data.decode(preferred_encoding, errors="replace")

    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_entries(input_path: Path, encoding: str, limit: int = 0) -> list[dict]:
    """
    Load raw file, segment it into logical entry blocks, and parse them.
    Customize the splitting logic (e.g. splitting by <hr/>, blockquotes, or newlines).
    """
    source = decode_html(input_path.read_bytes(), encoding)
    
    # Locate body boundaries in HTML (or skip if parsing raw text files)
    body_start = source.find("<body>")
    body_end = source.rfind("</body>")
    if body_start != -1 and body_end != -1 and body_end > body_start:
        body_html = source[body_start + len("<body>") : body_end]
    else:
        body_html = source

    parsed_entries = []
    entry_counter = 0

    # CUSTOMIZABLE: Define how entries are divided. 
    # Example: Splitting by <hr/> blocks or blockquotes
    blocks = body_html.split("<hr/>")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
            
        entry_counter += 1
        
        # Example split: headword is in first part, body in second
        # (Customize this segmentation to fit your specific dictionary structure)
        first_div = block.find("</div>")
        if first_div != -1:
            raw_head = block[:first_div]
            raw_body = block[first_div + len("</div>"):]
        else:
            raw_head = block
            raw_body = ""

        try:
            record = parse_entry(entry_counter, raw_head, raw_body)
            if record:
                parsed_entries.append(record)
        except Exception as e:
            print(f"Warning: Failed to parse entry {entry_counter} due to error: {e}", file=sys.stderr)

        if limit > 0 and len(parsed_entries) >= limit:
            break

    return parsed_entries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Structured dictionary template parser. Reads custom file formats and outputs standard CSV/JSONL."
    )
    parser.add_argument("input_file", type=Path, help="Path to raw source dictionary file.")
    parser.add_argument(
        "--jsonl",
        dest="jsonl_path",
        type=Path,
        default=Path("work/dictionary_entries.jsonl"),
        help="Output JSONL path (default: work/dictionary_entries.jsonl)."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=Path("work/dictionary_entries.csv"),
        help="Output CSV path (default: work/dictionary_entries.csv)."
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Input file encoding. Defaults to utf-8."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit parsing to N successfully parsed entries for testing."
    )
    args = parser.parse_args()

    if not args.input_file.exists():
        print(f"Error: Input file does not exist: {args.input_file}", file=sys.stderr)
        return 1

    print(f"Parsing entries from {args.input_file}...")
    entries = extract_entries(args.input_file, args.encoding, args.limit)
    print(f"Successfully parsed {len(entries)} entries.")

    # Write JSONL output
    args.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"Wrote JSONL to: {args.jsonl_path}")

    # Write CSV output
    args.csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["entry_id", config.headword_field, config.definition_source_field]
    # Check if examples are present to add to headers
    if any(config.examples_source_field in entry for entry in entries):
        fieldnames.append(config.examples_source_field)
    fieldnames.append("entry_text_en")

    with args.csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)
    print(f"Wrote CSV to: {args.csv_path}")

    # Print first few samples to terminal
    print("\nSample parsed entries:")
    print(json.dumps(entries[:3], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
