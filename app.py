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
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ScreenshotAutomation:
    def __init__(self):
        self.setup_google_services()
        self.setup_selenium_driver()
        
    def setup_google_services(self):
        """Initialize Google API services with proper error handling"""
        try:
            # Constants
            self.DELEGATED_USER = 'y.kuanysh@prpillar.com'
            self.SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
            self.SPREADSHEET_ID = '1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0'
            self.SHEET_NAME = 'Database'
            
            # Get service account credentials
            service_account_info = os.environ.get("GOOGLE_SERVICE_ACCOUNT")
            if not service_account_info:
                raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT environment variable")
            
            # Setup credentials
            credentials = Credentials.from_service_account_info(
                json.loads(service_account_info),
                scopes=self.SCOPES,
                subject=self.DELEGATED_USER
            )
            
            # Initialize services
            self.gc = gspread.authorize(credentials)
            self.drive_service = build('drive', 'v3', credentials=credentials)
            
            # Get spreadsheet data
            sheet = self.gc.open_by_key(self.SPREADSHEET_ID).worksheet(self.SHEET_NAME)
            self.records = sheet.get_all_records()
            
            logger.info(f"Successfully loaded {len(self.records)} records from spreadsheet")
            
        except Exception as e:
            logger.error(f"Failed to setup Google services: {str(e)}")
            raise
    
    def setup_selenium_driver(self):
        """Initialize Selenium driver with timeout and performance optimizations"""
        try:
            chrome_options = Options()
            
            # Performance optimizations
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-plugins")
            # chrome_options.add_argument("--disable-images")  # Faster loading
            # chrome_options.add_argument("--disable-javascript")  # Optional: faster but may affect some sites
            
            # Timeout settings
            chrome_options.add_argument("--page-load-strategy=eager")  # Don't wait for all resources
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Set timeouts - THIS FIXES YOUR TIMEOUT ISSUES
            self.driver.set_page_load_timeout(30)  # 30 seconds max for page load
            self.driver.implicitly_wait(10)  # 10 seconds for element finding
            
            logger.info("Selenium driver initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to setup Selenium driver: {str(e)}")
            raise
    
    def sanitize_filename(self, text, max_length=100):
        """Create safe filename from URL or text"""
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*', ' ', '#', '%']
        safe_text = ''.join('_' if c in invalid_chars else c for c in text)
        
        # Remove consecutive underscores and trim
        safe_text = '_'.join(filter(None, safe_text.split('_')))
        
        if len(safe_text) > max_length:
            safe_text = safe_text[:max_length]
            
        return safe_text
    
    def take_screenshot(self, url, client_name):
        """Take screenshot with proper error handling and retries"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempting to load {url} (attempt {attempt + 1}/{max_retries})")
                
                # Navigate to URL with timeout handling
                self.driver.get(url)
                
                # Wait for page to load with random delay
                time.sleep(random.uniform(2, 4))
                
                # Get page dimensions with fallbacks
                try:
                    page_width = self.driver.execute_script('return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth)')
                    page_height = self.driver.execute_script('return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)')
                except Exception:
                    page_width = page_height = None
                
                # Set reasonable defaults if dimensions can't be determined
                if not page_width or page_width <= 0:
                    page_width = 1920
                if not page_height or page_height <= 0:
                    page_height = 1080
                
                # Limit maximum dimensions to prevent memory issues
                page_width = min(page_width, 1920)
                page_height = min(page_height, 10000)  # Reasonable max for long pages
                
                # Set window size and take screenshot
                self.driver.set_window_size(page_width, page_height)
                
                # Generate filename
                current_date = datetime.now().strftime('%Y-%m-%d')
                safe_url = self.sanitize_filename(url)
                screenshot_path = f"{current_date}-{client_name}-{safe_url}.png"
                
                # Take screenshot
                self.driver.save_screenshot(screenshot_path)
                logger.info(f"Screenshot saved: {screenshot_path}")
                
                return screenshot_path
                
            except TimeoutException:
                logger.warning(f"Timeout on attempt {attempt + 1} for {url}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Failed to load {url} after {max_retries} attempts")
                    return None
                    
            except (WebDriverException, InvalidArgumentException) as e:
                logger.error(f"WebDriver error on {url}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    return None
                    
            except Exception as e:
                logger.error(f"Unexpected error taking screenshot of {url}: {str(e)}")
                return None
        
        return None
    
    def upload_to_drive(self, file_path, folder_id):
        """Upload file to Google Drive with error handling"""
        try:
            # Verify folder exists
            try:
                folder = self.drive_service.files().get(fileId=folder_id, fields='name').execute()
                logger.info(f"Uploading to folder: {folder.get('name', 'Unknown')}")
            except Exception as e:
                logger.warning(f"Could not verify folder {folder_id}: {str(e)}")
            
            # Upload file
            file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
            media = MediaFileUpload(file_path, mimetype='image/png')
            
            result = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            logger.info(f"Successfully uploaded {file_path} to Google Drive (ID: {result.get('id')})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload {file_path} to Google Drive: {str(e)}")
            return False
    
    def cleanup_file(self, file_path):
        """Remove local file with error handling"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted local file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete {file_path}: {str(e)}")
    
    def process_all_records(self):
        """Main processing loop with comprehensive error handling"""
        successful_count = 0
        failed_count = 0
        
        logger.info(f"Starting to process {len(self.records)} records")
        
        for i, record in enumerate(self.records, 1):
            url = record.get('Link', '').strip()
            folder_id = record.get('Link to folder', '').strip()
            client_name = record.get('Client', 'Unknown').strip()
            
            logger.info(f"Processing record {i}/{len(self.records)}: {client_name} - {url}")
            
            # Validate required fields
            if not url or not folder_id:
                logger.warning(f"Skipping record {i}: Missing URL or folder ID")
                failed_count += 1
                continue
            
            # Validate URL format
            try:
                parsed = urlparse(url)
                if not parsed.scheme or not parsed.netloc:
                    logger.warning(f"Skipping record {i}: Invalid URL format: {url}")
                    failed_count += 1
                    continue
            except Exception:
                logger.warning(f"Skipping record {i}: Could not parse URL: {url}")
                failed_count += 1
                continue
            
            # Take screenshot
            screenshot_path = self.take_screenshot(url, client_name)
            
            if screenshot_path:
                # Upload to Drive
                if self.upload_to_drive(screenshot_path, folder_id):
                    successful_count += 1
                else:
                    failed_count += 1
                
                # Clean up local file
                self.cleanup_file(screenshot_path)
            else:
                failed_count += 1
                logger.error(f"Failed to take screenshot for {url}")
            
            # Add delay between requests to be respectful
            time.sleep(random.uniform(1, 2))
        
        logger.info(f"Processing complete. Successful: {successful_count}, Failed: {failed_count}")
        return successful_count, failed_count
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
                logger.info("Selenium driver closed")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

def main():
    """Main execution function"""
    automation = None
    try:
        automation = ScreenshotAutomation()
        successful, failed = automation.process_all_records()
        
        print(f"\n=== SUMMARY ===")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total processed: {successful + failed}")
        
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise
    finally:
        if automation:
            automation.cleanup()

if __name__ == "__main__":
    main()