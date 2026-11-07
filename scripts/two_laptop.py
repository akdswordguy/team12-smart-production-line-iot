"""Run one half of the Team 12 demo against the same remote MQTT broker."""
import argparse
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common import CONFIG, connect, now_iso, topic  # noqa: E402
from run_demo import LOGS, STOP_FILE, prepare_flow, wait_log, wait_port  # noqa: E402


def broker_check(profile):
    if profile in ("public", "public-tls"):
        settings = json.loads((ROOT / "config/public_broker.json").read_text(encoding="utf-8"))
        root = settings["topic_root"]
        if not re.fullmatch(r"team12/demo-[a-f0-9]{16,32}", root):
            raise SystemExit("Invalid project topic root in config/public_broker.json")
        if profile == "public":
            os.environ.update(TEAM12_MQTT_HOST="broker.hivemq.com", TEAM12_MQTT_PORT="8000",
                              TEAM12_MQTT_TLS="false", TEAM12_MQTT_TRANSPORT="websockets",
                              TEAM12_TOPIC_ROOT=root)
            print("Using HiveMQ's public, unencrypted WebSocket test broker", flush=True)
        else:
            os.environ.update(TEAM12_MQTT_HOST="broker.hivemq.com", TEAM12_MQTT_PORT="8883",
                              TEAM12_MQTT_TLS="true", TEAM12_MQTT_TRANSPORT="tcp",
                              TEAM12_TOPIC_ROOT=root)
        os.environ.pop("TEAM12_MQTT_USERNAME", None)
        os.environ.pop("TEAM12_MQTT_PASSWORD", None)
        print(f"Public test broker profile; project topic root: {root}", flush=True)
    else:
        os.environ.pop("TEAM12_TOPIC_ROOT", None)
        os.environ.pop("TEAM12_MQTT_TRANSPORT", None)
    local_test = os.getenv("TEAM12_LOCAL_SPLIT_TEST") == "1" and os.getenv("TEAM12_MQTT_HOST") == "localhost"
    if profile in ("public", "public-tls") or local_test:
        pass
    else:
        if not os.getenv("TEAM12_MQTT_HOST") or not os.getenv("TEAM12_MQTT_USERNAME"):
            raise SystemExit("Set TEAM12_MQTT_HOST, TEAM12_MQTT_USERNAME and TEAM12_MQTT_PASSWORD on both laptops.")
        if os.getenv("TEAM12_MQTT_TLS", "").lower() not in ("1", "true", "yes"):
            raise SystemExit("Set TEAM12_MQTT_TLS=true for the HiveMQ Cloud connection.")
    event = threading.Event()
    result = []
    client = connect("split-check")

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        result.append(reason_code)
        event.set()

    client.on_connect = on_connect
    client.loop_start()
    ok = event.wait(12)
    client.loop_stop()
    client.disconnect()
    if not ok or result[0].is_failure:
        raise SystemExit("MQTT broker did not accept this client; check internet and broker settings.")
    print("MQTT broker connection accepted", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("cloud", "device"))
    parser.add_argument("--broker", choices=("cloud", "public", "public-tls"), default="cloud")
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--line-speed", type=float, default=None,
                        help="virtual-line simulated seconds per real second; use 40 for a slower walkthrough")
    parser.add_argument("--limit", type=int, default=0,
                        help="quick check: send at most N records per company (0 = all)")
    parser.add_argument("--reset-db", action="store_true")
    parser.add_argument("--scenario", choices=("slowdown", "alarm", "healthy"), default="slowdown")
    parser.add_argument("--manual-replay", action="store_true",
                        help="wait for separate Company A and B dashboard Start buttons")
    parser.add_argument("--ml-driven", "--ml-arrivals", dest="ml_driven", action="store_true",
                        help="optional: each virtual stage's capacity follows the active model's "
                             "forecast for its machine, so the model decides the bottleneck")
    args = parser.parse_args()
    if args.speed is None:
        args.speed = 60 if args.broker.startswith("public") else 200
    if args.speed <= 0:
        parser.error("--speed must be positive")
    if args.line_speed is not None and (not math.isfinite(args.line_speed) or args.line_speed <= 0):
        parser.error("--line-speed must be a positive finite number")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    broker_check(args.broker)
    LOGS.mkdir(exist_ok=True)
    STOP_FILE.unlink(missing_ok=True)
    children = []
    handles = []
    control_client = None

    def start(name, command, env=None):
        handle = (LOGS / f"{name}.log").open("w", encoding="utf-8")
        handles.append(handle)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=handle,
                                stderr=subprocess.STDOUT, creationflags=flags)
        children.append((name, proc))
        print(f"{name} started (PID {proc.pid})", flush=True)
        return proc

    try:
        if args.role == "cloud":
            command = [sys.executable, str(ROOT / "scripts/init_db.py")]
            if args.reset_db:
                command.append("--reset")
            subprocess.run(command, check=True, cwd=ROOT)
            flow = prepare_flow()
            start("nodered", ["node", str(ROOT / "nodered/node_modules/node-red/red.js"),
                              "--userDir", str(ROOT / "nodered"), str(flow)])
            wait_port(1880, "nodered", seconds=180)
            wait_log("nodered", "Connected to broker:", seconds=180)
            for name, source, ready in (
                ("analytics", "analytics.py", "Watching " + os.getenv("TEAM12_TOPIC_ROOT", "team12") + "/observed/validated/#"),
                ("analytics_b", "analytics_b.py", "Company B analytics watching"),
                ("ml_demo", "ml_demo.py", "ML demo trainer ready"),
                ("decision", "decision.py", "Decision engine watching")):
                start(name, [sys.executable, "-u", str(ROOT / "src" / source)])
                wait_log(name, ready, seconds=60)
            print("Cloud laptop ready: http://localhost:1880/ui", flush=True)
        else:
            env = os.environ.copy()
            env["TEAM12_SCENARIO"] = "none" if args.scenario == "healthy" else args.scenario
            if args.line_speed is not None:
                env["TEAM12_SIM_SPEED"] = str(args.line_speed)
            if args.ml_driven:
                env["TEAM12_ML_DRIVEN"] = "1"
                print("ML-driven line ON: the active model's forecasts set the stage capacities", flush=True)
            requests = queue.Queue()
            replay_state = {"A": "ready", "B": "ready", "line": "not started"}
            replay_process = {}
            line_started = False
            last_status = 0.0

            def report(company, state):
                changed = replay_state[company] != state
                replay_state[company] = state
                control_client.publish(topic("replay_status"), json.dumps({
                    "company": company, "state": state, "ts_replay": now_iso()
                }), qos=1)
                if changed:
                    print(f"Company {company} replay: {state}", flush=True)

            def on_connect(client, _userdata, _flags, reason_code, _properties):
                if not reason_code.is_failure:
                    client.subscribe(topic("replay_control"), qos=1)
                    for company in replay_state:
                        report(company, replay_state[company])

            def on_message(_client, _userdata, message):
                try:
                    request = json.loads(message.payload)
                    if request.get("action") == "start" and request.get("company") in ("A", "B"):
                        requests.put(request["company"])
                    elif request.get("action") == "restart_line":
                        requests.put("line")
                except (ValueError, TypeError, AttributeError):
                    pass

            control_client = connect("replay-control")
            control_client.on_connect = on_connect
            control_client.on_message = on_message
            control_client.loop_start()
            if not args.manual_replay:
                requests.put("A")
                requests.put("B")
            print("Device ready for separate Company A and B replay requests", flush=True)
        while not STOP_FILE.exists():
            if args.role == "device":
                while not requests.empty():
                    company = requests.get_nowait()
                    if company == "line":
                        # Restart the virtual shift from t=0 (dashboard button).
                        if not line_started:
                            continue
                        for entry in [c for c in children if c[0] == "line_sim"]:
                            if entry[1].poll() is None:
                                entry[1].terminate()
                                try:
                                    entry[1].wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    entry[1].kill()
                            children.remove(entry)
                        start("line_sim", [sys.executable, "-u", str(ROOT / "src/line_sim.py")], env)
                        report("line", "restarted")
                        report("line", "running")
                        continue
                    # A finished company can be replayed again; a running one cannot.
                    if replay_state[company] not in ("ready", "completed", "error"):
                        report(company, replay_state[company])
                        continue
                    if not line_started:
                        start("line_sim", [sys.executable, "-u", str(ROOT / "src/line_sim.py")], env)
                        line_started = True
                        report("line", "running")
                        time.sleep(1)
                    command = [sys.executable, "-u", str(ROOT / "src/publisher.py" if company == "A"
                                                          else ROOT / "src/publisher_b.py"),
                               "--speed", str(args.speed)]
                    if args.limit:
                        command += ["--limit", str(args.limit)]
                    name = "publisher" if company == "A" else "publisher_b"
                    replay_process[company] = start(name, command)
                    report(company, "running")
                for company, proc in replay_process.items():
                    if replay_state[company] == "running" and proc.poll() is not None:
                        report(company, "completed" if proc.returncode == 0 else "error")
                if time.monotonic() - last_status >= 5:
                    for company in replay_state:
                        report(company, replay_state[company])
                    last_status = time.monotonic()
            for name, proc in children:
                if (proc.poll() is not None and proc.returncode
                        and name not in ("publisher", "publisher_b")):
                    raise RuntimeError(f"{name} exited with error; inspect logs/{name}.log")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if control_client is not None:
            control_client.loop_stop()
            control_client.disconnect()
        for name, proc in reversed(children):
            if proc.poll() is None:
                proc.terminate()
        for name, proc in reversed(children):
            if proc.poll() is None:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        for handle in handles:
            handle.close()
        STOP_FILE.unlink(missing_ok=True)
        print("Stopped this laptop's services", flush=True)


if __name__ == "__main__":
    main()
