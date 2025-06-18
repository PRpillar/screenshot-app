from google.oauth2.service_account import Credentials
import gspread
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidArgumentException
from webdriver_manager.chrome import ChromeDriverManager
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
from datetime import datetime
import json
import random
import time
from urllib.parse import urlparse

def main():
    # Google API Setup
    DELEGATED_USER = 'y.kuanysh@prpillar.com'
    SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
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

    print("Done.")
    
    print("Accessing spreadsheet data...")
    # Spreadsheet setup
    spreadsheet_id = '1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0'
    
    # Database setup
    sheet_name = 'Database'
    sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)

    # Configuration setup
    sheet_name = 'Configurations'
    config_sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)

    print("Reading config sheet contents...")
    # Read configs from the sheet
    start_row = config_sheet.acell("B2").value
    if start_row is None or start_row.strip() == "" or not start_row.strip().isdigit():
        start_row = 0
        config_sheet.update("B2", "0")
        print("B2 was empty or invalid. Reset to 0")
    else:
        start_row  = int(start_row.strip())

    batch_size = config_sheet.acell("B1").value
    if batch_size is None or not batch_size.strip().isdigit():
        raise ValueError("Invalid batch size in B1")
    batch_size = int(batch_size.strip())
    
    print("Done.")

    print("Calculating batch size...")
    # Select batch rows
    all_records = sheet.get_all_records()
    total_rows = len(all_records)

    # Calculating end row
    end_row = min(start_row + batch_size, total_rows)

    if start_row >= total_rows:
        print(f"WARNING: start row ({start_row}) exceeds total rows ({total_rows}). Nothing to process")
        config_sheet.update("B2", "0")
        return True
    print("Done.")

    batch_records = all_records[start_row:end_row]
    print(f"Processing batch: rows {start_row} to {end_row - 1}")

    # For debugging
    status_results = []

    print("Preparing Selenium...")
    # Selenium setup
    chrome_options = Options()
    # Selenium arguments
    # TODO add bypasses for sites?
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--page-load-strategy=eager")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.maximize_window()

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)

    print("Done.")
    print("Beginning data parsing.")

    for index, record in enumerate(batch_records):
        url = record['Link']
        platform = record['Platform']
        folder_id = record['Link to folder']
        status = ""

        try:
            driver.get(url)

            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            time.sleep(random.uniform(1, 3))
        except TimeoutException:
            status = "Timeout"
            print(f"Timeout while trying to connect to {url}")
            status_results.append([status])
            continue
        except WebDriverException as e:
            status = "WebDriver error"
            print(f"WebDriver error on {url}: {e}")
            status_results.append([status])
            continue

        try:
            if platform == "google.com":
                page_width = 1920
                page_height = 1080
            else:
                page_width = driver.execute_script('return document.body.scrollWidth')
                page_height = driver.execute_script('return document.body.scrollHeight')

                if page_width is None or page_height is None or page_width <= 0 or page_height <= 0:
                    page_width = 800
                    page_height = 600
            driver.set_window_size(page_width, page_height)
            
            current_date = datetime.now().strftime('%Y-%m-%d')
            
            safe_url = sanitize_filename(url)
            screenshot_path = f"{current_date}-{record['Client']}-{safe_url}.png"

            driver.save_screenshot(screenshot_path)
        except Exception as e:
            status = "Screenshot error"
            print(f"Screenshot error for {url}: {e}")
            status_results.append([status])
            continue

        try:
            file_metadata = {'name': screenshot_path, 'parents': [folder_id]}
            media = MediaFileUpload(screenshot_path, mimetype='image/png')
            drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        except Exception as e:
            status = "Upload failed"
            print(f"Failed to upload {screenshot_path} for {url} to Google Drive: {e}")
            status_results.append([status])
            continue

        try:
            os.remove(screenshot_path)
        except Exception as e:
            print(f"Failed to delete local screenshot {screenshot_path}: {str(e)}")

        status_results.append(["True"]) # if all went well
        if index % 10 == 0:
            print(f"Processed {index + 1} rows")

    driver.quit()
    print("Finished parsing the batch")

    # Write status results to column F (Status) in 'Database' sheet
    print("Updating status column in 'Database' sheet...")
    status_cell_range = f"F{start_row + 2}:F{end_row + 1}" # +2 for 1-based index + header
    sheet.update(status_cell_range, status_results)
    print("Done.")

    # Update next start row in Configurations!B2
    config_sheet.update("B2", [[str(end_row)]])
    print(f"Updated start row in Configurations!B2 to {end_row}")

    # Check if this is the final batch
    if end_row >= total_rows:
        print("All rows have been processed")
        config_sheet.update("B2", "0")
        return True
    else:
        print(f"More rows ({total_rows - end_row} remain to be processed)")
        return False
    

def sanitize_filename(url, max_length = 100):
    invalid_characters = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', ' ']
    safe_text = ''.join('_' if c in invalid_characters else c for c in url)

    if len(safe_text) > max_length:
        safe_text = safe_text[:max_length]

    return safe_text

if __name__ == "__main__":
    done = main()
    if done:
        exit(0)
    else:
        exit(100) # Github rerun signal
