from __future__ import annotations

import logging
import os

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from backend.config import settings

logger = logging.getLogger(__name__)

CHROMIUM_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
]

CHROMEDRIVER_PATHS = [
    "/usr/bin/chromedriver",
    "/usr/local/bin/chromedriver",
    "/usr/lib/chromium-browser/chromedriver",
]


def find_browser_executable() -> str:
    if settings.browser_executable and os.path.exists(settings.browser_executable):
        return settings.browser_executable

    for path in CHROMIUM_PATHS:
        if os.path.exists(path):
            return path

    from shutil import which
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = which(name)
        if found:
            return found

    raise RuntimeError("No Chromium/Chrome browser found. Install chromium-browser.")


def find_chromedriver() -> str | None:
    for path in CHROMEDRIVER_PATHS:
        if os.path.exists(path):
            return path

    from shutil import which
    found = which("chromedriver")
    if found:
        return found

    return None


def create_browser() -> WebDriver:
    options = Options()
    options.add_argument("--headless=new" if settings.headless else "")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--user-data-dir=/tmp/chrome-profile")

    browser_path = find_browser_executable()
    options.binary_location = browser_path

    driver_path = find_chromedriver()
    service = Service(executable_path=driver_path) if driver_path else Service()

    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(5)

    logger.info("Browser started: %s", browser_path)
    return driver


def navigate_safe(driver: WebDriver, url: str, timeout: int = 30) -> bool:
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        return True
    except (WebDriverException, TimeoutException) as e:
        logger.error("Navigation failed: %s", e)
        return False


def take_screenshot(driver: WebDriver) -> bytes:
    return driver.get_screenshot_as_png()


def collect_dom_elements(driver: WebDriver, max_elements: int = 80) -> list[dict]:
    script = """
    const elements = [];
    const selectors = [
        'input[type="text"]', 'input[type="email"]', 'input[type="tel"]',
        'input[type="password"]', 'input:not([type])',
        'button[type="submit"]', 'button', 'input[type="submit"]',
        'a[href*="login"]', 'a[href*="sign"]',
        '[role="button"]', '[role="textbox"]',
        '[aria-label]', '[placeholder]'
    ];
    const seen = new Set();
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (seen.has(el) || elements.length >= MAX) continue;
            seen.add(el);
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            let cssSel = '';
            try {
                if (el.id) cssSel = '#' + CSS.escape(el.id);
                else if (el.name) cssSel = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                else {
                    let path = [];
                    let current = el;
                    while (current && current !== document.body) {
                        let selector = current.tagName.toLowerCase();
                        if (current.id) { selector = '#' + CSS.escape(current.id); path.unshift(selector); break; }
                        if (current.className && typeof current.className === 'string') {
                            const cls = current.className.trim().split(/\\s+/).filter(c => c && !c.includes('--')).slice(0,2).map(c => '.' + c).join('');
                            selector += cls;
                        }
                        path.unshift(selector);
                        current = current.parentElement;
                    }
                    cssSel = path.join(' > ');
                }
            } catch(e) {}
            let xpath = '';
            try {
                const xp = document.evaluate('absoluteXPath' , el, null, 0, null);
            } catch(e) {}
            const labels = [];
            if (el.id) {
                const lbl = document.querySelector('label[for="' + el.id + '"]');
                if (lbl) labels.push(lbl.textContent.trim());
            }
            let parent = el.parentElement;
            for (let i = 0; i < 3 && parent; i++) {
                const lbl = parent.querySelector('label');
                if (lbl && lbl.textContent.trim()) labels.push(lbl.textContent.trim());
                parent = parent.parentElement;
            }
            elements.push({
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                name: el.getAttribute('name') || null,
                type: el.getAttribute('type') || null,
                placeholder: el.getAttribute('placeholder') || null,
                aria_label: el.getAttribute('aria-label') || null,
                text: (el.textContent || '').trim().substring(0, 100) || null,
                role: el.getAttribute('role') || null,
                css_selector: cssSel || null,
                xpath: null,
                nearby_labels: labels.length ? labels : null,
            });
        }
    }
    return elements;
    """.replace("MAX", str(max_elements))

    try:
        result = driver.execute_script(script)
        return result if result else []
    except (WebDriverException, TypeError, KeyError) as e:
        logger.error("DOM collection failed: %s", e)
        return []


def detect_captcha(driver: WebDriver) -> bool:
    captcha_indicators = [
        "captcha", "recaptcha", "hcaptcha", "cf-challenge",
        "verify you are human", "unusual traffic", "access denied",
        "rate limit", "security check", "please wait", "cloudflare",
        "challenge-platform", "g-recaptcha", "h-captcha",
    ]
    try:
        page_source = driver.page_source.lower()
        for indicator in captcha_indicators:
            if indicator in page_source:
                return True

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            title = iframe.get_attribute("title") or ""
            if any(ind in (src + title).lower() for ind in ["captcha", "recaptcha", "hcaptcha", "challenge"]):
                return True
    except (WebDriverException, AttributeError) as e:
        logger.debug("CAPTCHA detection error (ignored): %s", e)
    return False
