from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
 
from config_helper import config

# Common grammatical markers to exclude from headword index keys
GRAMMAR_MARKERS = {
    "n.",
    "adj.",
    "v.",
    "adv.",
    "prep.",
    "f.",
    "m.",
    "pl.",
    "sing.",
    "pron.",
    "conj.",
    "art.",
    "sufijo",
    "prefijo",
    "n",
    "adj",
    "v",
    "adv",
    "prep",
    "f",
    "m",
    "pl",
    "sing",
}


def extract_lookup_keys(headword: str) -> list[str]:
    """Clean and extract multiple lookup keys (orthographies) from a rich Spanish headword."""
    keys: list[str] = []

    # Clean the raw headword first (remove leading/trailing spaces, quotes, punctuation)
    cleaned_hw = headword.strip()
    if not cleaned_hw:
        return keys

    # Find all text inside parentheses
    parens = re.findall(r"\(([^)]+)\)", cleaned_hw)

    # Main part is the headword with parentheses removed
    main_part = re.sub(r"\([^)]+\)", "", cleaned_hw).strip()

    # Helper to process and split a segment of a headword
    def process_segment(segment: str):
        # Split on common delimiters like comma, semicolon, or slash
        parts = re.split(r"[,;/]", segment)
        for part in parts:
            part_clean = part.strip()
            # Clean symbols from the lookup search key
            part_clean = re.sub(r'[#$"\'+*^~?`|\[\]]', "", part_clean).strip()
            # Compress multiple spaces into a single space
            part_clean = re.sub(r'\s+', ' ', part_clean).strip()
            # Strip trailing sense numbers (e.g. 'desalmado 1' -> 'desalmado')
            part_clean = re.sub(r'\s+\d+$', '', part_clean).strip()
            # Strip trailing grammatical indicators (e.g. 'abad n.' -> 'abad')
            words = part_clean.split()
            if len(words) > 1 and words[-1].lower() in GRAMMAR_MARKERS:
                part_clean = " ".join(words[:-1]).strip()
            # Avoid single letters unless it is a valid single-letter word in Spanish (like a, o, y)
            if not part_clean or (len(part_clean) == 1 and part_clean.lower() not in ("a", "o", "y")):
                continue
            # Avoid purely grammatical indicators
            if part_clean.lower() in GRAMMAR_MARKERS:
                continue
            if part_clean not in keys:
                keys.append(part_clean)

    # Process the main part
    process_segment(main_part)

    # Process all parenthetical phrases
    for paren in parens:
        process_segment(paren)

    # Fallback to the original cleaned headword without parentheticals if no keys could be extracted
    if not keys:
        fallback = re.sub(r'[#$"\'+*^~?`|\[\]()]', "", cleaned_hw).strip()
        if fallback:
            keys.append(fallback)

    return keys


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


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


_HEB_RE = re.compile(r'[\u0590-\u05FF]')

def reverse_hebrew_words_in_text(text: str) -> str:
    """Reverse the word order of a text block if it contains Hebrew, preserving surrounding spacing and newlines."""
    if not _HEB_RE.search(text):
        return text
    
    lines = text.split('\n')
    reversed_lines = []
    for line in lines:
        if not _HEB_RE.search(line):
            reversed_lines.append(line)
            continue
            
        leading_ws = line[:len(line) - len(line.lstrip())]
        trailing_ws = line[len(line.rstrip()):]
        
        words = line.strip().split()
        words.reverse()
        reversed_lines.append(leading_ws + " ".join(words) + trailing_ws)
        
    return '\n'.join(reversed_lines)



def reverse_hebrew_in_html(html_str: str) -> str:
    """Split html by tag patterns and reverse Hebrew words inside text nodes."""
    parts = re.split(r'(<[^>]+>)', html_str)
    for i in range(len(parts)):
        if i % 2 == 0:  # Text node
            parts[i] = reverse_hebrew_words_in_text(parts[i])
    return "".join(parts)


