import json
import textwrap
from pathlib import Path

from pollevbot import PollBot

COOKIE_PATH = Path("session_cookies.json")


def prompt(text: str) -> str:
    while True:
        response = input(text).strip()
        if response:
            return response
        print("Please enter a value.")


def parse_cookie_string(raw: str) -> dict:
    cookies = {}
    segments = [segment.strip() for segment in raw.split(';') if segment.strip()]
    for segment in segments:
        if '=' not in segment:
            continue
        key, value = segment.split('=', 1)
        cookies[key.strip()] = value.strip()
    return cookies


def prompt_for_cookies(path: Path) -> dict:
    instructions = textwrap.dedent(
        """
        Step 1: In your browser, open https://pollev.com/ and complete the login (including MFA).
        Step 2: Once you see your dashboard, open the browser developer tools.
                • Chrome/Edge: View → Developer → Developer Tools.
                • Firefox: Tools → Browser Tools → Web Developer Tools.
        Step 3: Open the Application/Storage tab, expand “Cookies”, and select https://pollev.com.
                Copy the values for any of these cookies: pe_auth_token, pollev_visitor, pollev_visit.
        Step 4: Assemble them into a single line such as:
                pe_auth_token=<value>; pollev_visitor=<value>; pollev_visit=<value>
        Step 5: Return here and paste that line when prompted.
        """
    ).strip()
    print(instructions)
    input("Press Enter once you have completed the steps above.")

    while True:
        raw_cookie = input("\nPaste the cookie string here:\n> ").strip()
        cookies = parse_cookie_string(raw_cookie)
        if not cookies:
            print("No cookies detected. Please try pasting the string again.")
            continue
        if "pe_auth_token" not in cookies:
            print("Warning: pe_auth_token not found. Ensure you copied it from Application → Cookies → https://pollev.com.")
            retry = input("Paste again? [Y/n]: ").strip().lower()
            if retry in {"", "y", "yes"}:
                continue
        with path.open("w") as fh:
            json.dump(cookies, fh, indent=2)
        print(f"Saved session cookies to {path.resolve()}")
        return cookies


def load_cookies(path: Path) -> dict:
    if not path.exists():
        return prompt_for_cookies(path)

    use_saved = input(f"Found saved session cookies at {path}. Use them? [Y/n]: ").strip().lower()
    if use_saved in {"", "y", "yes"}:
        try:
            with path.open() as fh:
                cookies = json.load(fh)
        except json.JSONDecodeError:
            print("Could not read the saved cookie file. We'll capture new cookies.")
            cookies = prompt_for_cookies(path)
        return cookies

    return prompt_for_cookies(path)


def main():
    print("=== PollEv Cookie Assistant ===")
    host = prompt("Poll host (e.g. teacher123): ")

    cookies = load_cookies(COOKIE_PATH)
    print("Using provided cookies to continue.\n")

    with PollBot(user="cookie-user", password="", host=host, login_type='pollev',
                 session_cookies=cookies) as bot:
        bot.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
