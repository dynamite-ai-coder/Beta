from __future__ import annotations

import asyncio
import logging
import signal
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from urllib.parse import urlparse

from client.config import ClientConfig
from client.ui import print_header, print_status, print_error
from client.websocket_client import WebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CREDENTIALS_FILE_PATH: str | None = None
TARGET_URL: str | None = None


def _pick_credentials() -> tuple[str, list[tuple[str, str]]]:
    root = tk.Tk()
    root.title("Beta Client - Credentials")
    root.geometry("480x220")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    result: dict[str, object] = {}

    tk.Label(root, text="Login URL:", font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(16, 0))
    url_var = tk.StringVar(value="https://")
    url_entry = tk.Entry(root, textvariable=url_var, width=56, font=("Segoe UI", 10))
    url_entry.pack(padx=16, pady=(2, 8))
    url_entry.focus_set()

    tk.Label(root, text="Credentials file (user:pass per line):", font=("Segoe UI", 10)).pack(anchor="w", padx=16)
    file_frame = tk.Frame(root)
    file_frame.pack(fill="x", padx=16, pady=(2, 12))

    file_var = tk.StringVar(value="No file selected")
    tk.Label(file_frame, textvariable=file_var, width=40, anchor="w", font=("Segoe UI", 9)).pack(side="left")

    pairs_list: list[tuple[str, str]] = []

    def browse():
        nonlocal pairs_list
        path = filedialog.askopenfilename(
            title="Select credentials file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
            pairs = []
            for line in lines:
                if ":" not in line:
                    continue
                user, passw = line.split(":", 1)
                if user.strip() and passw.strip():
                    pairs.append((user.strip(), passw.strip()))
            if not pairs:
                messagebox.showerror("Error", "File contains no valid user:pass pairs.")
                return
            pairs_list = pairs
            file_var.set(f"{path} ({len(pairs)} accounts)")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot read file:\n{e}")

    tk.Button(file_frame, text="Browse...", command=browse, font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

    def on_submit():
        url = url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "URL cannot be empty.")
            return
        if not pairs_list:
            messagebox.showerror("Error", "Select a credentials file first.")
            return
        parsed = urlparse(url)
        if not parsed.scheme:
            url = "https://" + url
        result["url"] = url
        result["pairs"] = pairs_list
        root.destroy()

    tk.Button(root, text="Start", command=on_submit, width=14, font=("Segoe UI", 10, "bold")).pack(pady=(0, 16))

    root.protocol("WM_DELETE_WINDOW", lambda: (result.clear(), root.destroy()))
    root.mainloop()

    if not result:
        print_error("Cancelled.")
        sys.exit(0)

    return str(result["url"]), list(result["pairs"])  # type: ignore[arg-type]


def submit_task(config: ClientConfig, url: str, username: str, password: str) -> str | None:
    import json
    import urllib.request
    import urllib.error

    task_url = f"{config.backend_url}/api/v1/task"
    headers = {"Content-Type": "application/json"}
    if config.client_token:
        headers["Authorization"] = f"Bearer {config.client_token}"

    payload = json.dumps({
        "target_url": url,
        "username": username,
        "password": password,
        "natural_language_instruction": "Log in with the provided credentials",
    }).encode()

    try:
        req = urllib.request.Request(task_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            task_id = data.get("task_id", "")
            print_status(f"Task created for {username}: {task_id}")
            return task_id
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print_error(f"Failed to create task ({e.code}): {body}")
        return None
    except Exception as e:
        print_error(f"Cannot reach backend: {e}")
        return None


async def main() -> None:
    config = ClientConfig.from_env()
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))

    logger.info(f"Starting Windows Browser Agent: {config.client_id}")
    logger.info(f"Backend: {config.backend_url}")

    url, pairs = _pick_credentials()

    print_status(f"Loaded {len(pairs)} account(s). Creating tasks on backend...")
    for user, passw in pairs:
        submit_task(config, url, user, passw)

    client = WebSocketClient(config, on_task=lambda m: None)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(client.disconnect()))
        except NotImplementedError:
            pass

    try:
        await client.connect()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await client.disconnect()
        logger.info("Agent stopped")


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
