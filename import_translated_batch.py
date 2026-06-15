from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import re
import sys
import os
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

from config_helper import config

# Prevent Windows charmap encoding errors when printing Unicode content
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

MOJIBAKE_MARKERS = ("Ã", "Â", "×")

# Loaded dynamically in main() based on source batch examples field existence
REQUIRED_FIELDS = {
    "entry_id",
    config.headword_field,
    config.definition_target_field,
    config.examples_target_field,
}

FIELD_ORDER = [
    "entry_id",
    config.headword_field,
    config.definition_target_field,
    config.examples_target_field,
]


def _build_cp1252_reverse_map() -> dict[str, int]:
    mapping = {chr(i): i for i in range(256)}
    for byte in range(256):
        try:
            char = bytes([byte]).decode("cp1252")
        except UnicodeDecodeError:
            continue
        mapping[char] = byte
    return mapping


# Build global cp1252 map for mojibake recovery
CP1252_REVERSE_MAP = _build_cp1252_reverse_map()


def _clean_string_value(raw: str) -> str:
    value = raw.strip()
    if value.endswith(","):
        value = value[:-1].rstrip()
    if value.startswith('"'):
        value = value[1:]
    if value.endswith('"'):
        value = value[:-1]
    if value.startswith("'"):
        value = value[1:]
    if value.endswith("'"):
        value = value[:-1]
    value = value.replace('\\"', '"')
    value = value.replace("\\r\\n", "\n").replace("\\r", "\n").replace("\\n", "\n")
    return value


def _contains_mojibake_markers(value: str) -> bool:
    if any(marker in value for marker in MOJIBAKE_MARKERS):
        return True
    return any("\x80" <= ch <= "\x9f" for ch in value)


def _repair_score(value: str) -> int:
    score = 0
    for ch in value:
        if "\u0590" <= ch <= "\u05ff":
            score += 5
        elif ch.isalpha():
            score += 1
        if ch in MOJIBAKE_MARKERS or "\x80" <= ch <= "\x9f":
            score -= 4
    return score


def repair_mojibake_text(value: str) -> str:
    if not value or not _contains_mojibake_markers(value):
        return value

    try:
        raw_bytes = bytes(CP1252_REVERSE_MAP[ch] for ch in value)
        repaired = raw_bytes.decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return value

    if _repair_score(repaired) <= _repair_score(value):
        return value
    return repaired


# ---------- Task 1: POS / register post-processing ----------

_POS_EXACT_FIXES: dict[str, str] = {
    "(תא')":  "(תואר)",
    "(תא' )":  "(תואר)",
    "(ת')":   "(תואר הפועל)",
    "(ת' )":   "(תואר הפועל)",
    "(סלנג)": "(דיבורי)",
}

_ARABIC_TO_HEBREW_HOMOGLYPHS = {
    '\u0627': '\u05d0',  # Arabic Alef (ا) -> Hebrew Alef (א)
    '\u0622': '\u05d0',  # Arabic Alef with Madda (آ) -> Hebrew Alef (א)
    '\u0623': '\u05d0',  # Arabic Alef with Hamza Above (أ) -> Hebrew Alef (א)
    '\u0625': '\u05d0',  # Arabic Alef with Hamza Below (إ) -> Hebrew Alef (א)
    '\u0671': '\u05d0',  # Arabic Alef Wasla (ٱ) -> Hebrew Alef (א)
    '\u0628': '\u05d1',  # Arabic Beh (ב) -> Hebrew Bet (ב)
    '\u062a': '\u05ea',  # Arabic Teh (ת) -> Hebrew Tav (ת)
    '\u062f': '\u05d3',  # Arabic Dal (ד) -> Hebrew Dalet (ד)
    '\u0633': '\u05e1',  # Arabic Samekh (ס) -> Hebrew Samekh (ס)
    '\u0634': '\u05e9',  # Arabic Sheen (ש) -> Hebrew Shin (ש)
    '\u0644': '\u05dc',  # Arabic Lam (ל) -> Hebrew Lamed (ל)
    '\u0645': '\u05de',  # Arabic Meem (מ) -> Hebrew Mem (מ)
    '\u0647': '\u05d4',  # Arabic Heh (ה) -> Hebrew He (ה)
    '\u0648': '\u05d5',  # Arabic Waw (ו) -> Hebrew Vav (ו)
    '\u064a': '\u05d9',  # Arabic Yeh (י) -> Hebrew Yod (י)
    '\u0626': '\u05d9',  # Arabic Yeh with Hamza (ئ) -> Hebrew Yod (י)
    '\u0629': '\u05d4',  # Arabic Teh Marbuta (ة) -> Hebrew He (ה)
    '\u0646': '\u05e0',  # Arabic Noon (ن) -> Hebrew Nun (נ)
    '\u0631': '\u05e8',  # Arabic Reh (ر) -> Hebrew Resh (ר)
    '\u0641': '\u05e4',  # Arabic Feh (ف) -> Hebrew Pe (פ)
    '\u0642': '\u05e7',  # Arabic Qaf (ق) -> Hebrew Qof (ק)
    '\u0632': '\u05d6',  # Arabic Zain (ז) -> Hebrew Zayin (ז)
    '\u062c': '\u05d2',  # Arabic Jeem (ج) -> Hebrew Gimel (ג)
    '\u062d': '\u05d7',  # Arabic Het (ح) -> Hebrew Het (ח)
    '\u0637': '\u05d8',  # Arabic Tah (ط) -> Hebrew Tet (ט)
    '\u0635': '\u05e6',  # Arabic Sad (ص) -> Hebrew Tsadi (צ)
    '\u0636': '\u05e6',  # Arabic Dad (ض) -> Hebrew Tsadi (צ)
    '\u0639': '\u05e2',  # Arabic Ain (ع) -> Hebrew Ayin (ע)
    '\u0643': '\u05db',  # Arabic Kaf (ك) -> Hebrew Kaf (כ)
    '\u062e': '\u05db',  # Arabic Khah (خ) -> Hebrew Kaf (כ)
}


