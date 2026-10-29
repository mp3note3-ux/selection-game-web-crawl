"""
Multi-bot player for Sub-Teacher's "반짝 결! 합!" room game.

Edit config.json beside this file and run:
    python play_room_bot.py

Command-line flags can override config values for one run.
"""

from __future__ import annotations

import argparse
import itertools
import json
import secrets
import string
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

GAME_URL = "https://sub-teacher.com/API/combinationgame/combinationgame.html"
CARD_SELECTOR = "#card-grid .card"
ALERT_SELECTOR = "#banjjak-alert"
MAX_BOTS = 20
ALPHABET = string.ascii_uppercase + string.digits
CONFIG_PATH = Path(__file__).resolve().with_name("config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "room_code": "1112",
    "bot_count": 5,
    "nickname_prefix": "BOT",
    "browser": "chromium",
    "show_browser": False,
    "max_minutes": 30,
    "join_delay_seconds": 0.6,
    "action_delay_seconds": 1.7,
}


def load_config() -> dict[str, Any]:
    """Read config.json and fill any missing keys with defaults."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}. Keep config.json beside play_room_bot.py."
        )
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {CONFIG_PATH}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("config.json must contain a JSON object.")
    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    return config


def parse_args(config: dict[str, Any]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Join an existing room with randomized student bots and play automatically."
    )
    parser.add_argument("--code", help="Override config room_code for this run")
    parser.add_argument("--count", "-n", type=int, help="Override config bot_count for this run")
    parser.add_argument("--nickname-prefix", help="Override config nickname_prefix")
    parser.add_argument("--browser", choices=("chromium", "msedge", "chrome"), help="Override config browser")
    parser.add_argument("--show-browser", action="store_true", default=None, help="Show browser windows for debugging")
    parser.add_argument("--max-minutes", type=float, help="Override config max_minutes; 0 means no limit")
    parser.add_argument("--join-delay", type=float, help="Override config join_delay_seconds")
    parser.add_argument("--action-delay", type=float, help="Override config action_delay_seconds")
    args = parser.parse_args()

    args.code = args.code if args.code is not None else str(config["room_code"])
    args.count = args.count if args.count is not None else int(config["bot_count"])
    args.nickname_prefix = (
        args.nickname_prefix if args.nickname_prefix is not None else str(config["nickname_prefix"])
    )
    args.browser = args.browser if args.browser is not None else str(config["browser"])
    args.show_browser = (
        args.show_browser if args.show_browser is not None else bool(config["show_browser"])
    )
    args.max_minutes = (
        args.max_minutes if args.max_minutes is not None else float(config["max_minutes"])
    )
    args.join_delay = (
        args.join_delay if args.join_delay is not None else float(config["join_delay_seconds"])
    )
    args.action_delay = (
        args.action_delay if args.action_delay is not None else float(config["action_delay_seconds"])
    )

    if len(args.code) != 4 or not args.code.isdigit():
        parser.error("room_code/--code must be exactly four digits")
    if not 1 <= args.count <= MAX_BOTS:
        parser.error(f"bot_count/--count must be between 1 and {MAX_BOTS}")
    if not 1 <= len(args.nickname_prefix) <= 4:
        parser.error("nickname_prefix must be between 1 and 4 characters")
    if args.browser not in ("chromium", "msedge", "chrome"):
        parser.error("browser must be chromium, msedge, or chrome")
    if args.max_minutes < 0 or args.join_delay < 0 or args.action_delay < 0:
        parser.error("time settings cannot be negative")
    return args


def make_names(count: int, prefix: str) -> list[str]:
    """Return unique 8-character nicknames."""
    names: list[str] = []
    seen: set[str] = set()
    for _ in range(count):
        while True:
            name = prefix + "".join(secrets.choice(ALPHABET) for _ in range(8 - len(prefix)))
            if name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
                break
    return names


def valid_attribute(values: tuple[int, int, int]) -> bool:
    return len(set(values)) in (1, 3)


def find_haps(cards: list[dict[str, int]]) -> list[tuple[int, int, int]]:
    """Find triples where each attribute is all same or all different."""
    answers: list[tuple[int, int, int]] = []
    for i, j, k in itertools.combinations(range(len(cards)), 3):
        triple = (cards[i], cards[j], cards[k])
        if all(
            valid_attribute(tuple(card[key] for card in triple))
            for key in ("s", "c", "b")
        ):
            answers.append((i, j, k))
    return answers


def parse_found(found: list[str]) -> set[tuple[int, int, int]]:
    parsed: set[tuple[int, int, int]] = set()
    for item in found:
        try:
            triple = tuple(sorted(int(part) for part in item.split(",")))
            if len(triple) == 3:
                parsed.add(triple)  # type: ignore[arg-type]
        except (AttributeError, TypeError, ValueError):
            pass
    return parsed


def read_state(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const el = id => document.getElementById(id);
          const visible = id => !!el(id) && !el(id).classList.contains('hidden');
          return {
            round: Number(el('current-round-display')?.textContent || 0),
            cards: (typeof currentBoardCards !== 'undefined' ? currentBoardCards : [])
              .map(({s,c,b}) => ({s,c,b})),
            found: (typeof currentFoundHaps !== 'undefined' ? currentFoundHaps : []).slice(),
            gameVisible: visible('game-board'),
            lobbyVisible: visible('lobby-board'),
            finishVisible: visible('finish-board'),
            alertVisible: visible('banjjak-alert'),
            hapDisabled: !!el('btn-hap-shout')?.disabled,
            gyeolDisabled: !!el('btn-gyeol-shout')?.disabled,
            penaltyActive: typeof isPenaltyActive !== 'undefined' && isPenaltyActive,
            selectingHap: typeof isSelectingHap !== 'undefined' && isSelectingHap
          };
        }"""
    )


