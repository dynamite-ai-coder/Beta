from __future__ import annotations

import sys


def print_header() -> None:
    print("=" * 60)
    print("  Browser Automation Client")
    print("  Authorized testing tool - use only on owned accounts")
    print("=" * 60)
    print()


def print_status(message: str) -> None:
    print(f"[STATUS] {message}")


def print_error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)


def print_result(message: str) -> None:
    print(f"[RESULT] {message}")


def print_events(events: list[dict]) -> None:
    if events:
        print("\n--- Task Events ---")
        for ev in events:
            ts = ev.get("timestamp", "")
            ev_name = ev.get("event", "")
            data = ev.get("data", "")
            print(f"  [{ts}] {ev_name}: {data}")
        print("---")


def get_input(prompt: str, secure: bool = False) -> str:
    if secure:
        import getpass
        return getpass.getpass(prompt)
    return input(prompt)


def confirm_action(message: str) -> bool:
    response = input(f"{message} [y/N]: ").strip().lower()
    return response in ("y", "yes")


def print_task_state(state: str) -> None:
    state_display = {
        "QUEUED": "Queued...",
        "STARTING": "Starting browser...",
        "RUNNING": "Running automation...",
        "WAITING_FOR_MANUAL_ACTION": "Manual action required!",
        "SUCCESS": "SUCCESS",
        "FAILURE": "FAILURE",
        "STOPPED": "STOPPED",
        "TIMEOUT": "TIMEOUT",
    }
    display = state_display.get(state, state)
    print(f"[STATE] {display}")


def print_tasks(tasks: list[dict]) -> None:
    if not tasks:
        print("No tasks found.")
        return
    print(f"\n{'ID':<12} {'State':<20} {'URL':<40} {'Created'}")
    print("-" * 90)
    for t in tasks:
        tid = t.get("task_id", "")[:8]
        state = t.get("state", "")
        url = t.get("target_url", "")[:38]
        created = t.get("created_at", "")[:19]
        print(f"{tid:<12} {state:<20} {url:<40} {created}")


def print_scheduled_tasks(tasks: list[dict]) -> None:
    if not tasks:
        print("No scheduled tasks.")
        return
    print(f"\n{'ID':<12} {'Name':<20} {'Cron':<20} {'Next Run'}")
    print("-" * 80)
    for t in tasks:
        tid = t.get("id", "")[:8]
        name = t.get("name", "")[:18]
        cron = t.get("cron_expression", "")[:18]
        next_run = str(t.get("next_run", ""))[:19]
        print(f"{tid:<12} {name:<20} {cron:<20} {next_run}")


def print_metrics(metrics: str) -> None:
    print("\n--- Prometheus Metrics ---")
    for line in metrics.strip().split("\n"):
        if not line.startswith("#"):
            print(f"  {line}")
    print("---")
