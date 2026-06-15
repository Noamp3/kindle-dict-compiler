# Spanish to Hebrew Dictionary Translation Guidelines

Use these rules when translating one source batch from `work/translation_batches/*.jsonl`.

## Goal

Keep the Spanish headword unchanged and translate only the English content into natural, concise Hebrew suitable for dictionary use.

The default operating mode is one whole 100-row batch per subagent or model call.

## Input fields

- `entry_id`
- `headword_es`
- `definition_en`
- `examples_en`

## Output fields

Return one JSON object per input row with these fields:

- `entry_id`
- `headword_es`
- `analysis`
- `definition_he`
- `examples_he`

## Rules

1. Preserve the Spanish headword exactly.
2. **Chain of Thought**: You must generate an `"analysis"` string field *before* the definition. In it, briefly state the parts of speech, the total number of numbered senses, and any regional/register labels. This will help you plan your translation.
3. Translate definitions into concise dictionary-style Hebrew.
4. Translate examples into readable Hebrew, but keep symbols such as `#`, `*`, `(`, `)` and structural punctuation unchanged.
5. If multiple examples are present, keep them separated with ` || `.
6. Do not invent senses that are not present in the English source.
7. Return JSONL only. Do not wrap output in markdown fences or add commentary before or after the JSONL.
8. Output exactly one JSON object for every input row, with no skipped or duplicated `entry_id` values.
9. Keep `entry_id` numeric and unchanged.
10. Prefer concise Hebrew wording over explanatory prose so full batches fit within model limits.
12. Do NOT use shortened abbreviations for POS (e.g. `ז'`, `נ'`, `פ"י`, `פ"ע`, `פ'`, `ת'`, `תה"פ`). Use only the **full, unshortened** grammatical markers inside tags or parentheses (e.g., `<i>(תואר)</i>` or `<i>(זכר)</i>`).
13. **RTL/LTR Separation**: If a parenthesized Hebrew grammatical tag or register label directly precedes a numbered sense list, separate them with ` — ` (space, em-dash, space) if they are in plain text, but if they are already separated by structural HTML blocks/divs, keep the HTML structure intact.
14. **Allowed Characters Only**: The translation must contain only Hebrew, Latin/Spanish, numbers, and standard punctuation. Never output foreign scripts (like Cyrillic, Arabic, or Hindi/Devanagari).
15. **HTML Style & Layout Preservation**: The input `definition_en` contains HTML formatting tags (`<b>`, `<i>`, `<blockquote>`, `<a>`, `<br/>`, `<sup>`, `<sub>`, `<div>`). You **MUST** preserve all HTML tags and their structural hierarchy *exactly* in your translated `definition_he`. Translate *only* the English definition and example texts inside the tags into Hebrew, leaving any Spanish words (usually inside `<i>...</i>`), numbers, and structural HTML tags completely unchanged in their original positions. While the exact HTML tag hierarchy and structure must be preserved, the Hebrew text inside these elements should flow naturally in Right-to-Left (RTL) reading order, which is welcomed and required for Hebrew translations.

## Part-of-Speech Formatting

Do NOT use shortened abbreviations for grammatical part-of-speech tags. Instead, always use **full, unshortened Hebrew words** in parentheses at the start of `definition_he`:

| POS | Full Hebrew Format |
|-----|--------------------|
| Masculine noun | (זכר) |
| Feminine noun | (נקבה) |
| Verb (transitive) | (פועל יוצא) |
| Verb (intransitive) | (פועל עומד) |
| Verb (general) | (פועל) |
| Adjective | (תואר) |
| Adverb | (תואר הפועל) |
| Preposition | (מילת יחס) |
| Conjunction | (מילת קישור) |
| Pronoun | (כינוי גוף) |
| Compound/phrase entry | *omit POS entirely* |

## Strict Sense Preservation & Omission Prevention

1. **Translate EVERY numbered sense**: If the English source contains numbered senses (e.g. `1. ... 2. ... 3. ...`), you **MUST** translate every single sense. You are strictly forbidden from omitting senses or only translating the first one.
2. **Preserve sense numbering**: Keep the exact numbering `1.`, `2.`, etc., matching the English layout.

## Few-Shot Examples for Complex Entries

### Example 1: Entry with HTML Tags & Cross-References
*   **Input**:
    ```json
    {"entry_id": 2, "headword_es": "A", "definition_en": "<div> <div> <div> <i>m</i> - (Med)</div> <div> A ▶grupo sanguíneo <div>see also: <a href=\"#filepos14884245\">grupo sanguíneo</a></div> </div> </div> </div>"}
    ```
*   **Output**:
    ```json
    {"entry_id": 2, "headword_es": "A", "analysis": "POS: masculine noun (m). Domain: Medicine (Med). Senses: 1. Contains a cross-reference link.", "definition_he": "<div> <div> <div> <i>(זכר)</i> - (רפואה)</div> <div> סוג דם A <div>ראה גם: <a href=\"#filepos14884245\">grupo sanguíneo</a></div> </div> </div> </div>"}
    ```

### Example 2: Prefix Entry with Italicized Examples
*   **Input**:
    ```json
    {"entry_id": 4, "headword_es": "a-", "definition_en": "<div> <div> <div> <i>pref</i> </div> <div> a- (as in amoral, asexuado etc) <i>evolución atípica </i> | atypical <i>o</i> unusual development see also: <a href=\"#filepos1574397\">amoral</a> </div> </div> </div>"}
    ```
*   **Output**:
    ```json
    {"entry_id": 4, "headword_es": "a-", "analysis": "POS: prefix (pref). Senses: 1. Contains inline italics and cross-references.", "definition_he": "<div> <div> <div> <i>(תחילית)</i> </div> <div> a- (כמו ב-amoral, asexuado וכו') <i>evolución atípica </i> | התפתחות לא טיפוסית או חריגה ראה גם: <a href=\"#filepos1574397\">amoral</a> </div> </div> </div>"}
    ```

## Output Contract

Every output line must be one valid JSON object with these fields in this exact order:

1. `entry_id`
2. `headword_es`
3. `analysis`
4. `definition_he`
5. `examples_he` (if requested)

Minimal valid example:

`{"entry_id": 123, "headword_es": "casa", "analysis": "POS: feminine noun (f). Senses: 1.", "definition_he": "<div> <div> <i>(נקבה)</i> בית </div> </div>", "examples_he": ""}`

## Batch Handling Rules

- Preferred unit: one full 100-row batch.
- If a batch fails because of response length, rerun that batch alone with shorter wording requirements.
- Split a batch into smaller ranges only as a fallback after a full-batch attempt fails.
- Import is file-based: the model output should be saved as a UTF-8 file and then passed to `import_translated_batch.py --input-file`.
- Do not rely on stdin piping for Hebrew output.

## Recommended Prompt Shape

Translate the attached JSONL batch from a Spanish-English dictionary into a Spanish-Hebrew dictionary.
Preserve `entry_id` and `headword_es` exactly.
Translate `definition_en` and `examples_en` into Hebrew using the output schema in these guidelines.
Return JSONL only, one object per line, with no markdown fences, no extra commentary, and no skipped rows.

## Import Gate

A translated batch is considered complete only if `import_translated_batch.py` accepts it and writes the destination batch file successfully.
