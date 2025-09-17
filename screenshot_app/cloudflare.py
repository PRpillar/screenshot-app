import time
import uuid
from typing import List

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains


def is_cloudflare_verification(driver) -> bool:
    try:
        WebDriverWait(driver, 5).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "div.cf-browser-verification")
            or d.find_elements(By.XPATH, "//h1[contains(text(), 'Verify you are human')]")
            or d.find_elements(By.XPATH, "//iframe[contains(@src, 'challenges.cloudflare.com')]")
        )
        return True
    except TimeoutException:
        return False


def bypass_cloudflare_verification(driver, max_wait: int = 60) -> bool:
    end_time = time.time() + max_wait

    possible_selectors: List[str] = [
        "//button[contains(., 'Verify') and not(contains(@style,'display: none'))]",
        "//input[@type='button' and contains(@value, 'Verify')]",
        "//button[contains(., 'Continue')]",
        "//span[contains(text(), 'Verify')]/ancestor::button",
        "//label[contains(., 'Verify you are human')]",
    ]

    def try_click_in_iframes() -> bool:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            src = frame.get_attribute("src") or ""
            if "challenge" in src or "turnstile" in src or "hcaptcha" in src:
                try:
                    ActionChains(driver).move_to_element(frame).pause(0.3).click().perform()
                except Exception:
                    pass
                try:
                    driver.switch_to.frame(frame)
                    checkbox_like = driver.find_elements(
                        By.XPATH,
                        "//input[@type='checkbox'] | //div[contains(@class,'ctp-checkbox')] | //label",
                    )
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
            return True
        try:
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
            if not clicked:
                try_click_in_iframes()
        except Exception:
            pass
        time.sleep(3)
    return not is_cloudflare_verification(driver)


def debug_dump_cloudflare_page(driver, url: str):
    try:
        filename_safe = sanitize_filename(url, 50)
        dump_id = uuid.uuid4().hex[:8]
        html_path = f"cf_debug_{filename_safe}_{dump_id}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[DEBUG] Saved Cloudflare page HTML to {html_path}")
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"[DEBUG] Number of iframes detected: {len(frames)}")
        for idx, frame in enumerate(frames[:10]):
            print(f"    iframe #{idx}: src={frame.get_attribute('src')}")
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
                print(
                    f"        First element tag: {found[0].tag_name} class: {found[0].get_attribute('class')}"
                )
    except Exception as e:
        print(f"[DEBUG] Failed to dump Cloudflare page details: {e}")


def sanitize_filename(text: str, max_length: int = 100) -> str:
    invalid_characters = ["<", ">", ":", '"', "/", "\\", "|", "?", "*", " "]
    safe_text = "".join("_" if c in invalid_characters else c for c in text)
    if len(safe_text) > max_length:
        safe_text = safe_text[:max_length]
    return safe_text


