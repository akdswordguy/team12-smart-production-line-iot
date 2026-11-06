"""
Shared helpers. Small on purpose - read this file first.

Everything here is used by the other scripts:
  CONFIG      the parsed config/config.yaml
  path(...)   turn a config path into a real path
  connect()   connect to the MQTT broker
  now_iso()   wall-clock timestamp as text
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Read the config once, when this module is imported.
with open(ROOT / "config" / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)


def path(key):
    """Look up a path from config['paths'] and return it as a full path.

    Example: path("clean_events") -> /.../team12/data/processed/events_clean.csv
    """
    return ROOT / CONFIG["paths"][key]


def require(key, how_to_fix):
    """Return a path from config, or stop with a message that says what to do.

    A clear sentence beats a traceback when someone is running this for the
    first time.
    """
    p = path(key)
    if not p.exists():
        raise SystemExit(
            f"\nMissing file: {p}\n\n{how_to_fix}\n"
        )
    return p


def now_iso():
    """Current wall-clock time, as text. This is the REPLAY timestamp -
    it says when we published, not when the factory recorded anything."""
    return datetime.now(timezone.utc).isoformat()


def topic(name, suffix=None):
    """Build a topic name from config. topic('observed_machine', 3) ->
    'team12/observed/machine/3'"""
    base = CONFIG["topics"][name]
    root = os.getenv("TEAM12_TOPIC_ROOT", "team12").strip("/")
    if root != "team12":
        if not base.startswith("team12/"):
            raise ValueError(f"Unexpected project topic: {base}")
        base = root + base[len("team12"):]
    return f"{base}/{suffix}" if suffix is not None else base


def connect(client_name):
    """Connect to the MQTT broker and return a connected client.

    Retries for a few seconds so you can start the services in any order.
    """
    import paho.mqtt.client as mqtt

    cfg = CONFIG["mqtt"]
    host = os.getenv("TEAM12_MQTT_HOST", cfg["host"])
    port = int(os.getenv("TEAM12_MQTT_PORT", cfg["port"]))
    username = os.getenv("TEAM12_MQTT_USERNAME")
    password = os.getenv("TEAM12_MQTT_PASSWORD")
    tls = os.getenv("TEAM12_MQTT_TLS", "false").lower() in ("1", "true", "yes")
    transport = os.getenv("TEAM12_MQTT_TRANSPORT", "tcp")
    if transport not in ("tcp", "websockets"):
        raise SystemExit("TEAM12_MQTT_TRANSPORT must be tcp or websockets")
    client_id = f"{cfg['client_prefix']}-{client_name}-{uuid.uuid4().hex[:10]}"

    # CallbackAPIVersion keeps us on the modern paho API (paho-mqtt 2.x).
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                         transport=transport)
    if transport == "websockets":
        client.ws_set_options(path="/mqtt")
    if tls:
        client.tls_set()
    if username:
        client.username_pw_set(username, password)

    last_error = None
    for attempt in range(10):
        try:
            client.connect(host, port, keepalive=60)
            print(f"[{client_name}] connected to MQTT at {host}:{port}")
            return client
        except Exception as e:  # broker not up yet
            last_error = e
            print(f"[{client_name}] broker not ready ({e}); retrying...")
            time.sleep(1.5)

    raise SystemExit(
        f"[{client_name}] could not reach the MQTT broker at "
        f"{host}:{port}.\n"
        f"Last error: {last_error}\n"
        f"Start one with:  python scripts/run_broker.py   (or: mosquitto)"
    )


def publish(client, topic_name, payload):
    """Publish a dict as JSON. Keeps every publish in one place so the
    message format cannot drift between services."""
    client.publish(topic_name, json.dumps(payload), qos=0)


def load_json(p):
    with open(p) as f:
        return json.load(f)


def save_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, default=str)
