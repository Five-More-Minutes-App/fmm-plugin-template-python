"""The smallest useful plugin: it connects, says what it may do, and reports what happens to the
computer until you stop it. Replace the body of the loop with what you actually want - turn a light
red, send a message, block a device - and keep the rest.

    FMM_URL=http://192.168.1.10:5072 FMM_API_KEY=fmmk_... python example.py
    python example.py --start 30 "Homework"        also starts 30 minutes, if the key may
"""

from __future__ import annotations

import asyncio
import os
import sys

from fmm_client import FiveMoreMinutes, FmmError, describe, events_between


async def main() -> int:
    url, key = os.environ.get("FMM_URL"), os.environ.get("FMM_API_KEY")
    if not url or not key:
        print("Set FMM_URL and FMM_API_KEY. See .env.example, and README.md for how to make a key.", file=sys.stderr)
        return 2

    try:
        async with FiveMoreMinutes(url, key) as fmm:
            # Prove the address and the key work before doing anything else, and say what this key
            # may do, so that a missing permission is a message now rather than a failure later.
            me = await fmm.me()
            print(f'Connected as "{me.name}" to {me.device_name}.')
            print(f"This key may: {', '.join(me.scopes)}")
            if me.expires_at:
                print(f"It expires {me.expires_at}.")

            args = sys.argv[1:]
            if args[:1] == ["--start"] and len(args) >= 2:
                print(describe(await fmm.start(minutes=int(args[1]), message=" ".join(args[2:]) or None)))

            previous = None
            async for state in fmm.watch():
                if previous is None:
                    print(describe(state))

                for event in events_between(previous, state):
                    # This is where your plugin does its work.
                    print(f"{event}: {describe(state)}")

                previous = state
    except FmmError as error:
        # Every message here is safe to show a person; none contains the key.
        print(error, file=sys.stderr)
        return 2 if error.kind == "config" else 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("Stopped.")
