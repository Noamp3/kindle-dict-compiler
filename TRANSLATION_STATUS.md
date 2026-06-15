# Dictionary Translation Status

This file tracks the current batch state on disk, translated metrics, and operational guidelines.

---

## Translation Progress & Metrics

*   **Total Source Entries**: 90,141 entries (split into `batch_0001.jsonl` through `batch_0902.jsonl`).
*   **Total Completed Batches**: 142 batches (`batch_0001` through `batch_0142` inclusive).
*   **Total Translated Entries**: **14,200 entries** (verified, imported, and compiled).
*   **Current Gaps**: **0 Gaps**. Batches `batch_0138` and `batch_0140` have been fully translated, validated, and merged into the canonical database.
*   **Database Schema**: Clean 4-field schema (`entry_id`, `headword_es`, `definition_he`, `examples_he`). All deprecated fields (`entry_text_he`, `needs_review`, `notes`) have been successfully removed.

---

## Core Active Workflow

1.  **Assign Batch Range**: Run translation on new batches by passing starting/ending batch arguments to `translate_batches.py`.
2.  **API Streaming Translator**: The runner uses the official `google-genai` SDK with `gemma-4-31b-it` and `thinking_level="MINIMAL"`.
3.  **Live Logging**: Translations stream chunk-by-chunk live to `stdout`.
4.  **Automatic Import Verification**: The translator automatically runs `import_translated_batch.py` to validate each completed JSONL chunk. Only successful imports are saved to `work/translated_batches/`.
5.  **Rate-Limit Cooldown**: Safely operates with a strict 5.0-second delay between batches to stay below the ~15 RPM limit.
6.  **Error Recovery**: Automatically retries on Google API `500`/`503` server load spikes with exponential backoff.

---

## Known Errors & Recovery Actions

*   **Google API 500/503 Errors**: High traffic can trigger server-side errors on the `gemma-4-31b-it` backend. The translation runner automatically retries up to 6 times with exponential backoff (starting at 15s).
*   **Unicode Encoding Errors on Windows**: Standard Windows terminals fail to write Hebrew characters directly. The runner automatically overrides stdout encoding to UTF-8 to prevent failure.
*   **Validation Failures**: If a translated batch contains mismatched entry counts or invalid formats, the import gate blocks it and keeps the database clean. Simply re-run translation on that specific batch.

---

## Next Steps for Future Batches

1.  To translate the next range of batches (e.g. `batch_0143` to `batch_0150`), run:
    ```powershell
    python translate_batches.py --start 143 --end 150
    ```
2.  Once completed, merge the translations to update the CSV/JSONL files:
    ```powershell
    python merge_translated_batches.py
    ```
3.  Compile the Kindle dictionary source files:
    ```powershell
    python build_kindle_dict.py
    ```