# Global validation patterns
SHORT_POS_PATTERN = re.compile(r'(?<![\u0590-\u05fe])(ז\'|נ\'|פ"י|פ"ע|פ\'|ת\'|תה"פ)(?![\u0590-\u05fe])')
SHORT_POS_IN_PARENTHESES = re.compile(r'\((ז\'|נ\'|פ"י|פ"ע|פ\'|ת\'|תה"פ)\)')
REPEATING_CHAR_PATTERN = re.compile(r'([\u0590-\u05fe])\1{4,}')
FORBIDDEN_SCRIPT_PATTERN = re.compile(r'[\u0900-\u097F\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF]')
PHRASE_LOOP_PATTERN = re.compile(r'(\b[\u0590-\u05fe\s]+\b)(?:\s+\1){4,}')


def load_env_var(var_name: str, default: str = "") -> str:
    """Load an environment variable from os.environ or the local .env file."""
    env_path = Path(".env")
    if not env_path.exists():
        env_path = Path("../.env")
    env_val = os.environ.get(var_name, "")
    if env_val:
        return env_val
    if not env_path.exists():
        return default
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, value = line.split("=", 1)
            if k.strip() == var_name:
                val = value.strip()
                if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                    val = val[1:-1].strip()
                return val
    except Exception:
        pass
    return default


def load_api_key(key_name: str = "GEMINI_API_KEY") -> str:
    """Load an API key by name from .env file or environment variables."""
    val = load_env_var(key_name, "")
    if val:
        return val
    # Legacy fallback: also accept GOOGLE_API_KEY as a synonym for the primary key
    if key_name == "GEMINI_API_KEY":
        val = load_env_var("GOOGLE_API_KEY", "")
        if val:
            return val
    return ""


def get_default_judge_model() -> str:
    """Load the default LLM judge model from environment variable LLM_JUDGE_MODEL, defaulting to gemini-2.5-flash."""
    return load_env_var("LLM_JUDGE_MODEL", "gemini-2.5-flash")


def get_llm_client(key_name: str = "GEMINI_API_KEY"):
    """Create a Gemini client using the specified API key name."""
    if genai is None:
        return None
    api_key = load_api_key(key_name)
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def get_llm_client2():
    """Create a fallback Gemini client using GEMINI_API_KEY2."""
    return get_llm_client("GEMINI_API_KEY2")


