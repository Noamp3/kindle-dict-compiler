from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from config_helper import config


def load_batch(path: Path):
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Merge translated JSONL batches into one JSONL and CSV file.'
    )
    parser.add_argument(
        '--input-dir',
        type=Path,
        default=Path('work/translated_batches'),
    )
    parser.add_argument(
        '--jsonl',
        dest='jsonl_path',
        type=Path,
        default=Path(f'work/dictionary_{config.source_lang_code}_{config.target_lang_code}.jsonl'),
    )
    parser.add_argument(
        '--csv',
        dest='csv_path',
        type=Path,
        default=Path(f'work/dictionary_{config.source_lang_code}_{config.target_lang_code}.csv'),
    )
    args = parser.parse_args()

    rows = []
    for path in sorted(args.input_dir.glob('batch_*.jsonl')):
        rows.extend(load_batch(path))

    rows.sort(key=lambda row: row.get('entry_id', 0))

    args.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl_path.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    has_examples = any(config.examples_target_field in row for row in rows)
    if has_examples:
        fieldnames = [
            'entry_id',
            config.headword_field,
            config.definition_target_field,
            config.examples_target_field,
        ]
    else:
        fieldnames = [
            'entry_id',
            config.headword_field,
            config.definition_target_field,
        ]
        
    with args.csv_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fieldnames})

    print(json.dumps({'merged_rows': len(rows), 'jsonl': str(args.jsonl_path), 'csv': str(args.csv_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
