# Team split and simple demonstration runbook

For the click-by-click presentation demo, use [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## Who owns what

Give each person one folder or interface to own, plus a reviewer. The
publisher person is responsible for **one shared input stream**; the three
model people receive the same cleaned five-minute features so their
comparison is fair.

1. **Data and MQTT owner:** fixed Company A dataset, data audit, cleaning,
   replay publisher, MQTT broker, Node-RED validation and SQLite. Show one
   valid record stored and one bad record rejected. Files: src/clean.py,
   src/publisher.py, config/config.yaml, nodered/flow.json.
2. **Traditional model owner:** Ridge regression, feature scaling and
   regularization choice. Deliver the validation-fold scores and test
   scores using the common split. Files: src/ml_features.py and the Ridge
   part of src/ml_train.py.
3. **Ensemble model owner:** histogram gradient boosting and its validation
   scores. Explain nonlinear thresholds and why it was selected.
4. **Neural-network owner:** two-hidden-layer MLP and its validation
   scores. Explain that it was genuinely trained and compared, even though
   it was not the winner.
5. **Decision and feedback owner:** consume the selected model's forecast
   and publish an operator advisory. On the separate virtual line, detect
   a sustained growing queue, propose a bounded MQTT rate command for the
   operator to accept or reject, and show
   the virtual actuator acknowledgement. Files: src/decision.py and
   src/line_sim.py.
6. **Integration/presentation owner (if available):** run the entire demo,
   verify the dashboard, tests and slides, and check observed versus
   simulated labels. If there are only five people, this becomes a shared
   review responsibility.

**Important interface rule:** the three model owners share **evaluation
findings** (validation Active MAE, held-out test metrics, model file and
limitations). The winner is chosen on validation evidence. The live
decision engine consumes the **selected** model's forecast. Sending three
different live predictions to an actuator and choosing whichever looks
largest would not be a valid model comparison because the future answer
is unknown during the live run.

## What the numbers mean in one sentence each

- **Items per productive slot:** real recorded machine output when that
  machine was producing; machines are not ranked against each other.
- **Coverage:** share of expected five-minute reports received. Missing
  data lowers confidence; it does not mean zero production.
- **Forecast:** estimated item count for one machine in the next 30
  minutes. It is a prediction, not a measurement.
- **Active MAE:** average forecast error in items on windows where the
  machine actually produced; smaller is better.
- **Virtual queue:** simulated work waiting before a stage. A sustained
  growing queue plus high busy time supports a bottleneck finding.
- **Command and acknowledgement:** a bounded rate change sent by MQTT to
  the virtual actuator and its response.

## Suggested five-minute explanation to the examiner

1. Start the slowdown demo with `--reset-db`, then open
   http://localhost:1880/ui. Point to the **live SQLite storage** card:
   accepted rows, rejected rows, saved forecasts, command acknowledgements
   and five recent records come from SQL read-back every four seconds.
2. Point to the validation bar chart, four-fold trend and three-model table.
   State that Ridge, boosted trees and a
   neural network used the **same data, target and forward-in-time
   validation folds**. Mean validation Active MAE was 2.010, 1.739 and
   1.764 respectively. Gradient boosting won. The scores are close, so
   do not call it overwhelmingly superior.
3. Point to the live forecast and machine table. Explain that the selected,
   refit boosted model predicts the next 30 minutes. The decision service
   can recommend an operator inspect low expected output. This is an
   advisory about observed machines, not a physical control command.
4. Point to the virtual-line queue and action. Explain that stage order
   and queues are simulated because the CSV has none. In slowdown mode
   the detector finds Stage 2. Accept the proposed command on the dashboard;
   it then sends the bounded change by MQTT and gets
   an acknowledgement. Use the queue and busy-time graphs to explain the
   constraint, then point to the *simulated* no-action versus with-action
   comparison: 202 versus 223 completed, 1805s versus 829s average wait.
5. Click each demo training button and compare its validation error. Select
   one for live forecasts, then restore the full-study winner. The quick
   training scores are from a smaller subset and have a separate label.
6. Run `scripts/show_database.py` or `scripts/check_demo.py --require-command --require-review`
   in another terminal. Explain that validated records are stored before
   analytics receives them, while rejected records stay separate. End with
   the limitation: simulated throughput improvements are not factory
   measurements.

**Why these three algorithms?** Ridge is a simple linear reference,
gradient boosting is a nonlinear tree ensemble, and the two-layer MLP is a
neural model. They cover the three families in the project architecture.
Random Forest would also be an ensemble, but it was not trained in this
comparison; do not claim it scored worse. Gradient boosting was selected
from the models that were actually trained using forward-in-time validation.

## Reliable demo commands

Run setup once from the extracted team12 folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
.\.venv\Scripts\python.exe tests\test_logic.py
```

For a short dashboard rehearsal:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py slowdown --reset-db --once --speed 1000
.\.venv\Scripts\python.exe scripts\check_demo.py
```

For a presentation showing the actuator, use:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py slowdown --reset-db --speed 200
```

While that command remains running, open a **second terminal** in the
project folder and run:

```powershell
.\.venv\Scripts\python.exe scripts\check_demo.py --require-command
.\.venv\Scripts\python.exe scripts\show_database.py
```

Open the dashboard while the runner is active. The quick run closes after
the replay; the slower run stays open so you can speak and inspect SQLite.
All four live graphs and the model, stored-record, machine and stage tables
are on the Production Monitor page. Omit `--reset-db` to retain earlier runs.

## What to hand back to the team

Each owner should submit: changed source files, the exact command run,
passing tests, generated result files, a short explanation of the result,
and one limitation. Avoid editing the same file at the same time; use
separate branches or agree on file ownership. The data owner should not
replace or modify the fixed source CSV.


