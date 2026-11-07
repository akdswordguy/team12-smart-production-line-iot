# Team 12 - Smart Production-Line Monitoring and Bottleneck Detection

B.Tech CSE, Semester 7 - IoT mini-project.

For the live teacher demonstration, start with [START_HERE.md](START_HERE.md).
For the no-payment two-laptop route, follow [docs/PUBLIC_BROKER_DEMO.md](docs/PUBLIC_BROKER_DEMO.md).
For the private HiveMQ Cloud trial setup, follow [docs/TWO_LAPTOP_DEMO.md](docs/TWO_LAPTOP_DEMO.md).

A closed-loop IoT prototype built on both companies in the fixed
[SME Manufacturing Dataset](https://github.com/HumanCenteredTechnology/SME-Manufacturing-Dataset).

Real Company A and B machine records are replayed over MQTT, validated and stored
by Node-RED in SQLite, then forwarded after a successful write to
the analytics service. The dashboard shows rolling indicators and a
30-minute Company A output forecast. Company B has its own operating-state
analytics and a nine-month interruption comparison chart. Because the dataset contains no stage
order, no queues and no waiting times, line-level analysis runs on a
clearly labelled **virtual production line**, where a decision engine
detects the limiting stage, requests operator approval for a bounded MQTT
command, receives an
acknowledgement, and the effect is measured against an identical run with
no action.

> **The one thing to remember:** this project keeps **observed** data and
> **simulated** results strictly apart - in the MQTT payloads, in the
> database tables, and on the dashboard. No simulated improvement is ever
> described as a real factory measurement.

---

## Quick start

This folder includes the unchanged fixed Company A CSV and Company B ZIP, cleaned events,
training features, replay slice, trained model and measured results. No other
dataset is substituted. The raw CSV's SHA-256 checksum is checked by
`scripts/fetch_dataset.py` and recorded in `PACKAGE_MANIFEST.json` when packaged.

### Windows (PowerShell, Python 3.12 and Node.js; the Codex Python runtime also works)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
.\.venv\Scripts\python.exe tests\test_logic.py
.\.venv\Scripts\python.exe scripts\run_demo.py slowdown --reset-db --speed 200
```

The last command is the local rehearsal and automatically starts the MQTT broker, Node-RED, SQLite,
analytics, interactive model trainer, virtual line, decision engine and dataset replay. It loads
`nodered/flow.json` with the correct local database path. Open
<http://localhost:1880/ui> while the replay runs. The single
**Production Monitor** page shows live SQLite row counts and recent stored
records for both companies, a nine-month A/B comparison, a three-model
Company A evaluation with validation-fold and cost metrics, live
training and model-selection controls, machine and stage tables, four trends,
operator approval and command acknowledgement. The
slowdown command creates a demonstrable virtual bottleneck and keeps the
dashboard open until stopped. `--reset-db` makes this run start clean; omit
it on later runs to retain earlier database records.

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py slowdown --speed 200
# Other modes:
.\.venv\Scripts\python.exe scripts\run_demo.py alarm
.\.venv\Scripts\python.exe scripts\run_demo.py bad
.\.venv\Scripts\python.exe scripts\run_demo.py healthy
```

After you accept a proposed virtual action, `.\.venv\Scripts\python.exe scripts\check_demo.py --require-command --require-review` checks MQTT persistence, forecast advice, the operator review and actuator acknowledgement. Press Ctrl+C in the runner, or from another terminal run
`.\.venv\Scripts\python.exe scripts\stop_services.py`. Logs are written under `logs/`.
To show the database directly, run `.\.venv\Scripts\python.exe scripts\show_database.py`
in a second terminal. The live file is `db/team12.db`.

### Linux/macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm install --prefix nodered
.venv/bin/python scripts/run_demo.py
```

The runner is portable; `scripts/run_demo.sh` is a Bash wrapper for it.


### Reproduce all data and results

```bash
python scripts/fetch_dataset.py       # fixed Company A source file
python src/audit.py                    # raw-data audit
python src/clean.py                    # cleaned slots, replay and baselines
python src/ml_features.py              # complete forecast windows
python src/ml_train.py                 # retrain and compare models
python src/ml_train_b.py               # Company B's separate three-model classification study
python scripts/compare_companies.py    # fixed A/B monthly interruption comparison
python scripts/update_company_dashboard.py # refresh A/B and B-model panels
python scripts/update_dashboard.py     # refresh saved scores on dashboard
python src/scenario_compare.py         # virtual-line before/after
python tests/test_logic.py             # 60 tests
```

The unchanged raw CSV and prepared features are included in this Desktop
folder so training can be reproduced offline. The fetch script can also
download repository revision `0d37af3` and verifies Company A's SHA-256 checksum.
The optional `--recorder` flag runs without Node-RED for diagnostics; the
normal graded demo should use Node-RED and its dashboard.

---

## What you get

| Output | Where |
|---|---|
| Data audit of the raw files | `docs/DATA_AUDIT.md` |
| Changes made to the supplied ZIP | `docs/REPAIR_NOTES.md` |
| Assumptions and limits | `docs/ASSUMPTIONS.md` |
| Three-family model comparison | `results/MODEL_RESULTS.md` |
| Virtual-line before/after | `results/SCENARIO_RESULTS.md` |
| Live MQTT, Node-RED and SQLite verification | `results/LIVE_INTEGRATION.md` |
| ML workflow and team explanation | `docs/ML_WORKFLOW.md` |
| Architecture check and teacher demo evidence | `docs/WORKFLOW_CHECK.md` |
| What every file does | `docs/CODE_MAP.md` |
| Presentation view and speaking order | `docs/PRESENTATION_RUNBOOK.md` |
| Step-by-step demo script (two laptops or one) | `docs/DEMO_SCRIPT.md` |
| Team work plan and demo order | `docs/TEAM_ROADMAP.md` |
| Prompt for AI-assisted teammate tasks | `docs/AI_HANDOFF_PROMPT.md` |
| How to change things live | `docs/LIVE_MODIFICATION_GUIDE.md` |
| Likely viva questions | `docs/VIVA_NOTES.md` |
| Topics and payloads | `docs/MQTT_SPEC.md` |

---

## Headline results

**Data audit** (measured, not quoted from the paper):

- 1,520,330 rows, 9 machines, Mar 2021 - Oct 2022
- status `0` (idle) **never occurs**; only 1, 2 and 3 appear
- `alarm` equals `status == 3` in **every** row - redundant, and a leakage
  risk
- `power_avg` reaches 16,777,216 (2^24); 7 rows are flagged as sensor faults
- 18,687 rows report items produced with `cycle_time == 0`
- the real reporting interval is **300 s**, not the 60 s the paper describes

**Virtual line** (all simulated, identical arrivals in both runs):

| Scenario | What the engine did | Completed | Avg wait (s) |
|---|---|---|---|
| healthy | nothing | 223 -> 223 | 357 -> 357 |
| Stage 2 slowdown | 6 rate commands to **Stage 2** | 202 -> **223** | 1805 -> **829** |
| Stage 2 alarm | advice "investigate interruption", then 2 commands to **Stage 3** | 223 -> 224 | 1003 -> 897 |

The detector finds the stage we deliberately broke, and leaves a healthy
line alone.

The alarm row is worth reading carefully. Stage 2 stops at t=7200s. At
t=7801s the engine says **"investigate interruption"** and sends *no* rate
command - speeding up a stopped machine achieves nothing. Once Stage 2
restarts at t=10800s its backlog floods downstream, and only then does the
engine add capacity, to **Stage 3**, which is now the constraint. Same
detector, different cause, different action.

**Forecasting** (next 30 minutes of machine output; all use the same fixed dataset):

| Family and algorithm | Validation Active MAE (mean of 4 folds) | Test Active MAE | Test Idle MAE | Test MAE |
|---|---:|---:|---:|---:|
| Traditional ML — Ridge regression | 2.010 | 2.936 | 1.009 | 1.380 |
| **Ensemble ML — gradient boosting (selected)** | **1.739** | **2.338** | 0.369 | **0.748** |
| Deep learning — two-layer neural network | 1.764 | 2.392 | 0.519 | 0.879 |
| Simple persistence reference | 2.067 | 3.109 | **0.201** | 0.761 |

The model is chosen on **four rolling-origin validation folds**, before the
later test period is evaluated. A single validation block put gradient
boosting and the neural network 2.2% apart — the same size as the tie-break
rule — so the folds exist to show whether that ordering is real. It is not
unanimous: the neural network wins the first two folds and gradient
boosting the last two. Gradient boosting is 1.45% ahead on the fold mean
and 5.43% ahead on the most recent fold, which is the fold whose idle share
most resembles the test period.

Because 80.7% of test windows have zero output, we report **Active MAE**
(error when the machine is really producing) and **Idle MAE** (output
wrongly promised from a stopped machine) alongside overall MAE. The shipped
model beats persistence on both Active MAE and overall MAE. See
results/MODEL_RESULTS.md and docs/ML_WORKFLOW.md.


**Closed-loop performance** (measured live; timings depend on the computer and network):

| Measure | How it is measured | Result |
|---|---|---|
| Command round trip | operator Accept -> MQTT command -> device applies -> ACK back, both ends on the processing laptop's clock | 0.36-0.39 s over the HiveMQ public broker; about 2 ms on a local broker |
| Record -> forecast | Node-RED receipt -> validation -> SQLite -> MQTT -> analytics -> forecast | shown live on the dashboard (average and p95) |
| Stability | commands on a healthy line; shortest gap between commands | 0 commands; gaps never below the 1,800 s cooldown |
| Live forecast accuracy | each forecast scored against the real next 30 minutes once they arrive | gradient boosting about 0.7 items average error on the replay day |
| Control effect (simulated) | identical arrivals, Stage 2 slowdown, with vs without action | 202 -> 223 items, wait 1805 -> 829 s |

The dashboard's **Closed-loop performance** panel and `scripts/check_demo.py`
read these from the `loop_metrics` table.

---

## Folder structure

```
config/config.yaml      main thresholds, rates and horizons
data/raw/               the fixed dataset, read-only, never modified
data/processed/         cleaned slots, replay slice, baselines
db/schema.sql           separate observed A, observed B and simulated tables
docs/                   audit, assumptions, code map, viva notes
logs/                   one log file per service
nodered/flow.json       the Node-RED flow loaded by the runner
results/                audit, model and scenario outputs
scripts/                dataset fetch, broker, db init, demo runner
src/                    the services (one job per file)
tests/test_logic.py     60 tests, no pytest required
```

---

## Acceptance checks

The brief lists measurable checks. How to verify each:

| Check | How |
|---|---|
| A record travels MQTT -> SQLite -> dashboard | `scripts/listen.py`, then `SELECT * FROM machine_events LIMIT 5`, then the dashboard chart |
| An invalid record is flagged, metrics uncorrupted | `python src/publisher.py --inject-bad 5`; `rejected_records` fills and the bad event produces no metric |
| A sustained slowdown creates a bottleneck and a growing queue | `python src/scenario_compare.py` - Stage 2's queue grows; `test_slowing_a_stage_makes_its_queue_grow` |
| An approved decision produces a command and acknowledgement | Accept a dashboard proposal; `logs/decision.log` shows the operator acceptance then `[ack] ... accepted`; `sim_reviews` records the choice |
| With/without action use the same arrivals | both runs report the same `tokens_arrived` (229); `test_same_seed_gives_the_same_arrivals` |
| Forecast metrics come from held-out later timestamps | `results/model_comparison.json` -> `split.test_period` |
| Dashboard labels identify observed/forecast/simulated | every group title and chart label says which; payloads carry `source` |

---

## Known limits

Set out in full in `docs/ASSUMPTIONS.md`. The short version:

- The dataset cannot prove a real line bottleneck; queues and waiting times
  come only from the virtual line.
- Starvation is not measurable on real data, because status 0 never occurs.
- `cycle_time` is capped at 60 s despite five-minute record spacing,
  so it is only a reported timing indicator, not verified time-per-product.
- Virtual stage rates are **calibrated** from real output (p90 while
  producing), not measured from a real line. The stage order is our
  assumption.
- We do not train a bottleneck classifier: this dataset has no verified
  bottleneck labels.

## Dataset citation

```bibtex
@article{atzeni2023data,
  title={Data-driven insights through industrial retrofitting: An anonymized
         dataset with machine learning use cases},
  author={Atzeni, Daniele and Ramjattan, Reshawn and Figli{\`e}, Roberto and
          Baldi, Giacomo and Mazzei, Daniele},
  journal={Sensors}, volume={23}, number={13}, pages={6078}, year={2023},
  publisher={MDPI}
}
```

The scores in `results/` are **ours**, produced by the scripts in this
repository. We do not reuse the paper's published figures.
