def reverse_hebrew_in_html_exclude_pipes(html_str: str) -> str:
    """Split html by tag patterns and reverse Hebrew words in text nodes, excluding nodes containing a pipe."""
    parts = re.split(r'(<[^>]+>)', html_str)
    for i in range(len(parts)):
        if i % 2 == 0:  # Text node
            if '|' not in parts[i]:
                parts[i] = reverse_hebrew_words_in_text(parts[i])
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a Spanish-Hebrew dictionary database into Kindle-compatible XHTML/OPF/NCX files."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("work/dictionary_es_he.jsonl"),
        help="Input JSONL file of the merged dictionary.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("work/kindle_source"),
        help="Output directory for generated Kindle source files.",
    )
    parser.add_argument(
        "--inflections",
        type=Path,
        default=None,
        help="Path to inflections JSON map file. If not specified, automatically searches under the input directory, work/, and work2/ folders.",
    )
    args = parser.parse_args()

    input_path = args.input
    if not input_path.exists():
        # Fallback to the sample file if main file doesn't exist yet
        sample_path = input_path.parent / "dictionary_es_he_sample.jsonl"
        if sample_path.exists():
            print(f"Input file '{input_path}' not found. Falling back to sample file: {sample_path}")
            input_path = sample_path
        else:
            print(f"Error: Input file '{input_path}' does not exist.")
            return 1

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    book_html_path = output_dir / "book.html"
    content_opf_path = output_dir / "content.opf"
    toc_ncx_path = output_dir / "toc.ncx"

    print(f"Reading dictionary from: {input_path}")
    entries = list(load_jsonl(input_path))
    print(f"Loaded {len(entries)} entries.")

    # Load inflections map if available
    inflections_map = {}
    inflections_path = args.inflections
    if not inflections_path:
        # Search candidate locations
        candidates = [
            input_path.parent / "inflections_map.json",
            Path("work/inflections_map.json"),
            Path("work2/inflections_map.json")
        ]
        for candidate in candidates:
            if candidate.exists():
                inflections_path = candidate
                break

    if inflections_path and inflections_path.exists():
        print(f"Loading inflections map from: {inflections_path}")
        with inflections_path.open("r", encoding="utf-8") as inf_f:
            inflections_map = json.load(inf_f)
        print(f"Loaded {len(inflections_map)} inflections.")
    else:
        print("No inflections map found. Proceeding without inflections lookup rules.")

    # 1. Write book XHTML source files (split into multiple parts to avoid KindleGen parsing bottleneck)
    entries_per_file = 2000
    chunks = [entries[i : i + entries_per_file] for i in range(0, len(entries), entries_per_file)]
    print(f"Splitting {len(entries)} entries into {len(chunks)} HTML files (max {entries_per_file} entries each).")
    
    html_files = []
    
    for chunk_idx, chunk in enumerate(chunks, 1):
        part_name = f"part_{chunk_idx:03d}.html"
        part_path = output_dir / part_name
        html_files.append(part_name)
        print(f"Generating XHTML part {chunk_idx}/{len(chunks)}: {part_name}")
        
        with part_path.open("w", encoding="utf-8") as f:
            f.write(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<html xmlns:idx="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf"\n'
                '      xmlns:mbp="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf">\n'
                "<head>\n"
                '  <meta http-equiv="content-type" content="text/html; charset=utf-8" />\n'
                f"  <title>Spanish Hebrew Dictionary Part {chunk_idx}</title>\n"
                "  <style>\n"
                "    blockquote {\n"
                "      margin: 0.2em 0 0.5em 1.5em;\n"
                "    }\n"
                "    .definition {\n"
                "      direction: rtl;\n"
                "      unicode-bidi: embed;\n"
                "      text-align: right;\n"
                "      display: block;\n"
                "    }\n"
                "    .example {\n"
                "      direction: rtl;\n"
                "      unicode-bidi: embed;\n"
                "      text-align: right;\n"
                "      font-style: italic;\n"
                "      color: #555555;\n"
                "      display: block;\n"
                "      margin-top: 0.1em;\n"
                "    }\n"
                "    hr {\n"
                "      border: none;\n"
                "      border-bottom: 1px solid #e0e0e0;\n"
                "      margin: 0.3em 0;\n"
                "    }\n"
                "  </style>\n"
                "</head>\n"
                "<body>\n"
                "  <mbp:frameset>\n"
            )

            for entry in chunk:
                headword_es = entry.get("headword_es", "")
                definition_he = entry.get("definition_he", "")
                examples_he = entry.get("examples_he", "")

                # Pre-reverse Hebrew word order in HTML text nodes, excluding pipe-separated examples
                definition_he = reverse_hebrew_in_html_exclude_pipes(definition_he)

                # Extract lookup keys for this entry
                lookup_keys = extract_lookup_keys(headword_es)

                f.write('    <idx:entry name="default" scriptable="yes" spell="yes">\n')
                # Write all lookup orthographies
                for key in lookup_keys:
                    escaped_key = html.escape(key)
                    infl_block = inflections_map.get(key, "")
                    if infl_block:
                        f.write(f'      <idx:orth value="{escaped_key}">\n')
                        f.write(f'        {infl_block}\n')
                        f.write(f'      </idx:orth>\n')
                    else:
                        f.write(f'      <idx:orth value="{escaped_key}" />\n')

                # Write the visual content of the dictionary entry
                escaped_hw = html.escape(headword_es)
                
                if '<' in definition_he and '>' in definition_he:
                    # Rich HTML definitions
                    formatted_def = definition_he
                    
                    # ---------------------------------------------------------------
                    # Comprehensive BiDi fix for Kindle word-reversal bugs.
                    #
                    # Problem: When Hebrew and LTR Latin text appear in the same
                    # block-level element, Kindle's bidi algorithm reorders words.
                    #
                    # Fix: Split every <blockquote> or <div> that contains a pipe-
                    # separated bilingual example (LTR | RTL) into two direction-
                    # isolated child divs. Handles:
                    #   - Single pipes:   <bq>Spanish | עברית</bq>
                    #   - Multiple pipes: <bq>ES1 | HE1 | ES2 | HE2</bq>
                    #   - <div> elements: same logic as blockquotes
                    # ---------------------------------------------------------------
                    _HEB_RE = re.compile(r'[\u0590-\u05FF]')
                    _TAG_RE = re.compile(r'<[^>]*>')
                    
                    def _has_heb(s: str) -> bool:
                        return bool(_HEB_RE.search(_TAG_RE.sub('', s)))
                    
                    def _make_bidi_pairs(inner: str) -> list[tuple[str, str]]:
                        """
                        Split inner content by | and pair adjacent (LTR, RTL) segments.
                        Returns list of (ltr_content, rtl_content) tuples.
                        Unpaired tail segments are returned as (None, segment).
                        """
                        segs = [s.strip() for s in inner.split('|')]
                        pairs = []
                        i = 0
                        while i < len(segs):
                            seg = segs[i]
                            if i + 1 < len(segs):
                                nxt = segs[i + 1]
                                seg_heb = _has_heb(seg)
                                nxt_heb = _has_heb(nxt)
                                if not seg_heb and nxt_heb:
                                    # Standard LTR | RTL pair
                                    pairs.append((seg, nxt))
                                    i += 2
                                    continue
                                elif seg_heb and not nxt_heb:
                                    # Reversed RTL | LTR — treat RTL as unpaired, retry nxt
                                    pairs.append((None, seg))
                                    i += 1
                                    continue
                            # Unpaired segment — put it in RTL (Hebrew) slot
                            pairs.append((None, seg))
                            i += 1
                        return pairs
                    
                    def _split_bidi_element(inner: str, is_blockquote: bool) -> str | None:
                        """
                        Given inner content of a <blockquote> or <div>, return
                        replacement HTML if it contains mixed bidi pipe patterns.
                        Returns None if no split needed.
                        """
                        # Skip if already direction-split
                        if 'dir="ltr"' in inner or 'dir="rtl"' in inner:
                            return None
                        # Only process if there is a | separator
                        if '|' not in inner:
                            return None
                        # Only process if there is Hebrew somewhere (it's a real translation)
                        if not _has_heb(inner):
                            return None
                        
                        pairs = _make_bidi_pairs(inner)
                        # Require at least one valid (LTR, RTL) pair
                        if not any(ltr is not None for ltr, rtl in pairs):
                            return None
                        
                        LTR_DIV = '<div dir="ltr" align="right" style="direction: ltr; text-align: right; display: block; font-style: italic; color: #555555; margin-bottom: 0.1em;">\u200e{}</div>'
                        RTL_DIV = '<div dir="rtl" align="right" style="direction: rtl; text-align: right; display: block; color: #111111; margin-right: 1.2em;">\u200f{}</div>'
                        
                        children = []
                        for ltr_content, rtl_content in pairs:
                            if ltr_content is not None:
                                children.append(f'          {LTR_DIV.format(ltr_content)}')
                            if rtl_content:
                                reversed_rtl = reverse_hebrew_in_html(rtl_content)
                                children.append(f'          {RTL_DIV.format(reversed_rtl)}')
                        
                        tag = 'blockquote' if is_blockquote else 'div'
                        if is_blockquote:
                            attrs = 'dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; margin: 0.2em 0 0.5em 1.5em;"'
                        else:
                            attrs = 'dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; margin-bottom: 0.15em;"'
                        
                        return f'<{tag} {attrs}>\n' + '\n'.join(children) + f'\n        </{tag}>'
                    
                    def fix_bidi_in_html(html_str: str) -> str:
                        # Pass 1: leaf <blockquote> elements
                        def replace_blockquote(m: re.Match) -> str:
                            result = _split_bidi_element(m.group(1), is_blockquote=True)
                            return result if result is not None else m.group(0)
                        
                        html_str = re.sub(
                            r'<blockquote>((?:(?!<blockquote>).)*?)</blockquote>',
                            replace_blockquote,
                            html_str,
                            flags=re.DOTALL
                        )
                        
                        # Pass 2: leaf <div> elements (no nested div or blockquote)
                        def replace_div(m: re.Match) -> str:
                            result = _split_bidi_element(m.group(1), is_blockquote=False)
                            return result if result is not None else m.group(0)
                        
                        html_str = re.sub(
                            r'<div>((?:(?!<div>|<blockquote>).)*?)</div>',
                            replace_div,
                            html_str,
                            flags=re.DOTALL
                        )
                        return html_str
                    
                    formatted_def = fix_bidi_in_html(formatted_def)
                    
                    # Inject RTL attributes to top level div/blockquote containers for Kindle lookup compatibility
                    formatted_def = re.sub(
                        r'<div>',
                        r'<div dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; margin-bottom: 0.15em;">',
                        formatted_def
                    )
                    formatted_def = re.sub(
                        r'<blockquote>',
                        r'<blockquote dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; margin: 0.2em 0 0.5em 1.5em;">',
                        formatted_def
                    )
                    # Ensure the HTML formatting is perfectly closed and balanced to prevent styling spillover
                    formatted_def = balance_and_fix_html(formatted_def)
                else:
                    # Plain-text definitions fallback
                    escaped_def = html.escape(definition_he)
                    
                    # Format line breaks in definition with perfect RTL isolation
                    formatted_def = ""
                    for line in escaped_def.split("\n"):
                        line_str = line.strip()
                        if line_str:
                            # Clean up parenthesis shifting: Wrap mixed segments (like (נקבה) or <Mús>) in separate direction isolation
                            # This ensures trailing indicators or list numbers ('1.', '2.') do not flip to the wrong side.
                            line_str = re.sub(
                                r'(\d+\.)\u200e?\s*',
                                r'<span style="direction: ltr; unicode-bidi: embed; display: inline-block; margin-left: 0.25em;">\1</span>' + '\u200f ',
                                line_str
                            )
                            # Wrap any parenthesized segments to guarantee LTR/RTL bounds are preserved
                            line_str = re.sub(
                                r'(\([\u0590-\u05fe/a-zA-Z\s,+-]+\))',
                                r'<span style="unicode-bidi: embed; direction: rtl;">\1</span>' + '\u200f',
                                line_str
                            )
                            # Wrap brackets (<Mús>)
                            line_str = re.sub(
                                r'(&lt;[^&]+&gt;)',
                                r'<span style="direction: ltr; unicode-bidi: embed; display: inline-block;">\1</span>' + '\u200f',
                                line_str
                            )
                            formatted_def += f'<div class="definition" dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; margin-bottom: 0.15em;">\u200f{line_str}</div>'
                
                f.write(f"      <b>{escaped_hw}</b>\n")
                f.write(f"      <blockquote>\n")
                if '<div' in formatted_def:
                    f.write(f'        {formatted_def}\n')
                else:
                    f.write(f'        <div class="definition" dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; display: block;">{formatted_def}</div>\n')
     
                if examples_he:
                    examples_list = [ex.strip() for ex in examples_he.split(" || ") if ex.strip()]
                    if examples_list:
                        for ex in examples_list:
                            if '|' in ex:
                                parts = ex.split('|', 1)
                                spanish_part = parts[0].strip()
                                hebrew_part = parts[1].strip()
                                
                                escaped_es = html.escape(spanish_part)
                                escaped_he = html.escape(hebrew_part)
                                reversed_he = reverse_hebrew_words_in_text(escaped_he)
                                
                                # Write Spanish example in LTR flow and Hebrew translation in RTL flow on separate lines
                                f.write(
                                    f'        <div class="example" dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; display: block; margin-top: 0.35em; border-top: 1px dashed #eeeeee; padding-top: 0.25em;">\n'
                                    f'          <div dir="ltr" align="right" style="direction: ltr; text-align: right; display: block; font-style: italic; color: #555555; margin-bottom: 0.15em;">\u200e{escaped_es}</div>\n'
                                    f'          <div dir="rtl" align="right" style="direction: rtl; text-align: right; display: block; color: #111111; font-weight: normal; margin-right: 1.2em;">\u200f{reversed_he}</div>\n'
                                    f'        </div>\n'
                                )
                            else:
                                escaped_ex = html.escape(ex)
                                reversed_ex = reverse_hebrew_words_in_text(escaped_ex)
                                f.write(f'        <div class="example" dir="rtl" align="right" style="direction: rtl; text-align: right; unicode-bidi: embed; font-style: italic; color: #555555; display: block; margin-top: 0.25em; border-top: 1px dashed #eeeeee; padding-top: 0.15em;">Ex: \u200f{reversed_ex}</div>\n')
     
                f.write(f"      </blockquote>\n")
                f.write("    </idx:entry>\n")
                f.write("    <hr />\n")

            f.write("  </mbp:frameset>\n" "</body>\n" "</html>\n")

    # 2. Write content.opf
    print(f"Generating OPF: {content_opf_path}")
    
    title = config.kindle_title
    creator = config.kindle_creator
    publisher = config.kindle_publisher
    description = config.kindle_description
    identifier = config.kindle_identifier
    
    if "work2" in str(input_path) or "work2" in str(output_dir):
        title = "Oxford Spanish Hebrew Dictionary"
        creator = "Oxford University Press"
        publisher = "Oxford University Press"
        description = "Spanish-Hebrew Dictionary compiled from Oxford Spanish-English Dictionary"
        identifier = "es-he-dict-oxford"

    # Generate manifest and spine HTML references
    manifest_items = []
    spine_items = []
    for idx, f_name in enumerate(html_files, 1):
        manifest_items.append(f'    <item id="part_{idx:03d}" media-type="text/html" href="{f_name}" />')
        spine_items.append(f'    <itemref idref="part_{idx:03d}" />')
        
    manifest_xml = "\n".join(manifest_items)
    spine_xml = "\n".join(spine_items)

    # We will give it a standard unique identifier
    content_opf_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">\n'
        f"    <dc:title>{title}</dc:title>\n"
        f"    <dc:language>{config.source_lang_code}</dc:language>\n"
        f'    <dc:identifier id="uid">{identifier}</dc:identifier>\n'
        f"    <dc:creator>{creator}</dc:creator>\n"
        f"    <dc:publisher>{publisher}</dc:publisher>\n"
        f'    <dc:subject BASICCode="REF008000">{config.kindle_subject}</dc:subject>\n'
        f"    <dc:description>{description}</dc:description>\n"
        '    <meta name="output encoding" content="utf-8" />\n'
        "    <x-metadata>\n"
        f"      <DictionaryInLanguage>{config.source_lang_code}</DictionaryInLanguage>\n"
        f"      <DictionaryOutLanguage>{config.target_lang_code}</DictionaryOutLanguage>\n"
        '      <DefaultLookupIndex>default</DefaultLookupIndex>\n'
        "    </x-metadata>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        f"{manifest_xml}\n"
        '    <item id="ncx" media-type="application/x-dtbncx+xml" href="toc.ncx" />\n'
        "  </manifest>\n"
        '  <spine toc="ncx">\n'
        f"{spine_xml}\n"
        "  </spine>\n"
        "  <tours />\n"
        "  <guide />\n"
        "</package>\n",
        encoding="utf-8",
    )

    # 3. Write toc.ncx
    print(f"Generating NCX: {toc_ncx_path}")
    toc_ncx_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="en">\n'
        "  <head>\n"
        f'    <meta content="{identifier}" name="dtb:uid" />\n'
        '    <meta content="1" name="dtb:depth" />\n'
        '    <meta content="Antigravity Kindle Compiler" name="dtb:generator" />\n'
        '    <meta content="0" name="dtb:totalPageCount" />\n'
        '    <meta content="0" name="dtb:maxPageNumber" />\n'
        "  </head>\n"
        "  <docTitle>\n"
        f"    <text>{title}</text>\n"
        "  </docTitle>\n"
        "  <navMap>\n"
        '    <navPoint id="navpoint-1" playOrder="1">\n'
        "      <navLabel>\n"
        f"        <text>{title}</text>\n"
        "      </navLabel>\n"
        '      <content src="part_001.html" />\n'
        "    </navPoint>\n"
        "  </navMap>\n"
        "</ncx>\n",
        encoding="utf-8",
    )

    print("\nKindle dictionary sources compiled successfully!")
    print(f"Output folder: {output_dir.resolve()}")
    print("Files created:")
    print(f"  - part files : {len(html_files)} XHTML files (part_001.html to part_{len(html_files):03d}.html)")
    print(f"  - content.opf: {content_opf_path.name} ({content_opf_path.stat().st_size} bytes)")
    print(f"  - toc.ncx    : {toc_ncx_path.name}    ({toc_ncx_path.stat().st_size} bytes)")
    print("\nNext step: Import the 'content.opf' file into Kindle Previewer 3 or run 'kindlegen content.opf -o dictionary_es_he.prc' to generate the Kindle .prc dictionary!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
