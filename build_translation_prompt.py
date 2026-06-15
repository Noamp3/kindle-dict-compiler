from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from string import Template

from config_helper import config


# ---------------------------------------------------------------------------
# POS-hint extraction
# ---------------------------------------------------------------------------

# Ordered so longer / more-specific tokens are tried first.
_POS_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^v\s+pron$"),         "reflexive verb"),
    (re.compile(r"^v\s+pron\b"),        "reflexive verb"),
    (re.compile(r"^vt$"),               "transitive verb"),
    (re.compile(r"^vi$"),               "intransitive verb"),
    (re.compile(r"^mf$"),               "masculine/feminine noun"),
    (re.compile(r"^m\s*$"),             "masculine noun"),
    (re.compile(r"^f\s*$"),             "feminine noun"),
    (re.compile(r"^adj$"),              "adjective"),
    (re.compile(r"^adv$"),              "adverb"),
    (re.compile(r"^prep$"),             "preposition"),
    (re.compile(r"^conj$"),             "conjunction"),
    (re.compile(r"^compuesto$"),        "compound/phrase"),
]

# Pattern for numbered sub-entries like "I. vt", "II. v pron"
_NUMBERED_RE = re.compile(r"^[IVXLC]+\.\s+(.+)$")
# Pattern for feminine-form lines like "fem -da" which precede the real POS
_FEM_FORM_RE = re.compile(r"^fem\s+\S")


def _match_pos_token(text: str) -> str:
    """Return a human-readable POS label for *text*, or empty string."""
    text = text.strip()
    for pattern, label in _POS_TOKENS:
        if pattern.match(text):
            return label
    return ""


def strip_html_tags(text: str) -> str:
    """Strip all HTML tags from a string for text-only parsing."""
    return re.sub(r"<[^>]+>", " ", text)


def extract_pos_hint(definition_en: str) -> str:
    """Extract a POS / gender hint from the first few lines of *definition_en*.

    Returns a human-readable string such as ``"masculine noun"``,
    ``"adjective"``, ``"transitive verb"``, etc.  Returns ``""`` when no
    recognisable marker is found.
    """
    if not definition_en:
        return ""

    plain_def = strip_html_tags(definition_en)
    lines = plain_def.split("\n")[:3]  # only inspect first 3 lines

    for line in lines:
        text = line.strip()
        if not text:
            continue

        # Skip feminine-form lines like "fem -da" — the real POS follows
        if _FEM_FORM_RE.match(text):
            continue

        # Handle numbered sub-entries: "I. vt" → try "vt"
        m = _NUMBERED_RE.match(text)
        if m:
            text = m.group(1).strip()

        result = _match_pos_token(text)
        if result:
            return result

    return ""


def adapt_guidelines_for_no_examples(guidelines: str) -> str:
    # 1. Remove examples_source from Input fields
    guidelines = guidelines.replace(f"- `{config.examples_source_field}`", "")
    guidelines = guidelines.replace(f"- {config.examples_source_field}", "")

    # 2. Remove examples_target from Output fields
    guidelines = guidelines.replace(f"- `{config.examples_target_field}`", "")
    guidelines = guidelines.replace(f"- {config.examples_target_field}", "")

    # 3. Remove rule 3 and rule 4 from Rules
    lines = guidelines.splitlines()
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("3. Translate examples into"):
            continue
        if stripped.startswith("4. If multiple examples are present"):
            continue
        filtered_lines.append(line)
    guidelines = "\n".join(filtered_lines)

    # 4. Modify Output Contract using regex substitution
    new_contract = f"""## Output Contract

Every output line must be one valid JSON object with these fields in this exact order:

1. `entry_id`
2. `{config.headword_field}`
3. `{config.definition_target_field}`

Minimal valid example:

`{{"entry_id": 123, "{config.headword_field}": "casa", "{config.definition_target_field}": "<div> <div> <i>(נקבה)</i> בית </div> </div>"}}`"""

    guidelines = re.sub(
        r"(?is)## Output Contract.*?`\{\"entry_id\".*?\}`",
        new_contract,
        guidelines
    )

    # 5. Modify Preflight Checklist
    guidelines = guidelines.replace("Every row contains all 4 required fields.", "Every row contains all 3 required fields.")
    guidelines = guidelines.replace("contains all 4 required fields", "contains all 3 required fields")

    # 6. Modify Recommended Prompt Shape
    guidelines = guidelines.replace(
        f"Translate `{config.definition_source_field}` and `{config.examples_source_field}` into {config.target_lang_name}",
        f"Translate `{config.definition_source_field}` into {config.target_lang_name}"
    )
    guidelines = guidelines.replace(
        f"Translate {config.definition_source_field} and {config.examples_source_field} into {config.target_lang_name}",
        f"Translate {config.definition_source_field} into {config.target_lang_name}"
    )

    return guidelines


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a single prompt packet for translating one JSONL batch."
    )
    parser.add_argument("batch_jsonl", type=Path)
    parser.add_argument(
        "--guidelines",
        type=Path,
        default=Path("translation_guidelines.md"),
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=Path("prompt_templates"),
        help="Directory containing prompt templates (default: prompt_templates)."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output prompt file. Defaults to work/prompt_packets/<batch>.prompt.txt",
    )
    args = parser.parse_args()

    batch_name = args.batch_jsonl.stem
    output_path = args.output or Path("work/prompt_packets") / f"{batch_name}.prompt.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    guidelines = args.guidelines.read_text(encoding="utf-8")
    rows = list(load_jsonl(args.batch_jsonl))
    
    # Strip redundant entry_text_en to optimize token usage
    for row in rows:
        if "entry_text_en" in row:
            del row["entry_text_en"]

    # Inject POS hint so the translation model picks the right Hebrew tag
    for row in rows:
        hint = extract_pos_hint(row.get(config.definition_source_field, ""))
        if hint:
            row["pos_hint"] = hint

    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)

    has_examples = any(config.examples_source_field in row for row in rows)
    
    if has_examples:
        template_file = args.templates_dir / "translation_with_examples.txt"
        if not template_file.exists():
            print(f"Error: Prompt template file not found: {template_file}")
            return 1
            
        template_text = template_file.read_text(encoding="utf-8")
        prompt_tmpl = Template(template_text)
        
        prompt = prompt_tmpl.safe_substitute(
            source_lang=config.source_lang_name,
            target_lang=config.target_lang_name,
            guidelines=guidelines,
            batch_file=str(args.batch_jsonl),
            num_entries=len(rows),
            payload=payload
        )
    else:
        adapted_guidelines = adapt_guidelines_for_no_examples(guidelines)
        template_file = args.templates_dir / "translation_no_examples.txt"
        if not template_file.exists():
            print(f"Error: Prompt template file not found: {template_file}")
            return 1
            
        template_text = template_file.read_text(encoding="utf-8")
        prompt_tmpl = Template(template_text)
        
        prompt = prompt_tmpl.safe_substitute(
            source_lang=config.source_lang_name,
            target_lang=config.target_lang_name,
            headword_field=config.headword_field,
            definition_source_field=config.definition_source_field,
            definition_target_field=config.definition_target_field,
            guidelines=adapted_guidelines,
            num_entries=len(rows),
            payload=payload
        )

    output_path.write_text(prompt, encoding="utf-8")
    print(
        json.dumps(
            {
                "batch": str(args.batch_jsonl),
                "entries": len(rows),
                "prompt": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
