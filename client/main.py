from __future__ import annotations

import asyncio
import logging
import time

import httpx

from client.api_client import APIClient
from client.config import ClientConfig
from client.ui import (
    confirm_action,
    get_input,
    print_error,
    print_events,
    print_header,
    print_result,
    print_status,
    print_task_state,
)

logger = logging.getLogger(__name__)


async def run_client() -> None:
    print_header()

    config = ClientConfig.from_env()
    client = APIClient(config)

    print_status(f"Connecting to {config.api_url}...")

    try:
        health = await client.health()
        print_status(f"Backend connected. Status: {health.get('status', 'unknown')}")
    except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
        print_error(f"Cannot connect to backend: {e}")
        print_error("Make sure the backend is running: uvicorn backend.main:app --reload")
        return

    print()
    target_url = get_input("Target URL (authorized site): ").strip()
    if not target_url:
        print_error("URL is required")
        return

    username = get_input("Username: ").strip()
    if not username:
        print_error("Username is required")
        return

    password = get_input("Password: ", secure=True).strip()
    if not password:
        print_error("Password is required")
        return

    instruction = get_input("Instruction (optional, Enter for default): ").strip()
    if not instruction:
        instruction = "Log in with the provided credentials"

    print()
    print_status(f"Target: {target_url}")
    print_status(f"Username: {username}")
    print_status("Password: [hidden]")

    if not confirm_action("\nSubmit task?"):
        print_status("Cancelled.")
        return

    try:
        print_status("Creating task...")
        task = await client.create_task(target_url, username, password, instruction)
        task_id = task["task_id"]
        print_status(f"Task created: {task_id}")

        if task.get("preview_url"):
            print_status(f"Preview: {config.api_url}{task['preview_url']}")

        print()
        last_state = None
        max_wait = 300
        start = time.time()

        while time.time() - start < max_wait:
            await asyncio.sleep(2)

            try:
                task_info = await client.get_task(task_id)
            except (httpx.HTTPError, OSError) as e:
                logger.debug("Poll error (retrying): %s", e)
                continue

            state = task_info.get("state", "UNKNOWN")
            if state != last_state:
                print_task_state(state)
                last_state = state

            if state == "WAITING_FOR_MANUAL_ACTION":
                print_status("Manual action required. Please complete the action in the browser.")
                print_status(f"Preview: {config.api_url}{task.get('preview_url', '')}")
                if confirm_action("Resume automation?"):
                    try:
                        await client.manual_action(task_id)
                        print_status("Resumed.")
                    except (httpx.HTTPError, OSError) as e:
                        print_error(f"Failed to resume: {e}")

            if state in ("SUCCESS", "FAILURE", "STOPPED", "TIMEOUT"):
                break

        print()
        print_result(f"Final state: {state}")

        if task_info.get("reason"):
            print_result(f"Reason: {task_info['reason']}")

        events = await client.get_events(task_id)
        print_events(events)

        if state == "SUCCESS" and confirm_action("Save screenshot?"):
                print_result("Screenshot saved in img/ directory on server")

    except KeyboardInterrupt:
        print_status("\nInterrupted. Stopping task...")
        try:
            await client.stop_task(task_id)
        except (httpx.HTTPError, OSError) as e:
            logger.debug("Stop task error (ignored): %s", e)
    except (httpx.HTTPError, OSError, ValueError) as e:
        print_error(f"Error: {e}")


def main() -> None:
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