def close_alert(page: Page, timeout_ms: int = 12000) -> str:
    page.locator(ALERT_SELECTOR).wait_for(state="visible", timeout=timeout_ms)
    message = page.locator("#alert-msg").inner_text()
    page.locator("#banjjak-alert .modal-btn").click(timeout=timeout_ms)
    page.locator(ALERT_SELECTOR).wait_for(state="hidden", timeout=timeout_ms)
    return message


def join_room(page: Page, code: str, nickname: str) -> None:
    page.goto(GAME_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(400)
    login = page.locator("#student-login")
    if not login.is_visible():
        page.locator('button[onclick="showStudentLogin()"]').click(timeout=10000)
        login.wait_for(state="visible", timeout=10000)
    page.locator("#nickname").fill(nickname)
    page.locator("#room-code-input").fill(code)
    page.locator('button[onclick="joinGame()"]').click(timeout=10000)
    page.wait_for_function(
        """() => {
          const lobby = document.getElementById('lobby-board');
          const alert = document.getElementById('banjjak-alert');
          return (lobby && !lobby.classList.contains('hidden')) ||
                 (alert && !alert.classList.contains('hidden'));
        }""",
        timeout=20000,
    )
    if page.locator(ALERT_SELECTOR).is_visible():
        raise RuntimeError(f"Join failed for {nickname}: {close_alert(page)}")
    print(f"  Joined as {nickname}.")


def attempt_hap(page: Page, triple: tuple[int, int, int]) -> str:
    page.locator("#btn-hap-shout").click(timeout=6000)
    for index in triple:
        page.locator(CARD_SELECTOR).nth(index).click(timeout=6000)
    return close_alert(page)


def attempt_gyeol(page: Page) -> str:
    page.locator("#btn-gyeol-shout").click(timeout=6000)
    return close_alert(page)


def canonical_board(pages: list[Page]) -> tuple[tuple[int, str] | None, list[dict[str, Any]], set[tuple[int, int, int]]]:
    samples = []
    for page in pages:
        try:
            state = read_state(page)
            if state["finishVisible"]:
                return None, [], set()
            if state["gameVisible"] and len(state["cards"]) == 9:
                sig = json.dumps(state["cards"], sort_keys=True, separators=(",", ":"))
                samples.append((page, state, (int(state["round"]), sig)))
        except PlaywrightError:
            continue
    if not samples:
        return None, [], set()
    board_key = Counter(key for _, _, key in samples).most_common(1)[0][0]
    snapshots = [{"page": page, **state} for page, state, key in samples if key == board_key]
    found: set[tuple[int, int, int]] = set()
    for state in snapshots:
        found.update(parse_found(state["found"]))
    return board_key, snapshots, found


def pick_actor(pages: list[Page], snapshots: list[dict[str, Any]], cursor: int) -> tuple[Page | None, int]:
    by_page = {id(s["page"]): s for s in snapshots}
    for offset in range(len(pages)):
        index = (cursor + offset) % len(pages)
        page = pages[index]
        state = by_page.get(id(page))
        if state and not (
            state["penaltyActive"] or state["selectingHap"] or state["hapDisabled"] or state["alertVisible"]
        ):
            return page, (index + 1) % len(pages)
    return None, cursor


def wait_for_confirmation(pages: list[Page], board_key: tuple[int, str], combo: tuple[int, int, int], seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for page in pages:
            try:
                state = read_state(page)
                sig = json.dumps(state["cards"], sort_keys=True, separators=(",", ":"))
                if (int(state["round"]), sig) != board_key:
                    return False
                if combo in parse_found(state["found"]):
                    return True
            except PlaywrightError:
                pass
        time.sleep(0.25)
    return False


def coordinate_play(
    pages: list[Page],
    names: list[str],
    max_minutes: float,
    action_delay: float,
) -> None:
    deadline = None if max_minutes == 0 else time.monotonic() + max_minutes * 60
    cursor = 0
    active_board = None
    attempts: dict[tuple[int, str], dict[tuple[int, int, int], float]] = {}
    last_gyeol: dict[tuple[int, str], float] = {}
    complete_board = None
    last_idle = 0.0
    cooldown = 7.0

    print("\nBots connected. Waiting for the host to start a round.")
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            print("Reached max_minutes; shutting down all bots.")
            return

        try:
            if any(read_state(page)["finishVisible"] for page in pages):
                print("Room game finished. Shutting down all bots.")
                return
        except PlaywrightError:
            pass

        board_key, snapshots, found = canonical_board(pages)
        if board_key is None:
            now = time.monotonic()
            if now - last_idle >= 8:
                print("Waiting for an active board / next round...")
                last_idle = now
            time.sleep(0.4)
            continue

        round_no, signature = board_key
        cards = json.loads(signature)
        if board_key != active_board:
            active_board = board_key
            attempts[board_key] = {}
            complete_board = None
            print(f"Round {round_no} active; scanning cards.")

        if complete_board == board_key:
            time.sleep(0.5)
            continue

        now = time.monotonic()
        remaining = [c for c in find_haps(cards) if c not in found]
        board_attempts = attempts.setdefault(board_key, {})

        if remaining:
            choices = [c for c in remaining if c not in board_attempts or now - board_attempts[c] >= cooldown]
            if not choices:
                time.sleep(0.35)
                continue
            actor, cursor = pick_actor(pages, snapshots, cursor)
            if actor is None:
                time.sleep(0.35)
                continue

            combo = choices[0]
            board_attempts[combo] = now
            name = names[pages.index(actor)]
            print(f"{name} selects cards {[i + 1 for i in combo]}.")
            try:
                message = attempt_hap(actor, combo)
                print("  " + message.replace("\n", " "))
                if wait_for_confirmation(pages, board_key, combo):
                    print(f"  Confirmed: {name} found the combination.")
                    time.sleep(action_delay)
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                print(f"  Move interrupted: {exc}")
            continue

        actor, cursor = pick_actor(pages, snapshots, cursor)
        if actor is None:
            time.sleep(0.35)
            continue
        if now - last_gyeol.get(board_key, 0.0) < cooldown:
            time.sleep(0.35)
            continue
        last_gyeol[board_key] = now
        name = names[pages.index(actor)]
        print(f"{name} calls 결! (no remaining combinations).")
        try:
            message = attempt_gyeol(actor)
            print("  " + message.replace("\n", " "))
            if "성공" in message or "정답" in message:
                complete_board = board_key
            time.sleep(action_delay)
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            print(f"  결! interrupted: {exc}")


def main() -> int:
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"Could not read config.json: {exc}", file=sys.stderr)
        return 2
    args = parse_args(config)
    names = make_names(args.count, args.nickname_prefix)

    print(f"Room code: {args.code}")
    print(f"Bots: {args.count}")
    print(f"Browser: {args.browser}; show_browser={args.show_browser}")
    print("Random usernames:")
    for name in names:
        print(f"  - {name}")
    print("\nMoves are coordinated and serialized to avoid bots racing for the same set.")
    if args.count >= 10:
        print("Note: 10+ sessions may use substantial CPU/RAM. Consider starting with 3-5.")

    contexts = []
    pages: list[Page] = []
    joined_names: list[str] = []
    browser = None
    output_dir = Path(__file__).resolve().with_name("room_bot_diagnostics")
    output_dir.mkdir(exist_ok=True)

    try:
        with sync_playwright() as playwright:
            launch: dict[str, Any] = {
                "headless": not args.show_browser,
                "args": ["--disable-gpu", "--mute-audio"],
            }
            if args.browser == "msedge":
                launch["channel"] = "msedge"
            elif args.browser == "chrome":
                launch["channel"] = "chrome"
            browser = playwright.chromium.launch(**launch)

            for index, name in enumerate(names, start=1):
                context = browser.new_context()
                contexts.append(context)
                page = context.new_page()
                page.set_default_timeout(9000)
                print(f"Joining bot {index}/{args.count}: {name}")
                try:
                    join_room(page, args.code, name)
                    pages.append(page)
                    joined_names.append(name)
                except Exception as exc:
                    print(f"  Could not join {name}: {exc}", file=sys.stderr)
                    try:
                        (output_dir / f"join_failure_{index}.html").write_text(page.content(), encoding="utf-8")
                        context.close()
                        contexts.remove(context)
                    except Exception:
                        pass
                if index < args.count and args.join_delay:
                    time.sleep(args.join_delay)

            if not pages:
                print("No bots joined successfully.", file=sys.stderr)
                return 1
            print(f"{len(pages)} bot(s) joined. The host must start each round.")
            coordinate_play(pages, joined_names, args.max_minutes, args.action_delay)
            return 0

    except KeyboardInterrupt:
        print("\nCtrl+C detected; closing all bot sessions.")
        return 130
    except Exception as exc:
        print(f"BOT ERROR: {exc}", file=sys.stderr)
        try:
            if pages:
                (output_dir / "failure.html").write_text(pages[0].content(), encoding="utf-8")
                pages[0].screenshot(path=str(output_dir / "failure.png"), full_page=True)
                print(f"Diagnostics saved to {output_dir}", file=sys.stderr)
        except Exception:
            pass
        return 1
    finally:
        for context in contexts:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
