# Code map - what every file does

Read this before the viva. Each file has one job and is small enough to
read in a few minutes.

## The short version

```
config/config.yaml        main thresholds, rates and horizons. Start here.
src/common.py             config loading, MQTT connect, topic names
src/audit.py              Phase 1: checks our claims about the raw data
src/clean.py              Phase 1: quality flags, 5-min slots, baselines
src/publisher.py          the virtual IoT node - replays real records
src/analytics.py          rolling indicators, alerts, live forecast
src/line_sim.py           the VIRTUAL line + the actuator
src/decision.py           bottleneck rules + the control command
src/scenario_compare.py   before/after evidence (no MQTT, repeatable)
src/ml_features.py        turns slots into learning examples
src/ml_train.py           compares 3 models + 3 baselines, picks one on CV folds
src/recorder.py           optional: SQLite writer, mirrors the Node-RED flow
nodered/flow.json         the Node-RED flow (loaded by run_demo.py)
db/schema.sql             the database, observed and simulated kept apart
tests/test_logic.py       36 tests of the logic we claim in the viva
```

---

## File by file

### `config/config.yaml`
The main thresholds, rates, machine ids and forecast horizon.
If an evaluator asks you to change behaviour, this is
almost always the file to open. See `LIVE_MODIFICATION_GUIDE.md`.

### `src/common.py` (~90 lines)
The only shared code. `CONFIG` (the parsed YAML), `path()` for file paths,
`connect()` for MQTT (retries, so services can start in any order),
`publish()` so every message is serialised the same way.

### `src/audit.py` (~290 lines)
Reads the raw CSV and **measures** the things we assert: which status codes
exist, whether `alarm` duplicates `status == 3`, how extreme the power
outliers are, how many rows have items with zero cycle time, the real gap
between records, and which 4-hour windows have good coverage.
Writes `docs/DATA_AUDIT.md` and `results/audit.json`.
Most of its length is report formatting, not logic.

### `src/clean.py` (~190 lines)
Never deletes a row. Adds `power_ok` / `cycle_ok` flags, snaps records onto
a 5-minute grid, and builds:
- `data/processed/events_clean.csv` - slots for training
- `data/processed/replay_slice.csv` - the 146 records used in the demo
- `data/processed/baseline.json` - each machine's normal output per hour,
  **measured only over slots where it was producing**
- `results/calibration.json` - the rates we copy into the virtual line

### `src/publisher.py` (~130 lines)
Reads the replay slice and publishes it over MQTT at a configurable speed,
with both timestamps on every message. `--inject-bad N` corrupts every Nth
record so you can show validation working.

### `src/analytics.py` (~250 lines)
Consumes Node-RED's stored-and-validated messages, keeps a 6-slot rolling window per machine, and
publishes indicators and alerts. Compares each machine with **its own**
baseline at the same hour. Publishes a 30-minute forecast when a trained
model exists. Three parts, clearly separated: `validate`, `compute_metrics`,
`classify`.

### `src/line_sim.py` (~300 lines)
Two classes. `Stage` is one station (one token at a time, a queue, counters).
`Line` steps the whole thing forward one simulated second. It has **no MQTT
inside the simulation**, so tests and `scenario_compare.py` can use it
directly. `main()` adds the MQTT service and the actuator.

The important trick: each token's "effort" at each stage is drawn once when
it is created, and service time is `effort / rate`. Re-running with a
different rate therefore changes only the speed, never the randomness.

### `src/decision.py`
`choose_action(state, memory)` is a **pure function** - same input, same
output, no clock, no network. The live service and the offline comparison
both call it, so the demo and the written results cannot disagree. The live service also turns machine forecasts into explicit advisories; only virtual-line states can trigger actuator commands.

A stage is flagged only when it is busy, its queue is **growing**, and both
have held for several checks. A stopped stage gets different advice.

### `src/scenario_compare.py` (~220 lines)
Runs each scenario twice (with and without the engine) on identical
arrivals and writes `results/SCENARIO_RESULTS.md`. This is where the
before/after numbers come from.

