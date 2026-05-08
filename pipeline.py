"""End-to-end data pipeline orchestrator.

Runs the 6 steps that take fresh GSMArena pages all the way to the populated
MariaDB. Each step shells out to the existing standalone script so the
behavior is identical to running them by hand.

Usage:
    python pipeline.py                       # run everything
    python pipeline.py --skip-crawl          # skip crawl + flatten
                                             # (use existing flattened_data.csv)
    python pipeline.py --skip-pricing        # skip price scrape + conversion
                                             # (use existing pricing.csv if any)
    python pipeline.py --steps clean,load    # run only the named steps
    python pipeline.py --list                # show step inventory and exit

Each step verifies its expected output file(s) appeared before moving on,
so a silent failure halts the pipeline rather than corrupting downstream
artifacts.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# (step_name, script_or_callable, [expected_output_files])
# Scripts live in etl/; intermediate artifacts land in etl/data/.
STEPS = [
    ("crawl",     "etl/crawl.py",                ["etl/data/phone_info.json", "etl/data/phone_models_old.json", "etl/data/brand_links.json"]),
    ("flatten",   "etl/JsonToDataframe.py",      ["etl/data/flattened_data.csv"]),
    ("price",     "etl/extracrawling.py",        ["etl/data/pricing.json"]),
    ("price-csv", "etl/pricing_json_to_csv.py",  ["etl/data/pricing.csv"]),
    ("clean",     "etl/Data_cleaning.py",        ["etl/data/processed_data.csv"]),
    ("load",      "etl/newDatabase.py",          []),  # populates DB; no file output
]


def run_step(name: str, script: str, outputs: list[str]) -> None:
    print(f"\n=== {name}  ({script}) ===")
    started = time.monotonic()
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        sys.exit(f"!! step '{name}' failed with exit code {result.returncode}")
    for output in outputs:
        if not Path(output).exists():
            sys.exit(f"!! step '{name}' did not produce expected file: {output}")
    print(f"=== {name}  OK  ({time.monotonic() - started:.1f}s) ===")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skip-crawl", action="store_true", help="skip crawl + flatten (use cached flattened_data.csv)")
    p.add_argument("--skip-pricing", action="store_true", help="skip price scrape + conversion")
    p.add_argument("--steps", help="comma-separated step names to run (overrides --skip-* flags)")
    p.add_argument("--list", action="store_true", help="list available steps and exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.list:
        print("Available steps:")
        for name, script, outputs in STEPS:
            outs = ", ".join(outputs) if outputs else "(no file output)"
            print(f"  {name:<10} {script:<28} → {outs}")
        return

    if args.steps:
        wanted = {s.strip() for s in args.steps.split(",")}
        unknown = wanted - {n for n, _, _ in STEPS}
        if unknown:
            sys.exit(f"!! unknown step(s): {', '.join(sorted(unknown))}")
    else:
        wanted = {n for n, _, _ in STEPS}
        if args.skip_crawl:
            wanted -= {"crawl", "flatten"}
        if args.skip_pricing:
            wanted -= {"price", "price-csv"}

    print(f"Running steps in order: {[n for n, _, _ in STEPS if n in wanted]}")
    overall = time.monotonic()
    for name, script, outputs in STEPS:
        if name in wanted:
            run_step(name, script, outputs)
        else:
            print(f"--- skipping {name}")
    print(f"\n✓ pipeline complete in {time.monotonic() - overall:.1f}s")


if __name__ == "__main__":
    main()
