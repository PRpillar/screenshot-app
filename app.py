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
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)

    # Hide webdriver flag (best-effort)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
    except Exception:
        pass

    # --- helpers (kept inline for single-file simplicity) ---
    def is_error_page(drv) -> bool:
        try:
            url = drv.current_url or ""
        except Exception:
            url = ""
        if url.startswith("chrome-error://"):
            return True
        try:
            # Common Chrome net error page markers
            if drv.find_elements(By.ID, "main-frame-error"):
                return True
            if drv.find_elements(By.CSS_SELECTOR, ".error-code,.error-code span"):
                return True
            body_text = (drv.find_element(By.TAG_NAME, "body").text or "")[:2000]
            if "ERR_" in body_text or "This site can’t be reached" in body_text or "This site can't be reached" in body_text:
                return True
        except Exception:
            # If we cannot even query the DOM reliably, treat as error-ish signal
            return True
        return False

    def wait_page_or_error(drv, timeout=40):
        """Return 'ok' if page body present and not an error page; 'error' if Chrome error page detected."""
        end = time.time() + timeout
        last_err = None
        while time.time() < end:
            try:
                # body present?
                bodies = drv.find_elements(By.TAG_NAME, "body")
                if bodies:
                    if is_error_page(drv):
                        return "error"
                    # doc ready enough?
                    try:
                        rs = drv.execute_script("return document.readyState") or ""
                    except Exception:
                        rs = ""
                    if rs in ("interactive", "complete"):
                        return "ok"
                time.sleep(0.25)
            except Exception as e:
                last_err = e
                time.sleep(0.25)
        # Timeout of this loop: if we timed out but see an error page, return error, else None
        return "error" if is_error_page(drv) else None

    def reset_tab(drv):
        # Try to stop any loading / clear error state
        try:
            drv.execute_script("window.stop();")
        except Exception:
            pass
        try:
            drv.get("about:blank")
        except Exception:
            pass

    print("Beginning data parsing.")

    for index, record in enumerate(batch_records):
        url = record['Link']
        folder_id = record['Link to folder']

        nav_ok = False
        error_flag = False

        for attempt in range(1, 3):  # up to 2 tries
            try:
                start = time.time()
                driver.get(url)

                outcome = wait_page_or_error(driver, timeout=40)
                if outcome == "error":
                    error_flag = True
                    raise TimeoutException("Chrome network error page detected")
                if outcome is None:
                    raise TimeoutException("Navigation wait timed out")

                nav_ok = True
                error_flag = False
                break
            except (TimeoutException, WebDriverException) as e:
                if attempt == 2:
                    msg = "Connection error" if error_flag else "Timeout"
                    print(f"{msg} on {url}: {e}")
                    status_results.append([msg])
                else:
                    backoff = 3 * attempt
                    print(f"Retrying {url} in {backoff}s due to: {e}")
                    reset_tab(driver)
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
