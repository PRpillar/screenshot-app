from google.oauth2.service_account import Credentials
import gspread
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
from datetime import datetime
import json
import random
import time
from google.auth.transport.requests import Request

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

# Selenium Setup
chrome_options = Options()
chrome_options.add_argument("--headless")

# Add any Chrome options you need here
service = Service(ChromeDriverManager().install())

driver = webdriver.Chrome(service=service, options=chrome_options)
driver.maximize_window()

max_attempts = 5

for record in records:
    url = record['Link']
    folder_id = record['Link to folder']
    successful_connection = False  # Flag to track if connection was successful

    for attempt in range(max_attempts):
        try:
            driver.get(url)
            time.sleep(random.uniform(1, 3))  # Random delay after loading the page to imitate human behavior
            successful_connection = True  # Set the flag to True if successful
            break  # Exit the loop if successful
        except Exception as e:  # Catch the specific exception if possible
            print(f"Attempt {attempt + 1} of {max_attempts} failed: {str(e)}")
            time.sleep(10)  # Wait for 10 seconds before retrying

    if not successful_connection:
        print(f"Failed to connect to {url} after {max_attempts} attempts.")
        continue  # Skip the rest of the code in this loop iteration and move to the next record
    
    # If connection was successful, proceed with screenshot and upload
    current_date = datetime.now().strftime('%Y-%m-%d')
    page_width = driver.execute_script('return document.body.scrollWidth')
    page_height = driver.execute_script('return document.body.scrollHeight')
    screenshot_path = f"{current_date}-{record['Client']}-{record['Platform']}.png"
    driver.set_window_size(page_width, page_height)
    driver.save_screenshot(screenshot_path)

    # Check if token is valid and refresh if necessary before uploading
    if credentials.expired or credentials.valid is False:
        credentials.refresh(Request())
        # Ensure the Drive service uses the refreshed credentials
        drive_service = build('drive', 'v3', credentials=credentials)

    # Upload to Google Drive
    file_metadata = {'name': screenshot_path, 'parents': [folder_id]}
    media = MediaFileUpload(screenshot_path, mimetype='image/png')
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    
    # Optionally, delete the local file after upload
    os.remove(screenshot_path)

driver.quit()
