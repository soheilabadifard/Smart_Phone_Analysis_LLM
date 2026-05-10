"""Scrape per-config pricing for multi-configuration devices on GSMArena.

flattened_data.csv lists each phone once with `Memory_Internal` containing
multiple comma-separated configurations (e.g. "128GB 6GB RAM, 256GB 8GB RAM").
GSMArena hosts a per-config price table on each device page; this script
walks devices that actually expose multiple storage tiers, scrapes that
table, and emits pricing.json.

`pricing_json_to_csv.py` then converts the JSON to the columnar format the
cleaner consumes.

Output schema (since 2026-05): each model's value is a self-describing dict
with `scraped_at` (ISO timestamp) and `configs` (the dict of config→price,
or null when GSMArena had no widget). Old-format entries (value is the
raw config dict or None) are migrated on load.

CLI:
    python etl/extracrawling.py [--limit N] [--dry-run] [--refresh-older-than DAYS]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the repo root is on sys.path so the absolute import below resolves
# whether this is run as `python etl/extracrawling.py` (script) or imported
# as `etl.extracrawling` (module).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from bs4 import BeautifulSoup

from etl.crawl import HttpRequestManager

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def scrape_pricing(rsp: str | bytes) -> dict | None:
    """Extract the per-config price table from a GSMArena device page.

    Returns the {config: price} mapping, or None when no recognisable
    pricing widget is present. Defensive against malformed rows: any row
    without both a config cell and a price link is silently skipped, so a
    single broken row never blows up an entire run.
    """
    try:
        soup = BeautifulSoup(rsp, 'html.parser')
    except Exception:
        return None
    table = soup.find('table', class_='pricing inline widget')
    if not table:
        return None
    config_prices: dict[str, str] = {}
    for tr in table.find_all('tr'):
        td = tr.find('td')
        if td is None:
            continue  # header row or malformed — skip silently
        config = td.get_text(strip=True)
        if not config:
            continue
        link = tr.find('a')
        if link is None:
            continue
        price = link.get_text(strip=True)
        if not price:
            continue
        config_prices[config] = price
    return config_prices or None


# ---------------------------------------------------------------------------
# Config counting (tighter than the old comma-split heuristic)
# ---------------------------------------------------------------------------


_STORAGE_TOKEN = re.compile(r'\b\d+\s*(?:GB|TB|MB)\s*(?:RAM\b)?', re.IGNORECASE)


def count_storage_tiers(memory_internal: object) -> int:
    """Count distinct storage tiers in a Memory_Internal cell.

    Old version (`len(str(x).split(','))`) over-counted: it treated commas
    inside qualifiers like '(Africa)' as config separators. The new version
    counts tokens that look like storage capacities ('128GB', '1TB', '512MB')
    that are followed by a config break (comma, slash, or end of string).
    """
    if not isinstance(memory_internal, str) or not memory_internal:
        return 0
    # Split on commas first (the per-config separator), then count tokens
    # that look like storage capacities at the start of each fragment.
    fragments = [f.strip() for f in memory_internal.split(',') if f.strip()]
    return sum(1 for f in fragments if _STORAGE_TOKEN.search(f))


# ---------------------------------------------------------------------------
# JSON I/O with timestamp wrapper + format migration
# ---------------------------------------------------------------------------


def _migrate_entry(entry: object) -> dict:
    """Coerce a legacy value (None or a config dict) into the new format.

    New format: ``{"scraped_at": <iso8601>|None, "configs": <dict>|None}``.
    Old entries get scraped_at=None so a `--refresh-older-than 0` run will
    re-fetch them.
    """
    if isinstance(entry, dict) and ('scraped_at' in entry or 'configs' in entry):
        # Already in new format (or close enough to be passed through).
        return {
            'scraped_at': entry.get('scraped_at'),
            'configs': entry.get('configs'),
        }
    return {'scraped_at': None, 'configs': entry}


def load_existing_pricing(out_path: str) -> dict[str, dict]:
    """Return the previously-scraped pricing dict (empty if none).

    Migrates old-format entries on read so every value emitted from this
    function follows the {scraped_at, configs} schema.
    """
    path = Path(out_path)
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Could not load existing {out_path} ({exc}); starting fresh.")
        return {}
    return {model: _migrate_entry(entry) for model, entry in raw.items()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _is_stale(scraped_at: str | None, threshold: timedelta | None) -> bool:
    """True if the entry should be refreshed: missing timestamp, or older
    than ``threshold``. ``threshold=None`` means never stale."""
    if threshold is None:
        return False
    if scraped_at is None:
        return True
    try:
        ts = datetime.strptime(scraped_at, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - ts) > threshold


# ---------------------------------------------------------------------------
# Lookup index
# ---------------------------------------------------------------------------


def build_model_url_index(phone_links: dict) -> dict[str, str]:
    """Flatten the brand→model→url nested dict into model→url for O(1) lookup.

    On model-name collisions across brands, the later-seen entry wins. (Real
    collisions are rare — e.g. multiple brands listing a "Pixel" — and the
    earlier pipeline already produced unique model strings.)
    """
    return {
        model: url
        for models in phone_links.values()
        for model, url in models.items()
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    phone_models_path: str = str(DATA_DIR / 'phone_models.json'),
    flattened_csv: str = str(DATA_DIR / 'flattened_data.csv'),
    out_path: str = str(DATA_DIR / 'pricing.json'),
    limit: int | None = None,
    dry_run: bool = False,
    refresh_older_than_days: int | None = None,
) -> dict:
    with open(phone_models_path) as f:
        phone_links = json.load(f)
    data = pd.read_csv(flattened_csv)

    data['Config_Count'] = data['Memory_Internal'].apply(count_storage_tiers)
    devices_with_multiple_configs = data[data['Config_Count'] > 1]

    model_to_url = build_model_url_index(phone_links)
    final_dic = load_existing_pricing(out_path)
    refresh_threshold = (
        timedelta(days=refresh_older_than_days)
        if refresh_older_than_days is not None
        else None
    )

    queued: list[tuple[str, str]] = []
    skipped_fresh = missing_url = 0
    for _, row in devices_with_multiple_configs.iterrows():
        model = row['model']
        url = model_to_url.get(model)
        if not url:
            missing_url += 1
            continue
        existing = final_dic.get(model)
        if existing and not _is_stale(existing.get('scraped_at'), refresh_threshold):
            skipped_fresh += 1
            continue
        queued.append((model, url))
        if limit is not None and len(queued) >= limit:
            break

    print(
        f"Multi-config devices: {len(devices_with_multiple_configs)}; "
        f"queued for scrape: {len(queued)}; "
        f"skipped (fresh enough): {skipped_fresh}; "
        f"missing URL: {missing_url}."
    )

    if dry_run:
        print("--dry-run: not fetching.")
        return final_dic

    if not queued:
        print("Nothing to scrape.")
        return final_dic

    http = HttpRequestManager()
    scraped = failed = 0
    for model, url in queued:
        try:
            html = http.fetch(url)
        except Exception as exc:
            print(f"FAIL {model}: {type(exc).__name__}: {str(exc)[:80]}")
            failed += 1
            continue
        try:
            configs = scrape_pricing(html)
        except Exception as exc:
            print(f"PARSE-FAIL {model}: {type(exc).__name__}: {str(exc)[:80]}")
            failed += 1
            continue
        final_dic[model] = {'scraped_at': _now_iso(), 'configs': configs}
        scraped += 1
        n = len(configs) if configs else 0
        print(f"[{scraped}/{len(queued)}] {model}: {n} config(s)")
        # Incremental save — survives Ctrl-C.
        with open(out_path, 'w') as f:
            json.dump(final_dic, f, indent=4)

    print(
        f"\nDone. Scraped {scraped} new, {failed} failures, "
        f"{skipped_fresh} skipped (fresh)."
    )
    return final_dic


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    p.add_argument('--limit', type=int, default=None,
                   help="Stop after queueing N devices (testing / partial runs).")
    p.add_argument('--dry-run', action='store_true',
                   help="Print the queue size and exit without fetching.")
    p.add_argument('--refresh-older-than', type=int, default=None, metavar='DAYS',
                   help="Re-scrape entries whose scraped_at is older than N days "
                        "(or has no timestamp, e.g. legacy entries). "
                        "Default: never refresh (skip any model already present).")
    return p


if __name__ == '__main__':
    args = _build_argparser().parse_args()
    main(
        limit=args.limit,
        dry_run=args.dry_run,
        refresh_older_than_days=args.refresh_older_than,
    )
