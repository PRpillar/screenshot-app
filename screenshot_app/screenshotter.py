from datetime import datetime
import os
from typing import Tuple


def build_screenshot_filename(client: str, url: str) -> str:
    from .cloudflare import sanitize_filename  # reuse utility

    current_date = datetime.now().strftime("%Y-%m-%d")
    safe_url = sanitize_filename(url)
    safe_client = sanitize_filename(client)
    return f"{current_date}-{safe_client}-{safe_url}.png"


def take_fullpage_screenshot(driver, out_path: str) -> None:
    page_width = driver.execute_script("return document.body.scrollWidth")
    page_height = driver.execute_script("return document.body.scrollHeight")
    if not page_width or page_width <= 0:
        page_width = 800
    if not page_height or page_height <= 0:
        page_height = 600
    driver.set_window_size(page_width, page_height)
    driver.save_screenshot(out_path)


