"""
A local MQTT broker, in pure Python.

Use this if you do not want to install Mosquitto. It does the same job for
this project: it accepts connections on port 1883 and passes messages
between our services and Node-RED.

Run:  python scripts/run_broker.py
Stop: Ctrl-C

If you prefer the normal tool, install Mosquitto and run `mosquitto` instead;
nothing else in the project changes.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import CONFIG  # noqa: E402

from amqtt.broker import Broker  # noqa: E402

PORT = CONFIG["mqtt"]["port"]

BROKER_CONFIG = {
    "listeners": {
        "default": {"type": "tcp", "bind": f"0.0.0.0:{PORT}", "max_connections": 50}
    },
    "sys_interval": 0,          # do not publish $SYS topics, keeps logs clean
    "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
    "topic-check": {"enabled": False},
}


async def start():
    broker = Broker(BROKER_CONFIG)
    await broker.start()
    print(f"MQTT broker listening on port {PORT}. Press Ctrl-C to stop.")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        print("\nBroker stopped.")
