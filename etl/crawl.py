import csv
import gzip
import json
import os
import random
import re
import ssl
import time
import zlib
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from bs4 import BeautifulSoup
from tqdm import tqdm


# All scraped artifacts land in etl/data/ regardless of cwd.
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class BlockedError(Exception):
    """Raised when the crawler appears to be globally blocked — IP banned,
    Cloudflare-challenged, or rate-limited site-wide. Distinguishes a single
    bad URL from a state where every subsequent request will also fail.
    Catch at the call-site to halt cleanly with whatever progress was made.
    """


class HttpRequestManager:
    HEALTH_CHECK_URL = "https://www.gsmarena.com/"
    HEALTH_CHECK_TIMEOUT = 10
    # Substrings that indicate the response body is a Cloudflare interstitial
    # / hCaptcha page / generic block page rather than a real device page.
    BLOCK_MARKERS = (
        "Just a moment",
        "cf-challenge",
        "Attention Required",
        "Access denied",
        "hcaptcha",
    )

    # Pool of recent Chrome 132 UAs across platforms. Anti-detection (4):
    # rotate per session — each pipeline run picks one and sticks with it
    # (cookies and Sec-Ch-Ua client hints stay consistent within a session).
    # Last refreshed: 2026-05-08.
    USER_AGENTS = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    )

    def __init__(self, max_retries=5, backoff_factor=3, delay=10):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.delay = delay  # Delay in seconds between requests
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        # Anti-detection (4): pick a UA once per session so cookies and
        # client hints stay consistent (Cloudflare flags UA-flipping as
        # bot behavior).
        self.user_agent = random.choice(self.USER_AGENTS)

        # Anti-detection (2): persist cookies (notably Cloudflare's __cf_bm)
        # across the whole crawl so subsequent requests look like a
        # continuing session, not a fresh visit each time.
        self.cookie_jar = CookieJar()
        self.opener = build_opener(
            HTTPCookieProcessor(self.cookie_jar),
            HTTPSHandler(context=self.ctx),
        )

        # Anti-detection (1): track the last successfully-fetched URL so
        # the next request can carry it as Referer (real browsers always do).
        self.last_url: str | None = None

    @staticmethod
    def _platform_for_ua(user_agent: str) -> str:
        """Return Sec-Ch-Ua-Platform value matching the UA's OS."""
        if "Windows" in user_agent:
            return '"Windows"'
        if "Macintosh" in user_agent:
            return '"macOS"'
        if "Linux" in user_agent:
            return '"Linux"'
        return '"Unknown"'

    def _build_request(self, url: str, *, referer: str | None = None) -> Request:
        """Build a Request with the full set of headers a real Chrome would send.

        Anti-detection (3): the realistic header set drops your bot score
        meaningfully — Cloudflare sees ~12 headers instead of 2.
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            # Only advertise encodings we can actually decompress (see _read).
            "Accept-Encoding": "gzip, deflate",
            "Sec-Ch-Ua": (
                '"Google Chrome";v="132", "Chromium";v="132", "Not A;Brand";v="24"'
            ),
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": self._platform_for_ua(self.user_agent),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            # Anti-detection (1): same-origin when chained from a previous
            # fetch on gsmarena.com, "none" for the first request.
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            headers["Referer"] = referer
        return Request(url=url, headers=headers)

    def _read(self, response) -> str:
        """Read a response body, decompressing gzip/deflate if needed.

        urllib doesn't decompress automatically, so once we set
        Accept-Encoding the server may compress and we have to handle it.
        """
        body = response.read()
        encoding = response.headers.get("Content-Encoding", "").lower()
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)
        return body.decode("utf-8", errors="replace")

    def _open(self, url: str, *, referer: str | None = None, timeout: float | None = None):
        """Open a URL through the cookie-aware opener and return the response object."""
        if timeout is None:
            return self.opener.open(self._build_request(url, referer=referer))
        return self.opener.open(self._build_request(url, referer=referer), timeout=timeout)

    def _is_blocked_html(self, html: str) -> bool:
        """Heuristic: is this an interstitial / block page rather than real content?"""
        return any(marker in html for marker in self.BLOCK_MARKERS)

    def _diagnose(self) -> str:
        """Probe the homepage to distinguish per-URL failure from global block.

        Returns 'ok' if the homepage loads normally, 'blocked' if it returns
        a block page or 403/connection error, 'rate-limited' on 429.
        """
        try:
            html = self._read(self._open(self.HEALTH_CHECK_URL, timeout=self.HEALTH_CHECK_TIMEOUT))
            return "blocked" if self._is_blocked_html(html) else "ok"
        except HTTPError as e:
            if e.code == 429:
                return "rate-limited"
            if e.code == 403:
                return "blocked"
            return "ok"  # Some other HTTP error — not a global signal
        except Exception:
            return "blocked"  # Network-level failure — assume worst

    def _raise_if_globally_blocked(self) -> None:
        """If the homepage probe says we're blocked / rate-limited site-wide,
        bail out with BlockedError so the caller can stop early."""
        diagnosis = self._diagnose()
        if diagnosis != "ok":
            raise BlockedError(
                f"Crawler appears to be {diagnosis} site-wide. "
                "Wait for the cooldown window, lower the request rate, or use a different IP."
            )

    def fetch(self, url):
        retries = 0
        while retries < self.max_retries:
            time.sleep(self.delay)
            try:
                response = self._read(self._open(url, referer=self.last_url))
                if self._is_blocked_html(response):
                    # 200 OK but the body is a Cloudflare/captcha challenge.
                    print(f"⚠  block-page returned for {url}; probing homepage...")
                    self._raise_if_globally_blocked()
                    # Homepage is fine — the URL itself returned junk; back off and retry.
                    retries += 1
                    self._sleep_backoff(retries)
                    continue
                # Anti-detection (1): record this URL so the *next* fetch
                # carries it as Referer.
                self.last_url = url
                return response
            except HTTPError as e:
                if e.code == 403:
                    # Strong block signal — diagnose immediately.
                    print(f"⚠  HTTP 403 on {url}; probing homepage...")
                    self._raise_if_globally_blocked()
                    raise  # 403 was URL-specific; let the caller skip this one.
                if e.code in (429, 504):
                    retries += 1
                    self._sleep_backoff(retries, code=e.code)
                    # Mid-retry sanity check: if we've been failing for a while,
                    # don't keep waiting blindly — find out if we're banned.
                    if retries >= max(2, self.max_retries // 2):
                        self._raise_if_globally_blocked()
                else:
                    raise
            except URLError:
                retries += 1
                self._sleep_backoff(retries)
        # Exhausted retries on this URL. Last chance to detect a global block
        # before letting the caller treat it as a per-URL failure.
        self._raise_if_globally_blocked()
        raise Exception(f"Failed to fetch {url} after {self.max_retries} retries")

    def _sleep_backoff(self, retries: int, code: int | None = None) -> None:
        sleep_time = self.backoff_factor * (2 ** retries) + random.uniform(0, 1)
        suffix = f" (HTTP {code})" if code is not None else ""
        print(f"Retrying in {sleep_time:.1f}s{suffix}...")
        time.sleep(sleep_time)


class DataExtractor:
    def __init__(self, main_url):
        self.main_url = main_url
        self.http_request_manager = HttpRequestManager()
        self.brand_links = {}
        self.phone_models_links = {}
        self.phone_info = {}
        print("DataExtractor object created")

    def extract_brand_data(self, brand_links_file=str(DATA_DIR / 'brand_links.json')):
        # Check if the file exists
        if os.path.exists(brand_links_file):
            print(f"Loading brand links from {brand_links_file}")
            with open(brand_links_file, 'r') as file:
                self.brand_links = json.load(file)
        else:
            print("Fetching brand links...")
            html = self.http_request_manager.fetch(self.main_url)
            soup = BeautifulSoup(html, "html.parser")

            table = soup.find('table')
            extracted_data = {}
            for row in tqdm(table.find_all('tr')):
                #  for row in table.find_all('tr'):
                cells = row.find_all('td')

                name = re.sub(r'\d+ devices', '', cells[0].text).strip()  # Extract text from the first column
                link = cells[0].find('a')['href']  # Extract the link from the second column
                extracted_data[name] = "https://www.gsmarena.com/" + link

                name = re.sub(r'\d+ devices', '', cells[1].text).strip()  # Extract text from the first column
                link = cells[1].find('a')['href']  # Extract the link from the second column
                extracted_data[name] = "https://www.gsmarena.com/" + link

            self.brand_links = extracted_data
            print("Brand links extracted")

    def extract_phone_models(self, models_list, models_file_path=str(DATA_DIR / 'phone_models.json')):
        # Fast path: unified phone_models.json exists → load and return.
        if os.path.exists(models_file_path):
            print(f"Loading phone models from {models_file_path}")
            with open(models_file_path, 'r') as file:
                self.phone_models_links = json.load(file)
            return

        # Otherwise iterate brands. Recovery hierarchy per brand:
        #   1. Per-brand checkpoint `{brand}_models.json` exists  → load it (no fetch)
        #   2. No checkpoint                                       → fetch + save
        # Either way, append to the unified file after each brand so a future
        # rerun takes the fast path.
        print("Phone models file not found; resuming from per-brand checkpoints where available...")
        for brand, link in self.brand_links.items():
            if brand not in models_list:
                continue
            per_brand_path = DATA_DIR / f'{brand}_models.json'

            if per_brand_path.exists():
                print(f"Recovered {brand} from {per_brand_path.name} (skipping fetch)")
                with per_brand_path.open() as f:
                    self.phone_models_links[brand] = json.load(f)
            else:
                phone_models = {}
                while link:
                    html = self.http_request_manager.fetch(link)
                    soup = BeautifulSoup(html, "html.parser")

                    # Extract phone models on this page
                    for item in soup.select('.makers ul li a'):
                        name = item.text.strip()
                        href = 'https://www.gsmarena.com/' + item.get('href')
                        phone_models[name] = href

                    # Follow pagination if present
                    next_page = soup.find('a', class_='prevnextbutton', title='Next page')
                    if next_page and 'href' in next_page.attrs:
                        link = 'https://www.gsmarena.com/' + next_page.get('href')
                    else:
                        link = None
                self.phone_models_links[brand] = phone_models
                self.write_json_each(str(per_brand_path), phone_models)

            # Incremental unified save after every brand so the unified file
            # becomes complete in lock-step with the per-brand checkpoints.
            self.save_data(models_file_path, self.phone_models_links)
        print("Phone models extracted")

    def load_existing_data(self, filepath):
        """Load existing data from a JSON file."""
        try:
            with open(filepath, 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def save_data(self, filepath, data):
        """Save data to a JSON file."""
        with open(filepath, 'w') as file:
            json.dump(data, file, indent=4)

    def extract_phone_info(self, interested_sections, json_file_path=str(DATA_DIR / 'phone_info.json')):
        phone_info = self.load_existing_data(json_file_path)  # Load existing data
        parsed_links = set()  # Set to store parsed links

        passed_link_path = DATA_DIR / 'passed_link.csv'
        # Load previously parsed links
        try:
            with open(passed_link_path, 'r', newline='') as file:
                reader = csv.reader(file)
                for row in reader:
                    parsed_links.add(row[0])
        except FileNotFoundError:
            print(f"{passed_link_path} not found, creating a new one.")

        # Build the to-scrape queue upfront so tqdm has an accurate total.
        # Anything in parsed_links is already done and gets skipped.
        queue = [
            (brand, model, link)
            for brand, models in self.phone_models_links.items()
            for model, link in models.items()
            if link not in parsed_links
        ]
        total_known = sum(len(m) for m in self.phone_models_links.values())
        already_done = total_known - len(queue)
        print(
            f"To scrape: {len(queue)} new phones "
            f"({already_done} already in passed_link.csv, {total_known} total known)"
        )

        scraped = failed = 0
        blocked = False
        pbar = tqdm(queue, desc="Scraping", unit="phone", smoothing=0.05)

        def _update_postfix(current: str = "") -> None:
            """Show running scraped/failed counts plus the current item.

            Real-time visibility — if `failed` is climbing while `scraped`
            stays at 0 you know every URL is being challenged, without
            having to scroll the terminal looking for ✗ lines.
            """
            pbar.set_postfix_str(f"✓{scraped} ✗{failed} | {current[:40]}", refresh=False)

        with open(passed_link_path, 'a', newline='') as file:
            writer = csv.writer(file)
            for brand, model, link in pbar:
                if brand not in phone_info:
                    phone_info[brand] = {}
                _update_postfix(f"{brand}/{model}")
                try:
                    html = self.http_request_manager.fetch(link)
                    soup = BeautifulSoup(html, "html.parser")
                    extracted_info = self.parse_model_info(soup, interested_sections)
                except BlockedError as exc:
                    # Site-wide block diagnosed inside fetch(). Halt cleanly
                    # — every subsequent URL would fail the same way.
                    pbar.close()
                    print(f"\n!! {exc}")
                    blocked = True
                    break
                except Exception as exc:
                    # Per-URL failure (rate limit, parse error, 5xx). Not a
                    # global block; skip this URL and keep the crawl going.
                    # passed_link.csv stays unmodified → next run will retry.
                    tqdm.write(f"  ✗ {brand}/{model}: {exc.__class__.__name__}: {exc}")
                    failed += 1
                    _update_postfix(f"{brand}/{model}")
                    continue
                phone_info[brand][model] = extracted_info

                # Add link to parsed links and update the file. flush() so the
                # line hits disk immediately — without it, csv.writer buffers
                # ~8KB before writing, making `wc -l passed_link.csv` lag the
                # ✓ counter by minutes.
                parsed_links.add(link)
                writer.writerow([link])
                file.flush()

                # Save updated phone info to JSON after each link
                self.save_data(json_file_path, phone_info)
                scraped += 1

        if blocked:
            print(
                f"Crawl HALTED early. Scraped {scraped} new this run, {failed} per-URL failures "
                f"before block detected. Re-run when the block lifts; resume is automatic."
            )
        else:
            print(
                f"\nData extraction complete. Scraped {scraped} new, {failed} failed "
                f"(will retry on next run)."
            )

    def parse_model_info(self, soup, interested_sections):
        extracted_info = {}
        for section in interested_sections:
            section_data = {}  # Initialize section dictionary to empty by default
            for table in soup.find_all("table"):
                th = table.find("th")
                if th and th.text.strip() == section:  # Match the section
                    for row in table.find_all("tr"):
                        info_type_cell = row.find("td", class_="ttl")
                        info_value_cell = row.find("td", class_="nfo")
                        if info_type_cell and info_value_cell:
                            info_type = info_type_cell.text.strip()
                            info_value = info_value_cell.text.strip()
                            section_data[info_type] = info_value
                    extracted_info[section] = section_data
                    break
            if section not in extracted_info:  # If section was not found
                extracted_info[section] = None  # Or use {} for an empty dict instead
        return extracted_info

    def read_json(self, source_file, file_path):
        if source_file == 'brand links':
            with open(file_path, 'r') as f:
                self.brand_links = json.load(f)
            print("Brand links read")

        elif source_file == 'phone models':
            with open(file_path, 'r') as f:
                self.phone_models_links = json.load(f)
            print("Phone models read")

        elif source_file == 'phone info':
            with open(file_path, 'r') as f:
                self.phone_info = json.load(f)
            print("Phone info read")

        else:
            print("Invalid source file")

    def write_json(self, source_file, dest_file):
        if source_file == 'brand links':
            with open(dest_file, 'w') as f:
                json.dump(self.brand_links, f, ensure_ascii=False, indent=4)
            print("Brand links written")

        elif source_file == 'phone models':
            with open(dest_file, 'w') as f:
                json.dump(self.phone_models_links, f, ensure_ascii=False, indent=4)
            print("Phone models written")

        elif source_file == 'phone info':
            with open(dest_file, 'w') as f:
                json.dump(self.phone_info, f, ensure_ascii=False, indent=4)
            print("Phone info written")

        else:
            print("Invalid source file")

    def write_json_each(self, file, data):
        with open(file, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def get_brand_links(self):
        return self.brand_links

    def get_phone_models_links(self):
        return self.phone_models_links

    def get_phone_info(self):
        return self.phone_info


def main():
    # Brand list expanded 2026-05-08 to cover post-2022 risers. The original
    # 14 brands miss several major manufacturers that have grown significantly
    # in the 2024-2026 window — Google (Pixel), OnePlus, Honor (post-Huawei
    # split), Motorola (revived), and the Asian-market trio Oppo / Vivo /
    # Realme. Nothing is included for niche but visible coverage.
    brands_to_select = [
        # Original 14 — kept for back-compat with already-crawled data
        'alcatel', 'Apple', 'Asus', 'BLU', 'HTC', 'Huawei', 'Infinix',
        'Lenovo', 'LG', 'Nokia', 'Sony', 'Xiaomi', 'ZTE', 'Samsung',
        # New brands added 2026-05-08
        'Google', 'OnePlus', 'Honor', 'Motorola', 'Realme',
        'Oppo', 'vivo', 'Nothing',
    ]
    interested_sections = ['Network', 'Launch', 'Body', 'Display', 'Platform', 'Memory', 'Main Camera', 'Selfie camera',
                           'Sound', 'Comms', 'Features', 'Battery', 'Misc']

    main_links = "https://www.gsmarena.com/makers.php3"
    data_extractor = DataExtractor(main_links)
    data_extractor.extract_brand_data()
    # data_extractor.write_json('brand links', 'brand_links.json')
    data_extractor.extract_phone_models(brands_to_select)
    # data_extractor.write_json('phone models', 'phone_models_old.json')
    data_extractor.extract_phone_info(interested_sections)
    # data_extractor.write_json('phone info', 'phone_info.json')


if __name__ == '__main__':
    main()
    print("Done")
