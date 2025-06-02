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
scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
service_account_info = os.getenv('GOOGLE_SERVICE_ACCOUNT') or json.load(open('credentials.json'))

if service_account_info:
    credentials = Credentials.from_service_account_info(json.loads(service_account_info), scopes=scopes)
    print("Using service account:", credentials.service_account_email)
else:
    credentials = Credentials.from_service_account_file('credentials.json', scopes=scopes)

gc = gspread.authorize(credentials)
drive_service = build('drive', 'v3', credentials=credentials)

# Google Sheet and Drive Setup
spreadsheet_id = '1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0'
sheet_name = 'Database' 
sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
records = sheet.get_all_records()  # Assumes first row is header

# Selenium Setup
chrome_options = Options()
chrome_options.add_argument("--headless")

# Add any Chrome options you need here
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)
driver.maximize_window()

for record in records:
    url = record['Link']
    folder_id = record['Link to folder']
    successful_connection = False  # Flag to track if connection was successful

    try:
        driver.get(url)
        time.sleep(random.uniform(1, 3))  # Random delay after loading the page to imitate human behavior
        successful_connection = True
    except (TimeoutException, WebDriverException) as e:
        print(f"Timeout while trying to connect to {url}: {str(e)}")

    if not successful_connection:
        continue  # Skip the rest of the code in this loop iteration and move to the next record
    
    # If connection was successful, proceed with screenshot
    # Before trying to set the window size
    if successful_connection:
        try:
            current_date = datetime.now().strftime('%Y-%m-%d')
            page_width = driver.execute_script('return document.body.scrollWidth')
            page_height = driver.execute_script('return document.body.scrollHeight')
            
            # Validate page_width and page_height
            if page_width is None or page_height is None or page_width <= 0 or page_height <= 0:
                print(f"Invalid dimensions for {url}, using default values.")
                page_width = 800  # Default width
                page_height = 600  # Default height

            def sanitize_filename(url):
                invalid_characters = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', ' ']
                safe_url = ''.join('_' if c in invalid_characters else c for c in url)
                return safe_url
            
            safe_url = sanitize_filename(record['Link'])  # Use the sanitize function on the entire URL
            screenshot_path = f"{current_date}-{record['Client']}-{safe_url}.png"

            driver.set_window_size(page_width, page_height)
            driver.save_screenshot(screenshot_path)
        except (TimeoutException, WebDriverException, InvalidArgumentException) as e:
            print(f"Error while processing {url}: {str(e)}")
            continue  # Skip file upload for this record if there were any errors

    try:
        folder = drive_service.files().get(fileId=folder_id, fields='driveId, name').execute()
        # Check the service account's Drive quota
        try:
            about_info = drive_service.about().get(fields='storageQuota').execute()
            quota = about_info.get('storageQuota', {})

            def format_bytes(size):
                # Helper function to convert bytes to readable format
                for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                    if size < 1024.0:
                        return f"{size:.2f} {unit}"
                    size /= 1024.0
                return f"{size:.2f} PB"

            limit = int(quota.get('limit', '0'))
            usage = int(quota.get('usage', '0'))
            usage_in_drive = int(quota.get('usageInDrive', '0'))
            usage_in_trash = int(quota.get('usageInDriveTrash', '0'))

            print("\n📊 Service Account Storage Quota:")
            print(f"• Total Quota Limit      : {format_bytes(limit)}")
            print(f"• Total Used             : {format_bytes(usage)}")
            print(f"• Used in Drive          : {format_bytes(usage_in_drive)}")
            print(f"• Used in Drive Trash    : {format_bytes(usage_in_trash)}\n")

        except Exception as e:
            print(f"⚠️ Failed to fetch storage quota: {e}")

        if 'driveId' in folder:
            print(f"✅ Uploading to Shared Drive: {folder['name']}")
        else:
            print(f"⚠️ Uploading to a regular My Drive folder (uses service account quota): {folder['name']}")
    except Exception as e:
        print(f"⚠️ Failed to check folder drive type: {str(e)}")

    # Try to upload to Google Drive
    try:
        file_metadata = {'name': screenshot_path, 'parents': [folder_id]}
        media = MediaFileUpload(screenshot_path, mimetype='image/png')
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    except Exception as e:  # This catches general exceptions from the Drive upload
        print(f"Failed to upload {screenshot_path} to Google Drive: {str(e)}")
        # No 'continue' here since we want to attempt the next steps regardless

    # Optionally, delete the local file after upload
    try:
        os.remove(screenshot_path)
    except Exception as e:
        print(f"Failed to delete local screenshot {screenshot_path}: {str(e)}")

driver.quit()
