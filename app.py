from google.oauth2.service_account import Credentials
import gspread
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
from datetime import datetime
import json
import time

def main():
    # Google API Setup
    DELEGATED_USER = 'y.kuanysh@prpillar.com'
    SCOPES = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets',
    ]
    print(f"Logging in as delegated user: {DELEGATED_USER}...")

    service_account_info = os.environ.get("GOOGLE_SERVICE_ACCOUNT")
    if not service_account_info:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT secret")

    credentials = Credentials.from_service_account_info(
        json.loads(service_account_info),
        scopes=SCOPES,
        subject=DELEGATED_USER
    )

    gc = gspread.authorize(credentials)
    drive_service = build('drive', 'v3', credentials=credentials)

    print("Accessing spreadsheet data...")
    spreadsheet_id = '1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0'
    spreadsheet = gc.open_by_key(spreadsheet_id)

    sheet = spreadsheet.worksheet('Database')
    config_sheet = spreadsheet.worksheet('Configurations')

    print("Reading config sheet contents...")
    start_row = config_sheet.acell("B2").value
    if start_row is None or start_row.strip() == "" or not start_row.strip().isdigit():
        start_row = 0
        config_sheet.update(range_name="B2", values=[["0"]])
        print("B2 was empty or invalid. Reset to 0")
    else:
        start_row = int(start_row.strip())

    batch_size = config_sheet.acell("B1").value
    if batch_size is None or not batch_size.strip().isdigit():
        raise ValueError("Invalid batch size in B1")
    batch_size = int(batch_size.strip())

    print("Calculating batch size...")
    all_records = sheet.get_all_records()
    total_rows = len(all_records)
    end_row = min(start_row + batch_size, total_rows)

    if start_row >= total_rows:
        print(f"WARNING: start row ({start_row}) exceeds total rows ({total_rows}). Nothing to process")
        config_sheet.update(range_name="B2", values=[["0"]])
        return True

    batch_records = all_records[start_row:end_row]
    print(f"Processing batch: rows {start_row} to {end_row - 1}")

    status_results = []

    print("Preparing Selenium...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    # CI stability flags
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # A common desktop user-agent (helps with some anti-bot/CDN checks)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36")
    # Keep default (normal) page load strategy; eager can return too soon on heavy JS sites
    # chrome_options.add_argument("--page-load-strategy=eager")  # <- removed on purpose

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)

    # Reduce obvious bot fingerprint
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
    except Exception:
        pass

    print("Beginning data parsing.")

    for index, record in enumerate(batch_records):
        url = record['Link']
        folder_id = record['Link to folder']

        # --- Robust navigate with retries ---
        nav_ok = False
        for attempt in range(1, 3):  # up to 2 tries
            try:
                driver.get(url)

                WebDriverWait(driver, 40).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                WebDriverWait(driver, 40).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                # Light "network settled" wait: load event fired
                WebDriverWait(driver, 10).until(
                    lambda d: (d.execute_script("return (window.performance.timing.loadEventEnd||0)")) > 0
                )
                nav_ok = True
                break
            except (TimeoutException, WebDriverException) as e:
                if attempt == 2:
                    print(f"Navigate failed on {url}: {e}")
                    status_results.append(["Timeout"])
                else:
                    backoff = 3 * attempt
                    print(f"Retrying {url} in {backoff}s due to: {e}")
                    time.sleep(backoff)

        if not nav_ok:
            continue

        # --- Screenshot & upload ---
        try:
            page_width = driver.execute_script(
                'return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth);'
            )
            page_height = driver.execute_script(
                'return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);'
            )

            if not page_width or page_width <= 0 or not page_height or page_height <= 0:
                page_width, page_height = 1366, 768

            page_width = min(int(page_width), 1920)
            page_height = min(int(page_height), 20000)
            driver.set_window_size(page_width, page_height)

            current_date = datetime.utcnow().strftime('%Y-%m-%d')  # UTC for CI consistency
            safe_url = sanitize_filename(url)
            screenshot_path = f"{current_date}-{record['Client']}-{safe_url}.png"

            driver.save_screenshot(screenshot_path)
        except Exception as e:
            print(f"Screenshot error for {url}: {e}")
            status_results.append(["Screenshot error"])
            continue

        try:
            file_metadata = {'name': screenshot_path, 'parents': [folder_id]}
            media = MediaFileUpload(screenshot_path, mimetype='image/png')
            drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        except Exception as e:
            print(f"Failed to upload {screenshot_path} for {url} to Google Drive: {e}")
            status_results.append(["Upload failed"])
            continue

        try:
            os.remove(screenshot_path)
        except Exception as e:
            print(f"Failed to delete local screenshot {screenshot_path}: {str(e)}")

        status_results.append(["True"])
        if (index + 1) % 10 == 0:
            print(f"Processed {index + 1} rows")

    driver.quit()
    print("Finished parsing the batch")

    print("Updating status column in 'Database' sheet...")
    status_cell_range = f"F{start_row + 2}:F{end_row + 1}"
    sheet.update(range_name=status_cell_range, values=status_results)

    config_sheet.update(range_name="B2", values=[[str(end_row)]])
    print(f"Updated start row in Configurations!B2 to {end_row}")

    if end_row >= total_rows:
        print("All rows have been processed")
        config_sheet.update(range_name="B2", values=[["0"]])
        return True
    else:
        print(f"More rows ({total_rows - end_row} remain to be processed)")
        return False


def sanitize_filename(url, max_length=100):
    invalid_characters = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', ' ']
    safe_text = ''.join('_' if c in invalid_characters else c for c in url)
    return safe_text[:max_length] if len(safe_text) > max_length else safe_text


if __name__ == "__main__":
    done = main()
    # exit(0 if done else 100)
    exit(0)
