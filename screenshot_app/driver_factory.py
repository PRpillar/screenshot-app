import os
import random
import logging

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import InvalidArgumentException
from webdriver_manager.chrome import ChromeDriverManager

try:
    import undetected_chromedriver as uc
except Exception:  # pragma: no cover - optional dependency
    uc = None


def create_chrome_driver(headless: bool = True):
    logger = logging.getLogger("screenshot_app.driver")
    # Flags safe for CI containers and local use
    common_args = [
        "--disable-extensions",
        "--disable-plugins",
        "--page-load-strategy=eager",
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    # Randomize basic fingerprint bits
    accept_lang = os.getenv("BROWSER_ACCEPT_LANGUAGE", random.choice(["en-US,en;q=0.9","en-GB,en;q=0.9","en,en-US;q=0.8"]))
    ua = os.getenv("BROWSER_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/" + str(random.randint(120, 141)) + ".0.0.0 Safari/537.36")

    # Allow disabling UC via env (more stable in CI)
    disable_uc = os.getenv("DISABLE_UC", "false").lower() in ("1", "true", "yes")

    # Attempt using undetected-chromedriver first (unless disabled)
    if uc is not None and not disable_uc:
        try:
            uc_options = uc.ChromeOptions()
            if headless:
                uc_options.add_argument("--headless=new")
            for arg in common_args:
                uc_options.add_argument(arg)
            uc_options.add_argument(f"--user-agent={ua}")
            uc_options.add_argument(f"--accept-language={accept_lang}")
            driver = uc.Chrome(options=uc_options, use_subprocess=True)
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)
            logger.info("Using undetected-chromedriver")
            return driver
        except InvalidArgumentException:
            pass
        except Exception:
            pass

    # Fallback to vanilla Selenium
    options = Options()
    if headless:
        # Use new headless for modern Chrome, falls back if unsupported
        options.add_argument("--headless=new")
    for arg in common_args:
        options.add_argument(arg)
    options.add_argument(f"--user-agent={ua}")
    options.add_argument(f"--accept-language={accept_lang}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, \"webdriver\", {get: () => undefined})"},
        )
    except Exception:
        pass

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    logger.warning("Falling back to vanilla Selenium driver; UC unavailable or failed")
    return driver


