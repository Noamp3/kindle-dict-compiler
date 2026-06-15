# Dictionary Parsing Framework

This directory contains dictionary parsers that convert raw, extracted dictionary files (e.g., extracted Mobi/PRC HTML files, raw text, XML, or JSON) into structured database datasets. 

Isolating the parsing step makes it easy for developers and LLM agents to support new dictionary structures without modifying downstream translation, validation, and Kindle compilation scripts.

---

## The Target Parsed Schema

Every parser must output a unified JSONL (and optionally a companion CSV) file where each line is a valid JSON object with the following fields:

- `headword_<lang>` (e.g., `headword_es` for Spanish): The original source language headword.
- `definition_en`: The definition translated/written in English.
- `examples_en` (optional): Example sentences in the source language and/or their English translations, separated by ` || ` if multiple examples exist.
- `entry_text_en` (optional): The full raw text of the entry for debugging/recovery.

> [!NOTE]
> The exact keys used for the headword, definition, and examples should match the `fields` section of the root `config.json` file.

---

## Writing a New Custom Parser

To write a parser for a new dictionary format:

1. **Copy the Template**: Make a copy of `parsers/parser_template.py` and name it appropriately (e.g., `parsers/parse_french_dict.py`).
2. **Configure `config.json`**: Update the root `config.json` with the appropriate field names and metadata for the new dictionary (e.g., `"headword": "headword_fr"`).
3. **Implement `parse_entry`**: Inside your new parser script, locate the `parse_entry` function:
   ```python
   def parse_entry(raw_block: str) -> dict | None:
       # Write custom regexes, BeautifulSoup logic, or string manipulation here
       # to extract the headword and definition.
       ...
   ```
4. **Define Chunk Iteration**: If your raw input file has standard entry boundary tags (like `<hr/>`, `<mbp:pagebreak/>`, or newlines), define the splitting separator in your main loop.
5. **Run the Parser**:
   ```bash
   python parsers/parse_french_dict.py path/to/raw_dictionary.html --jsonl work/dictionary_entries.jsonl --csv work/dictionary_entries.csv
   ```

---

## Guidelines for LLM Agents

When an LLM agent is instructed to modify a parser or write a new one:
- **Inspect `parser_template.py`**: It handles all files, inputs, outputs, encodings, and CLI argument parsing out-of-the-box. Never rewrite the boilerplate.
- **Use Regex Carefully**: Raw dictionary files can have highly irregular HTML formatting or bad spacing. Prefer robust, fault-tolerant regex searches and use helper clean functions (like `clean_html_text` in the template) to normalize spacing and HTML entities.
- **Support Limits**: Keep the `--limit` CLI argument functional so that users can quickly run tests on the first 5–10 entries of a dictionary before parsing all 100,000+ entries.
