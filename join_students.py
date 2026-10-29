"""Open multiple isolated student sessions for the Sub-Teacher combination game.

Requirements (run in the VS Code terminal):
    python -m pip install playwright
    python -m playwright install chromium

Examples:
    python join_students.py                       # 5 students, room 1112
    python join_students.py --count 10             # 10 students, room 1112
    python join_students.py --count 8 --code 1112  # 8 students, room 1112

Each student gets a randomly generated, unique nickname. The browser runs headlessly by default (no visible tabs/windows) so it uses less desktop
resources. Sessions remain connected until Enter is pressed in the terminal. Use --show-browser
to display the windows; closing a page will disconnect that student.
"""

import argparse
import re
import sys
import time
import secrets
from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

GAME_URL = "https://sub-teacher.com/API/combinationgame/combinationgame.html"
DEFAULT_COUNT = 5
DEFAULT_ROOM_CODE = "1112"
MAX_STUDENTS = 30  # Safety limit to avoid opening an unexpectedly large number of sessions.
DELAY_BETWEEN_STUDENTS = 0.5

ADJECTIVES = [
    "Brave", "Bright", "Calm", "Clever", "Cool", "Cosmic", "Cozy", "Daring",
    "Eager", "Fancy", "Fast", "Gentle", "Happy", "Jolly", "Lucky", "Merry",
    "Mighty", "Nimble", "Peaceful", "Quick", "Rapid", "Shiny", "Silent", "Sunny",
]
ANIMALS = [
    "Badger", "Bear", "Bee", "Bird", "Bison", "Cat", "Cobra", "Crane", "Deer",
    "Dolphin", "Eagle", "Falcon", "Fox", "Gecko", "Hawk", "Koala", "Lemur",
    "Lynx", "Otter", "Owl", "Panda", "Puma", "Raven", "Robin", "Seal", "Tiger",
    "Whale", "Wolf", "Yak", "Zebra",
]


def make_random_names(count: int) -> list[str]:
    """Generate short, distinct nicknames such as CleverFox4821."""
    names: list[str] = []
    seen: set[str] = set()
    while len(names) < count:
        name = f"{secrets.choice(ADJECTIVES)}{secrets.choice(ANIMALS)}{secrets.randbelow(9000) + 1000}"
        if name.lower() not in seen:
            names.append(name)
            seen.add(name.lower())
    return names


def first_visible(locator: Locator) -> Optional[Locator]:
    """Return the first visible match, if any."""
    try:
        for i in range(locator.count()):
            candidate = locator.nth(i)
            if candidate.is_visible():
                return candidate
    except Exception:
        pass
    return None


def open_student_entry(page: Page) -> None:
    """Open the student panel if the login inputs aren't already visible."""
    nickname = first_visible(page.get_by_placeholder(re.compile("닉네임")))
    room_code = first_visible(page.get_by_placeholder(re.compile("방 코드")))
    if nickname and room_code:
        return

    student_button = first_visible(
        page.get_by_role("button", name=re.compile(r"학생.*참여하기"))
    )
    if student_button is None:
        # Fallback for pages where the accessible name has extra text or emoji.
        student_button = first_visible(
            page.locator("button").filter(has_text=re.compile("학생"))
        )

    if student_button:
        student_button.click()

    try:
        page.get_by_placeholder(re.compile("닉네임")).first.wait_for(
            state="visible", timeout=7000
        )
    except PlaywrightTimeoutError:
        # The next step will show a useful error if the form did not appear.
        pass


def find_input(page: Page, pattern: str, fallback_index: int) -> Locator:
    """Find a visible input by placeholder/label, with a field-order fallback."""
    by_placeholder = first_visible(page.get_by_placeholder(re.compile(pattern)))
    if by_placeholder:
        return by_placeholder

    by_label = first_visible(page.get_by_label(re.compile(pattern)))
    if by_label:
        return by_label

    candidates = page.locator("input:visible")
    visible: list[Locator] = []
    for i in range(candidates.count()):
        item = candidates.nth(i)
        input_type = (item.get_attribute("type") or "text").lower()
        if input_type not in {"hidden", "button", "submit", "checkbox", "radio"}:
            visible.append(item)
    if len(visible) > fallback_index:
        return visible[fallback_index]

    raise RuntimeError(
        f"Could not find the input for '{pattern}'. "
        "Check that the site's student-entry form is visible."
    )


