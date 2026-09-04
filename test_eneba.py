#!/usr/bin/env python3
"""Simulate Eneba login flow using the project's BrowserWorker."""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chromedriver_autoinstaller
cd_path = chromedriver_autoinstaller.install()

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


SAMPLE_USER = "testuser_example@example.com"
SAMPLE_PASS = "TestPassword123!"
TARGET_URL = "https://my.eneba.com/login"


class SimpleBrowser:
    def __init__(self):
        self._driver = None

    async def start(self):
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,720")
        options.add_argument("--headless=new")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        service = Service(executable_path="/usr/bin/chromedriver")
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.set_page_load_timeout(30)
        self._driver.implicitly_wait(5)
        return True

    async def stop(self):
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    async def navigate(self, url):
        self._driver.get(url)
        for _ in range(15):
            try:
                if self._driver.execute_script("return document.readyState") == "complete":
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return True

    async def screenshot(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = self._driver.get_screenshot_as_png()
        with open(path, "wb") as f:
            f.write(data)
        print(f"  -> Saved: {path}")

    async def find(self, selector):
        from selenium.webdriver.common.by import By
        try:
            return self._driver.find_element(By.CSS_SELECTOR, selector)
        except Exception:
            return None

    async def type_text(self, selector, text):
        elem = await self.find(selector)
        if not elem:
            return False
        elem.clear()
        elem.send_keys(text)
        return True

    async def click(self, selector):
        elem = await self.find(selector)
        if not elem:
            return False
        elem.click()
        return True

    async def dom_elements(self, max_el=50):
        js = """
        var MAX = arguments[0] || 50;
        var selectors = {};
        function addEl(el, sel) {
            if (!el || !sel || selectors[sel]) return;
            var tag = el.tagName ? el.tagName.toLowerCase() : '';
            if (['script','style','noscript','link','meta'].indexOf(tag) >= 0) return;
            selectors[sel] = {
                tag: tag, id: el.id || '', name: el.name || '',
                type: el.type || '', placeholder: el.placeholder || '',
                aria_label: el.getAttribute('aria-label') || '',
                text: (el.textContent || '').trim().substring(0, 100),
                role: el.getAttribute('role') || '',
                css_selector: sel
            };
        }
        function getSelector(el) {
            if (el.id) return '#' + el.id;
            if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
            var path = [];
            while (el && el.nodeType === 1) {
                var sel = el.tagName.toLowerCase();
                if (el.id) { path.unshift('#' + el.id); break; }
                if (el.className) sel += '.' + el.className.trim().split(/\\s+/).join('.');
                path.unshift(sel);
                el = el.parentElement;
            }
            return path.join(' > ');
        }
        document.querySelectorAll('input[type=text],input[type=email],input[type=tel],input[type=password],input:not([type]),button[type=submit],button,button[role=button],a[href]').forEach(function(el) {
            addEl(el, getSelector(el));
        });
        var result = [];
        var keys = Object.keys(selectors);
        for (var i = 0; i < Math.min(keys.length, MAX); i++) {
            result.push(selectors[keys[i]]);
        }
        return result;
        """
        return self._driver.execute_script(js, max_el) or []

    async def detect_captcha(self):
        source = self._driver.page_source.lower()
        indicators = ["captcha", "recaptcha", "hcaptcha", "cf-challenge",
                      "cloudflare", "g-recaptcha", "verify you are human",
                      "unusual traffic", "security check"]
        return any(ind in source for ind in indicators)

    @property
    def url(self):
        return self._driver.current_url if self._driver else ""

    @property
    def title(self):
        return self._driver.title if self._driver else ""


async def main():
    browser = SimpleBrowser()

    print("=" * 60)
    print("ENEBA LOGIN SIMULATION")
    print(f"User: {SAMPLE_USER}")
    print(f"URL:  {TARGET_URL}")
    print("=" * 60)

    # 1. Start browser
    print("\n[1/7] Starting headless Chromium...")
    await browser.start()
    print("  -> Browser started")

    # 2. Navigate to Eneba login
    print(f"\n[2/7] Navigating to {TARGET_URL}...")
    await browser.navigate(TARGET_URL)
    await asyncio.sleep(3)
    print(f"  -> Landed on: {browser.url}")
    print(f"  -> Title: {browser.title}")

    # 3. Screenshot before
    print("\n[3/7] Taking screenshot (initial)...")
    await browser.screenshot("img/eneba_01_initial.png")

    # 4. Collect DOM
    print("\n[4/7] Collecting DOM elements...")
    elements = await browser.dom_elements(60)
    print(f"  -> Found {len(elements)} elements:")
    for el in elements[:20]:
        tag = el.get("tag", "?")
        sel = el.get("css_selector", "")[:55]
        desc = el.get("name") or el.get("placeholder") or el.get("aria_label") or el.get("id") or el.get("text", "")[:40]
        print(f"     {tag:8s} | {sel:55s} | {desc}")

    # 5. Fill email
    print("\n[5/7] Filling email field...")
    email_sels = [
        'input[name="email"]', 'input[type="email"]',
        'input[name="username"]', 'input[name="login"]',
        'input[placeholder*="mail"]', 'input[placeholder*="user"]',
        'input[aria-label*="mail"]', '#email', '#username',
    ]
    filled = False
    for sel in email_sels:
        if await browser.type_text(sel, SAMPLE_USER):
            print(f"  -> Email typed into: {sel}")
            filled = True
            break
    if not filled:
        for el in elements:
            if el.get("tag") == "input" and el.get("type") in ("text", "email", "tel", ""):
                sel = el.get("css_selector", "")
                if sel and await browser.type_text(sel, SAMPLE_USER):
                    print(f"  -> Email typed into: {sel}")
                    filled = True
                    break
    if not filled:
        print("  -> WARNING: Email field not found")

    await browser.screenshot("img/eneba_02_email.png")

    # 6. Fill password
    print("\n[6/7] Filling password field...")
    pass_sels = [
        'input[name="password"]', 'input[type="password"]',
        'input[placeholder*="ass"]', '#password',
    ]
    filled = False
    for sel in pass_sels:
        if await browser.type_text(sel, SAMPLE_PASS):
            print(f"  -> Password typed into: {sel}")
            filled = True
            break
    if not filled:
        print("  -> Password field not found")

    await browser.screenshot("img/eneba_03_password.png")

    # 7. Find and click submit
    print("\n[7/7] Looking for submit button...")
    elements2 = await browser.dom_elements(60)
    clicked = False
    for el in elements2:
        tag = el.get("tag", "")
        text = el.get("text", "").lower()
        if tag in ("button", "input", "a") and any(w in text for w in ["log", "sign", "enter", "go", "submit"]):
            sel = el.get("css_selector", "")
            if sel:
                print(f"  -> Clicking: {sel} ('{el.get('text', '')[:30]}')")
                await browser.click(sel)
                clicked = True
                break
    if not clicked:
        print("  -> Submit button not found, trying Enter key...")
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.by import By
        try:
            pwd = browser._driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
            pwd.send_keys(Keys.RETURN)
            print("  -> Pressed Enter on password field")
        except Exception:
            print("  -> Could not submit")

    await asyncio.sleep(4)

    await browser.screenshot("img/eneba_04_after_submit.png")

    print(f"\n  Final URL: {browser.url}")
    print(f"  Final Title: {browser.title}")

    captcha = await browser.detect_captcha()
    if captcha:
        print("  WARNING: CAPTCHA detected!")
    else:
        print("  No CAPTCHA detected")

    # Page source snippet
    try:
        src = browser._driver.page_source[:500]
        print(f"\n  Page snippet:\n  {src[:300]}...")
    except Exception:
        pass

    await browser.stop()
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
