# Workflow check for the teacher demo

## What the supplied architecture asks for

The image shows: sensor or dataset replay → MQTT → Node-RED → dashboard and
database → analytics and three model families → performance comparison →
decision → MQTT command → actuator or simulator → new sensor state.

This project implements that flow with **three clearly separated paths**.

1. **Observed machine path.** The unchanged Company A CSV is replayed as a
   virtual IoT sensor. MQTT carries records to Node-RED. Node-RED validates
   them, writes accepted or rejected records to separate SQLite tables, and
   only then republishes accepted records for `analytics.py`. Analytics
   computes live machine indicators and a next-30-minute forecast using the
   saved selected model. Its forecast goes to `decision.py`, which publishes
   an operator advisory. Predictions, advisories and indicators are also
   stored in SQLite and shown on the dashboard.
2. **Virtual production-line path.** `line_sim.py` publishes stage queues,
   busy share and throughput over MQTT. `decision.py` checks sustained queue
   growth and high busy share, proposes a bounded rate command, and waits
   for an operator's accept/reject choice. Only an accepted proposal reaches
   the actuator. The simulator applies accepted commands
   and publishes subsequent states. Node-RED stores states, commands and
   acknowledgements and operator reviews in `sim_*` tables. The dashboard shows the feedback.
3. **Company B observed-state path.** The unchanged `company_B.zip` supplies
   a separate one-minute replay. MQTT carries B records to Node-RED, which
   validates and stores them in `company_b_events` before republishing them.
   `analytics_b.py` computes rolling state indicators; Node-RED stores these
   in `company_b_metrics`. B does not enter A's item-output model.

The A/B chart uses January–September 2022, the nine complete shared months.
It compares the machine-equal percentage of Alarm reports among Production
or Alarm reports. A averages 7.19%, B 8.55%; A is lower in seven months.
This is a conditional interruption proxy, not a throughput or overall
efficiency ranking. B also reports Standby, Loading, Tooling and MachineOn;
its report density is much lower, so the chart shows that context.

The three model candidates are **trained offline** on the same fixed data,
target, feature set and forward-in-time splits. Their scores are compared
before the later test period is opened. The live service loads only the
selected model by default. The dashboard also offers a *separate* quick
training experiment: buttons retrain Ridge, boosting and neural models on
the same 50,000 prepared rows from the weeks before replay, split forward in time with a 25-minute
label embargo. A shared per-machine upper forecast guard comes only from
training-period targets; guarded live forecasts are marked. Each result is
saved to `ml_demo_runs`. After training, a
user can activate any of those models for subsequent live forecasts or
restore the full-study winner. These quick scores are not the full-study
scores, and the simulated line's control rule does not depend on them.

## What the dataset can and cannot prove

Company A has timestamps, machine IDs, item counts, status, power and
reported cycle time. The repository does **not** provide machine-to-machine
product routes, actual queues, waiting times or a measured finished-line
throughput. Therefore the project cannot claim it discovered the real
factory's physical bottleneck or improved the real factory. The bottleneck
and control results are from a labelled, reproducible virtual line. This is
the scientifically honest interpretation of the fixed dataset.

The upstream repository describes the Company A fields at
<https://github.com/HumanCenteredTechnology/SME-Manufacturing-Dataset>.
The exact Company A file in this folder has SHA-256
`888838fe508a42e83c55f39ad4898566ef5e3dcc354edbac84000c8def49629a`.

## Model choice, in short

- **Ridge regression:** traditional linear model; easy and fast, but less
  suited to nonlinear thresholds.
- **Histogram gradient boosting:** nonlinear ensemble of sequential trees;
  selected from the actual validation evidence.
- **Two-layer neural network:** neural comparison; trained and evaluated on
  the same examples.

Mean validation Active MAE across four time-ordered folds is **2.010**
(Ridge), **1.739** (boosting) and **1.764** (neural). The two best models are
close: boosting leads by only 1.45% on the mean, and the neural model wins
the first two folds. The latest fold favours boosting by 5.43%, which breaks
the predeclared 2% tie. After selection, the chosen model was refit on all
pre-test data. Its held-out Active MAE is **2.338**, against **3.109** for a
simple persistence reference.

This is a **regression** problem: show MAE and RMSE, plus Active MAE and
Idle MAE because the late test period is mostly idle. Accuracy, precision,
recall and F1 apply to classification tasks, not this item-count forecast.
The dashboard also shows training time, prediction latency, model size and
all four validation folds. Random Forest would be another ensemble option,
but it was not trained here; do not say that boosting beat it.

## How to prove storage and control live

1. Run `python scripts/run_demo.py slowdown --reset-db --speed 200` from the
   project folder. The runner creates the MQTT broker, Node-RED, analytics,
   decision engine and virtual line. `--reset-db` is only for a clean
   presentation; omitting it preserves prior SQLite runs.
2. Open <http://localhost:1880/ui>. The **Saved records** section runs SQL
   read-back every four seconds: accepted and rejected rows, forecasts,
   sent and acknowledged commands, and the five latest stored machine rows.
   This demonstrates actual database persistence, rather than merely showing
   messages in a chart.
3. Scroll to **Why this model was selected**. Show the validation bar chart,
   fold trajectories, held-out errors and computation table.
4. Click each **Train demo model** button, show active/idle/overall MAE,
   then choose one for live forecasts. Restore the full-study winner after
   the demonstration.
5. Scroll to machine forecasts and virtual queue/busy graphs. When Stage 2
   slows, inspect the proposal. **Accept** sends the bounded MQTT command;
   **Reject** records the refusal without sending it. The virtual actuator
   acknowledges only a sent command.
6. In a second terminal, run `python scripts/show_database.py` and
   `python scripts/check_demo.py --require-command --require-review`.

The saved scenario comparison uses an automatic acceptance policy with identical simulated arrivals and shows
**202 → 223** completed items (+10.4%) and **1805 → 829 seconds** average
wait (−54.1%) with control versus no control. These are simulation results.

## Useful next experiments

- Add Random Forest as a **fourth** model only if the teacher asks. Train and
  score it on the same rolling folds, then update the dashboard from the new
  report; do not swap algorithms based on preference alone.
- Add a realized-forecast error monitor once the replay covers the future
  30-minute window; compare forecast to actual output by machine.
- If physical line sensors later become available, map product routes and
  measure real queues and waiting times. Only then can the system make a
  real-line bottleneck claim or send a physical control command.
