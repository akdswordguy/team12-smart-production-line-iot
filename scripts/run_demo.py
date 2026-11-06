"""Portable live demo runner: broker -> Node-RED -> analytics/simulator/decision -> replay."""
import argparse
import math
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
STOP_FILE = LOGS / "stop.request"
sys.path.insert(0, str(ROOT / "src"))
from common import CONFIG, path  # noqa: E402


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_port(port, name, seconds=35):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port):
            return
        time.sleep(0.25)
    raise RuntimeError(f"{name} did not open port {port}; inspect logs/{name}.log")


def wait_log(name, phrase, seconds=35):
    log = LOGS / f"{name}.log"
    deadline = time.time() + seconds
    while time.time() < deadline:
        if log.exists() and phrase in log.read_text(encoding="utf-8", errors="replace"):
            return
        time.sleep(0.25)
    raise RuntimeError(f"{name} did not report readiness; inspect logs/{name}.log")


def prepare_flow():
    """Write a local flow with an absolute SQLite path for any launch directory."""
    source = ROOT / "nodered" / "flow.json"
    target = ROOT / "nodered" / "flow.local.json"
    flow = json.loads(source.read_text(encoding="utf-8"))
    databases = [node for node in flow if node.get("type") == "sqlitedb"]
    if len(databases) != 1:
        raise RuntimeError("Expected one SQLite configuration node in flow.json")
    databases[0]["db"] = str(path("sqlite"))
    broker = next(node for node in flow if node.get("id") == "mqtt_broker")
    broker["broker"] = os.getenv("TEAM12_MQTT_HOST", CONFIG["mqtt"]["host"])
    broker["port"] = os.getenv("TEAM12_MQTT_PORT", str(CONFIG["mqtt"]["port"]))
    broker["usetls"] = os.getenv("TEAM12_MQTT_TLS", "false").lower() in ("1", "true", "yes")
    broker["verifyservercert"] = broker["usetls"]
    if os.getenv("TEAM12_MQTT_TRANSPORT") == "websockets":
        broker["broker"] = f"ws://{broker['broker']}:{broker['port']}/mqtt"
        broker["usetls"] = False
        broker["verifyservercert"] = False
    root = os.getenv("TEAM12_TOPIC_ROOT", "team12").strip("/")
    broker["clientid"] = "node-red-team12-" + hashlib.sha256(root.encode()).hexdigest()[:12]
    if os.getenv("TEAM12_MQTT_USERNAME"):
        broker["credentials"] = {"user": os.environ["TEAM12_MQTT_USERNAME"],
                                 "password": os.getenv("TEAM12_MQTT_PASSWORD", "")}
    serialized = json.dumps(flow, indent=2)
    if root != "team12":
        serialized = serialized.replace("team12/", root + "/")
    target.write_text(serialized, encoding="utf-8")
    return target


