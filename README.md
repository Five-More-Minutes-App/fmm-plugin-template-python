# Five More Minutes plugin starter (Python)

A starting point for connecting something in your home to [Five More Minutes](https://github.com/five-more-minutes/FiveMoreMinutes):
a small `aiohttp` client, a helper that turns "the state now" into "what just happened", and a working
example. Fork it, rename it, and put your idea in the middle.

It is free to build a plugin, free to list it in the marketplace, and there is nothing to sign up for.

## In five minutes

1. **Make a key.** In the Five More Minutes portal open **Plugins**, choose **Developer**, pick the
   computer, name the key, tick the permissions you need, and press **Create key**. The key is shown
   once. Copy it; it cannot be shown again.
2. **Tell the plugin.** Copy `.env.example` to `.env` and fill in the two lines.
3. **Run it.**

   ```bash
   python -m venv .venv
   . .venv/bin/activate            # on Windows: .venv\Scripts\activate
   pip install -e .
   set -a; . ./.env; set +a        # load the two variables
   python example.py
   ```

   You should see the computer's name, what the key may do, and then a line each time something happens
   to it. Start a timer from the portal and watch it appear.

To try starting one from here (if the key has `timer:start`):

```bash
python example.py --start 30 "Homework"
```

## What is in here

| | |
|---|---|
| `fmm_client/client.py` | The whole client: `me()`, `state()`, `start()`, `extend()`, `stop()`, `cancel()` and `watch()`. Read it; it is short on purpose. |
| `fmm_client/events.py` | `events_between(previous, current)`: `timer-started`, `timer-extended`, `timer-ended`, `lock-started`, `lock-ended`, `came-online`, `went-offline`. |
| `example.py` | The example. Connects, says what the key may do, and logs what happens. **Replace the loop's body.** |
| `tests/` | Tests, including a faithful mock of the API you can reuse. `pytest` |
| `fmm-plugin.json` | The manifest the marketplace lists your plugin from. Fill it in before you publish. |
| `icon.png` | Your plugin's icon: a square PNG, 128 to 512 pixels. Replace it. |

Python 3.11 or later. The only dependency is `aiohttp`.

## The API on one page

Everything is under `/api/integrations/v1`, sent with `Authorization: Bearer <your key>`.

| Call | Needs | What it does |
|---|---|---|
| `GET /me` | any key | Who the key is and what it may do. Call it first. |
| `GET /state` | `state:read` | The computer's timer and lock. Add `?wait=25&since=<signal>` to be answered the moment something changes. |
| `POST /timer/start` | `timer:start` | `{ "minutes": 30, "message": "Homework" }` or `{ "until": "20:00" }`. Starting during a lock lifts it. |
| `POST /timer/extend` | `timer:extend` | `{ "minutes": 10 }`, or nothing for the household's usual five more. |
| `POST /timer/stop` | `timer:stop` | Time is up, now: the timer ends and the lock begins. |
| `POST /timer/cancel` | `timer:cancel` | Let go: the timer ends, no lock. |

There is no computer id anywhere, because **a key opens exactly one computer**. A request cannot name
another. Times are absolute instants: count down from `ends_at`, do not count `seconds_left` yourself. The
full reference, with every error, is in the
[API documentation](https://github.com/five-more-minutes/FiveMoreMinutes/blob/main/docs/plugins/api-v1.md).

### Following a computer

Do not poll. Ask `watch()`:

```python
async for state in fmm.watch():
    ...  # runs once now, then each time something changes; reconnects by itself
```

It holds a request open that the service answers the moment a parent presses a button, so your plugin
reacts within a moment and makes about two requests a minute while nothing happens. It raises the error
when trying again cannot help: a revoked key, for instance.

### When it goes wrong

`FmmError.kind` says what to do about it, and every message is safe to show a person.

| `kind` | Means | Retry? |
|---|---|---|
| `config` | The address or the key is not usable | no |
| `auth` | The key was refused: wrong, revoked or expired | no |
| `network-only` | The service answers plugins on the local network only | no |
| `forbidden` | The key lacks a permission this call needs (the message names it) | no |
| `not-possible` | The computer is not in a state that allows it, such as nothing running to extend | no |
| `invalid` | The request was wrong | no |
| `rate-limited` | Too many requests; `retry_after` says how long | yes |
| `network` / `unexpected` | Could not reach it, or it said something strange | yes |

## Security, in the order it matters

- **Ask for as little as you need.** A plugin that only shows a countdown needs `state:read` and nothing
  else. A parent sees your list before they agree, and the service refuses anything outside it.
- **The key is a password.** Keep it in `.env` or your platform's secret store. Never commit it: `.env` is
  already in `.gitignore`. Never put it in a URL or a log line. The client keeps it out of error messages,
  `repr()` and pickles; keep it that way in your own code.
- **Local network only.** The service refuses your key from the internet. This is on purpose, and there is
  nothing to configure. Run your plugin on the same network as Five More Minutes.
- **Do not follow redirects with the key.** The client does not; if you replace it, do not either.
- **Handle a revoked key kindly.** A parent can end a key at any moment. Say so plainly ("the key was
  revoked; make a new one") rather than retrying for ever.
- **Do what you say.** The parent sees what your key has done, in the portal, for thirty days. Do not
  start or stop time except when the person using your plugin asked you to.

## Publishing to the marketplace

The marketplace lists plugins from a git registry. It is free, and it is a pull request.

1. **Make it yours.** Rename the repository, and fill in `fmm-plugin.json`:

   | Field | What to put |
   |---|---|
   | `id`, `name` | A short slug and a name people will search for |
   | `description` | What it does, in plain words, for a parent |
   | `permissions` | Each permission you use, **and why**: this is what the parent reads before saying yes |
   | `install.steps` | How to install it, one step at a time. Use `{{FMM_URL}}` and `{{API_KEY}}` inside code blocks; the portal fills them in |
   | `icon.png` | A square PNG, 128–512 px, under 100 KB. SVG is not accepted |

2. **Check it.**

   ```bash
   git clone https://github.com/five-more-minutes/fmm-plugin-registry
   node fmm-plugin-registry/scripts/validate.mjs --manifest fmm-plugin.json
   ```

3. **Document it.** A README with what it does, how to install it, how to configure it, what to do when
   it does not work, and what permissions it uses and why.
4. **Tag a release** and note the commit hash.
5. **Open a pull request** to [`fmm-plugin-registry`](https://github.com/five-more-minutes/fmm-plugin-registry)
   adding `plugins/<your-id>/` with your manifest, icon and a `listing.json` pinned to that commit. A check
   runs on the pull request and tells you what to fix.

Listings are **pinned to a commit**: what a reviewer read is what families see. To ship a new version, open
another pull request with the new commit.

## Testing

```bash
pip install -e ".[dev]"
pytest          # the client and the event logic, against a mock of the API
ruff check .
mypy
```

`tests/mock_fmm.py` implements the API over real HTTP, including long-polling, permissions, conflicts, the
local-network refusal and rate limiting. Use it to test your own code without a running service.

## Troubleshooting

| You see | Do this |
|---|---|
| "That does not look like a Five More Minutes API key" | The key starts `fmmk_` and is 81 characters. Copy all of it, with nothing before or after. |
| "The API key was not accepted" | It was revoked, has expired, or is for another installation. Make a new one. |
| "only answers plugins on the local network" | Run the plugin on the same network as Five More Minutes, and use its local address. |
| "Could not reach Five More Minutes" | Is it running? Is `FMM_URL` an address this computer can reach? |
| "does not have the … permission" | Make a new key with that permission ticked. A key's permissions cannot be changed. |
| "already running" | The computer has a timer. Use `extend` instead, or `cancel` first. |

## Licence

MIT. See [LICENSE](LICENSE).
