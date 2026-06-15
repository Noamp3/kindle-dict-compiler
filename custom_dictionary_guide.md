# Custom Dictionary Adaptation Guide

This guide explains how to adapt this translation and compilation pipeline for a new source language dictionary (e.g., French-English or Italian-English) to translate and compile it into a target language dictionary (e.g., French-Hebrew or Italian-Hebrew).

---

## 🛠️ What Needs to Be Customized?

To run the pipeline on a new language pair or dictionary source, you must customize four areas:

```
new-dictionary/
├── 1. parsers/custom_parser.py  <-- Parse raw source format
├── 2. config.json               <-- Language, metadata, and field names
├── 3. prompt_templates/ &       <-- Instructions & few-shot examples
│      translation_guidelines.md
└── 4. work/inflections_map.json <-- Inflected form lookup database
```

---

### 1. Source Dictionary Parser (`parsers/`)

Every raw dictionary has a unique HTML, XML, or text structure. You must write a custom parser to convert it into the standardized **4-field JSONL schema**.

1. Copy `parsers/parser_template.py` to a new parser file:
   ```bash
   cp parsers/parser_template.py parsers/parse_french_html.py
   ```
2. Modify `extract_entries()` to segment your raw file into entries. Common segment separators are `<hr/>`, `<mbp:pagebreak/>`, or newlines.
3. Modify `parse_entry()` to extract:
   - **Headword**: The word being defined.
   - **Definition**: The English definition/senses.
   - **Examples** (optional): Example sentences in the source language.
4. Run your parser to generate the source JSONL database:
   ```bash
   python parsers/parse_french_html.py path/to/raw_dict.html --jsonl work/dictionary_entries.jsonl --csv work/dictionary_entries.csv
   ```

---

### 2. Configuration Settings (`config.json`)

Update `config.json` at the root of the workspace to configure languages, database field names, and Kindle metadata:

```json
{
  "work_dir": "work",
  "model": "gemma-4-31b-it",
  "source_lang": {
    "name": "French",
    "code": "fr"
  },
  "target_lang": {
    "name": "Hebrew",
    "code": "he"
  },
  "fields": {
    "headword": "headword_fr",
    "definition_source": "definition_en",
    "definition_target": "definition_he",
    "examples_source": "examples_en",
    "examples_target": "examples_he"
  },
  "grammar_markers": [
    "adj.", "adv.", "v.", "n. f.", "n. m.", "prep."
  ],
  "kindle": {
    "title": "French Hebrew Dictionary",
    "creator": "Your Name",
    "publisher": "Your Publisher",
    "subject": "Dictionaries",
    "description": "French-Hebrew Dictionary compiled from raw source",
    "identifier": "fr-he-dict-custom"
  }
}
```

*Note: `grammar_markers` is used by the compiler to clean grammar abbreviations out of lookup keys (e.g., stripping `(adj.)` so the reader can select `grand` and match the headword).*

---

### 3. Prompt Templates & Translation Guidelines

The prompts instruct the LLM on target grammatical structures, registry rules, and output formatting.

1. **Prompt Templates (`prompt_templates/`)**:
   - Open `translation_no_examples.txt` or `translation_with_examples.txt`.
   - Update the instructions where Spanish is referenced to your source language (e.g., change `"Spanish word"` to `"French word"`).
2. **Translation Guidelines (`translation_guidelines.md`)**:
   - Update the guidelines to reflect source language part-of-speech abbreviations.
   - Update the **few-shot examples** to match your source language. For example:
     - Replace Spanish source words and examples with French equivalents.
     - Ensure the format of the examples matches the dictionary style of your new source.

---

### 4. Inflections Mapping (`inflections_map.json`)

To enable the Kindle to lookup conjugated verbs or plural nouns and resolve them to their root headword (e.g., selecting French verb `furent` or `eurent` matching `être` or `avoir`), you need an inflections map.

1. Generate or obtain an inflection database mapping inflected forms to root forms.
2. Format the file as a JSON object:
   ```json
   {
     "inflected_word": ["root_word_option1", "root_word_option2"]
   }
   ```
3. Save this file to your work directory as `inflections_map.json` (e.g., `work2/inflections_map.json` or as configured in `build_kindle_dict.py`). The compilation script will automatically load this file and inject `<idx:iform>` tags into the Kindle package.
