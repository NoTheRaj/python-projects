# ================================================================
#  core/browser_controller.py
#  Controls Chrome. Same in V1 and V2 — don't modify when upgrading.
# ================================================================

import time, os, logging
from selenium import webdriver
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import sys
sys.path.insert(0, r"C:\swayam_bot")
import config

logger = logging.getLogger(__name__)


class BrowserController:

    def __init__(self):
        self.driver = None
        self._tabs  = {}    # name → window handle

    def launch(self):
    
        opts = uc.ChromeOptions()
        temp_profile = r"C:\swayam_bot\chrome_session"
        os.makedirs(temp_profile, exist_ok=True)
        opts.add_argument(f"--user-data-dir={temp_profile}")
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")

        self.driver = uc.Chrome(options=opts)
        logger.info("Chrome launched with undetected-chromedriver.")
        return self

    def quit(self):
        if self.driver:
            self.driver.quit()
            logger.info("Browser closed.")

    # ── Tab helpers ───────────────────────────────────────────────

    def name_current_tab(self, name):
        """Give the current tab a label so we can switch back to it later."""
        self._tabs[name] = self.driver.current_window_handle

    def open_tab(self, url, name):
        """Open a new tab, go to url, remember it by name."""
        self.driver.execute_script("window.open('');")
        new_handle = [h for h in self.driver.window_handles
                      if h not in self._tabs.values()][-1]
        self._tabs[name] = new_handle
        self.driver.switch_to.window(new_handle)
        self.driver.get(url)
        time.sleep(config.PAGE_LOAD_WAIT)
        logger.info(f"Opened tab '{name}'")

    def switch_to(self, name):
        """Switch focus to a named tab."""
        self.driver.switch_to.window(self._tabs[name])

    # ── Navigation helpers ────────────────────────────────────────

    def go(self, url):
        self.driver.get(url)
        time.sleep(config.PAGE_LOAD_WAIT)

    def find(self, by, value, timeout=None):
        """Wait until element exists, then return it."""
        t = timeout or config.ELEMENT_WAIT
        return WebDriverWait(self.driver, t).until(
            EC.presence_of_element_located((by, value)))

    def find_clickable(self, by, value, timeout=None):
        """Wait until element is clickable, then return it."""
        t = timeout or config.ELEMENT_WAIT
        return WebDriverWait(self.driver, t).until(
            EC.element_to_be_clickable((by, value)))

    def click(self, by, value, timeout=None):
        el = self.find_clickable(by, value, timeout)
        el.click()
        time.sleep(0.5)
        return el

    def safe_find(self, by, value, timeout=5):
        """Return element or None if not found — never raises an error."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value)))
        except TimeoutException:
            return None

    def scroll_to(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
        time.sleep(0.3)

    def js_click(self, element):
        """Click via JavaScript — more reliable than .click() for hidden elements."""
        self.driver.execute_script("arguments[0].click();", element)

    def screenshot(self, name):
        if config.SCREENSHOT_ON_ERROR:
            os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
            path = os.path.join(config.SCREENSHOTS_DIR, f"{name}.png")
            self.driver.save_screenshot(path)
            logger.info(f"Screenshot saved → {path}")