# Setup & Onboarding Guide

Welcome to the Spanish-Hebrew Dictionary Translation & Kindle Compilation pipeline! This guide will help you set up and run the pipeline on your own machine.

---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed:
1. **Python 3.10+** (Python 3.12 or 3.13 is recommended).
2. **Git**.
3. **KindleGen** (command-line tool by Amazon to compile Kindle dictionaries).
   - A zip file `kindlegen_win32.zip` is available in `scratch/kindlegen_win32.zip`. Extract it or download it for your platform.

---

## 🚀 Quick Start

### 1. Clone and Setup Environment

Clone the repository to your local machine, navigate to the folder, and create a virtual environment:

```bash
# Clone the repository (or navigate to the directory if already cloned)
cd dic

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows (Command Prompt):
.venv\Scripts\activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Credentials

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your Gemini API key:
   ```env
   GEMINI_API_KEY=AIzaSy...
   ```
   *(You can get a free or pay-as-you-go Gemini API key from [Google AI Studio](https://aistudio.google.com/)).*

### 3. Verify the Installation

Run the test suite to make sure everything is working as expected:
```bash
python -m pytest tests/ -v
```

---

## 📂 Project Structure

- `config.json`: Project configuration (language names, codes, DB field names, and Kindle metadata).
- `translation_guidelines.md`: Quality constraints and instruction prompts injected into the translator.
- `prepare_translation_batches.py`: Splits the dictionary parsed database into batches.
- `translate_batches.py`: The translation runner that calls Gemini APIs.
- `import_translated_batch.py`: Import validation gate (cleans and validates LLM outputs).
- `merge_translated_batches.py`: Combines batches into a single database.
- `build_kindle_dict.py`: Compiles the database into Kindle-compatible XHTML, OPF, and NCX files.
- `parsers/`: Contains custom dictionary parser scripts.
- `tests/`: Automated unit and integration test suite.

---

## 🔄 Running the Pipeline End-to-End

### Step 1: Parse the Source Dictionary
Use one of the parsers in `parsers/` or write a custom one (see `parsers/README.md`) to convert your raw source dictionary HTML/text into the initial structured `dictionary_entries.jsonl` database inside your work directory (e.g. `work/` or `work2/`):
```bash
python parsers/parse_oxford_html.py path/to/raw_source.html --jsonl work2/dictionary_entries.jsonl --csv work2/dictionary_entries.csv
```

### Step 2: Prepare Translation Batches
Split the dataset into 100-entry batches:
```bash
python prepare_translation_batches.py work2/dictionary_entries.jsonl --output-dir work2/translation_batches --batch-size 100
```

### Step 3: Run the Translation
Run the translator over the target range of batches:
```bash
python translate_batches.py --source-dir work2/translation_batches --translated-dir work2/translated_batches --start-batch 1 --end-batch 10
```

### Step 4: Merge Batches
Once the batches are translated, merge them into a single file:
```bash
python merge_translated_batches.py --input-dir work2/translated_batches --jsonl work2/dictionary_es_he.jsonl --csv work2/dictionary_es_he.csv
```

### Step 5: Build Kindle Sources
Build Kindle-compatible XHTML/OPF files:
```bash
python build_kindle_dict.py --input work2/dictionary_es_he.jsonl --output-dir work2/kindle_source
```

### Step 6: Compile the PRC
Compile with KindleGen:
```bash
# On Windows
scratch\kindlegen\kindlegen.exe work2\kindle_source\content.opf -o oxford_es_he.prc
```
Copy `oxford_es_he.prc` to your Kindle e-reader's `dictionaries/` folder!
