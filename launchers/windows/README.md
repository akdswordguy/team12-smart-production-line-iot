# Double-click launchers (Windows)

Run the full HiveMQ demo without typing commands. Both roles connect only
through the free public broker `broker.hivemq.com`, under the topic root in
`config/public_broker.json`.

| File | What it does |
|---|---|
| `0_stop_everything.cmd` | Stops every demo process these launchers started. Use it before a fresh run or if a window was closed abruptly. |
| `1_start_processing.cmd` | **Processing role**: Node-RED, SQLite, analytics, decision engine and the dashboard. Starts with a fresh database. When it prints `Cloud laptop ready`, open <http://localhost:1880/ui>. |
| `2_start_device.cmd` | **Device role**: replays Company A and B as IoT sensors and runs the virtual line (slowdown scenario, about 12 minutes per shift). Waits for the dashboard's Start buttons. |
| `2b_start_device_ml.cmd` | Same device role, but the active model's forecasts set each stage's capacity, so the model decides the bottleneck. Use instead of `2_start_device.cmd`. |

## Order

1. `0_stop_everything.cmd` (optional, for a clean start)
2. `1_start_processing.cmd`, wait for `Cloud laptop ready`
3. `2_start_device.cmd` (or `2b_start_device_ml.cmd`)
4. Open <http://localhost:1880/ui>, click **Start Company A** and **Start Company B**, and accept a proposal when it appears.

To stop, close the two windows or run `0_stop_everything.cmd`.

## One laptop or two

- **One laptop:** run all of the above on it.
- **Two laptops:** clone or extract the same project on both. Run `1_start_processing.cmd`
  on the processing laptop and `2_start_device.cmd` on the device laptop.
  The topic root must match, so use the same `config/public_broker.json` on both.

The device role always runs from a sibling folder named `<project folder>-device`,
which the launcher creates and refreshes each time (it skips `.git`, `.venv`,
`node_modules`, logs, the database and the large raw dataset). This keeps the two
roles' logs and stop requests apart when they share one laptop.

## First run and requirements

- Python 3.12 (`py -3.12`) on both roles; Node.js only for the processing role.
- The first start installs packages (`scripts\setup_windows.ps1` or
  `scripts\setup_device_windows.ps1`), which takes a few minutes and needs internet.
- Output is also saved to `logs\launcher_processing.log` and
  `<project folder>-device\logs\launcher_device.log`.

## If something goes wrong

- **`db\team12.db` is still in use**: close any database viewer, run `0_stop_everything.cmd`, and start again.
- **Port 1880 already in use**: an older demo is still running; run `0_stop_everything.cmd`.
- **No connection to the broker**: check the internet connection; some networks block port 8000.
