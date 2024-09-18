import os
import time
import random
import json
import hashlib
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import undetected_chromedriver as uc
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from fake_useragent import UserAgent
from googleapiclient.errors import HttpError

# Google API Setup
scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
service_account_info = os.getenv('GOOGLE_SERVICE_ACCOUNT') or json.load(open('../credentials.json'))

if service_account_info:
    credentials = Credentials.from_service_account_info(json.loads(service_account_info), scopes=scopes)
else:
    credentials = Credentials.from_service_account_file('../credentials.json', scopes=scopes)

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
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace('.', '_')
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
    return f"{domain}_{url_hash}"

# Function to check for CAPTCHA
def is_captcha_present(driver):
    try:
        # Check for common CAPTCHA phrases or elements
        captcha_indicators = [
            'captcha',
            'recaptcha',
            'hcaptcha',
            'are you a human',
            'please verify',
            'security check',
            'i am not a robot',
            'verification required',
            'unusual traffic',
            'robot check'
        ]
        page_source = driver.page_source.lower()
        for indicator in captcha_indicators:
            if indicator in page_source:
                return True
        return False
    except Exception as e:
        print(f"Error checking for CAPTCHA: {e}")
        return False

# Selenium Setup with undetected-chromedriver
ua = UserAgent()
user_agent = ua.random

chrome_options = Options()
chrome_options.add_argument(f'--user-agent={user_agent}')
chrome_options.add_argument("--disable-blink-features=AutomationControlled")

driver = uc.Chrome(options=chrome_options)
driver.maximize_window()

for record in records:
    url = record['Link']
    folder_id = record['Link to folder']
    successful_connection = False

    # Check if folder_id is valid
    if not folder_id:
        print(f"No folder ID provided for {url}, skipping upload.")
        continue

    # Attempt to access the URL with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            driver.get(url)
            time.sleep(random.uniform(2, 5))
            successful_connection = True
            break
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
            time.sleep(random.uniform(5, 10))
    if not successful_connection:
        continue

    # ... [Simulate human behavior, check for CAPTCHA]

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
        driver.save_screenshot(screenshot_path)
    except Exception as e:
        print(f"Error while processing {url}: {e}")
        continue

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
            break

        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    except HttpError as e:
        if e.resp.status == 403 and 'storageQuotaExceeded' in str(e):
            print("Google Drive storage quota exceeded, stopping uploads.")
            break
        elif e.resp.status == 404:
            print(f"Folder not found for {url}: {e}")
            continue
        else:
            print(f"Failed to upload {screenshot_path} to Google Drive: {e}")
            continue
    except Exception as e:
        print(f"Failed to upload {screenshot_path} to Google Drive: {e}")
        continue

    # Delete local screenshot
    try:
        os.remove(screenshot_path)
    except Exception as e:
        print(f"Failed to delete local screenshot {screenshot_path}: {e}")

driver.quit()
