#!/usr/bin/env python3
"""Eneba login with stealth Selenium + proxy + Xvfb."""
import time, os, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

PROXY = "http://01a03626-786e-79a1-9d39-8d77a7fcf978:01a03626-786e-79a1-9d39-8d77a8bb0953@proxy-us.proxy-cheap.com:5959"
EMAIL = "testuser_example@example.com"
PASS = "TestPassword123!"

opts = Options()
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
opts.add_argument("--window-size=1280,720")
opts.add_argument(f"--proxy-server={PROXY}")
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option("useAutomationExtension", False)
opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
opts.binary_location = "/usr/bin/chromium-browser"

service = Service(executable_path="/usr/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=opts)
driver.set_page_load_timeout(25)
driver.implicitly_wait(5)

# Stealth patches
stealth_js = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = {runtime: {}};
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})

os.makedirs("img", exist_ok=True)

print("[1] Navigate...", flush=True)
driver.get("https://my.eneba.com/login")
time.sleep(4)
print(f"    URL: {driver.current_url}", flush=True)
print(f"    Title: {driver.title}", flush=True)
driver.save_screenshot("img/stealth_01.png")

print("[2] Fill email...", flush=True)
email = driver.find_element(By.CSS_SELECTOR, 'input[type="email"]')
email.clear()
email.send_keys(EMAIL)
driver.save_screenshot("img/stealth_02.png")

print("[3] Click password login...", flush=True)
for btn in driver.find_elements(By.TAG_NAME, "button"):
    if "hasła" in btn.text:
        btn.click()
        break
time.sleep(2)

print("[4] Fill password...", flush=True)
pwd = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
pwd.clear()
pwd.send_keys(PASS)
driver.save_screenshot("img/stealth_03.png")

print("[5] Submit...", flush=True)
for btn in driver.find_elements(By.TAG_NAME, "button"):
    txt = btn.text.strip().lower()
    if txt == "zaloguj się":
        btn.click()
        break

print("[6] Waiting for Cloudflare (30s)...", flush=True)
cleared = False
for i in range(30):
    time.sleep(1)
    try:
        src = driver.page_source.lower()
        if "verifying" not in src and "cloudflare" not in src and "turnstile" not in src:
            print(f"    Cleared after {i+1}s!", flush=True)
            cleared = True
            break
        if i % 5 == 0:
            print(f"    Verifying... ({i}s)", flush=True)
    except Exception as e:
        print(f"    Session issue at {i}s: {e}", flush=True)
        break

time.sleep(3)
try:
    driver.save_screenshot("img/stealth_04.png")
    print(f"    URL: {driver.current_url}", flush=True)
    print(f"    Title: {driver.title}", flush=True)
    body = driver.find_element(By.TAG_NAME, "body")
    text = body.text[:500]
    print(f"    Text: {text[:400]}", flush=True)
except Exception as e:
    print(f"    Error reading result: {e}", flush=True)

driver.quit()
print("DONE", flush=True)
