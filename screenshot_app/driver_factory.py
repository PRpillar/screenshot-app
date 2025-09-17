from typing import Optional

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
    common_args = [
        "--disable-extensions",
        "--disable-plugins",
        "--page-load-strategy=eager",
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-blink-features=AutomationControlled",
    ]

    # Attempt using undetected-chromedriver first
    if uc is not None:
        try:
            uc_options = uc.ChromeOptions()
            if headless:
                uc_options.add_argument("--headless=new")
            for arg in common_args:
                uc_options.add_argument(arg)
            driver = uc.Chrome(options=uc_options, use_subprocess=True)
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(10)
            return driver
        except InvalidArgumentException:
            pass
        except Exception:
            pass

    # Fallback to vanilla Selenium
    options = Options()
    if headless:
        options.add_argument("--headless")
    for arg in common_args:
        options.add_argument(arg)
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
    return driver


