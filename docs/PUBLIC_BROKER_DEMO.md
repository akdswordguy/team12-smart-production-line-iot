# Free public HiveMQ broker: two-laptop demo

This path needs **no HiveMQ account, license, payment card, hostname entry or MQTT password**. Both laptops connect to HiveMQ's shared public test broker. The project uses a unique topic root stored in `config/public_broker.json`; use the **same ZIP** on both laptops so the topic root matches.

The tested connection here is MQTT over WebSocket at `ws://broker.hivemq.com:8000/mqtt`. It is **unencrypted and unauthenticated**. Everyone using the public broker can subscribe to topics, and a random-looking topic root is only collision avoidance, not access control. Use the supplied public manufacturing dataset and the virtual line only. Never put passwords, private data or a physical actuator on this broker. HiveMQ does not guarantee uptime for its public test service.

## Easiest: double-click launchers

`launchers/windows/` runs everything below without typing: `1_start_processing.cmd`
on the processing laptop, `2_start_device.cmd` (or `2b_start_device_ml.cmd` for the
ML-driven line) on the device laptop, and `0_stop_everything.cmd` to stop. On one
laptop, run both there: the device role runs from a sibling `<folder>-device` copy
that the launcher keeps up to date. See `launchers/windows/README.md`.

## Prepare once

1. Extract the same project ZIP on both laptops. Keep both connected to the internet.
2. **Processing laptop:** install Python and Node.js, then in PowerShell from the extracted project folder run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
   ```

3. **Device laptop:** install Python; Node.js is not needed. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_device_windows.ps1
   ```

## Run in this order

On the **processing laptop**:

```powershell
.\.venv\Scripts\python.exe scripts\two_laptop.py cloud --broker public --reset-db
```

Wait for `Cloud laptop ready`, then open `http://localhost:1880/ui` on that laptop. This is its local dashboard, while both MQTT clients use the online HiveMQ broker.

On the **device laptop**:

```powershell
.\.venv\Scripts\python.exe scripts\two_laptop.py device --broker public --scenario slowdown --manual-replay --line-speed 40
```

The device waits for the dashboard's **Start Company A** and **Start Company B** buttons. Click either first, then the other; both streams can run together. Their MQTT topics, SQLite tables and analytics remain separate. The dashboard shows both streams' status and counts, a live conditional alarm comparison, and the fixed dataset's nine-month A/B graph. The virtual line starts with the first company. When a proposed Stage 2 action appears, click **Accept and send command**. The virtual device applies the rate change and sends an acknowledgement back through the public broker. On the processing laptop, verify the database:

```powershell
.\.venv\Scripts\python.exe scripts\check_demo.py --require-command --require-review
```

For a short connection rehearsal, add `--speed 200 --limit 60` to the **device** command. Omit `--limit` for the complete replay. To stop, press Ctrl+C in each role's terminal, or run `scripts\stop_services.py` in each project folder.

Omit `--manual-replay` for the original automatic A+B start. On one physical laptop with HiveMQ, extract the project into two **separate** folders on that computer and run the cloud and device commands in separate terminals. Both folders need the same `config/public_broker.json`.

The virtual line normally runs its eight-hour scenario at 240 simulated seconds
per real second (about two minutes). The manual command above uses
`--line-speed 40` for a slower walkthrough (about 12 minutes). This pacing
does not change the fixed dataset or offline model results. Once the simulated
shift ends, the virtual actuator stays connected but rejects late commands with
an explanatory ACK; accept a proposed action before the shift ends to show an
actual rate change.

If `broker.hivemq.com:8000` is blocked on your network, the public broker also offers MQTT over TLS on port 8883. Both laptops can try `--broker public-tls` instead of `--broker public`; do not mix profiles during a rehearsal. This computer could connect on 8000, while its outbound 8883 connection timed out.

## Showing it again, and the optional ML-driven line

After a replay finishes, its card offers **Replay Company A again** (or B). **Restart virtual shift** under the approval card starts a new simulated shift on the device and resets the detector, so the bottleneck can be shown again without restarting either role. Adding `--ml-driven` to the device command makes each stage's capacity follow the active model's forecast for its machine, so the model decides the bottleneck; see `docs/DEMO_SCRIPT.md`.

## What was verified here

On 2026-11-07 a complete run over `ws://broker.hivemq.com:8000/mqtt` used two separate project folders on one Windows laptop: 146/146 Company A and 1,526/1,526 Company B records were stored, three demo models were trained, two operator-approved Stage 2 commands were acknowledged in 0.36-0.39 s, one proposal was rejected, and `check_demo.py --require-command --require-review` passed every check. An earlier merged build had lost a few records during a temporary disconnect; Node-RED now keeps a persistent MQTT session and dashboard buttons use QoS 1. The included `db/team12.db` comes from a later complete local-broker run that also records the closed-loop timings; see `results/MERGED_VERIFICATION.md`. `--reset-db` starts a fresh presentation run.

The public broker is shared and may disconnect or lose messages. Rehearse on the classroom network and both physical laptops before presenting. A local broker on the processing laptop can be used if the public broker is unreliable, provided the device laptop can reach it.
