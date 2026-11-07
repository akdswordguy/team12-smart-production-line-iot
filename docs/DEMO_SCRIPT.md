# Presentation demo script (about 15 minutes)

This script shows every box of the architecture diagram: IoT devices →
MQTT broker → Node-RED → dashboard and SQLite → analytics and ML →
decision engine → MQTT control command → actuator acknowledgement.

It works on **two laptops** or on **one laptop with two project folders**.
Either way the two roles talk only through the HiveMQ public broker.

On Windows, `launchers/windows/` does the setup and start steps below with
double-clicks (`1_start_processing.cmd`, then `2_start_device.cmd` or
`2b_start_device_ml.cmd`), including one-laptop runs.

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
- *Interactive ML lab*: **Train and use** on Ridge trains it and switches
  live forecasts in one click. A box shows each machine's forecast before
  and after the switch, and a red dashed line marks the switch on the
  *Forecast trend* chart. **Restore full-study winner** switches back. Identical
  scores on every click are expected: same data, split and seed.
  **Train with new seed** on gradient boosting or the neural network
  retrains with a random seed; after a few clicks the card shows the mean
  and range across seeds. Say: "the range shows how much of a difference is
  just randomness; we never pick the luckiest seed." Ridge has no
  randomness, so its score never changes.

**4. The bottleneck (diagram steps 5, 7, 8).** About three minutes after
Start the device slows Stage 2. The *Virtual queue trend* climbs and
*Stage busy time* stays at 100%. When **Approve a proposed bottleneck
action** appears, read the evidence, click **Accept and send command**, and
show the command and the device's acknowledgement. Reject the next
proposal to show that nothing is sent without approval.

**5. Live model check.** *Forecast vs what really happened* scores each
forecast against the real next 30 minutes once they have arrived: the
average error per model, a forecast-vs-actual chart and the latest checks.
Company B shows its live next-state hit rate beside the same-state guess.

**6. Closed-loop performance.** The panel shows the command round trip
(Accept → device → ACK), record → forecast latency, model compute time,
acknowledgement rate, operator decisions, the shortest gap between
commands (cooldown, no rapid switching), zero actions on a healthy line,
and the offline control effect (202 → 223 items, wait −54%).

**7. Proof.** In a second PowerShell window on the processing role:

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

Add `--ml-driven` to the **device** command (in the one-laptop
`hivemq-test` setup, start `2b_start_device_ml.cmd` instead of
`2_start_device.cmd`). Each stage keeps its machine (Stage 1, 2, 3 <-
machine 0, 1, 8). The active model's 30-minute forecast for that machine
becomes the stage's capacity, demand is set near capacity and no fault is
scripted, so the model decides the bottleneck. The *Stage status* table
gains a **Model capacity** column, and each proposal says which forecast
caused it, for example "the demo_neural_network model forecasts machine 0
at 17.9 items in 30 min, so this stage can do 0.60 tokens/min". Use
**Train and use** to switch models during the shift and watch the queues,
busy time and proposals change. This is an extension: the standard results
in `results/` were produced without it.

## Backup plans

- HiveMQ blocked: restart both roles with `--broker public-tls`.
- No internet: on the processing role alone,
  `.\.venv\Scripts\python.exe scripts\run_demo.py slowdown --reset-db --line-speed 40`
  (local broker, both companies start automatically).
- Something stuck: Ctrl+C both roles, start them again, press Start again.
