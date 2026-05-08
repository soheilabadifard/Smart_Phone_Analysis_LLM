"""Convert pricing.json (from extracrawling.py) to pricing.csv (for Data_cleaning.py).

extracrawling.py writes:
    {model_name: {config_str: price_str, ...}, ...}

Data_cleaning.expand_memory_configurations reads a DataFrame with columns:
    Model, Configuration, Price

This script bridges the two. Without it the per-config pricing scraped in
extracrawling never reaches the cleaner — the documented "pipeline gotcha".
"""

import json
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def convert(
    json_path: str = str(DATA_DIR / 'pricing.json'),
    csv_path: str = str(DATA_DIR / 'pricing.csv'),
) -> int:
    """Read pricing.json, emit pricing.csv. Returns the number of rows written.

    Returns 0 (and creates an empty CSV with the right header) if the JSON
    file is missing or empty — Data_cleaning.py handles an empty extraprice
    DataFrame gracefully.
    """
    src = Path(json_path)
    if not src.exists():
        print(f"{json_path} not found — writing empty {csv_path}")
        pd.DataFrame(columns=['Model', 'Configuration', 'Price']).to_csv(csv_path, index=False)
        return 0

    with src.open() as f:
        data = json.load(f)

    rows = []
    for model, configs in data.items():
        if configs is None:
            continue
        for config, price in configs.items():
            rows.append({'Model': model, 'Configuration': config, 'Price': price})

    pd.DataFrame(rows, columns=['Model', 'Configuration', 'Price']).to_csv(csv_path, index=False)
    print(f"Wrote {len(rows)} rows to {csv_path}")
    return len(rows)


if __name__ == '__main__':
    sys.exit(0 if convert() >= 0 else 1)
