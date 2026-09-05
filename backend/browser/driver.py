from __future__ import annotations

import logging
import os
from typing import Any

from backend.config import settings
from backend.browser.proxy_manager import proxy_manager

logger = logging.getLogger(__name__)

CHROMIUM_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
]

_selenium_available = None
_uc_available = None


def _check_selenium() -> bool:
    global _selenium_available
    if _selenium_available is None:
        try:
            import selenium
            _selenium_available = True
        except ImportError:
            _selenium_available = False
            logger.warning("Selenium not available - browser automation disabled")
    return _selenium_available


def _check_uc() -> bool:
    global _uc_available
    if _uc_available is None:
        try:
            import undetected_chromedriver
            _uc_available = True
        except ImportError:
            _uc_available = False
    return _uc_available


def find_browser_executable() -> str:
    if settings.browser_executable:
        if os.path.exists(settings.browser_executable):
            return settings.browser_executable

    for path in CHROMIUM_PATHS:
        if os.path.exists(path):
            return path

    from shutil import which
    names = ("chromium", "chromium-browser", "google-chrome")
    for name in names:
        found = which(name)
        if found:
            return found

    raise RuntimeError("No Chromium/Chrome browser found.")


STEALTH_JS = """
// Override webdriver property
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Override chrome runtime
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({state: Notification.permission}) :
    originalQuery(parameters)
);

// Override plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Override languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Remove automation indicators
delete navigator.__proto__.webdriver;

// Override getOwnPropertyDescriptor
const originalGetOwnPropertyDescriptor = Object.getOwnPropertyDescriptor;
Object.getOwnPropertyDescriptor = function(obj, prop) {
    if (prop === 'webdriver') {
        return undefined;
    }
    return originalGetOwnPropertyDescriptor(obj, prop);
};
"""


def create_browser(proxy_url: str | None = None) -> Any:
    if not _check_selenium():
        raise RuntimeError(
            "Selenium not installed. Install with: pip install selenium"
        )

    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()

    if settings.headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--user-data-dir=/tmp/chrome-profile")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--js-flags=--max-old-space-size=512")
    options.add_argument("--disable-features=TranslateUI")
    options.add_argument("--disable-features=Translate")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-accelerated-2d-canvas")
    options.add_argument("--disable-gpu-compositing")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--lang=en-US,en")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    try:
        browser_path = find_browser_executable()
        options.binary_location = browser_path
    except RuntimeError as e:
        logger.warning("Browser not found: %s", e)

    effective_proxy = proxy_url
    if not effective_proxy:
        if settings.proxy_enabled and settings.proxy_url:
            effective_proxy = settings.proxy_url
        elif proxy_manager.enabled:
            entry = proxy_manager.get_next()
            if entry:
                effective_proxy = entry.url
                logger.info("Using rotating proxy: %s", entry.ip)
    if effective_proxy:
        options.add_argument(f"--proxy-server={effective_proxy}")
        logger.info("Proxy enabled: %s", effective_proxy.split("@")[-1] if "@" in effective_proxy else effective_proxy)

    driver = None
    if _check_uc():
        try:
            import undetected_chromedriver as uc
            driver = uc.Chrome(
                options=options,
                headless=settings.headless,
                version_main=None,
                use_subprocess=True,
            )
        except Exception as e:
            logger.warning(
                "undetected-chromedriver failed (%s), "
                "falling back to standard Chrome", e
            )

    if driver is None:
        from selenium import webdriver

        driver_path = None
        for p in [
            "/usr/bin/chromedriver",
            "/usr/local/bin/chromedriver",
        ]:
            if os.path.exists(p):
                driver_path = p
                break
        from shutil import which as _which
        if not driver_path:
            driver_path = _which("chromedriver")

        service = (
            Service(executable_path=driver_path)
            if driver_path
            else Service()
        )
        driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": STEALTH_JS
    })

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(5)

    logger.info("Browser started with stealth mode")
    return driver


def navigate_safe(
    driver: Any, url: str, timeout: int = 30
) -> bool:
    if not _check_selenium():
        return False
    from selenium.common.exceptions import WebDriverException, TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return document.readyState"
            )
            == "complete"
        )
        return True
    except (WebDriverException, TimeoutException) as e:
        logger.error("Navigation failed: %s", e)
        return False


