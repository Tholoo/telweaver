from pathlib import Path
import requests
from bs4 import BeautifulSoup
from loguru import logger

DOMAIN = "https://core.telegram.org"
API_PATH = "/bots/api"
# API_TYPE = "available-types"

CACHE_PATH = Path("cache/response.txt")

# URL = f"{DOMAIN}{API_PATH}#{API_TYPE}"
URL = f"{DOMAIN}{API_PATH}"


def get_page(url: str, cache_path=CACHE_PATH) -> str:
    """Get page content and return the content as a string"""
    if Path.exists(cache_path):
        logger.info(f"Using cached response for {url}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()

    logger.info(f"Fetching {url}")
    response = requests.get(url)
    # logger.info(f"Fetched {url} with ")
    response.raise_for_status()
    text = response.text
    if not text:
        raise Exception("Response text is empty")

    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)

    return text


def parse_page(content: str):
    """Parse Page content and extract useful fields"""
    logger.info("Parsing...")
    bs = BeautifulSoup(content, "html.parser")
    titles = bs.find_all("h4")
    logger.info(f"Found {len(titles)} titles")

    results = {}
    for title in titles:
        description = title.find_next_sibling("p")
        table = description.find_next_sibling("table") if description else None

        # Check if the sequence h4 -> p -> table exists
        if not description or not table:
            continue

        results[title] = (description, table)

    logger.info(
        f"Found {len(results)} tables out of {len(titles)} titles ({len(results)/len(titles):.2%})"
    )
    return results


content = get_page(URL)
parse_page(content)
