# Live modification guide

The evaluation includes **live modification and debugging**. This page
lists the changes most likely to be asked for: which file to open, what to
expect, and how to prove it worked.

**The golden rule: almost everything lives in `config/config.yaml`.**
Edit it and restart the demo runner. In manual service mode, restart only the affected service.

Which service to restart:

| you changed | restart |
|---|---|
| `monitoring:` | `src/analytics.py` |
| `simulation:` | `src/line_sim.py` |
| `decision:` | `src/decision.py` |
| `replay:` | `src/publisher.py` |
| `ml:` | re-run `src/ml_features.py` then `src/ml_train.py` |
| `cleaning:` | re-run `src/clean.py` |

---

## 1. "Make the machine alert fire sooner / later"

**File:** `config/config.yaml` -> `monitoring`

```yaml
low_output_ratio: 0.60    # raise to 0.80 = alert on a smaller drop
sustained_slots: 3        # lower to 1 = alert immediately
```

**Expect:** with `low_output_ratio: 0.9` and `sustained_slots: 1`, almost
every machine alerts at once. With `0.2` and `6`, almost nothing alerts.

**Prove it:** restart `analytics.py`, re-run the publisher, and watch the
`ALERT` lines, or the alert panel on the dashboard.

---

## 2. "Make the virtual Stage 2 slower / faster"

**File:** `config/config.yaml` -> `simulation.stages`

```yaml
- name: "Stage 2 - Welding"
  rate_per_min: 0.80      # lower = less capacity
```

**Expect:** any stage set below `arrival_rate_per_min` (0.50) becomes a
permanent bottleneck - its queue grows for the whole run. Set every stage
above 0.50 and the queues stay short.

**Prove it:** `python src/scenario_compare.py` and look at "queue at end".

---

## 3. "Add a fourth stage"

**File:** `config/config.yaml` -> `simulation.stages`, add an entry:

```yaml
- name: "Stage 4 - Packing"
  rate_per_min: 0.70
```

Nothing else changes. The simulator builds stages from this list, the
dashboard series are driven by `stage_name`, and the decision engine loops
over whatever stages arrive.

**Prove it:** `python src/scenario_compare.py` prints four rows per table.

---

## 4. "Change which problem the virtual line has"

**File:** `config/config.yaml` -> `simulation.scenario`

```yaml
kind: "slowdown"      # "none" | "slowdown" | "alarm"
stage_index: 1        # 0-based: 1 = Stage 2
start_second: 7200
severity: 0.45        # slowdown only: 0.45 = 45% of normal speed
```

Or, without editing anything:

```bash
TEAM12_SCENARIO=alarm python src/line_sim.py
python scripts/run_demo.py alarm
```

**Expect:** `slowdown` produces a capacity constraint and rate commands;
`alarm` produces "investigate interruption" advice instead. That difference
is the point - the recommendation changes with the cause.

---

## 5. "Show me what happens without the queue-growth check"

**File:** `config/config.yaml` -> `decision`

```yaml
require_queue_growth: false
```

**Expect:** the engine starts "fixing" the healthy line. Stage 3 runs at
83% busy in a healthy line, so it looks suspicious whenever its queue is
briefly long. With the check on, a healthy line gets **zero** commands.

**Prove it:** `python src/scenario_compare.py` - compare the "healthy" row
with and without. This is a good thing to volunteer: it shows you know why
the rule is there.

Same idea for `warmup_seconds: 3600` -> set it to `0` and the engine reacts
to the line filling up at start-up, which is not a bottleneck.

---

## 6. "Make the decision engine more aggressive"

**File:** `config/config.yaml` -> `decision`

```yaml
rate_increase: 0.10          # 0.25 = bigger steps
cooldown_seconds: 1800       # 300 = act more often
max_rate_multiplier: 1.50    # the hard ceiling
max_commands: 6
```

**Expect:** the ceiling always holds. With `max_rate_multiplier: 1.0` the
engine cannot raise anything, and instead produces
*"escalate - automatic limit reached"*.

**Prove it:** `python tests/test_logic.py` -
`test_action_is_bounded_by_the_ceiling` asserts exactly this.

---

## 7. "Break the data and show me nothing silently breaks"

```bash
python src/publisher.py --inject-bad 5
```

**Expect:** every 5th record is published with `items: -5` and
`status: 99`. The validator rejects them, they land in
`rejected_records`, the "Records REJECTED" counter rises, and **the metrics
do not move**.

**Prove it:**

```sql
SELECT COUNT(*) FROM machine_events;     -- accepted
SELECT reason, COUNT(*) FROM rejected_records GROUP BY reason;
```

The metrics row count equals the accepted count, never the total sent.

---

## 8. "Replay different machines, or a different time window"

**File:** `config/config.yaml` -> `replay`

```yaml
assets: [0, 1, 8]
start: "2022-03-28 04:00:00+00:00"
end:   "2022-03-28 08:00:00+00:00"
speed: 60        # 1 = real time, 600 = very fast
```

Then rebuild the slice: `python src/clean.py`.

`results/audit.json` lists other windows with good coverage under
`replay_window_candidates`, so you can pick one with confidence.

---

## 9. "Change the forecast horizon"

**File:** `config/config.yaml` -> `ml`

```yaml
horizon_minutes: 30     # 60 = predict an hour ahead
lookback_slots: 6       # how much history goes in
```

Then:

```bash
python src/ml_features.py
python src/ml_train.py
```

**Expect:** a longer horizon is harder, so the error rises. The persistence
baseline gets relatively worse too, which is worth pointing out.

---

## 10. "Change something in Node-RED"

Open <http://localhost:1880>, edit the node, click **Deploy**.

- Validation rules live in the **"validate record"** function node. Its
  output 1 is accepted, output 2 is rejected.
- To add a dashboard chart: add a `ui_chart`, wire it to the function node
  that already has the value, set `msg.topic` to the series name.

Export afterwards (menu -> Export -> all flows) and overwrite
`nodered/flow.json` so your change is saved with the project.

---

## If something stops working

```bash
python scripts/stop_services.py     # request clean shutdown; wait for runner to exit
python scripts/run_demo.py --reset-db  # restart with a clean SQLite file
```

Then check `logs/` - every service writes its own log file.

A quick way to see whether a service is alive at all:

```bash
python scripts/listen.py            # prints every MQTT message
```

If nothing appears, the broker is not running or the services are not
connected.



