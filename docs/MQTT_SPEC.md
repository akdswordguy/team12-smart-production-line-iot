# MQTT topics and message formats

Every topic name is defined once, in `config/config.yaml` under `topics`.
Change it there and every service follows.

## The rule that governs every message

Each payload carries a **`source`** field with exactly one of three values:

| `source` | meaning | where it may be shown |
|---|---|---|
| `observed` | a real Company A record, or something computed from real records | labelled "OBSERVED" |
| `simulated` | produced by the virtual line | labelled "SIMULATED" |
| `forecast` | a model prediction about the future | labelled "FORECAST" |

Nothing on the dashboard or in the database mixes them.

## Two timestamps, always

| field | meaning |
|---|---|
| `ts_dataset` | when the factory actually recorded this, in 2021-2022 |
| `ts_replay` | when our publisher sent it, today |

This is why a live demo cannot be mistaken for live factory data. The
dashboard shows both, and `machine_events` stores both.

---

## `team12/observed/machine/<asset>`
Published by `src/publisher.py`, one message per replayed record.

```json
{
  "schema_version": 1,
  "source": "observed",
  "run_id": "0b892b6d",
  "seq": 17,
  "asset": 1,
  "ts_dataset": "2022-03-28T04:05:00+00:00",
  "ts_replay": "2026-10-27T00:31:12.345678+00:00",
  "items": 8.0,
  "status": 2,
  "status_time": 43.0,
  "power_avg": 2.0,
  "cycle_time": 0.0,
  "power_ok": true,
  "cycle_ok": false
}
```

`run_id` + `asset` + `ts_dataset` is unique, so restarting the replay
cannot create duplicate rows (`INSERT OR IGNORE`).

`power_ok` / `cycle_ok` are the quality flags from `src/clean.py`. `false`
means the reading exists but we do not trust it.

## team12/observed/validated/<asset>
Node-RED republishes a valid observed record to this topic **after SQLite
accepts the machine-event write**. Its JSON body is the same as the raw
observed message above. src/analytics.py subscribes here, so a record
rejected by Node-RED cannot create metrics, forecasts or decisions. The
optional Python recorder mirrors this route when Node-RED is absent.

## `team12/observed/metrics/<asset>`
Published by src/analytics.py after every stored, validated record.

```json
{
  "source": "observed",
  "asset": 1,
  "ts_dataset": "2022-03-28T04:25:00+00:00",
  "ts_replay": "...",
  "window_slots": 6,
  "rolling_items": 20.0,
  "items_per_slot": 3.33,
  "items_per_productive_slot": 3.33,
  "productive_share": 1.0,
  "alarm_share": 0.0,
  "cycle_time_indicator": 41.2,
  "coverage": 1.0,
  "baseline_items_per_slot": 3.0,
  "baseline_ratio": 1.111,
  "baseline_hour": 4
}
```

`baseline_ratio` is this machine against **its own** history at the same
hour of day. It is `null` when the machine has no productive slots in the
window (then `alarm_share` is the thing to look at).

## `team12/observed/alert`
Published only when a machine's state **changes**, so the dashboard is not
flooded with the same message.

```json
{
  "source": "observed",
  "asset": 1,
  "level": "warning",
  "kind": "interruption",
  "recommendation": "investigate interruption",
  "message": "Machine 1: 100% of the last 5 records were in alarm state ...",
  "ts_dataset": "...",
  "ts_replay": "..."
}
```

`kind` is one of `interruption`, `underperformance`, `insufficient_data`,
`cleared`.

## `team12/forecast/<asset>`
Published by src/analytics.py when the selected trained model is present.
The model field is also saved in SQLite for traceability.

```json
{
  "source": "forecast",
  "asset": 1,
  "model": "gradient_boosting",
  "horizon_minutes": 30,
  "predicted_items": 10.38,
  "ts_dataset": "...",
  "ts_replay": "..."
}
```

---

## `team12/decision/forecast_advisory`
Published by the decision service after a forecast. This is a recommendation
about observed-machine output, not a physical control command. Comparison
with the machine's own productive baseline is made only when the recent
window has full coverage and high productive share.

```json
{
  "source": "forecast",
  "asset": 1,
  "predicted_items": 2.0,
  "expected_items": 18.0,
  "recommendation": "inspect machine or replan workload",
  "reason": "ML predicts 2.0 items in 30 minutes versus 18.0 expected..."
}
```

---

## `team12/sim/state`
Published by `src/line_sim.py` once per simulated minute. **Simulated.**

```json
{
  "source": "simulated",
  "sim_second": 11160,
  "ts_replay": "...",
  "stages": [
    {
      "stage_index": 1,
      "stage_name": "Stage 2 - Welding",
      "rate_per_min": 0.36,
      "configured_rate": 0.8,
      "queue_length": 5,
      "busy_share": 1.0,
      "starved_share": 0.0,
      "completed": 94,
      "avg_wait_seconds": 612.5,
      "is_down": false
    }
  ],
  "line_completed": 88,
  "line_throughput_per_hour": 28.4,
  "avg_wait_seconds": 663.4,
  "tokens_in_system": 12
}
```

`busy_share` and `starved_share` cover the **last 15 simulated minutes**
(`simulation.metrics_window_seconds`), not the whole run.

## `team12/sim/command`  (decision engine -> actuator)

```json
{
  "source": "simulated",
  "command_id": "f4cb4db6",
  "action": "increase_rate",
  "sim_second": 11160,
  "stage_index": 1,
  "stage_name": "Stage 2 - Welding",
  "old_rate": 0.36,
  "new_rate": 0.396,
  "reason": "Stage 2 - Welding is the limiting stage (busy 100%, queue 5, ...)"
}
```

`action` is currently only `increase_rate`. The actuator **refuses**
anything else, and says so in the acknowledgement.

## `team12/sim/ack`  (actuator -> everyone)

```json
{
  "source": "simulated",
  "command_id": "f4cb4db6",
  "sim_second": 11161,
  "action": "increase_rate",
  "stage_index": 1,
  "accepted": true,
  "old_rate": 0.36,
  "new_rate": 0.396,
  "reason": "rate updated"
}
```

Every command gets an acknowledgement, including refusals
(`"accepted": false`).

## `team12/sim/alert`
Scenario injections and the engine's advice (for example "investigate
interruption" when a stage is stopped rather than slow).

---

## Watching the traffic

```bash
python scripts/listen.py                 # everything
python scripts/listen.py team12/sim/#    # just the virtual line
```

It prints an `OBSERVED` / `SIMULATED` / `FORECAST` label on every message,
which is a quick way to show in the viva that the separation is real.
