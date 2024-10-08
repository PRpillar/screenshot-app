import os
import time
import random
import json
import hashlib
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
import undetected_chromedriver as uc
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Google API Setup

# Specify the user to impersonate
user_to_impersonate = 'a.zhubekov@prpillar.com'

scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
service_account_info = os.getenv('GOOGLE_SERVICE_ACCOUNT')
if service_account_info:
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(service_account_info),
        scopes=scopes,
        subject=user_to_impersonate
    )
else:
    credentials = service_account.Credentials.from_service_account_file(
        '../credentials.json',
        scopes=scopes,
        subject=user_to_impersonate
    )

gc = gspread.authorize(credentials)
drive_service = build('drive', 'v3', credentials=credentials)

# Google Sheet and Drive Setup
spreadsheet_id = '1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0'
sheet_name = 'Database'
sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
records = sheet.get_all_records()  # Assumes first row is header

# Updated sanitize_filename function
def sanitize_filename(url):
    # Extract domain and create a hash of the URL
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace('.', '_')
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
    return f"{domain}_{url_hash}"

# Function to process a single record
def process_record(record):
    url = record['Link']
    folder_id = record['Link to folder']
    successful_connection = False

    # Check if folder_id is valid
    if not folder_id:
        print(f"No folder ID provided for {url}, skipping upload.")
        return

    # Selenium Setup with undetected-chromedriver
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument('--headless')  # Enable headless mode
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)")
    driver = uc.Chrome(options=chrome_options, browser_executable_path='/usr/bin/google-chrome')

    try:
        # Attempt to access the URL with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                driver.get(url)
                # Dynamic wait: Wait until the page is fully loaded
                WebDriverWait(driver, 20).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                successful_connection = True
                break
            except (TimeoutException, WebDriverException) as e:
                print(f"Attempt {attempt + 1} failed for {url}: {e}")
                time.sleep(random.uniform(5, 10))
        if not successful_connection:
            return

        # Proceed with screenshot
        try:
            current_date = datetime.now().strftime('%Y-%m-%d')
            page_width = driver.execute_script('return document.body.scrollWidth')
            page_height = driver.execute_script('return document.body.scrollHeight')

            # Validate dimensions
            if not page_width or not page_height:
                page_width = 800
                page_height = 600

            safe_url = sanitize_filename(url)
            client_name = sanitize_filename(record['Client'])
            screenshot_path = f"{current_date}-{client_name}-{safe_url}.png"

            driver.set_window_size(page_width, page_height)
            # Additional wait to ensure elements are loaded
            time.sleep(random.uniform(1, 2))
            driver.save_screenshot(screenshot_path)
        except Exception as e:
            print(f"Error while processing {url}: {e}")
            return

        # Try to upload to Google Drive
        try:
            file_metadata = {'name': os.path.basename(screenshot_path), 'parents': [folder_id]}
            media = MediaFileUpload(screenshot_path, mimetype='image/png')

            # Check storage quota before uploading
            about = drive_service.about().get(fields="storageQuota").execute()
            used = int(about['storageQuota']['usage'])
            total = int(about['storageQuota']['limit'])
            if used >= total:
                print("Drive storage quota exceeded, stopping uploads.")
                return

            drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print(f"Uploaded {screenshot_path} to Google Drive.")
        except HttpError as e:
            if e.resp.status == 403 and 'storageQuotaExceeded' in str(e):
                print("Google Drive storage quota exceeded, stopping uploads.")
            elif e.resp.status == 404:
                print(f"Folder not found for {url}: {e}")
            else:
                print(f"Failed to upload {screenshot_path} to Google Drive: {e}")
            return
        except Exception as e:
            print(f"Failed to upload {screenshot_path} to Google Drive: {e}")
            return

        # Delete local screenshot
        try:
            os.remove(screenshot_path)
            print(f"Deleted local screenshot {screenshot_path}.")
        except Exception as e:
            print(f"Failed to delete local screenshot {screenshot_path}: {e}")
    finally:
        driver.quit()

# Main execution using ThreadPoolExecutor for parallel processing
def main():
    max_workers = min(5, len(records))  # Limit the number of workers
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_record = {executor.submit(process_record, record): record for record in records}

        for future in as_completed(future_to_record):
            record = future_to_record[future]
            try:
                future.result()
            except Exception as e:
                print(f"Exception occurred while processing record {record['Link']}: {e}")

if __name__ == "__main__":
    main()
