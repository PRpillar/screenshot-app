import os
import random
import time
from typing import List, Tuple

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


def read_config_values(config_sheet: gspread.Worksheet) -> Tuple[int, int]:
    start_row_value = config_sheet.acell("B2").value
    if start_row_value is None or start_row_value.strip() == "" or not start_row_value.strip().isdigit():
        start_row = 0
        config_sheet.update("B2", [["0"]])
    else:
        start_row = int(start_row_value.strip())

    batch_size_value = config_sheet.acell("B1").value
    if batch_size_value is None or not batch_size_value.strip().isdigit():
        raise ValueError("Invalid batch size in B1")
    batch_size = int(batch_size_value.strip())
    return start_row, batch_size


def read_database_records(sheet: gspread.Worksheet) -> List[RowRecord]:
    records = sheet.get_all_records()
    out: List[RowRecord] = []
    for r in records:
        out.append(
            RowRecord(
                link=r.get("Link", ""),
                platform=r.get("Platform", ""),
                folder_id=r.get("Link to folder", ""),
                client=r.get("Client", ""),
            )
        )
    return out


def process_batch(
    gc: gspread.Client,
    drive_service,
    spreadsheet_id: str,
    database_sheet_name: str,
    config_sheet_name: str,
    debug_cloudflare: bool,
) -> bool:
    sheet = gc.open_by_key(spreadsheet_id).worksheet(database_sheet_name)
    config_sheet = gc.open_by_key(spreadsheet_id).worksheet(config_sheet_name)

    start_row, batch_size = read_config_values(config_sheet)
    all_records = read_database_records(sheet)
    total_rows = len(all_records)
    end_row = min(start_row + batch_size, total_rows)

    if start_row >= total_rows:
        config_sheet.update("B2", [["0"]])
        return True

    batch_records = all_records[start_row:end_row]

    driver = create_chrome_driver(headless=True)
    driver.maximize_window()
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)

    status_results: List[List[str]] = []

    for index, record in enumerate(batch_records):
        url = record.link
        folder_id = record.folder_id
        status = ""
        try:
            driver.get(url)
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(random.uniform(5, 10))
        except TimeoutException:
            status = "Timeout"
            status_results.append([status])
            continue
        except WebDriverException:
            status = "WebDriver error"
            status_results.append([status])
            continue

        if is_cloudflare_verification(driver):
            if not bypass_cloudflare_verification(driver):
                if debug_cloudflare:
                    debug_dump_cloudflare_page(driver, url)
                status = "Cloudflare verification detected"
                status_results.append([status])
                continue

        try:
            screenshot_path = build_screenshot_filename(record.client, url)
            take_fullpage_screenshot(driver, screenshot_path)
        except Exception:
            status = "Screenshot error"
            status_results.append([status])
            continue

        try:
            file_metadata = {"name": screenshot_path, "parents": [folder_id]}
            media = MediaFileUpload(screenshot_path, mimetype="image/png")
            drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        except Exception:
            status = "Upload failed"
            status_results.append([status])
            continue
        finally:
            try:
                os.remove(screenshot_path)
            except Exception:
                pass

        status_results.append(["True"])
        if index % 10 == 0:
            pass

    driver.quit()

    status_cell_range = f"F{start_row + 2}:F{end_row + 1}"
    sheet.update(status_cell_range, status_results)
    config_sheet.update("B2", [[str(end_row)]])

    if end_row >= total_rows:
        config_sheet.update("B2", [["0"]])
        return True
    return False


