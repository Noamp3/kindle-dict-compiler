from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from config_helper import config

# Try to import Google GenAI SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: The 'google-genai' package is not installed. Please run 'pip install google-genai'.")
    sys.exit(1)


def load_google_key(env_path: Path, api_key_var: str = "GEMINI_API_KEY") -> str:
    """Load Google API key safely from environment or .env file, removing any surrounding quotes."""
    # 1. Try environment variables first
    for env_name in (api_key_var, "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name)
        if val:
            val_clean = val.strip()
            if val_clean.startswith(('"', "'")) and val_clean.endswith(('"', "'")):
                val_clean = val_clean[1:-1].strip()
            if val_clean:
                return val_clean

    # 2. Fall back to reading .env file
    if not env_path.exists():
        raise ValueError(f"No .env file found at {env_path}")
    env_text = env_path.read_text(encoding="utf-8")
    for line in env_text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in {api_key_var, "GOOGLE_API_KEY", "GEMINI_API_KEY"}:
            val_clean = value.strip()
            if val_clean.startswith(('"', "'")) and val_clean.endswith(('"', "'")):
                val_clean = val_clean[1:-1].strip()
            if val_clean:
                return val_clean
    raise ValueError(f"No {api_key_var} or GEMINI_API_KEY or GOOGLE_API_KEY found in environment or {env_path}")


def call_google_api(api_key: str, model: str, prompt: str, temperature: float = 0.0, batch_name: str = "") -> str:
    """Call Google Gemini/Gemma generateContent API endpoint using the official google-genai SDK with streaming and periodic logging."""
    client = genai.Client(api_key=api_key)
    
    # Configure strict JSON output and minimal thinking for the model
    generate_content_config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level="MINIMAL",
        ),
        response_mime_type="application/json",
        temperature=temperature
    )

    raw_chunks = []
    
    # Stream the output
    response_stream = client.models.generate_content_stream(
        model=model,
        contents=prompt,
        config=generate_content_config,
    )
    
    start_time = time.time()
    last_heartbeat = start_time
    
    for chunk in response_stream:
        if text := chunk.text:
            raw_chunks.append(text)
            now = time.time()
            if now - last_heartbeat >= 30.0:
                elapsed = int(now - start_time)
                print(f"[{batch_name}] Still processing... (elapsed {elapsed}s)", flush=True)
                last_heartbeat = now
            
    full_response = "".join(raw_chunks).strip()
    if not full_response:
        raise RuntimeError("Model returned an empty response.")
        
    return full_response


def get_next_batches(source_dir: Path, translated_dir: Path) -> list[Path]:
    """Find all missing canonical translated batches, prioritizing gaps first and ignoring locked batches."""
    source_batches = sorted(source_dir.glob("batch_*.jsonl"))
    translated_batches = sorted(translated_dir.glob("batch_*.jsonl"))

    translated_names = {path.name for path in translated_batches if len(path.stem) == 10}
    locked_names = {path.name[:-5] for path in translated_dir.glob("batch_*.jsonl.lock")}
    
    # 1. Look for gaps (missing files up to the highest translated batch)
    if translated_batches:
        max_stem = max(int(path.stem.split("_")[1]) for path in translated_batches if len(path.stem) == 10)
    else:
        max_stem = 0

    gaps = []
    upward = []

    for path in source_batches:
        if len(path.stem) != 10:
            continue
        batch_num = int(path.stem.split("_")[1])
        if path.name not in translated_names and path.name not in locked_names:
            if batch_num < max_stem:
                gaps.append(path)
            else:
                upward.append(path)

    # Prioritize gaps first, then continue upward
    return gaps + upward


