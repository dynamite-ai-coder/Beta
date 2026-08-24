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
            print(f"  [{ev.get('timestamp', '')}] {ev.get('event', '')}: {ev.get('data', '')}")
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