def _do_llm_correction(client, prompt: str, model: str = None) -> str:
    """Execute the Gemini generate_content call and strip any markdown wraps."""
    if model is None:
        model = get_default_judge_model()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0
        )
    )
    text = response.text.strip()
    # Clean up markdown code-block wraps if the model returned them
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def call_llm_corrector(
    client,
    headword_es: str,
    definition_en: str,
    definition_he: str,
    fallback_client=None,
) -> str:
    """Uses the configured Gemini model (from LLM_JUDGE_MODEL) to proofread and correct a dictionary entry's Hebrew translation
    that has failed validation due to spelling typos, visual homoglyphs, or leaked foreign scripts.

    Falls back to GEMINI_API_KEY2 and ultimately to Gemini 3.1 Flash Lite (gemini-3.1-flash-lite)
    on the primary key and fallback key if errors occur.
    """
    prompt = f"""You are an elite bilingual lexicographer and copyeditor. A Spanish-Hebrew dictionary entry contains typos, visual homoglyphs, or leaked foreign script characters.
    
Your task is to correct the Hebrew translation so it is perfectly natural, grammatically correct, and free of any foreign scripts, typos, or homoglyphs.

Dictionary Entry Details:
- Spanish Headword: {headword_es}
- Source English Definition/Structure: {definition_en}
- Translated Hebrew (containing errors/typos): {definition_he}

CRITICAL RULES:
1. PRESERVE ALL STRUCTURAL HTML TAGS: Keep <b>, <i>, <a>, <div>, <blockquote>, sub, sup, br in their exact correct locations to match the structural layout of the source. Do NOT unwrap or delete them.
2. FIX MIXED-SCRIPT HOMOGLYPHS: The translation contains letters from other alphabets (like Cyrillic, Arabic, or Latin) that look visually identical to Hebrew letters but have completely different unicode code points (e.g. Cyrillic 'лум' instead of Hebrew 'לומ' in 'בקוлумביה' -> 'בקולומביה'). You MUST convert any such visually identical foreign characters into their true, correct Hebrew letters (range \u0590 to \u05FF) based on the semantic context.
3. CORRECT FOREIGN LEAKS AND TYPOS: Replace any leaked foreign characters (like Japanese Katakana, Chinese, or Cyrillic) with their proper Hebrew translations (e.g. Katakana in 'בローチ' must be corrected to 'בסיכה', and 'מ前ור' must be corrected to 'מתאבן' or similar proper Hebrew word). Fix any spelling typos or metatheses (e.g. 'רפפרה' must be corrected to 'רפרפה').
4. Output ONLY the corrected raw HTML string. Do NOT add any markdown wraps or conversational explanation.
"""
    primary_model = get_default_judge_model()

    # 1. Try primary model on primary key
    try:
        return _do_llm_correction(client, prompt, model=primary_model)
    except Exception as e:
        print(f"WARNING: LLM Corrector primary key with {primary_model} failed: {e}", file=sys.stderr)
        
        # 2. Try primary model on fallback key
        if fallback_client is not None:
            print(f"INFO: Retrying with GEMINI_API_KEY2 and {primary_model}...", file=sys.stderr)
            try:
                return _do_llm_correction(fallback_client, prompt, model=primary_model)
            except Exception as e2:
                print(f"WARNING: LLM Corrector fallback key with {primary_model} failed: {e2}", file=sys.stderr)

        # 3. Try gemini-3.1-flash-lite on primary key if primary model is not already gemini-3.1-flash-lite
        if primary_model != "gemini-3.1-flash-lite":
            print("INFO: Falling back to GEMINI_API_KEY with gemini-3.1-flash-lite...", file=sys.stderr)
            try:
                return _do_llm_correction(client, prompt, model="gemini-3.1-flash-lite")
            except Exception as e3:
                print(f"WARNING: LLM Corrector primary key with gemini-3.1-flash-lite failed: {e3}", file=sys.stderr)

                # 4. Try gemini-3.1-flash-lite on fallback key
                if fallback_client is not None:
                    print("INFO: Retrying with GEMINI_API_KEY2 and gemini-3.1-flash-lite...", file=sys.stderr)
                    try:
                        return _do_llm_correction(fallback_client, prompt, model="gemini-3.1-flash-lite")
                    except Exception as e4:
                        print(f"WARNING: LLM Corrector fallback key with gemini-3.1-flash-lite failed: {e4}", file=sys.stderr)
                    
        return definition_he


