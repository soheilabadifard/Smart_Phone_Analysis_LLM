"""Flatten phone_info.json (nested dict from crawl.py) into flattened_data.csv.

Each output row is a single phone, with column names derived from the
nested keys (e.g. 'Network_2G bands', 'Memory_Internal'). The cleaner in
Data_cleaning.py consumes those column names directly, so renaming any of
the GSMArena section/field names will break the cleaner.
"""

import json
import pandas as pd


def flatten_json(y):
    """Flatten a nested dict/list into a single-level dict with '_'-joined keys."""
    out = {}

    def flatten(x, name=''):
        if isinstance(x, dict):
            for a in x:
                flatten(x[a], f'{name}{a}_')
        elif isinstance(x, list):
            for i, a in enumerate(x):
                flatten(a, f'{name}{i}_')
        else:
            out[name[:-1]] = x

    flatten(y)
    return out


def process_json(data):
    """Turn the brand→model→info nested JSON into a flat DataFrame."""
    flattened_data = []
    for brand, models in data.items():
        for model, details in models.items():
            flat_details = flatten_json(details)
            flat_details['brand'] = brand
            flat_details['model'] = model
            flattened_data.append(flat_details)
    return pd.DataFrame(flattened_data)


def main(json_file_path='phone_info.json', output_csv='flattened_data.csv'):
    with open(json_file_path) as file:
        data = json.load(file)
    df = process_json(data)
    df.to_csv(output_csv, index=False)
    print(df.head())
    return df


if __name__ == '__main__':
    main()
