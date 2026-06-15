#!/bin/bash
# ==============================================================================
# start_runners.sh - Launch parallel translation runners
# ==============================================================================

# Configuration (override with environment variables or CLI arguments)
WORK_DIR="${DICT_WORK_DIR:-.}"
SOURCE_DIR="${1:-work/translation_batches}"
TRANSLATED_DIR="${2:-work/translated_batches}"
NUM_RUNNERS="${3:-12}"
DELAY="${4:-15}"
LOG_FILE="${5:-work/translation_run.log}"

# Shift arguments so remaining arguments can be passed to python scripts
shift 4 2>/dev/null || true

echo "Changing directory to: $WORK_DIR"
cd "$WORK_DIR"

echo "Launching $NUM_RUNNERS parallel runners..."
echo "Source: $SOURCE_DIR, Translated: $TRANSLATED_DIR, Delay: ${DELAY}s"
echo "Logs are being redirected to: $LOG_FILE"

# Make sure log parent directory exists
mkdir -p "$(dirname "$LOG_FILE")"

for i in $(seq 1 $NUM_RUNNERS); do
    # Alternate between API keys if multiple exist, otherwise fallback to GEMINI_API_KEY
    if (( i % 2 == 1 )); then
        KEY_VAR="GEMINI_API_KEY"
    else
        # If GEMINI_API_KEY2 is not set, fallback to GEMINI_API_KEY
        if [ -z "${GEMINI_API_KEY2}" ]; then
            KEY_VAR="GEMINI_API_KEY"
        else
            KEY_VAR="GEMINI_API_KEY2"
        fi
    fi

    echo "  [Runner $i] Using API Key Var: $KEY_VAR"
    nohup .venv/bin/python -u translate_batches.py \
        --source-dir "$SOURCE_DIR" \
        --translated-dir "$TRANSLATED_DIR" \
        --api-key-var "$KEY_VAR" \
        --delay "$DELAY" "$@" >> "$LOG_FILE" 2>&1 &
done

echo "All runners launched. Check status with: ps aux | grep translate_batches.py"