def validate_single_entry(row, src_def: str) -> list[str]:
    errors = []
    entry_id = int(row["entry_id"])
    def_he = row.get(config.definition_target_field, "").strip()
    
    # 1. Zero-Empty Enforcer
    if not def_he:
        errors.append(f"entry_id {entry_id} has empty translation definition_he")
        return errors
        
    # 2. Forbidden POS Tag Scanner
    if SHORT_POS_PATTERN.search(def_he) or SHORT_POS_IN_PARENTHESES.search(def_he):
        errors.append(f"entry_id {entry_id} uses forbidden shortened POS tags in '{def_he}'")
        
    # 3. Hallucination Repeater Check
    if REPEATING_CHAR_PATTERN.search(def_he) or PHRASE_LOOP_PATTERN.search(def_he):
        errors.append(f"entry_id {entry_id} has repeating character/phrase hallucination loop in '{def_he}'")
        
    # 4. Forbidden Script Scanner
    if FORBIDDEN_SCRIPT_PATTERN.search(def_he):
        errors.append(f"entry_id {entry_id} contains forbidden foreign script characters in '{def_he}'")
        
    # 5. HTML Balance Check
    if not check_html_balance(def_he):
        errors.append(f"entry_id {entry_id} has unbalanced or malformed HTML tags in '{def_he}'")
        
    return errors



class HTMLBalanceChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.balanced = True
        self.allowed_tags = {"div", "blockquote", "a", "b", "i", "sub", "sup"}
        
    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in self.allowed_tags:
            self.stack.append(tag_lower)
            
    def handle_endtag(self, tag):
        if not self.balanced:
            return
        tag_lower = tag.lower()
        if tag_lower in self.allowed_tags:
            if self.stack and self.stack[-1] == tag_lower:
                self.stack.pop()
            else:
                self.balanced = False


def check_html_balance(html_str: str) -> bool:
    checker = HTMLBalanceChecker()
    try:
        checker.feed(html_str)
        return checker.balanced and len(checker.stack) == 0
    except Exception:
        return False


def balance_and_fix_html(html_str: str) -> str:
    """
    Parses the HTML string, keeps a stack of open tags, and:
    1. Closes any unclosed tags at the end.
    2. Ignores/removes any dangling closing tags that don't match the stack.
    Only operates on allowed formatting/structural tags:
    {'div', 'blockquote', 'a', 'b', 'i', 'sub', 'sup'}
    """
    tag_pattern = re.compile(r'(</?[a-zA-Z1-6]+(?:\s+[^>]*)?>)')
    parts = tag_pattern.split(html_str)
    
    stack = []
    fixed_parts = []
    
    allowed_tags = {"div", "blockquote", "a", "b", "i", "sub", "sup"}
    
    for part in parts:
        if part.startswith('<') and part.endswith('>'):
            if part.startswith('<!--'):
                fixed_parts.append(part)
                continue
                
            tag_name = part[1:-1].strip().split()[0].lower()
            if tag_name.endswith('/'):
                fixed_parts.append(part)
                continue
                
            is_closing = tag_name.startswith('/')
            if is_closing:
                tag_name = tag_name[1:]
                
            if tag_name not in allowed_tags:
                fixed_parts.append(part)
                continue
                
            if is_closing:
                if stack and stack[-1][0] == tag_name:
                    stack.pop()
                    fixed_parts.append(part)
                else:
                    continue
            else:
                stack.append((tag_name, part))
                fixed_parts.append(part)
        else:
            fixed_parts.append(part)
            
    while stack:
        tag_name, _ = stack.pop()
        fixed_parts.append(f"</{tag_name}>")
        
    return "".join(fixed_parts)


