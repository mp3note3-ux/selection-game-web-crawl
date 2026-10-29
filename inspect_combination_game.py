"""
Inspect the public "반짝 결! 합!" game in a real browser.
This does not submit scores or automate gameplay. It opens Single Player mode,
then saves the rendered DOM and a screenshot for local analysis.
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://sub-teacher.com/API/combinationgame/combinationgame.html"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="game_inspection", help="Output folder")
    parser.add_argument("--show-browser", action="store_true", help="Show Chromium window")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.show_browser)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: print(f"[page error] {exc}"))
        saved_assets = set()
        def capture_asset(resp):
            url = resp.url.lower()
            if resp.status >= 400 or not any(ext in url for ext in (".js", ".css")):
                return
            print(f"[HTTP {resp.status}] {resp.url}")
            try:
                suffix = ".css" if ".css" in url else ".js"
                filename = f"asset_{len(saved_assets)+1:02d}{suffix}"
                body = resp.body()
                (out / filename).write_bytes(body)
                saved_assets.add(resp.url)
            except Exception as exc:
                print(f"Could not save asset {resp.url}: {exc}")
        page.on("response", capture_asset)

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        # Save the initial page as well, in case the Single Player button is not found.
        (out / "landing.html").write_text(page.content(), encoding="utf-8")
        try:
            single = page.get_by_role("button", name="싱글 모드").first
            single.click(timeout=8000)
            page.wait_for_timeout(1500)
        except Exception as exc:
            print(f"Could not click Single Player automatically: {exc}")
            print("Open the browser visibly and click the Single Player button manually.")
            if not args.show_browser:
                browser.close()
                return

        (out / "single_player.html").write_text(page.content(), encoding="utf-8")
        (out / "single_player_url.txt").write_text(page.url, encoding="utf-8")
        page.screenshot(path=str(out / "single_player.png"), full_page=True)
        print(f"\nSaved inspection files to: {out.resolve()}")
        print(f"Current URL: {page.url}")
        print("Review single_player.html and single_player.png, then share them for help building a solver.")
        browser.close()

if __name__ == "__main__":
    main()
