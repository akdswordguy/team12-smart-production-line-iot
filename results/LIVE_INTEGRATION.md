# Live integration evidence for the three-model project

Tested on Windows with Python 3.12, Node-RED 5.0.9,
node-red-dashboard 3.6.6 and node-red-node-sqlite 2.0.1.
The fixed Company A replay slice and the model chosen from the
three-family comparison were used. Each run resets SQLite first.
In the commands below, python means the project's virtual environment
Python (on Windows: .\.venv\Scripts\python.exe).

## Validation-first model training

Command: python src/ml_train.py

- 681,935 complete consecutive examples, 45 past-only features
- 487,520 train / 91,338 validation / 102,992 later test examples
- 25-minute purge at split boundaries; no shuffled records
- Validation Active MAE: Ridge 2.007, gradient boosting 1.698,
  two-hidden-layer neural network 1.735
- **Gradient boosting selected on validation before test evaluation**
- Held-out test Active MAE: gradient boosting 2.346 versus
  persistence 3.109
- Held-out overall MAE: gradient boosting 0.767 versus persistence
  0.761 (the simple reference is slightly better on this measure)

All results, including RMSE, per-machine errors, training time,
prediction latency and model size, are in MODEL_RESULTS.md and
model_comparison.json.

## Full MQTT and actuator run

Command: python scripts/run_demo.py slowdown --once --speed 200

- SQLite machine_events: **146**
- SQLite machine_metrics: **146**
- SQLite forecasts: **129**, all tagged gradient_boosting
- SQLite forecast_advisories: **129**
- SQLite sim_state: **873**
- SQLite sim_commands: **6** rows, representing three Stage 2
  rate commands and three accepted acknowledgements
- Node-RED SQLite errors: **0**

Command: python scripts/check_demo.py --require-command

Every check passed: stored records, metrics, selected-model forecasts,
ML advisories, virtual state, source separation, accepted actuator
acknowledgements and no SQLite errors. The decision log records commands
at simulated t=11,160 s, 12,960 s and 17,460 s. The dashboard served
at http://localhost:1880/ui while the services ran.

## Invalid-record run

Command: python scripts/run_demo.py bad --once --speed 1000

- SQLite machine_events: **132**
- SQLite rejected_records: **14**
- SQLite machine_metrics: **132**
- SQLite forecasts: **62**, all tagged gradient_boosting
- SQLite forecast_advisories: **62**
- Node-RED SQLite errors: **0**

Command: python scripts/check_demo.py --require-rejected

Every check passed. The fourteen deliberately corrupted records
entered rejected_records, while analytics received only Node-RED's
stored-and-validated MQTT messages. No rejected record produced a
rolling-metric row.

## Quick normal smoke run

Command: python scripts/run_demo.py --once --speed 1000

Stored 146 events, 146 metric rows, 129 selected-model forecasts
and 129 advisories. The integration checker passed.

## Logic and limits

Command: python tests/test_logic.py

**30/30** tests passed, including past-only features, gap handling,
split-boundary purge, validation-only model selection, Node-RED-to-analytics
routing, healthy-line restraint, bounded control and simulated queue growth.

This proves the **software path**: fixed dataset replay -> MQTT ->
Node-RED validation -> SQLite -> validated MQTT -> analytics/model ->
forecast and advisory -> Node-RED dashboard and database. The separate
virtual line sends MQTT state, receives bounded commands and acknowledges
them. The file has no verified real stage route or queue, so it cannot
establish a measured factory bottleneck or factory throughput gain.


## Reviewed presentation update

The reviewed project adds an Explain to Sir dashboard tab alongside the
original Detailed charts. The tab presents the fixed data flow, three-model
comparison, selected forecast, virtual queue, command and actuator
acknowledgement in plain language. The updated logic suite passed 36/36.

The presentation-ready run used python scripts/run_demo.py slowdown --once --speed 200. It stored 146 machine events, 146 metrics, 129 forecasts, 129 advisories, 912 virtual-state rows and 6 command/acknowledgement rows. python scripts/check_demo.py --require-command passed; Node-RED logged no SQLite errors. This verifies the new dashboard flow deployed alongside the original IoT path.