### `src/ml_features.py` (~190 lines)
Builds learning examples. Lays each machine on a complete 5-minute grid so
gaps stay visible, builds lag features from **past** slots only, and the
target from **future** slots only. Any window touching a gap is dropped.
Also builds the live feature vector, in the same column order.

### ml_train.py
Chronological split on timestamps. Three references (always-zero,
persistence, machine-hour mean) and three distinct trained families:
Ridge, histogram gradient boosting and a two-hidden-layer neural network.

Selection runs on **rolling-origin cross-validation** (`rolling_origin_folds`
builds expanding-window folds inside the pre-test period), never on the
later test period. `choose_model` applies three rules in order: lowest fold
mean, then the best most-recent fold, then the smaller saved model. The
most-recent fold matters because the data drifts - machines grow steadily
more idle through the file.

Reports Active MAE (machine producing), **Idle MAE** (output wrongly
promised while the machine is stopped), overall MAE, RMSE, training time,
prediction latency and model size. After selection is locked it refits the
winner on all pre-test data and saves that as the shipped model.

Tunables live in `config/config.yaml` under `ml`: `cv_folds` and
`selection_tie_margin`.

### `src/recorder.py` (~210 lines)
Optional. Writes MQTT messages into SQLite with the same SQL as the
Node-RED flow. Use it when Node-RED is not running. **Do not run it at the
same time as Node-RED** or everything is stored twice.

### `nodered/flow.json`
37 nodes. MQTT in -> validate -> parameter binding -> SQLite -> validated MQTT, plus one responsive Production Monitor dashboard with four live graphs, model evaluation and live SQLite read-back. The validation
function node has two outputs: good records to machine_events, bad ones
to rejected_records and nowhere else. Only a successful SQLite write
forwards a record to the analytics service.

### `db/schema.sql`
Eight tables. `machine_*` is observed, `sim_*` is simulated, `forecasts` and `forecast_advisories` are
predictions and ML-based recommendations. **There is no table containing both**, so no query can mix
them by accident.

### `tests/test_logic.py`
Runs with plain `python`, no pytest needed. Covers validation, alert
classification, the decision rules (including that a healthy line is left
alone), simulator conservation and determinism, and the two leakage tests.

---

## Scripts

| script | what it does |
|---|---|
| `scripts/fetch_dataset.py` | downloads the fixed dataset, makes it read-only |
| `scripts/init_db.py` | creates the database (`--reset` to wipe it) |
| `scripts/run_broker.py` | a pure-Python MQTT broker, if you have no Mosquitto |
| `scripts/listen.py` | prints every MQTT message, with its source label |
| `scripts/setup_windows.ps1` | installs Python and Node-RED dependencies |
| `scripts/run_demo.py` | starts the full demo, including Node-RED, on Windows and Unix |
| `scripts/show_database.py` | prints stored SQLite counts, recent observed rows, forecasts and commands |
| `scripts/update_dashboard.py` | refreshes dashboard evaluation figures from saved model and simulator results |
| `scripts/verify_project.py` | checks the fixed CSV hash, saved model and dashboard before a demo |
| `scripts/run_demo.sh` | Bash wrapper for the portable runner |
| `scripts/stop_services.py` | asks the portable runner to cleanly stop its children |
| `scripts/verify_feature_parity.py` | replays real records through the live path and checks every model input against the training table |

## How the pieces talk

```
replay_slice.csv -> publisher.py -> MQTT observed/machine
                                      |
                                      v
                                    Node-RED validation
                                      |
                        +-------------+-------------+
                        | valid                     | invalid
                        v                           v
                    SQLite machine_events      rejected_records
                        |
                        v (only after SQL success)
                    MQTT observed/validated
                        |
                        v
                    analytics.py -> MQTT metrics, alerts, forecast
                                      |
                                      v
                            Node-RED -> SQLite and dashboard
                                      |
                                      v
                        decision.py -> MQTT forecast advisory

virtual line -> MQTT sim/state -> decision.py -> MQTT sim/command
     ^                                              |
     +--------------- virtual actuator <-----------+
                           |
                           v
                       MQTT sim/ack
```