def post_process_definition(definition_he: str) -> str:
    """Auto-fix known POS-tag abbreviations and register labels."""
    if not definition_he:
        return definition_he

    # 1. Auto-repair Arabic homoglyphs (model accidentally using Arabic characters that look like Hebrew)
    for ar_char, he_char in _ARABIC_TO_HEBREW_HOMOGLYPHS.items():
        definition_he = definition_he.replace(ar_char, he_char)



    # Apply exact whole-token replacements first.
    for wrong, right in _POS_EXACT_FIXES.items():
        definition_he = definition_he.replace(wrong, right)

    # Handle compound forms like (סלנג אנדים) → (דיבורי, אנדים)
    definition_he = re.sub(
        r"\(סלנג\s+([^)]+)\)",
        lambda m: f"(דיבורי, {m.group(1).strip()})",
        definition_he,
    )

    # Auto-expand standalone shortened POS tags (e.g. "ז'" or "נ'") into their full forms.
    _POS_EXPANSIONS = {
        "ז'": "(זכר)",
        "נ'": "(נקבה)",
        "פ\"י": "(פועל יוצא)",
        "פ\"ע": "(פועל עומד)",
        "פ'": "(פועל)",
        "ת'": "(תואר)",
        "תה\"פ": "(תואר הפועל)"
    }
    for short_form, full_form in _POS_EXPANSIONS.items():
        # Case 1: inside parentheses like "(ז')" or "( ז' )"
        definition_he = re.sub(
            rf"\(\s*{re.escape(short_form)}\s*\)",
            full_form,
            definition_he
        )
        # Case 2: standalone word with word-boundary or pipe boundaries, e.g. "| ז'" or " ז' "
        definition_he = re.sub(
            rf"(?<![\u0590-\u05fe]){re.escape(short_form)}(?![\u0590-\u05fe])",
            full_form,
            definition_he
        )

    # If the string contains HTML, do not apply plain-text spacing/layout corrections
    if '<' in definition_he and '>' in definition_he:
        return balance_and_fix_html(definition_he)

    # Clean up em-dashes between parenthesized tags and list number '1.': (תואר) — 1. → (תואר) 1.
    definition_he = re.sub(
        r'(\([\u0590-\u05fe/a-zA-Z\s,+-]+\))\s*[\u2014\u2013-]\s*(?=1\.)',
        r'\1 ',
        definition_he
    )

    # Separate parenthesized grammatical tags from the list number '1.' with a newline: (נקבה) 1. → (נקבה)\n1.
    definition_he = re.sub(
        r'(\([\u0590-\u05fe/a-zA-Z\s,+-]+\))\s+(?=1\.)',
        r'\1\n',
        definition_he
    )

    # Automatically insert a newline '\n' before list numbers starting from 2. to ensure clean separation
    definition_he = re.sub(r'\s+(?=(?:[2-9]|\d{2,})\.\s)', "\n", definition_he)

    # Insert LRM isolators after list numbers/letters to prevent flipping (now with a strong right-to-left layout guard)
    definition_he = re.sub(r'(^|\s)(\d+\.)\s+', "\\1\\2\u200e ", definition_he)
    definition_he = re.sub(r'(^|\s)([\u0590-\u05fe]\.)\s+', "\\1\\2\u200e ", definition_he)

    return definition_he



