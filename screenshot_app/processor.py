import os
import signal
import random
import time
import logging
from typing import List, Tuple, Any, Dict

import gspread
from googleapiclient.http import MediaFileUpload
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .cloudflare import (
    is_cloudflare_verification,
    bypass_cloudflare_verification,
    debug_dump_cloudflare_page,
)
from .driver_factory import create_chrome_driver
from .models import RowRecord
from .screenshotter import build_screenshot_filename, take_fullpage_screenshot


def safe_navigate(driver, url: str, wait_seconds: int = 20) -> None:
    """Navigate via JS to avoid rare hangs in driver.get.

    We set location with JS and then explicitly wait for a <body> to appear.
    This avoids blocking on network idle or long-loading trackers.
    """
    try:
        # Stop any current load and use CDP to navigate without blocking on driver.get
        try:
            driver.execute_cdp_cmd("Page.stopLoading", {})
        except Exception:
            pass
        try:
            driver.execute_cdp_cmd("Page.navigate", {"url": url})
        except Exception:
            # Fallback: JS redirect if CDP navigate is unavailable
            driver.execute_script("window.location.href = arguments[0];", url)
        WebDriverWait(driver, wait_seconds).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        # Propagate so caller can mark status and continue
        raise


def run_with_timeout(func, seconds: int):
    """Run callable with a hard timeout using Unix SIGALRM (Linux CI safe).

    Ensures we escape hangs inside WebDriver/CDP even if their own timeouts fail.
    """
    def _handler(signum, frame):
        raise TimeoutException("Hard timeout exceeded")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    try:
        signal.alarm(seconds)
        return func()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def read_config_values(config_sheet: gspread.Worksheet) -> Tuple[int, int]:
    start_row_value = config_sheet.acell("B2").value
    if start_row_value is None or start_row_value.strip() == "" or not start_row_value.strip().isdigit():
        start_row = 0
        config_sheet.update(range_name="B2", values=[["0"]])
    else:
        start_row = int(start_row_value.strip())

    batch_size_value = config_sheet.acell("B1").value
    if batch_size_value is None or not batch_size_value.strip().isdigit():
        raise ValueError("Invalid batch size in B1")
    batch_size = int(batch_size_value.strip())
    return start_row, batch_size


def read_database_records(sheet: gspread.Worksheet) -> List[RowRecord]:
    records: List[Dict[str, Any]] = sheet.get_all_records()
    normalized: List[RowRecord] = []
    for r in records:
        # Coerce potentially None/Any values to strings for safety
        link = str(r.get("Link", "") or "")
        platform = str(r.get("Platform", "") or "")
        folder_id = str(r.get("Link to folder", "") or "")
        client = str(r.get("Client", "") or "")
        normalized.append(RowRecord(link=link, platform=platform, folder_id=folder_id, client=client))
    return normalized


def process_batch(
    gc: gspread.Client,
    drive_service: Any,
    spreadsheet_id: str,
    database_sheet_name: str,
    config_sheet_name: str,
    debug_cloudflare: bool,
) -> bool:
    logger = logging.getLogger("screenshot_app.processor")
    sheet = gc.open_by_key(spreadsheet_id).worksheet(database_sheet_name)
    config_sheet = gc.open_by_key(spreadsheet_id).worksheet(config_sheet_name)

    start_row, batch_size = read_config_values(config_sheet)
    logger.info("Batch config: start_row=%s batch_size=%s", start_row, batch_size)
    all_records = read_database_records(sheet)
    total_rows = len(all_records)
    end_row = min(start_row + batch_size, total_rows)
    logger.info("Total rows=%s; processing [%s, %s)", total_rows, start_row, end_row)

    if start_row >= total_rows:
        logger.info("Start row beyond total rows; resetting to 0 and exiting")
        config_sheet.update(range_name="B2", values=[["0"]])
        return True

    batch_records = all_records[start_row:end_row]

    driver = create_chrome_driver(headless=True)
    driver.maximize_window()
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    logger.info("WebDriver initialized")

    status_results: List[List[str]] = []

    for index, record in enumerate(batch_records):
        url = record.link
        folder_id = record.folder_id
        status = ""
        row_idx = start_row + index
        t0 = time.time()
        logger.info("Row %s: Navigating %s", row_idx, url)
        try:
            # Hard cap navigation at 45s to avoid indefinite hangs
            run_with_timeout(lambda: safe_navigate(driver, url, wait_seconds=20), seconds=45)
            time.sleep(random.uniform(2, 5))
        except TimeoutException:
            status = "Timeout"
            logger.warning("Row %s: Timeout navigating %s", row_idx, url)
            status_results.append([status])
            continue
        except WebDriverException:
            status = "WebDriver error"
            logger.exception("Row %s: WebDriver error on %s", row_idx, url)
            status_results.append([status])
            continue

        if is_cloudflare_verification(driver):
            if not bypass_cloudflare_verification(driver):
                if debug_cloudflare:
                    debug_dump_cloudflare_page(driver, url)
                status = "Cloudflare verification detected"
                logger.warning("Row %s: Cloudflare challenge not bypassed for %s", row_idx, url)
                status_results.append([status])
                continue

        try:
            screenshot_path = build_screenshot_filename(record.client, url)
            take_fullpage_screenshot(driver, screenshot_path)
        except Exception:
            status = "Screenshot error"
            logger.exception("Row %s: Screenshot error for %s", row_idx, url)
            status_results.append([status])
            continue

        try:
            file_metadata = {"name": screenshot_path, "parents": [folder_id]}
            media = MediaFileUpload(screenshot_path, mimetype="image/png")
            logger.info("Row %s: Uploading %s to folder %s", row_idx, screenshot_path, folder_id)
            drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
            logger.info("Row %s: Upload complete %s", row_idx, screenshot_path)
        except Exception:
            status = "Upload failed"
            logger.exception("Row %s: Upload failed for %s", row_idx, screenshot_path)
            status_results.append([status])
            continue
        finally:
            try:
                os.remove(screenshot_path)
            except Exception:
                logger.debug("Row %s: Failed to remove temp file %s", row_idx, screenshot_path)

        status_results.append(["True"])
        elapsed = time.time() - t0
        logger.info("Row %s: Done in %.2fs", row_idx, elapsed)

    driver.quit()
    logger.info("WebDriver closed")

    status_cell_range = f"F{start_row + 2}:F{end_row + 1}"
    sheet.update(range_name=status_cell_range, values=status_results)
    logger.info("Statuses written to %s", status_cell_range)
    config_sheet.update(range_name="B2", values=[[str(end_row)]])
    logger.info("Next start row set to %s", end_row)
    if end_row >= total_rows:
        config_sheet.update(range_name="B2", values=[["0"]])
        logger.info("All rows processed; start row reset to 0")
        return True
    return False