def join_one_student(
    browser: Browser, name: str, code: str, index: int, total: int
) -> tuple[BrowserContext, Page, bool]:
    """Create one isolated browser context and submit that student's entry form."""
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(10000)

    try:
        print(f"[{index}/{total}] Opening student session: {name}")
        page.goto(GAME_URL, wait_until="domcontentloaded", timeout=30000)
        open_student_entry(page)

        nickname_input = find_input(page, "닉네임", 0)
        code_input = find_input(page, "방 코드", 1)
        nickname_input.fill(name)
        code_input.fill(code)

        join_button = first_visible(
            page.get_by_role("button", name=re.compile("입장 완료"))
        )
        if join_button is None:
            join_button = first_visible(
                page.locator("button").filter(has_text=re.compile("입장 완료"))
            )
        if join_button is None:
            raise RuntimeError("Could not find the '입장 완료!' button.")

        join_button.click()
        page.wait_for_timeout(1200)
        print(
            f"[{index}/{total}] Join form submitted for {name}. "
            "Check the game room to confirm the result."
        )
        return context, page, True

    except Exception as exc:
        print(f"[{index}/{total}] FAILED for {name}: {exc}", file=sys.stderr)
        try:
            screenshot_path = f"join_error_{index}.png"
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"    Diagnostic screenshot saved: {screenshot_path}", file=sys.stderr)
        except Exception:
            pass
        # Keep the page open so the user can inspect the problem or finish manually.
        return context, page, False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open multiple student sessions for the Sub-Teacher combination game."
    )
    parser.add_argument(
        "--count", "-n", type=int, default=DEFAULT_COUNT,
        help=f"Number of students to open (default: {DEFAULT_COUNT}, maximum: {MAX_STUDENTS})",
    )
    parser.add_argument(
        "--code", default=DEFAULT_ROOM_CODE,
        help=f"Four-digit room code (default: {DEFAULT_ROOM_CODE})",
    )
    parser.add_argument(
        "--delay", type=float, default=DELAY_BETWEEN_STUDENTS,
        help=f"Seconds to pause between sessions (default: {DELAY_BETWEEN_STUDENTS})",
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="Show browser windows instead of running headlessly (uses more resources)",
    )
    args = parser.parse_args()

    if not 1 <= args.count <= MAX_STUDENTS:
        parser.error(f"--count must be between 1 and {MAX_STUDENTS}")
    if not re.fullmatch(r"\d{4}", args.code):
        parser.error("--code must be exactly four digits")
    if args.delay < 0:
        parser.error("--delay cannot be negative")

    names = make_random_names(args.count)
    print(f"Game: {GAME_URL}")
    print(f"Room code: {args.code}")
    print(f"Preparing {args.count} student session(s) with random nicknames:\n")
    for i, name in enumerate(names, start=1):
        print(f"  {i:02d}. {name}")
    print()

    contexts: list[BrowserContext] = []
    successes = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.show_browser)
        try:
            for index, name in enumerate(names, start=1):
                context, _page, success = join_one_student(
                    browser, name, args.code, index, args.count
                )
                contexts.append(context)
                successes += int(success)
                if index < args.count and args.delay:
                    time.sleep(args.delay)

            print(f"\nSubmitted {args.count} join attempt(s); {successes} form submission(s) completed.")
            print("This does not guarantee the server accepted every student; verify the students appear in the game room.")
            if args.show_browser:
                print("Visible browser windows are open. Closing a student page disconnects that session.")
            else:
                print("Running headlessly: no visible tabs are opened, but the student pages stay connected in the background.")
            input("Press Enter in this terminal to disconnect all students and exit... ")
        except KeyboardInterrupt:
            print("\nStopping; closing browser sessions...")
        finally:
            for context in contexts:
                try:
                    context.close()
                except Exception:
                    pass
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