def main():
    ap = argparse.ArgumentParser(description="Run the complete Team 12 MQTT demo")
    ap.add_argument("mode", nargs="?", default="slowdown",
                    choices=("slowdown", "alarm", "healthy", "bad"))
    ap.add_argument("--speed", type=float, default=None,
                    help="dataset seconds per real second (default from config)")
    ap.add_argument("--line-speed", type=float, default=None,
                    help="virtual-line simulated seconds per real second; use 40 for a slower walkthrough")
    ap.add_argument("--limit", type=int, default=0,
                    help="replay at most N records; 0 means all")
    ap.add_argument("--once", action="store_true",
                    help="stop all services after the replay and 3 seconds to flush")
    ap.add_argument("--reset-db", action="store_true",
                    help="clear SQLite before this run; default keeps prior runs")
    ap.add_argument("--recorder", action="store_true",
                    help="use SQLite recorder without Node-RED (diagnostics only)")
    args = ap.parse_args()
    if args.speed is not None and args.speed <= 0:
        ap.error("--speed must be positive")
    if args.line_speed is not None and (not math.isfinite(args.line_speed) or args.line_speed <= 0):
        ap.error("--line-speed must be a positive finite number")
    if args.limit < 0:
        ap.error("--limit cannot be negative")

    if not path("replay_slice").exists() or not path("baseline").exists():
        raise SystemExit("Replay data missing. Run python src/clean.py after fetching the dataset.")
    if not args.recorder and not (ROOT / "data/processed/company_b_replay.csv").exists():
        raise SystemExit("Company B replay missing. Run python scripts/prepare_company_b.py.")
    if not args.recorder and not (ROOT / "nodered" / "node_modules" / "node-red" / "red.js").exists():
        raise SystemExit("Node-RED missing. Run scripts/setup_windows.ps1 (Windows) or npm install --prefix nodered.")
    LOGS.mkdir(exist_ok=True)
    STOP_FILE.unlink(missing_ok=True)
    children = []
    log_handles = []
    b_metrics_before = 0

    def start(name, command, env=None):
        stream = (LOGS / f"{name}.log").open("w", encoding="utf-8")
        log_handles.append(stream)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, creationflags=flags)
        children.append((name, proc))
        print(f"  {name}: PID {proc.pid}")
        return proc

    try:
        print(f"Team 12 live demo: {args.mode}")
        if port_open(CONFIG["mqtt"]["port"]):
            print("  using existing MQTT broker")
        else:
            start("broker", [sys.executable, "-u", str(ROOT / "scripts" / "run_broker.py")])
            wait_port(CONFIG["mqtt"]["port"], "broker")

        with (LOGS / "init_db.log").open("w", encoding="utf-8") as init_log:
            db_command = [sys.executable, str(ROOT / "scripts" / "init_db.py")]
            if args.reset_db:
                db_command.append("--reset")
            subprocess.run(db_command, cwd=ROOT, check=True, stdout=init_log)
        print(f"  SQLite: {path('sqlite')} "
              f"({'fresh database' if args.reset_db else 'preserving earlier runs'})")
        if not args.recorder:
            with sqlite3.connect(path("sqlite")) as conn:
                b_metrics_before = conn.execute("SELECT COUNT(*) FROM company_b_metrics").fetchone()[0]

        if args.recorder:
            start("recorder", [sys.executable, "-u", str(ROOT / "src" / "recorder.py")])
            wait_log("recorder", "Recording everything")
        else:
            flow = prepare_flow()
            start("nodered", ["node", str(ROOT / "nodered" / "node_modules" /
                                           "node-red" / "red.js"),
                               "--userDir", str(ROOT / "nodered"), str(flow)])
            wait_port(1880, "nodered", seconds=180)
            wait_log("nodered", "Connected to broker:", seconds=180)
            print("  dashboard: http://localhost:1880/ui")

        start("analytics", [sys.executable, "-u", str(ROOT / "src" / "analytics.py")])
        if not args.recorder:
            start("analytics_b", [sys.executable, "-u", str(ROOT / "src" / "analytics_b.py")])
        start("ml_demo", [sys.executable, "-u", str(ROOT / "src" / "ml_demo.py")])
        env = os.environ.copy()
        env["TEAM12_SCENARIO"] = {"healthy": "none", "bad": "slowdown"}.get(
            args.mode, args.mode)
        if args.line_speed is not None:
            env["TEAM12_SIM_SPEED"] = str(args.line_speed)
        start("line_sim", [sys.executable, "-u", str(ROOT / "src" / "line_sim.py")], env)
        start("decision", [sys.executable, "-u", str(ROOT / "src" / "decision.py")])
        wait_log("analytics", "Watching team12/observed/validated/#")
        if not args.recorder:
            wait_log("analytics_b", "Company B analytics watching")
        wait_log("ml_demo", "ML demo trainer ready")
        wait_log("decision", "Decision engine watching")
        time.sleep(0.5)

        command = [sys.executable, "-u", str(ROOT / "src" / "publisher.py")]
        if args.speed is not None:
            command += ["--speed", str(args.speed)]
        if args.limit:
            command += ["--limit", str(args.limit)]
        if args.mode == "bad":
            command += ["--inject-bad", "10"]
        publisher = start("publisher", command)
        publisher_b = None
        if not args.recorder:
            b_command = [sys.executable, "-u", str(ROOT / "src" / "publisher_b.py")]
            if args.speed is not None:
                b_command += ["--speed", str(args.speed)]
            publisher_b = start("publisher_b", b_command)
        print("  replay running; follow logs/*.log or open the dashboard.")
        print("  Ctrl+C or python scripts/stop_services.py to stop.")

        while not STOP_FILE.exists():
            if publisher.poll() is not None:
                if publisher.returncode:
                    raise RuntimeError("Publisher failed; inspect logs/publisher.log")
                print("  replay complete")
                if args.once:
                    if publisher_b is not None:
                        print("  waiting for Company B replay to finish")
                        publisher_b.wait()
                        if publisher_b.returncode:
                            raise RuntimeError("Company B publisher failed; inspect logs/publisher_b.log")
                    target = sum(1 for _ in (ROOT / "data/processed/company_b_replay.csv").open(
                        encoding="utf-8")) - 1
                    deadline = time.time() + 90
                    while time.time() < deadline and not STOP_FILE.exists():
                        with sqlite3.connect(path("sqlite")) as conn:
                            written = conn.execute("SELECT COUNT(*) FROM company_b_metrics").fetchone()[0] - b_metrics_before
                        if written >= target:
                            break
                        time.sleep(0.5)
                    if STOP_FILE.exists():
                        break
                    if written < target:
                        raise RuntimeError(f"Company B analytics did not drain: {written}/{target} metrics")
                    time.sleep(2)
                    break
                publisher = None
            for name, proc in children:
                if name == "publisher_b":
                    if proc.poll() is not None and proc.returncode:
                        raise RuntimeError("Company B publisher failed; inspect logs/publisher_b.log")
                    continue
                if name == "publisher" or name == "line_sim":
                    continue
                if proc.poll() is not None:
                    raise RuntimeError(f"{name} exited; inspect logs/{name}.log")
            time.sleep(0.5)
            if publisher is None:
                # Keep monitoring and the dashboard available until stopped.
                while not STOP_FILE.exists():
                    for name, proc in children:
                        if name == "publisher_b":
                            if proc.poll() is not None and proc.returncode:
                                raise RuntimeError("Company B publisher failed; inspect logs/publisher_b.log")
                            continue
                        if name not in ("publisher", "line_sim") and proc.poll() is not None:
                            raise RuntimeError(f"{name} exited; inspect logs/{name}.log")
                    time.sleep(0.5)
                break
    except KeyboardInterrupt:
        print("\nStopping on Ctrl+C")
    finally:
        for name, proc in reversed(children):
            if proc.poll() is None:
                proc.terminate()
        for name, proc in reversed(children):
            if proc.poll() is None:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        for stream in log_handles:
            stream.close()
        STOP_FILE.unlink(missing_ok=True)
        print("Services stopped. Logs are in logs/.")


if __name__ == "__main__":
    main()


