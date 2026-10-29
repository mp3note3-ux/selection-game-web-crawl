# Multi-bot room player

## Configure it without terminal arguments

Edit `config.json` in VS Code:

- `room_code`: four-digit room code.
- `bot_count`: number of bots (1-20).
- `nickname_prefix`: prefix for random 8-character usernames (1-4 chars).
- `browser`: `chromium`, `msedge`, or `chrome`.
- `show_browser`: `false` runs headlessly; `true` shows windows.
- `max_minutes`: automatic stop time; use `0` for no limit.
- `join_delay_seconds`: pause between bot sign-ins.
- `action_delay_seconds`: pause after a successful move so sessions can synchronize.

## Install once

```powershell
python -m pip install playwright
python -m playwright install chromium
```

For Microsoft Edge, choose `"browser": "msedge"` in `config.json`.

## Run

```powershell
python play_room_bot.py
```

The script reads `config.json` from the same folder automatically. CLI flags
are also available to override individual settings for one run, for example:

```powershell
python play_room_bot.py --code 1234 --count 3
```

Bots join an existing room as students. The host still starts the rounds.
Moves are serialized by a coordinator to reduce the chance of two bots trying
the same combination. Successful moves affect real room scores; use only in a
room where bot participation is authorized.

Start with 3-5 bots and increase only if your laptop and the game room can
handle more sessions.
