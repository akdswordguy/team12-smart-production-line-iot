"""
Print every MQTT message the project sends. A debugging window.

Useful in the viva: it proves a record really travelled over MQTT, and it
shows the observed / simulated / forecast labels on every payload.

Run:  python scripts/listen.py
      python scripts/listen.py team12/sim/#      (only the virtual line)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import connect  # noqa: E402

PATTERN = sys.argv[1] if len(sys.argv) > 1 else "team12/#"

# Colour-code the three kinds of data so they are never confused on screen.
LABEL = {
    "observed": "OBSERVED ",
    "simulated": "SIMULATED",
    "forecast": "FORECAST ",
}


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())
    except Exception:
        print(f"[?] {message.topic}: <not JSON> {message.payload[:80]}")
        return

    label = LABEL.get(payload.get("source"), "?        ")
    short = {k: v for k, v in payload.items()
             if k not in ("source", "schema_version", "run_id", "stages")}
    if "stages" in payload:
        short["stages"] = [
            f"{s['stage_name'][:7]} q={s['queue_length']} "
            f"busy={s['busy_share']:.0%}"
            for s in payload["stages"]
        ]
    print(f"[{label}] {message.topic}")
    print(f"            {json.dumps(short, default=str)[:300]}")


def main():
    client = connect("listener")
    client.on_message = on_message
    client.subscribe(PATTERN)
    print(f"Listening on {PATTERN}. Ctrl-C to stop.\n")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
