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

# Google API Setup
DELEGATED_USER = 'y.kuanysh@prpillar.com'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

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

spreadsheet_id = '1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0'
sheet_name = 'Database'
sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
records = sheet.get_all_records()

chrome_options = Options()
chrome_options.add_argument("--headless")
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)
driver.maximize_window()

driver.set_page_load_timeout(15)
driver.implicitly_wait(5)

for record in records:
    url = record['Link']
    folder_id = record['Link to folder']
    successful_connection = False

    try:
        driver.get(url)
        time.sleep(random.uniform(1, 3))
        successful_connection = True
    except (TimeoutException, WebDriverException) as e:
        print(f"Timeout while trying to connect to {url}: {str(e)}")

    if not successful_connection:
        continue

    try:
        current_date = datetime.now().strftime('%Y-%m-%d')
        page_width = driver.execute_script('return document.body.scrollWidth')
        page_height = driver.execute_script('return document.body.scrollHeight')

        if page_width is None or page_height is None or page_width <= 0 or page_height <= 0:
            page_width = 800
            page_height = 600

        def sanitize_filename(url):
            max_length = 150
            invalid_characters = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', ' ']
            safe_text = ''.join('_' if c in invalid_characters else c for c in url)
        
            if len(safe_text) > max_length:
                safe_text = safe_text[:max_length]
        
            return safe_text

        safe_url = sanitize_filename(record['Link'])
        screenshot_path = f"{current_date}-{record['Client']}-{safe_url}.png"

        driver.set_window_size(page_width, page_height)
        driver.save_screenshot(screenshot_path)
    except (TimeoutException, WebDriverException, InvalidArgumentException) as e:
        print(f"Error while processing {url}: {str(e)}")
        continue

    try:
        folder = drive_service.files().get(fileId=folder_id, fields='driveId, name').execute()
    except Exception as e:
        print(f"⚠️ Failed to check folder drive type: {str(e)}")

    try:
        file_metadata = {'name': screenshot_path, 'parents': [folder_id]}
        media = MediaFileUpload(screenshot_path, mimetype='image/png')
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    except Exception as e:
        print(f"Failed to upload {screenshot_path} to Google Drive: {str(e)}")

    try:
        os.remove(screenshot_path)
    except Exception as e:
        print(f"Failed to delete local screenshot {screenshot_path}: {str(e)}")

driver.quit()