def split_and_translate_subbatches(
    api_key: str,
    model: str,
    source_batch: Path,
    translated_batch: Path,
    delay: float,
    dry_run: bool
) -> bool:
    print(f"\n[AUTO-SPLIT] Validation failed. Initiating sub-batch split recovery (chunk size = 25) for {source_batch.name}...")
    
    # 1. Load source rows
    try:
        with source_batch.open("r", encoding="utf-8") as f:
            source_rows = [json.loads(line.strip()) for line in f if line.strip()]
    except Exception as e:
        print(f"[AUTO-SPLIT] Error reading source batch: {e}")
        return False

    # Split into chunks of 25
    chunk_size = 25
    chunks = [source_rows[i:i + chunk_size] for i in range(0, len(source_rows), chunk_size)]
    print(f"[AUTO-SPLIT] Split {len(source_rows)} rows into {len(chunks)} sub-batches.")
    
    temp_dir = source_batch.parent.parent / "tmp" / f"split_{source_batch.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    subbatch_translated_paths = []
    
    for idx, chunk in enumerate(chunks, 1):
        sub_source_path = temp_dir / f"sub_{idx:02d}.jsonl"
        sub_trans_path = temp_dir / f"sub_{idx:02d}.translated.jsonl"
        sub_prompt_path = temp_dir / f"sub_{idx:02d}.prompt.txt"
        sub_raw_path = temp_dir / f"sub_{idx:02d}.raw.txt"
        
        # Save chunk rows to temp source path
        with sub_source_path.open("w", encoding="utf-8") as f:
            for row in chunk:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                
        print(f"\n--- [AUTO-SPLIT] Sub-batch {idx}/{len(chunks)} ({len(chunk)} entries) ---")
        
        # A. Build prompt
        cmd_prompt = [
            sys.executable,
            "build_translation_prompt.py",
            str(sub_source_path),
            "--output",
            str(sub_prompt_path)
        ]
        res = subprocess.run(cmd_prompt, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[AUTO-SPLIT] build_translation_prompt failed for sub-batch {idx}: {res.stderr}")
            return False
            
        # B. Call API with retries
        prompt_text = sub_prompt_path.read_text(encoding="utf-8")
        retries = 5
        wait_time = 15.0
        success = False
        for attempt in range(retries):
            try:
                raw_text = call_google_api(api_key, model, prompt_text, batch_name=f"{source_batch.name}/sub_{idx}")
                sub_raw_path.write_text(raw_text, encoding="utf-8")
                success = True
                break
            except Exception as exc:
                print(f"[AUTO-SPLIT] Sub-batch {idx} attempt {attempt + 1} failed: {exc}")
                if attempt < retries - 1:
                    time.sleep(wait_time)
                    wait_time = min(wait_time * 2, 60.0)
                    
        if not success:
            print(f"[AUTO-SPLIT] Sub-batch {idx} failed translation after {retries} retries.")
            return False
            
        # C. Import and Validate
        cmd_import = [
            sys.executable,
            "import_translated_batch.py",
            str(sub_source_path),
            str(sub_trans_path),
            "--input-file",
            str(sub_raw_path)
        ]
        res = subprocess.run(cmd_import, capture_output=True, text=True)
        print(res.stdout)
        if res.returncode != 0:
            print(f"[AUTO-SPLIT] Import validation failed for sub-batch {idx}: {res.stderr}")
            return False
            
        subbatch_translated_paths.append(sub_trans_path)
        time.sleep(delay) # Cooldown delay
        
    # 3. Merge sub-batches into the final translated_batch
    all_translated_rows = []
    for path in subbatch_translated_paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        all_translated_rows.append(json.loads(line.strip()))
        except Exception as e:
            print(f"[AUTO-SPLIT] Error reading sub-batch output {path}: {e}")
            return False
            
    # Sort and save
    all_translated_rows.sort(key=lambda r: int(r.get("entry_id", 0)))
    with translated_batch.open("w", encoding="utf-8") as f:
        for row in all_translated_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            
    print(f"\n[AUTO-SPLIT] Success! Merged all {len(chunks)} sub-batches into canonical destination: {translated_batch}")
    
    # Clean up temp folder
    try:
        for file in temp_dir.iterdir():
            file.unlink()
        temp_dir.rmdir()
    except Exception:
        pass
        
    return True


def translate_batch(
    api_key: str,
    model: str,
    source_batch: Path,
    translated_batch: Path,
    delay: float,
    dry_run: bool
) -> bool:
    """Packages, translates, and validates a single batch."""
    print(f"\n==========================================")
    print(f"Processing Batch: {source_batch.name}")
    print(f"==========================================")

    # 1. Build prompt file
    root = source_batch.parent.parent
    prompt_file = root / "prompt_packets" / f"{source_batch.stem}.prompt.txt"
    if not dry_run:
        print(f"Building prompt packet...")
        cmd = [
            sys.executable,
            "build_translation_prompt.py",
            str(source_batch),
            "--output",
            str(prompt_file)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error: build_translation_prompt.py failed: {res.stderr}")
            return False
    else:
        print(f"[DRY-RUN] Would build prompt packet to: {prompt_file}")

    # Read prompt text
    if not dry_run:
        if not prompt_file.exists():
            print(f"Error: prompt packet file {prompt_file} not created.")
            return False
        prompt_text = prompt_file.read_text(encoding="utf-8")
    else:
        prompt_text = "Dry-run mock prompt"

    # 2. Call Google API
    raw_output_path = root / "tmp" / f"{source_batch.stem}.raw.txt"
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        retries = 19
        wait_time = 15.0
        success = False
        for attempt in range(retries + 1):
            try:
                raw_text = call_google_api(api_key, model, prompt_text, batch_name=source_batch.name)
                raw_output_path.write_text(raw_text, encoding="utf-8")
                print(f"Saved raw response to {raw_output_path}")
                success = True
                break
            except Exception as exc:
                print(f"\n[{source_batch.name}] Error on attempt {attempt + 1}/{retries + 1}: {exc}")
                # Check for rate limits or transient errors
                if attempt < retries:
                    print(f"[{source_batch.name}] Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    wait_time = min(wait_time * 2, 60.0)
                    continue
                return False
        if not success:
            return False
    else:
        print(f"[DRY-RUN] Would query SDK model '{model}' and stream output to: {raw_output_path}")

    # 3. Import and Validate
    if not dry_run:
        print(f"Importing and validating raw translated output...")
        cmd = [
            sys.executable,
            "import_translated_batch.py",
            str(source_batch),
            str(translated_batch),
            "--input-file",
            str(raw_output_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(res.stdout)
        if res.returncode != 0:
            print(f"Import validation failed: {res.stderr}")
            # Try sub-batch split as auto-recovery fallback
            split_success = split_and_translate_subbatches(
                api_key=api_key,
                model=model,
                source_batch=source_batch,
                translated_batch=translated_batch,
                delay=delay,
                dry_run=dry_run
            )
            return split_success
        print(f"Import succeeded! Saved canonical batch to: {translated_batch}")
    else:
        print(f"[DRY-RUN] Would run import_translated_batch.py to save canonical batch to: {translated_batch}")

    # 4. Strict delay cooldown to respect RPM limits
    print(f"Throttling delay: waiting {delay}s before next request...")
    time.sleep(delay)
    return True



def main() -> int:
    # Reconfigure stdout/stderr to use UTF-8 to prevent charmap encoding errors on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(
        description="Automated local batch translator using official Google GenAI SDK with streaming and rate-limiting."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("work/translation_batches"),
        help="Source batches folder.",
    )
    parser.add_argument(
        "--translated-dir",
        type=Path,
        default=Path("work/translated_batches"),
        help="Translated canonical batches folder.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=config.model,
        help="Google API model identifier (e.g. gemma-4-31b-it, gemini-1.5-flash). Defaults to the model specified in config.json.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Cooldown delay in seconds after each API call to respect RPM limits (default: 5s = 12 RPM).",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="Maximum number of batches to translate in this run (0 = all available).",
    )
    parser.add_argument(
        "--start-batch",
        type=int,
        default=None,
        help="Optional starting batch number (inclusive).",
    )
    parser.add_argument(
        "--end-batch",
        type=int,
        default=None,
        help="Optional ending batch number (inclusive).",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Environment variables file to load API keys.",
    )
    parser.add_argument(
        "--api-key-var",
        type=str,
        default="GEMINI_API_KEY",
        help="Name of the environment variable containing the Google API key (default: GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the run immediately if any single batch fails to translate.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the run: scans directories, builds prompts, and prints throttle info without making API calls.",
    )
    args = parser.parse_args()

    # Load Google API key unless it is a dry-run
    api_key = ""
    if not args.dry_run:
        try:
            api_key = load_google_key(args.env_file, args.api_key_var)
        except Exception as exc:
            print(f"Error loading API key: {exc}")
            return 1

    # Resolve paths
    args.source_dir = args.source_dir.resolve()
    args.translated_dir = args.translated_dir.resolve()
    args.translated_dir.mkdir(parents=True, exist_ok=True)

    # Scan and filter batches
    next_batches = get_next_batches(args.source_dir, args.translated_dir)
    if args.start_batch is not None or args.end_batch is not None:
        filtered = []
        for batch_path in next_batches:
            try:
                num = int(batch_path.stem.split("_")[1])
                if args.start_batch is not None and num < args.start_batch:
                    continue
                if args.end_batch is not None and num > args.end_batch:
                    continue
                filtered.append(batch_path)
            except (ValueError, IndexError):
                filtered.append(batch_path)
        next_batches = filtered

    if not next_batches:
        print("No batches found within the specified range.")
        return 0

    print(f"Found {len(next_batches)} batches pending translation.")
    if args.max_batches > 0:
        next_batches = next_batches[:args.max_batches]
        print(f"Limiting execution to the first {args.max_batches} batches.")

    print(f"Starting run using model '{args.model}' with a throttling delay of {args.delay}s (Dry-run: {args.dry_run}).")

    completed_count = 0
    failed_batches = []

    for source_batch in next_batches:
        translated_batch = args.translated_dir / source_batch.name
        
        # Skip if already translated by another runner
        if not args.dry_run and translated_batch.exists():
            continue
            
        # Atomic lock file acquisition for parallel safety
        lock_file = args.translated_dir / f"{source_batch.name}.lock"
        if not args.dry_run:
            try:
                # 'x' mode is atomic and fails if the file already exists
                with open(lock_file, "x") as f:
                    f.write(str(os.getpid()))
            except FileExistsError:
                # Already being processed by another parallel runner
                continue

        success = False
        try:
            success = translate_batch(
                api_key=api_key,
                model=args.model,
                source_batch=source_batch,
                translated_batch=translated_batch,
                delay=args.delay,
                dry_run=args.dry_run
            )
        finally:
            # Clean up the lock file so it can be retried on failure or shows as completed
            if not args.dry_run and lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass

        if success:
            completed_count += 1
        else:
            failed_batches.append(source_batch.name)
            print(f"\n[ERROR] Failed to process batch: {source_batch.name}")
            if args.stop_on_error:
                print("Stopping run early due to --stop-on-error.")
                break
            else:
                print("Continuing to next batch...")

    print(f"\n==========================================")
    print(f"Run Summary")
    print(f"==========================================")
    print(f"Successfully processed: {completed_count} batches")
    print(f"Failed or skipped     : {len(failed_batches)} batches")
    if failed_batches:
        print(f"Failed batch list     : {', '.join(failed_batches)}")
    print(f"Pending batches left  : {len(get_next_batches(args.source_dir, args.translated_dir))}")
    return 1 if failed_batches else 0


if __name__ == "__main__":
    raise SystemExit(main())
