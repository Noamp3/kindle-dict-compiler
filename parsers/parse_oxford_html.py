from __future__ import annotations

import argparse
import csv
import html as htmllib
import json
import re
import sys
from pathlib import Path

# Add parent directory to sys.path to load config
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config_helper import config

# Prevent Windows charmap encoding errors when printing Unicode content
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

# Bold text that looks like a usage example: <b>word phrase</b>
# Oxford examples follow the pattern: <b>Spanish text</b> = English text
# We capture <b> content and the trailing " = ..." part if present.
EXAMPLE_BOLD_RE = re.compile(
    r"<b>\s*(?:•\s*)?([^<]{3,}?)\s*</b>\s*(?:=\s*([^<|\n]{2,}))?",
    re.DOTALL,
)

# Part-of-speech markers Oxford uses (inside <i> tags)
POS_RE = re.compile(r"<i>\s*((?:m|f|mf|m/f|adj|adv|prep|pron|conj|v|vi|vt|vr|v aux|v mod|v impers|v pron|n|nf|nm|npl|abbr|pref|suf|interj|art|det|num)[^<]{0,30}?)\s*</i>")


def clean_tags(s: str) -> str:
    """Strip all HTML tags, unescape entities, collapse whitespace, but preserve block newlines."""
    # Convert block tags to newlines to preserve visual line breaks
    s = re.sub(r"</?(?:div|p|br|blockquote)[^>]*>", "\n", s)
    s = TAG_RE.sub(" ", s)
    s = htmllib.unescape(s)
    s = s.replace("\xa0", " ")
    s = s.replace("\xad", "") # Strip soft hyphens
    
    # Reconstruct standard clean text preserving newlines
    lines = []
    for line in s.splitlines():
        line_clean = SPACE_RE.sub(" ", line).strip()
        if line_clean:
            lines.append(line_clean)
    return "\n".join(lines)


ALLOWED_TAG_NAMES = {'b', 'i', 'blockquote', 'br', 'sub', 'sup', 'a', 'div'}


def clean_tags_html(s: str) -> str:
    """Clean HTML string while preserving only specific visual and structural formatting tags."""
    # 1. Strip comments
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    
    # 2. Process all HTML tags using regex
    def repl(match):
        tag = match.group(0)
        # Check if closing tag
        if tag.startswith("</"):
            name = tag[2:-1].strip().lower()
            if name in ALLOWED_TAG_NAMES:
                return f"</{name}>"
            return ""
        
        # Opening or self-closing tag
        m = re.match(r"<([a-zA-Z0-9:]+)", tag)
        if not m:
            return ""
        name = m.group(1).lower()
        
        if name in ALLOWED_TAG_NAMES:
            if name == 'a':
                # Keep href if present
                href_match = re.search(r'href=["\']([^"\']+)["\']', tag, re.IGNORECASE)
                if href_match:
                    return f'<a href="{href_match.group(1)}">'
                return '<a>'
            elif name == 'br':
                return '<br/>'
            return f"<{name}>"
        return ""

    s = re.compile(r"<[^>]+>").sub(repl, s)
    s = htmllib.unescape(s)
    
    # Normalize spacing
    s = re.sub(r'[ \t]+', ' ', s)
    
    # Remove empty tags like <b> </b> or <i> </i> or <div></div>
    for _ in range(3):
        s = re.compile(r'<([a-z]+)></\1>').sub('', s)
        s = re.compile(r'<([a-z]+)>\s+</\1>').sub(' ', s)
        
    # Reconstruct standard clean text preserving newlines
    lines = []
    for line in s.splitlines():
        line_clean = line.strip()
        if line_clean:
            lines.append(line_clean)
            
    return "\n".join(lines)


def extract_headword(block: str) -> str:
    """Extract the headword from the first <b>...</b> in the block."""
    m = re.search(r"<b>(.*?)</b>", block, re.DOTALL)
    if not m:
        return ""
    return clean_tags(m.group(1))


def extract_pos(block: str) -> str:
    """Extract first part-of-speech marker."""
    m = POS_RE.search(block)
    return m.group(1).strip() if m else ""


def split_definition_examples(body_raw: str) -> str:
    """
    From the raw body HTML (after the headword div), extract:
    - definition_en: the primary descriptive text (POS + gloss)
    """
    return clean_tags_html(body_raw)


def iter_entries(html: str):
    """Yield raw (entry_id, headword, definition, examples) tuples."""
    # Find body
    body_start = html.find("<body>")
    body_end = html.rfind("</body>")
    if body_start == -1:
        body_start = 0
    if body_end == -1:
        body_end = len(html)
    body = html[body_start:body_end]

    # Skip front-matter: everything before the first <mbp:frameset>
    # which immediately follows the <mbp:pagebreak/> that opens the dictionary proper
    frameset_pos = body.find("<mbp:frameset>")
    if frameset_pos > 0:
        body = body[frameset_pos:]

    blocks = body.split("<hr/>")
    entry_id = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        headword = extract_headword(block)
        if not headword:
            continue

        # Skip section headers: headwords with more than 5 words
        if len(headword.split()) > 5:
            continue

        # Body is everything after the headword container (ends with </div> </div> or fallback </div>)
        hw_close = block.find("</div> </div>")
        if hw_close >= 0:
            body_raw = block[hw_close + len("</div> </div>"):]
        else:
            first_close = block.find("</div>")
            body_raw = block[first_close + len("</div>"):] if first_close >= 0 else block

        definition_en = split_definition_examples(body_raw)

        if not definition_en:
            continue

        entry_id += 1
        yield {
            "entry_id": entry_id,
            config.headword_field: headword,
            config.definition_source_field: definition_en,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse extracted Oxford MOBI/HTML into structured JSONL/CSV rows."
    )
    parser.add_argument(
        "input_html",
        type=Path,
        nargs="?",
        default=Path("work2/book.html"),
        help="Path to the extracted book.html (default: work2/book.html).",
    )
    parser.add_argument(
        "--jsonl",
        dest="jsonl_path",
        type=Path,
        default=Path("work2/dictionary_entries.jsonl"),
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=Path("work2/dictionary_entries.csv"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max entries to export (for testing).",
    )
    args = parser.parse_args()

    if not args.input_html.exists():
        print(f"Error: input file not found: {args.input_html}")
        return 1

    print(f"Reading {args.input_html} ({args.input_html.stat().st_size:,} bytes)...")
    html = args.input_html.read_text(encoding="utf-8", errors="replace")

    print("Parsing entries...")
    entries = list(iter_entries(html))
    if args.limit > 0:
        entries = entries[: args.limit]

    # Write JSONL
    args.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl_path.open("w", encoding="utf-8") as f:
        for row in entries:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Write CSV
    args.csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["entry_id", config.headword_field, config.definition_source_field]
    with args.csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entries)

    sample = entries[:5]
    print(
        json.dumps(
            {
                "entries": len(entries),
                "jsonl": str(args.jsonl_path),
                "csv": str(args.csv_path),
                "sample": sample,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
