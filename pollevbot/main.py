import json
import textwrap
from getpass import getpass
from pathlib import Path
from typing import Optional

from pollevbot import PollBot

COOKIE_PATH = Path("session_cookies.json")
HOST_PATH = Path("last_host.txt")
TOKEN_PATH = Path("firehose_tokens.json")


def prompt(text: str, default: Optional[str] = None) -> str:
    while True:
        response = input(text).strip()
        if not response and default is not None:
            return default
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


def load_token_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open() as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: could not read firehose token cache ({exc}). We'll recreate it.")
        return {}
    if isinstance(data, dict):
        filtered = {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
        if len(filtered) != len(data):
            print("Warning: firehose token cache included non-string entries. "
                  "Those entries were ignored.")
        return filtered
    print("Warning: firehose token cache format was unexpected. Ignoring it.")
    return {}


def save_token_cache(path: Path, cache: dict) -> None:
    try:
        path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        print(f"Warning: could not save firehose token cache ({exc}).")


def prompt_for_firehose_token(host: str, path: Path) -> Optional[str]:
    cache = load_token_cache(path)
    existing = cache.get(host)

    if existing:
        use_saved = input(f"Found saved firehose token for {host}. Use it? [Y/n]: ").strip().lower()
        if use_saved in {"", "y", "yes"}:
            print("Using cached firehose token.\n")
            return existing

    firehose_prompt = f"Firehose token for {host} (press Enter to skip): "
    token = input(firehose_prompt).strip()
    if token:
        cache[host] = token
        save_token_cache(path, cache)
        print("Saved firehose token for this host.\n")
        return token

    return None


def choose_login(host: str):
    use_cookies = input("Use cookie-based login? [Y/n]: ").strip().lower()
    if use_cookies in {"", "y", "yes"}:
        cookies = load_cookies(COOKIE_PATH)
        print("Using provided cookies to continue.\n")
        return {
            "user": "cookie-user",
            "password": "",
            "host": host,
            "login_type": "pollev",
            "session_cookies": cookies
        }

    user = prompt("PollEv username: ")
    password = getpass("PollEv password: ")
    login_type = input("Login type [pollev/uw] (default pollev): ").strip().lower() or "pollev"
    print("Starting bot with credential login.\n")
    return {
        "user": user,
        "password": password,
        "host": host,
        "login_type": login_type,
        "session_cookies": None
    }


def load_last_host(path: Path) -> Optional[str]:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def save_last_host(path: Path, host: str) -> None:
    path.write_text(host.strip(), encoding="utf-8")


def main():
    print("=== PollEv Assistant ===")
    last_host = load_last_host(HOST_PATH)
    if last_host:
        host_prompt = f"Poll host (e.g. teacher123) [{last_host}]: "
    else:
        host_prompt = "Poll host (e.g. teacher123): "
    host = prompt(host_prompt, default=last_host)
    config = choose_login(host)
    try:
        save_last_host(HOST_PATH, host)
    except OSError as exc:
        print(f"Warning: could not remember host ({exc}).")

    firehose_token = prompt_for_firehose_token(host, TOKEN_PATH)
    config["firehose_token"] = firehose_token

    with PollBot(**config) as bot:
        bot.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
