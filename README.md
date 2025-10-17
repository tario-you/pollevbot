# pollevbot

**pollevbot** is a bot that automatically checks a PollEverywhere host page and
submits a random response when a new multiple-choice poll opens.

The current workflow targets Python 3.8+ and assumes you will authenticate with
an existing browser session (needed for accounts protected by MFA).

---

## Quick start

Clone the fork that includes the cookie workflow and create an isolated
environment:

```bash
git clone https://github.com/tario-you/pollevbot.git
cd pollevbot
conda create -y -n pollevbot-env python=3.8
conda activate pollevbot-env
pip install -r requirements.txt
```

---

## Running the bot

Run the helper and follow the prompts:

```
python -m pollevbot.main
```

The assistant will:
1. Ask for the poll host (everything after `https://pollev.com/`).
2. Prompt you to choose between cookie-based login (MFA compatible) or direct
   username/password login (legacy accounts).
3. Offer to reuse a cached firehose token for that host (stored in
   `firehose_tokens.json`) or paste a fresh token if you have one handy.

When you select cookie login, the helper stores the cookies needed for
authenticated requests in `session_cookies.json` and then maintains a long-poll
connection to the host (up to ~25 seconds per request) until you stop the
process. Leave your computer powered on and awake
while it runs; closing the laptop or killing the process ends the loop.

### Cookie flow (recommended for MFA accounts)

1. Log into <https://pollev.com/> in your browser and finish any MFA step.
2. Open developer tools (Application/Storage in Chrome/Edge, Storage in
   Firefox), expand **Cookies**, and select the `https://pollev.com` entry.
3. Copy the values for any of these: `pe_auth_token`, `pollev_visitor`, and
   `pollev_visit`, then paste a single line in the CLI like:
   ```
   pe_auth_token=<value>; pollev_visitor=<value>; pollev_visit=<value>
   ```
4. The helper saves the mapping to `session_cookies.json` and reuses it on
   subsequent runs until PollEverywhere expires the session.
5. Paste the firehose token shown in the PollEverywhere network console
   (or press Enter to let the bot request one automatically). Provided tokens
   are cached per host in `firehose_tokens.json`, so you only need to capture
   them once per presenter session.

When cookies are supplied, the bot skips the username/password login entirely.

### 2. Optional: direct login (no MFA accounts)

If you have a legacy PollEverywhere account without MFA, you can choose the
credential option in the helper or instantiate the bot manually:

```python
from pollevbot import PollBot

user = "my_username"
password = "my_password"
host = "teacher123"  # everything after https://pollev.com/

with PollBot(user, password, host, login_type="pollev") as bot:
    bot.run()
```

Use `login_type="uw"` only if you can authenticate through the UW SSO flow
without MFA.

---

## Scheduling / deployment

This repo still ships Heroku helper scripts (`clock.py`, `herokuapp.py`) that
previously relied on username/password logins. Because PollEverywhere now
requires MFA for most accounts, they will only work if you supply fresh cookies
through environment variables or disable MFA on the account. Evaluate whether a
different hosting option (e.g., a personal server with a cron job) is easier in
2025; Heroku Scheduler cannot interactively satisfy MFA challenges.

---

## Disclaimer

This project is for educational purposes only. Use it responsibly and in
accordance with any applicable academic integrity or site policies.