def repair_mojibake_value(value):
    if isinstance(value, str):
        return repair_mojibake_text(value)
    if isinstance(value, list):
        return [repair_mojibake_value(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_mojibake_value(item) for key, item in value.items()}
    return value


def read_input_text(input_file: Path | None) -> str:
    if input_file:
        raw_text = input_file.read_text(encoding="utf-8")
    else:
        raw_text = sys.stdin.buffer.read().decode("utf-8-sig")
    return raw_text


def _repair_line_with_schema(line: str):
    """Best-effort parser for malformed JSON objects with known key order."""
    start = line.find("{")
    end = line.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    text = line[start : end + 1]

    values: dict[str, str] = {}
    pos = 0
    for idx, key in enumerate(FIELD_ORDER):
        # Look for the raw key name (e.g. 'headword_es') to be resilient to missing quotes
        key_pos = text.find(key, pos)
        if key_pos == -1:
            return None
        colon_pos = text.find(":", key_pos + len(key))
        if colon_pos == -1:
            return None

        value_start = colon_pos + 1
        if idx + 1 < len(FIELD_ORDER):
            next_key = FIELD_ORDER[idx + 1]
            next_key_pos = text.find(next_key, value_start)
            if next_key_pos == -1:
                return None
            raw_value = text[value_start:next_key_pos]
            # Strip trailing quotes, commas, and whitespace before the next key
            raw_value = raw_value.rstrip().rstrip(',').rstrip('"').rstrip("'").rstrip(',')
            pos = next_key_pos
        else:
            raw_value = text[value_start:-1] # Strip trailing "}"
        values[key] = raw_value.strip()

    repaired = {}
    match = re.search(r"-?\d+", values["entry_id"])
    if not match:
        return None
    repaired["entry_id"] = int(match.group(0))

    for key in FIELD_ORDER:
        if key == "entry_id":
            continue
        repaired[key] = _clean_string_value(values[key])
    return repaired


def _parse_json_line(line: str):
    line_clean = line.strip()
    if line_clean.startswith("{") and not line_clean.endswith("}"):
        if line_clean.endswith(")"):
            line_clean = line_clean[:-1].strip()
        if not line_clean.endswith("}"):
            line_clean = line_clean.rstrip(",") + "}"
            
    try:
        return json.loads(line_clean)
    except json.JSONDecodeError:
        return _repair_line_with_schema(line_clean)


def load_jsonl_text(text: str):
    rows = []
    normalized = text.replace("\r\n", "\n")

    # Prefer chunk parsing by entry object starts; this handles wrapped multiline objects.
    starts = [m.start() for m in re.finditer(r"\{\s*\"entry_id\"\s*:", normalized)]
    if starts:
        starts.append(len(normalized))
        for idx in range(len(starts) - 1):
            chunk = normalized[starts[idx] : starts[idx + 1]].strip()
            end = chunk.rfind("}")
            if end != -1:
                chunk = chunk[: end + 1]
            parsed = _parse_json_line(chunk)
            if parsed is None:
                raise json.JSONDecodeError("Unable to parse or repair JSON chunk", chunk[:200], 0)
            rows.append((idx + 1, parsed))
        return rows

    # Fallback for strict JSONL sources.
    for line_no, line in enumerate(normalized.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith("{"):
            object_start = line.find("{")
            if object_start == -1:
                continue
            line = line[object_start:]
        parsed = _parse_json_line(line)
        if parsed is None:
            raise json.JSONDecodeError("Unable to parse or repair JSON line", line, 0)
        rows.append((line_no, parsed))
    return rows


def load_source_map(path: Path) -> dict[int, str]:
    mapping: dict[int, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            mapping[int(row["entry_id"])] = row[config.headword_field]
    return mapping


def extract_tag_sequence(html_str: str) -> list[str]:
    tags = []
    for tag in re.findall(r"<[^>]+>", html_str):
        if tag.startswith("<!--"):
            continue
        if tag.startswith("</"):
            # Closing tag
            tag_content = tag[2:-1].strip()
            if tag_content:
                name = tag_content.split()[0].lower()
                tags.append(f"</{name}>")
        else:
            # Opening tag
            tag_content = tag[1:-1].strip()
            if tag_content:
                name = tag_content.split()[0].lower()
                if name.endswith("/"):
                    name = name[:-1]
                tags.append(f"<{name}>")
    return tags


def normalize_structural_tags(tags: list[str]) -> list[str]:
    # 1. Map div and blockquote to a generic block container tag
    mapped = []
    for t in tags:
        t_lower = t.lower()
        if t_lower in {"<div>", "<blockquote>"}:
            mapped.append("<block>")
        elif t_lower in {"</div>", "</blockquote>"}:
            mapped.append("</block>")
        else:
            mapped.append(t)
            
    # 2. Collapse consecutive redundant closing </block> tags
    collapsed = []
    for t in mapped:
        if t == "</block>" and collapsed and collapsed[-1] == "</block>":
            continue
        collapsed.append(t)
        
    # 3. Strip trailing </block> tags from the end of the sequence
    while collapsed and collapsed[-1] == "</block>":
        collapsed.pop()
        
    return collapsed


def validate(rows, source_map: dict[int, str], source_batch_path: Path | None = None):
    errors: list[str] = []
    seen_ids: set[int] = set()
    
    # Load source definitions for HTML tag sequence validation
    source_defs: dict[int, str] = {}
    if source_batch_path is not None:
        with source_batch_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                src_row = json.loads(line)
                source_defs[int(src_row["entry_id"])] = str(src_row.get(config.definition_source_field, ""))

    for line_no, row in rows:
        missing = sorted(REQUIRED_FIELDS - set(row.keys()))
        if missing:
            errors.append(f"line {line_no}: missing fields {missing}")
            continue
            
        entry_id = int(row["entry_id"])
        if entry_id in seen_ids:
            errors.append(f"line {line_no}: duplicate entry_id {entry_id}")
        seen_ids.add(entry_id)
        
        expected = source_map.get(entry_id)
        if expected is None:
            errors.append(f"line {line_no}: entry_id {entry_id} not found in source batch")
            
        src_def = source_defs.get(entry_id, "")
        row_errors = validate_single_entry(row, src_def)
        for err in row_errors:
            errors.append(f"line {line_no}: {err}")
            
        # HTML Tag Consistency Check (non-fatal warning)
        def_he = row.get(config.definition_target_field, "").strip()
        if '<' in src_def or '>' in src_def or '<' in def_he or '>' in def_he:
            src_tags = extract_tag_sequence(src_def)
            tgt_tags = extract_tag_sequence(def_he)
            
            strict_tags = {"div", "/div", "blockquote", "/blockquote", "br", "a", "/a"}
            src_struct = [t for t in src_tags if t[1:-1].strip().lower() in strict_tags]
            tgt_struct = [t for t in tgt_tags if t[1:-1].strip().lower() in strict_tags]
            
            src_norm = normalize_structural_tags(src_struct)
            tgt_norm = normalize_structural_tags(tgt_struct)
            
            if src_norm != tgt_norm:
                headword = source_map.get(entry_id, "?")
                print(
                    f"WARNING: Entry {entry_id} ({headword}) tag structure mismatch. "
                    f"Expected structural tags: {src_norm}, Got tags: {tgt_norm}",
                    file=sys.stderr
                )
                
    return errors


            
    return errors



def canonicalize_headwords(rows, source_map: dict[int, str]):
    fixed_rows = []
    for line_no, row in rows:
        entry_id = int(row.get("entry_id", 0))
        expected = source_map.get(entry_id)
        if expected is not None:
            row[config.headword_field] = expected
        fixed_rows.append((line_no, row))
    return fixed_rows


def normalize_and_backfill(rows, source_map: dict[int, str], source_batch_path: Path):
    normalized = []
    seen_ids: set[int] = set()

    # Load source batch definitions for English fallback backfilling
    source_defs = {}
    with source_batch_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            src_row = json.loads(line)
            source_defs[int(src_row["entry_id"])] = src_row

    # Initialize Gemini clients for on-demand LLM proofreading / correction
    # A second client is used as a fallback when the primary hits a 429 quota error.
    client = get_llm_client()
    fallback_client = get_llm_client2()

    for line_no, row in rows:
        if "entry_id" not in row:
            continue
        try:
            entry_id = int(row["entry_id"])
        except (TypeError, ValueError):
            continue

        # Ensure schema completeness with safe defaults.
        row.setdefault(config.headword_field, "")
        row.setdefault(config.definition_target_field, "")
        if config.examples_target_field in REQUIRED_FIELDS:
            row.setdefault(config.examples_target_field, "")

        # Normalize string-like fields.
        row[config.headword_field] = str(row.get(config.headword_field, ""))
        row[config.definition_target_field] = str(row.get(config.definition_target_field, ""))
        if config.examples_target_field in REQUIRED_FIELDS:
            row[config.examples_target_field] = str(row.get(config.examples_target_field, ""))

        # Auto-fix POS tags / register labels before validation.
        row[config.definition_target_field] = post_process_definition(
            row[config.definition_target_field]
        )

        # Validate entry. If it fails and we have the LLM client, try self-healing!
        src_row = source_defs.get(entry_id, {})
        src_def = src_row.get(config.definition_source_field, "")
        
        row_errors = validate_single_entry(row, src_def)
        if row_errors and client:
            headword = source_map.get(entry_id, "?")
            print(f"INFO: Entry {entry_id} ({headword}) failed validation: {row_errors}. Initiating LLM corrector...", file=sys.stderr)
            
            raw_he = row[config.definition_target_field]
            corrected_he = call_llm_corrector(client, headword, src_def, raw_he, fallback_client=fallback_client)
            
            # Post-process and re-validate corrected text
            corrected_processed = post_process_definition(corrected_he)
            test_row = dict(row)
            test_row[config.definition_target_field] = corrected_processed
            test_errors = validate_single_entry(test_row, src_def)
            
            if not test_errors:
                print(f"SUCCESS: Entry {entry_id} ({headword}) successfully corrected by LLM judge!", file=sys.stderr)
                row[config.definition_target_field] = corrected_processed
            else:
                print(f"WARNING: Entry {entry_id} ({headword}) LLM corrector failed to clear all errors: {test_errors}", file=sys.stderr)
                # --- Regex-strip fallback: never drop an entry just for stray foreign chars ---
                # Apply Arabic→Hebrew homoglyph substitution first, then strip remaining
                # forbidden characters. This is always safe since these are LLM leakage artifacts.
                stripped_he = corrected_processed
                for ar_char, he_char in _ARABIC_TO_HEBREW_HOMOGLYPHS.items():
                    stripped_he = stripped_he.replace(ar_char, he_char)
                stripped_he = FORBIDDEN_SCRIPT_PATTERN.sub('', stripped_he)
                stripped_row = dict(row)
                stripped_row[config.definition_target_field] = stripped_he
                strip_errors = validate_single_entry(stripped_row, src_def)
                if not strip_errors:
                    print(f"INFO: Entry {entry_id} ({headword}) salvaged by regex-strip fallback.", file=sys.stderr)
                    row[config.definition_target_field] = stripped_he
                else:
                    print(f"WARNING: Entry {entry_id} ({headword}) regex-strip fallback still has errors: {strip_errors}. Keeping best available.", file=sys.stderr)
                    row[config.definition_target_field] = stripped_he  # save anyway — strip is always an improvement

        normalized.append((line_no, row))
        seen_ids.add(entry_id)

    # Backfill any missing ids using the source English definition as a fallback.
    for entry_id in sorted(set(source_map) - seen_ids):
        src_row = source_defs.get(entry_id, {})
        src_def = src_row.get(config.definition_source_field, "")
        src_ex = src_row.get(config.examples_source_field, "")
        
        headword = source_map[entry_id]
        print(f"WARNING: Entry {entry_id} ({headword}) was omitted by the model. Backfilling with source English definition as fallback.", file=sys.stderr)
        
        entry_to_backfill = {
            "entry_id": entry_id,
            config.headword_field: headword,
            config.definition_target_field: post_process_definition(src_def),
        }
        if config.examples_target_field in REQUIRED_FIELDS:
            entry_to_backfill[config.examples_target_field] = src_ex
        normalized.append((-1, entry_to_backfill))

    normalized.sort(key=lambda pair: int(pair[1]["entry_id"]))
    return normalized


def has_examples_field(path: Path) -> bool:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            return config.examples_source_field in row
    return False


# ---------- Task 2: Sense-count mismatch warnings ----------

def _count_numbered_senses(text: str) -> int:
    """Count distinct leading sense numbers like '1.', '2.' in *text*."""
    return len(set(re.findall(r"(?:^|\n)\s*(\d+)\.", text)))


def warn_sense_count_mismatches(rows, source_batch_path: Path) -> None:
    """Print warnings to stderr when a translation has fewer numbered senses
    than the corresponding source definition."""
    # Build a map of entry_id → source definition_en from the batch file.
    source_defs: dict[int, str] = {}
    with source_batch_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            src_row = json.loads(line)
            eid = int(src_row["entry_id"])
            source_defs[eid] = str(src_row.get(config.definition_source_field, ""))

    for _line_no, row in rows:
        eid = int(row["entry_id"])
        src_def = source_defs.get(eid, "")
        src_count = _count_numbered_senses(src_def)
        if src_count < 2:
            continue  # single-sense entries don't need checking
        tgt_def = str(row.get(config.definition_target_field, ""))
        tgt_count = _count_numbered_senses(tgt_def)
        if tgt_count < src_count:
            headword = row.get(config.headword_field, "?")
            print(
                f"WARNING: entry {eid} ({headword}): source has {src_count} senses "
                f"but translation has {tgt_count}",
                file=sys.stderr,
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a full translated batch from a file or stdin and validate it."
    )
    parser.add_argument("source_batch", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Optional translated JSONL file to import; otherwise read from stdin.",
    )
    args = parser.parse_args()

    # Dynamically adjust required output schema fields based on input batch content
    global REQUIRED_FIELDS, FIELD_ORDER
    if not has_examples_field(args.source_batch):
        REQUIRED_FIELDS = {"entry_id", config.headword_field, config.definition_target_field}
        FIELD_ORDER = ["entry_id", config.headword_field, config.definition_target_field]
    else:
        REQUIRED_FIELDS = {"entry_id", config.headword_field, config.definition_target_field, config.examples_target_field}
        FIELD_ORDER = ["entry_id", config.headword_field, config.definition_target_field, config.examples_target_field]

    raw_text = read_input_text(args.input_file)

    rows = [(line_no, repair_mojibake_value(row)) for line_no, row in load_jsonl_text(raw_text)]
    source_map = load_source_map(args.source_batch)
    rows = canonicalize_headwords(rows, source_map)
    rows = normalize_and_backfill(rows, source_map, args.source_batch)
    errors = validate(rows, source_map, args.source_batch)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    # Warn about sense-count mismatches (non-fatal).
    warn_sense_count_mismatches(rows, args.source_batch)

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for _, row in rows) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "valid": True,
                "rows": len(rows),
                "output": str(args.output_jsonl),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
