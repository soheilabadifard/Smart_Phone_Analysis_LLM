"""Scrape per-config pricing for multi-configuration devices on GSMArena.

flattened_data.csv lists each phone once with `Memory_Internal` containing
multiple comma-separated configurations (e.g. "128GB 6GB RAM, 256GB 8GB RAM").
GSMArena hosts a per-config price table on each device page; this script
walks devices with >1 config, scrapes that table, and emits pricing.json.

`pricing_json_to_csv.py` then converts the JSON to the columnar format the
cleaner consumes.
"""

import json
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from crawl import HttpRequestManager

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def scrape_pricing(rsp):
    soup = BeautifulSoup(rsp, 'html.parser')
    table = soup.find('table', class_='pricing inline widget')
    if not table:
        return None
    config_prices = {}
    for tr in table.find_all('tr'):
        config = tr.find('td').text.strip()
        price_link = tr.find('a')
        if price_link:
            config_prices[config] = price_link.text.strip()
    return config_prices


def build_model_url_index(phone_links):
    """Flatten the brand→model→url nested dict into model→url for O(1) lookup.

    Replaces the previous O(N×M) nested-loop scan in the main path.
    """
    return {
        model: url
        for models in phone_links.values()
        for model, url in models.items()
    }


def main(
    phone_models_path=str(DATA_DIR / 'phone_models.json'),
    flattened_csv=str(DATA_DIR / 'flattened_data.csv'),
    out_path=str(DATA_DIR / 'pricing.json'),
):
    with open(phone_models_path) as f:
        phone_links = json.load(f)
    data = pd.read_csv(flattened_csv)

    data['Config_Count'] = data['Memory_Internal'].apply(
        lambda x: len(str(x).split(',')) if pd.notna(x) else 0
    )
    devices_with_multiple_configs = data[data['Config_Count'] > 1]

    model_to_url = build_model_url_index(phone_links)
    final_dic = {}
    http = HttpRequestManager()

    for _, row in devices_with_multiple_configs.iterrows():
        model_url = model_to_url.get(row['model'])
        if not model_url:
            print(f"No URL found for {row['model']}")
            continue
        final_dic[row['model']] = scrape_pricing(http.fetch(model_url))
        print(f"Scraped {final_dic[row['model']]}")
        # Incremental save — if we crash at row N we keep N-1 results.
        with open(out_path, 'w') as f:
            json.dump(final_dic, f, indent=4)

    return final_dic


if __name__ == '__main__':
    main()
