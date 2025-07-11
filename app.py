from google.oauth2.service_account import Credentials
import gspread
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidArgumentException, NoSuchElementException
# NEW: import undetected_chromedriver
try:
    import undetected_chromedriver as uc
except ImportError:
    uc = None  # Fallback handled later
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
from datetime import datetime
import json
import random
import time
from urllib.parse import urlparse
# NEW: ActionChains for frame clicking
from selenium.webdriver.common.action_chains import ActionChains
import uuid

DEBUG_CLOUDFLARE = os.getenv("DEBUG_CLOUDFLARE", "false").lower() in ("1", "true", "yes")

# ---------------- Selenium driver factory -----------------

def create_chrome_driver(headless: bool = True):
    """Return a configured Chrome WebDriver instance, with automatic fallback.

    Prefers undetected_chromedriver (uc) when installed; if uc fails or is not
    present, falls back to the regular Selenium driver.
    """
    common_args = [
        "--disable-extensions",
        "--disable-plugins",
        "--page-load-strategy=eager",
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-blink-features=AutomationControlled",
    ]

    # -------- Attempt #1: undetected-chromedriver --------
    if uc is not None:
        try:
            uc_options = uc.ChromeOptions()
            if headless:
                uc_options.add_argument("--headless=new")
            for arg in common_args:
                uc_options.add_argument(arg)
            # NOTE: uc already takes care of excludeSwitches / useAutomationExtension
            driver = uc.Chrome(options=uc_options, use_subprocess=True)
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)
            return driver
        except InvalidArgumentException as uc_err:
            # uc produced an invalid option for the current Chrome version – fall back
            print(f"undetected-chromedriver failed ({uc_err}); falling back to regular Selenium driver...")
        except Exception as uc_generic_err:
            print(f"undetected-chromedriver failed ({uc_generic_err}); falling back...")

    # -------- Fallback: regular Selenium driver --------
    options = Options()
    if headless:
        options.add_argument("--headless")
    for arg in common_args:
        options.add_argument(arg)
    # Anti-detection tweaks supported by vanilla Chrome
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    # hide webdriver flag
    try:
        driver.execute_cdp_cmd(
            'Page.addScriptToEvaluateOnNewDocument',
            {'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'}
        )
    except Exception:
        pass

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    return driver

# ---------------- End driver factory -----------------


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
        config_sheet.update("B2", [["0"]])
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
        config_sheet.update("B2", [["0"]])
        return True
    print("Done.")

    batch_records = all_records[start_row:end_row]
    print(f"Processing batch: rows {start_row} to {end_row - 1}")

    # For debugging
    status_results = []

    print("Preparing Selenium...")
    # Generate Selenium driver (using undetected-chromedriver when available)
    driver = create_chrome_driver(headless=True)
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

            time.sleep(random.uniform(5, 10))
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

        if is_cloudflare_verification(driver):
            # Attempt to bypass Cloudflare banner automatically
            if not bypass_cloudflare_verification(driver):
                if DEBUG_CLOUDFLARE:
                    debug_dump_cloudflare_page(driver, url)
                status = "Cloudflare verification detected"
                print(f"Cloudflare detected on {url} and could not be bypassed")
                status_results.append([status])
                continue

        try:
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
        config_sheet.update("B2", [["0"]])
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

def is_cloudflare_verification(driver):
    """Return True if the current page appears to be a Cloudflare challenge."""
    try:
        WebDriverWait(driver, 5).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, 'div.cf-browser-verification') or
                      d.find_elements(By.XPATH, "//h1[contains(text(), 'Verify you are human')]") or
                      d.find_elements(By.XPATH, "//iframe[contains(@src, 'challenges.cloudflare.com')]")
        )
        return True
    except TimeoutException:
        return False

def bypass_cloudflare_verification(driver, max_wait=60):
    """Attempt to automatically bypass Cloudflare \"Verify you are human\" banner.

    The function tries to click on common verification buttons or simply waits
    for Cloudflare to redirect if the challenge is passive. Returns True if the
    banner disappears within the given timeout, otherwise False.
    """
    end_time = time.time() + max_wait

    # Common XPATH selectors that appear on Cloudflare verification pages
    possible_selectors = [
        "//button[contains(., 'Verify') and not(contains(@style,'display: none'))]",
        "//input[@type='button' and contains(@value, 'Verify')]",
        "//button[contains(., 'Continue')]",
        "//span[contains(text(), 'Verify')]/ancestor::button",
        "//label[contains(., 'Verify you are human')]",
    ]

    # Attempt clicking inside potential iframes (Cloudflare Turnstile / hCaptcha)
    def try_click_in_iframes():
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            src = frame.get_attribute("src") or ""
            if "challenge" in src or "turnstile" in src or "hcaptcha" in src:
                try:
                    # Attempt to click the centre of the iframe to trigger checkbox
                    ActionChains(driver).move_to_element(frame).pause(0.3).click().perform()
                except Exception:
                    pass
                try:
                    driver.switch_to.frame(frame)
                    # search for checkbox type input or label
                    checkbox_like = driver.find_elements(By.XPATH, "//input[@type='checkbox'] | //div[contains(@class,'ctp-checkbox')] | //label")
                    if checkbox_like:
                        try:
                            ActionChains(driver).move_to_element(checkbox_like[0]).pause(0.2).click().perform()
                            driver.switch_to.default_content()
                            return True
                        except Exception:
                            pass
                    driver.switch_to.default_content()
                except Exception:
                    driver.switch_to.default_content()
        return False

    while time.time() < end_time:
        if not is_cloudflare_verification(driver):
            return True  # banner gone

        try:
            # First try on main document
            clicked = False
            for sel in possible_selectors:
                elements = driver.find_elements(By.XPATH, sel)
                if elements:
                    try:
                        elements[0].click()
                        clicked = True
                    except Exception:
                        pass
                    break

            # If not clicked, try inside iframes
            if not clicked:
                try_click_in_iframes()
        except Exception:
            pass

        time.sleep(3)  # Give page a moment to update

    return not is_cloudflare_verification(driver)


def debug_dump_cloudflare_page(driver, url: str):
    """Dump the current page source and basic Cloudflare info to help with debugging."""
    try:
        filename_safe = sanitize_filename(url, 50)
        dump_id = uuid.uuid4().hex[:8]
        html_path = f"cf_debug_{filename_safe}_{dump_id}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[DEBUG] Saved Cloudflare page HTML to {html_path}")

        # Provide quick stats in the log
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"[DEBUG] Number of iframes detected: {len(frames)}")
        for idx, frame in enumerate(frames[:10]):
            print(f"    iframe #{idx}: src={frame.get_attribute('src')}")

        # List first 1-2 matching selectors (if any)
        candidates = [
            "//input[@type='checkbox']",
            "//div[contains(@class,'ctp-checkbox')]",
            "//button[contains(., 'Verify')]",
            "//label[contains(., 'Verify')]",
        ]
        for sel in candidates:
            found = driver.find_elements(By.XPATH, sel)
            if found:
                print(f"[DEBUG] Selector '{sel}' returned {len(found)} element(s)")
                print(f"        First element tag: {found[0].tag_name} class: {found[0].get_attribute('class')}")
    except Exception as e:
        print(f"[DEBUG] Failed to dump Cloudflare page details: {e}")


if __name__ == "__main__":
    done = main()
    if done:
        exit(0)
    else:
        exit(100) # Github rerun signal
