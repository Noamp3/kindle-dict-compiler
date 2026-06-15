#!/bin/bash
# ==============================================================================
# wait_and_build.sh - Wait for batch completion and build dictionary
# ==============================================================================
set -e

# Configuration (override with environment variables or CLI arguments)
WORK_DIR="${DICT_WORK_DIR:-.}"
TRANSLATED_DIR="${2:-work/translated_batches}"
OUTPUT_DIR="${3:-work}"
LOG_FILE="${4:-$OUTPUT_DIR/wait_and_build.log}"

# Detect total batches from manifest if not explicitly provided as the first argument
TOTAL="$1"
if [ -z "$TOTAL" ]; then
    # Look for manifest.json in the sibling translation_batches folder
    MANIFEST_PATH="$(dirname "$TRANSLATED_DIR")/translation_batches/manifest.json"
    if [ -f "$MANIFEST_PATH" ]; then
        # Parse "batches": <num> using grep/sed to avoid dependency on jq
        TOTAL=$(grep -o '"batches":\s*[0-9]*' "$MANIFEST_PATH" | grep -o '[0-9]*')
        if [ -n "$TOTAL" ]; then
            echo "Auto-detected total batches from manifest: $TOTAL"
        fi
    fi
fi
# Fallback if detection failed or file doesn't exist
TOTAL="${TOTAL:-100}"

cd "$WORK_DIR"

# Make sure output directory and log folder exist
mkdir -p "$OUTPUT_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$(date)] Waiting for all $TOTAL batches to be translated..." | tee -a "$LOG_FILE"

while true; do
    DONE=$(ls "$TRANSLATED_DIR"/*.jsonl 2>/dev/null | wc -l || echo 0)
    echo "[$(date)] Progress: $DONE / $TOTAL batches translated" | tee -a "$LOG_FILE"
    if [ "$DONE" -ge "$TOTAL" ]; then
        echo "[$(date)] All $TOTAL batches complete!" | tee -a "$LOG_FILE"
        break
    fi
    sleep 60
done

echo "" | tee -a "$LOG_FILE"
echo "=== STEP 1: Merge translated batches into dictionary JSONL ===" | tee -a "$LOG_FILE"
.venv/bin/python merge_translated_batches.py \
    --input-dir "$TRANSLATED_DIR" \
    --jsonl "$OUTPUT_DIR/dictionary_es_he.jsonl" \
    --csv "$OUTPUT_DIR/dictionary_es_he.csv" \
    2>&1 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "=== STEP 2: Build Kindle XHTML sources ===" | tee -a "$LOG_FILE"
.venv/bin/python build_kindle_dict.py \
    --input "$OUTPUT_DIR/dictionary_es_he.jsonl" \
    --output-dir "$OUTPUT_DIR/kindle_source" \
    2>&1 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "=== STEP 3: Compile PRC with KindleGen ===" | tee -a "$LOG_FILE"
# Check if kindlegen executable exists in scratch folder or globally
KINDLEGEN_BIN="scratch/kindlegen/kindlegen"
if [ -f "$KINDLEGEN_BIN" ]; then
    "$KINDLEGEN_BIN" "$OUTPUT_DIR/kindle_source/content.opf" -o "dictionary_es_he.prc" \
        2>&1 | tee -a "$LOG_FILE" || true
elif command -v kindlegen &> /dev/null; then
    kindlegen "$OUTPUT_DIR/kindle_source/content.opf" -o "dictionary_es_he.prc" \
        2>&1 | tee -a "$LOG_FILE" || true
else
    echo "Warning: KindleGen executable not found. Kindle package created but not compiled to PRC." | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "=== DONE ===" | tee -a "$LOG_FILE"