def take_screenshot(driver: Any) -> bytes:
    return driver.get_screenshot_as_png()


JS_COLLECT_DOM = """
const elements = [];
const selectors = [
    'input[type="text"]', 'input[type="email"]',
    'input[type="tel"]', 'input[type="password"]',
    'input:not([type])', 'button[type="submit"]',
    'button', 'input[type="submit"]',
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
            if (el.id) {
                cssSel = '#' + CSS.escape(el.id);
            } else if (el.name) {
                cssSel = el.tagName.toLowerCase()
                    + '[name="' + el.name + '"]';
            } else {
                let path = [];
                let current = el;
                while (current && current !== document.body) {
                    let s = current.tagName.toLowerCase();
                    if (current.id) {
                        s = '#' + CSS.escape(current.id);
                        path.unshift(s);
                        break;
                    }
                    if (current.className
                        && typeof current.className === 'string'
                    ) {
                        const cls = current.className
                            .trim().split(/\\s+/)
                            .filter(c => c && !c.includes('--'))
                            .slice(0, 2)
                            .map(c => '.' + c).join('');
                        s += cls;
                    }
                    path.unshift(s);
                    current = current.parentElement;
                }
                cssSel = path.join(' > ');
            }
        } catch(e) {}
        let xpath = '';
        try {
            const xp = document.evaluate(
                'absoluteXPath', el, null, 0, null
            );
        } catch(e) {}
        const labels = [];
        if (el.id) {
            const lbl = document.querySelector(
                'label[for="' + el.id + '"]'
            );
            if (lbl) labels.push(lbl.textContent.trim());
        }
        let parent = el.parentElement;
        for (let i = 0; i < 3 && parent; i++) {
            const lbl = parent.querySelector('label');
            if (lbl && lbl.textContent.trim()) {
                labels.push(lbl.textContent.trim());
            }
            parent = parent.parentElement;
        }
        elements.push({
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            name: el.getAttribute('name') || null,
            type: el.getAttribute('type') || null,
            placeholder: el.getAttribute('placeholder') || null,
            aria_label: el.getAttribute('aria-label') || null,
            text: (el.textContent || '').trim()
                .substring(0, 100) || null,
            role: el.getAttribute('role') || null,
            css_selector: cssSel || null,
            xpath: null,
            nearby_labels: labels.length ? labels : null,
        });
    }
}
return elements;
"""


def collect_dom_elements(
    driver: Any, max_elements: int = 80
) -> list[dict]:
    if not _check_selenium():
        return []
    from selenium.common.exceptions import WebDriverException

    script = JS_COLLECT_DOM.replace("MAX", str(max_elements))
    try:
        result = driver.execute_script(script)
        return result if result else []
    except (WebDriverException, TypeError, KeyError) as e:
        logger.error("DOM collection failed: %s", e)
        return []


CAPTCHA_INDICATORS = [
    "captcha", "recaptcha", "hcaptcha", "cf-challenge",
    "verify you are human", "unusual traffic", "access denied",
    "rate limit", "security check", "please wait",
    "cloudflare", "challenge-platform", "g-recaptcha",
    "h-captcha",
]


def detect_captcha(driver: Any) -> bool:
    if not _check_selenium():
        return False
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By

    try:
        page_source = driver.page_source.lower()
        for indicator in CAPTCHA_INDICATORS:
            if indicator in page_source:
                return True

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            title = iframe.get_attribute("title") or ""
            combined = (src + title).lower()
            checks = ["captcha", "recaptcha", "hcaptcha"]
            if any(c in combined for c in checks):
                return True
    except (WebDriverException, AttributeError) as e:
        logger.debug("CAPTCHA detection error: %s", e)
    return False


def create_tor_browser() -> Any:
    """Create a Chromium instance routed through Tor SOCKS5 proxy."""
    tor_proxy = f"socks5://127.0.0.1:{settings.tor_socks_port}"
    return create_browser(proxy_url=tor_proxy)
