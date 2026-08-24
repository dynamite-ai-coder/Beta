from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
    print_metrics,
    print_result,
    print_scheduled_tasks,
    print_status,
    print_task_state,
    print_tasks,
)

logger = logging.getLogger(__name__)


def load_credentials_from_file(filepath: str) -> list[dict]:
    """Load user:pass pairs from a .txt file.
    Format per line: email:password
    """
    creds = []
    if not os.path.exists(filepath):
        print_error(f"File not found: {filepath}")
        return creds

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                print_error(
                    f"Line {line_num}: invalid format "
                    f"(expected user:pass): {line}"
                )
                continue
            parts = line.split(":", 1)
            creds.append({
                "username": parts[0].strip(),
                "password": parts[1].strip(),
            })

    print_status(f"Loaded {len(creds)} credentials from file")
    return creds


async def cmd_run(client: APIClient, config: ClientConfig) -> None:
    target_url = get_input("Target URL: ").strip()
    if not target_url:
        print_error("URL is required")
        return

    file_path = get_input(
        "Credentials file (user:pass .txt) or Enter for manual: "
    ).strip()

    credentials = []
    if file_path:
        credentials = load_credentials_from_file(file_path)
        if not credentials:
            print_error("No valid credentials loaded")
            return
    else:
        username = get_input("Username: ").strip()
        if not username:
            print_error("Username is required")
            return
        password = get_input("Password: ", secure=True).strip()
        if not password:
            print_error("Password is required")
            return
        credentials = [{"username": username, "password": password}]

    instruction = get_input(
        "Instruction (optional): "
    ).strip() or "Log in with the provided credentials"

    for i, cred in enumerate(credentials):
        username = cred["username"]
        password = cred["password"]

        if len(credentials) > 1:
            print_status(
                f"\n--- [{i+1}/{len(credentials)}] "
                f"Testing: {username} ---"
            )

        print_status(f"Creating task for {username}...")
        task = await client.create_task(
            target_url, username, password, instruction
        )
        task_id = task["task_id"]
        print_status(f"Task created: {task_id}")

        if task.get("preview_url"):
            print_status(
                f"Preview: {config.api_url}{task['preview_url']}"
            )

        last_state = None
        max_wait = 300
        start = time.time()

        while time.time() - start < max_wait:
            await asyncio.sleep(2)
            try:
                task_info = await client.get_task(task_id)
            except (httpx.HTTPError, OSError) as e:
                logger.debug("Poll error: %s", e)
                continue

            state = task_info.get("state", "UNKNOWN")
            if state != last_state:
                print_task_state(state)
                last_state = state

            if state == "WAITING_FOR_MANUAL_ACTION":
                print_status("Manual action required.")
                if confirm_action("Resume?"):
                    await client.manual_action(task_id)
                    print_status("Resumed.")

            if state in ("SUCCESS", "FAILURE", "STOPPED", "TIMEOUT"):
                break

        print_result(
            f"Result for {username}: {state}"
        )
        if task_info.get("reason"):
            print_result(
                f"Reason: {task_info['reason']}"
            )

        events = await client.get_events(task_id)
        print_events(events)

        if len(credentials) > 1 and i < len(credentials) - 1:
            await asyncio.sleep(1)


async def cmd_list(client: APIClient) -> None:
    state_filter = get_input(
        "Filter by state (optional): "
    ).strip() or None
    tasks = await client.list_tasks(state=state_filter)
    print_tasks(tasks)


async def cmd_scheduled(client: APIClient) -> None:
    tasks = await client.list_scheduled_tasks()
    print_scheduled_tasks(tasks)


async def cmd_schedule_add(client: APIClient) -> None:
    name = get_input("Schedule name: ").strip()
    target_url = get_input("Target URL: ").strip()
    username = get_input("Username: ").strip()
    password = get_input("Password: ", secure=True).strip()
    instruction = get_input("Instruction: ").strip()
    cron = get_input("Cron expression: ").strip()

    result = await client.create_scheduled_task(
        name, target_url, username, password, instruction, cron
    )
    print_status(f"Scheduled: {result.get('task', {}).get('id')}")


async def cmd_schedule_delete(client: APIClient) -> None:
    task_id = get_input("Schedule ID: ").strip()
    await client.delete_scheduled_task(task_id)
    print_status("Deleted.")


async def cmd_metrics(client: APIClient) -> None:
    metrics = await client.get_metrics()
    print_metrics(metrics)


async def cmd_stop(client: APIClient) -> None:
    task_id = get_input("Task ID to stop: ").strip()
    await client.stop_task(task_id)
    print_status("Task stopped.")


async def run_interactive(
    client: APIClient, config: ClientConfig
) -> None:
    while True:
        print()
        print("Commands:")
        print("  1. Run automation task")
        print("  2. List tasks")
        print("  3. List scheduled tasks")
        print("  4. Add scheduled task")
        print("  5. Delete scheduled task")
        print("  6. View metrics")
        print("  7. Stop a task")
        print("  0. Exit")
        print()

        choice = get_input("Select command: ").strip()

        if choice == "1":
            await cmd_run(client, config)
        elif choice == "2":
            await cmd_list(client)
        elif choice == "3":
            await cmd_scheduled(client)
        elif choice == "4":
            await cmd_schedule_add(client)
        elif choice == "5":
            await cmd_schedule_delete(client)
        elif choice == "6":
            await cmd_metrics(client)
        elif choice == "7":
            await cmd_stop(client)
        elif choice == "0":
            break
        else:
            print_error("Invalid choice")


async def run_client() -> None:
    print_header()

    config = ClientConfig.from_env()
    client = APIClient(config)

    print_status(f"Connecting to {config.api_url}...")

    try:
        health = await client.health()
        print_status(
            f"Backend connected. Status: {health.get('status', 'unknown')}"
        )
    except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
        print_error(f"Cannot connect to backend: {e}")
        print_error("Run: uvicorn backend.main:app --reload")
        return

    await run_interactive(client, config)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browser Automation CLI Client"
    )
    parser.add_argument(
        "--mode",
        choices=["interactive", "run", "list", "metrics"],
        default="interactive",
        help="Client mode",
    )
    args = parser.parse_args()

    try:
        if args.mode == "interactive":
            asyncio.run(run_client())
        else:
            config = ClientConfig.from_env()
            client = APIClient(config)
            if args.mode == "run":
                asyncio.run(cmd_run(client, config))
            elif args.mode == "list":
                asyncio.run(cmd_list(client))
            elif args.mode == "metrics":
                asyncio.run(cmd_metrics(client))
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
