"""Ask the portable demo runner to stop and clean up its own child services."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
logs = root / "logs"
logs.mkdir(exist_ok=True)
request = logs / "stop.request"
request.write_text("stop\n", encoding="utf-8")
print("Stop requested. The demo runner will close its services and logs.")

