# Presentation demo script (about 15 minutes)

This script shows every box of the architecture diagram: IoT devices →
MQTT broker → Node-RED → dashboard and SQLite → analytics and ML →
decision engine → MQTT control command → actuator acknowledgement.

It works on **two laptops** or on **one laptop with two project folders**.
Either way the two roles talk only through the HiveMQ public broker.

## Once, before the day

1. Extract the **same** project ZIP for each role (two laptops, or two
   separate folders on one laptop). The same ZIP gives the same
   `config/public_broker.json` topic root.
2. Processing role (Python 3.12 and Node.js):
   `powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1`
3. Device role (Python only):
   `powershell -ExecutionPolicy Bypass -File scripts\setup_device_windows.ps1`
4. Rehearse once on the classroom network. If port 8000 is blocked, use
   `--broker public-tls` in both commands below.

## Two minutes before presenting

Processing role:

```powershell
.\.venv\Scripts\python.exe scripts\two_laptop.py cloud --broker public --reset-db
```

Wait for `Cloud laptop ready`, then open <http://localhost:1880/ui>.

Device role:

```powershell
.\.venv\Scripts\python.exe scripts\two_laptop.py device --broker public --scenario slowdown --manual-replay --line-speed 40
```

Wait for `Device ready`. Both dashboard cards should say **Device: ready**.
At `--line-speed 40` the simulated eight-hour shift lasts about 12 minutes
after the first Start; use `--line-speed 20` for about 24 minutes.

## The demonstration

**1. Architecture (1 minute).** The device role replays real Company A and
B records as sensors and runs a virtual production line with an actuator.
The processing role runs Node-RED, SQLite, the models and the decision
engine. Observed data and simulated results are always labelled separately.

**2. Start the data (diagram steps 1-3).** Click **Start Company A**, then
**Start Company B**. "This run" counts rise towards 146 and 1,526. Each
record goes device → HiveMQ → Node-RED validation → SQLite, and only after
a successful write is it forwarded to analytics. **Saved records** is read
back from the database every four seconds.

**3. ML while the line warms up (diagram step 4, about 3 minutes).**
- *Company A vs B*: live bars from this run; nine-month graph from the full
  datasets (offline).
- *Why this model was selected*: three families (Ridge, gradient boosting,
  neural network), four time-ordered folds, gradient boosting chosen. The
  table shows ML performance (MAE, RMSE) and computational performance
  (training time, prediction time, size).
- *Interactive ML lab*: **Train demo model** on Ridge, then **Use for live
  forecasts**. The *Next 30-minute output* panel changes immediately to
  Ridge's forecast. **Restore full-study winner** switches back. Identical
  scores on every click are expected: same data, split and seed.

**4. The bottleneck (diagram steps 5, 7, 8).** About three minutes after
Start the device slows Stage 2. The *Virtual queue trend* climbs and
*Stage busy time* stays at 100%. When **Approve a proposed bottleneck
action** appears, read the evidence, click **Accept and send command**, and
show the command and the device's acknowledgement. Reject the next
proposal to show that nothing is sent without approval.

**5. Closed-loop performance.** The panel shows the command round trip
(Accept → device → ACK), record → forecast latency, model compute time,
acknowledgement rate, operator decisions, the shortest gap between
commands (cooldown, no rapid switching), zero actions on a healthy line,
and the offline control effect (202 → 223 items, wait −54%).

**6. Proof.** In a second PowerShell window on the processing role:

```powershell
.\.venv\Scripts\python.exe scripts\check_demo.py --require-command --require-review
```

Every line should say PASS, followed by the measured latencies.

## Showing it again without restarting

- **Restart virtual shift** (under the approval card) starts a new
  simulated shift on the device. The detector, cooldown and command budget
  reset, so the bottleneck can be shown again.
- **Replay Company A again** / **Replay Company B again** appears after a
  replay finishes. Analytics restarts that company's live window, and the
  card shows "this run" next to the total stored.

## Optional: let the chosen model drive the line

Add `--ml-arrivals` to the **device** command. The active model's 30-minute
forecasts for the replayed machines are compared with each machine's
normal output (training baselines); the mean ratio scales how much
material reaches Stage 1, bounded between 0.7× and 1.3×. The Stage status
card shows the current scale and model. Switching models can then change
which stage becomes the bottleneck. This is an extension: the standard
results in `results/` were produced without it.

## Backup plans

- HiveMQ blocked: restart both roles with `--broker public-tls`.
- No internet: on the processing role alone,
  `.\.venv\Scripts\python.exe scripts\run_demo.py slowdown --reset-db --line-speed 40`
  (local broker, both companies start automatically).
- Something stuck: Ctrl+C both roles, start them again, press Start again.
