# Three-family model comparison

Predict **items produced by one machine in the next 30 minutes**. This is a machine forecast, not a measured production-line bottleneck.

Source: fixed Company A data; 681,935 complete consecutive examples; 45 past-only features.
Chronological split: 487,520 training / 91,338 validation / 102,992 test.
Validation: 2022-07-27 21:35:00+00:00 to 2022-09-13 21:05:00+00:00.
Test: 2022-09-13 21:35:00+00:00 to 2022-10-27 12:30:00+00:00.
A 25-minute label embargo prevents overlap at split boundaries. Windows touching a missing five-minute slot are excluded. Test data is used for final reporting only, never to choose or tune a model.

## The three different algorithms

1. **Traditional ML: Ridge regression.** A regularized linear model.
2. **Ensemble ML: histogram gradient boosting.** Sequential trees learn nonlinear interactions.
3. **Deep learning: feed-forward neural network.** Two hidden layers (32 and 16 units) learn nonlinear patterns from scaled inputs.

All three use the **same fixed dataset, features, time split and target**. They introduce no extra data. Negative count predictions are clipped to zero, as in the live service.

## How the winner was chosen

Selection used **4 rolling-origin validation folds**, not a single validation block. Each fold trains on an expanding prefix of the pre-test period and scores the stretch of time immediately after it, always forwards, with the same label embargo.

This matters here. On one validation block the three families finished within about 2% of each other - the same size as the tie-break rule - so the ranking could have been an accident of that particular seven-week window. Several folds show whether the ordering is stable.

| Model | Fold active MAE (each fold) | Mean | Worst fold |
|---|---|---:|---:|
| **gradient_boosting** | 2.139, 1.693, 1.556, 1.568 | 1.7390 | 2.1390 |
| neural_network | 2.072, 1.671, 1.661, 1.653 | 1.7642 | 2.0721 |
| ridge | 2.231, 2.001, 1.886, 1.921 | 2.0097 | 2.2308 |

**gradient_boosting** was selected. It is **1.45% ahead of neural_network on the fold mean** and **5.43% ahead on the most recent fold** (a larger number means gradient_boosting is further ahead). It does not win every fold.

### The honest reading

The two leading families are close - closer than the 2% tie margin - and the ranking **flips between folds**. Claiming one is decisively better than the other on this dataset would not survive a careful question.

What breaks the tie is *which* folds each wins. The idle share climbs steadily through the file, and the test period is the idlest stretch of all, so the latest fold is the closest thing we have to "how will this behave next month". The selection rule therefore settles a tie on the most recent fold before it ever looks at model size: accuracy evidence should answer an accuracy question, and size is only a deployment convenience.

The full fold table is printed above precisely so a reader can check that reasoning instead of taking the single mean on trust.

## Held-out test results

Reported after selection was locked. **Active MAE** is the error on windows where the machine really produced something. **Idle MAE** is how much output a model wrongly promises on windows where the machine produced nothing - a model that cries wolf on a stopped machine sends operators chasing work that is never coming. The last period is 81% idle windows, so overall MAE mostly measures idleness detection; all three columns are needed to judge a model fairly.

Zero-output share: training 32.7%, validation 75.5%, test 80.7%.

| Model | Family | Test Active MAE | Test Idle MAE | Test MAE | Test RMSE | Train s | Predict ms/1000 | MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ridge | traditional ML | 2.936 | 1.009 | 1.38 | 3.752 | 0.63 | 0.4 | 0.002 |
| **gradient_boosting** | ensemble ML | 2.346 | 0.39 | 0.767 | 3.048 | 14.38 | 13.37 | 1.042 |
| neural_network | deep learning | 2.392 | 0.519 | 0.879 | 3.232 | 56.82 | 1.04 | 0.071 |
| baseline_persistence | reference | 3.109 | 0.201 | 0.761 | 4.161 | 0.0 | 0.0 | 0.0 |
| baseline_machine_hour | reference | 9.877 | 19.005 | 17.248 | 20.617 | 0.0 | 0.0 | 0.0 |
| baseline_always_zero | reference | 32.141 | 0.0 | 6.187 | 16.05 | 0.0 | 0.0 | 0.0 |

## The model we actually ship

Once gradient_boosting was selected, it was refit on **all pre-test data** (training plus validation) and saved to `results/chosen_model.joblib`. Selection was already locked, so this cannot leak the test period; it simply lets the shipped model learn from the most recent weeks as well, which matters because the machines grow steadily more idle through the file.

| Fitted on | Test Active MAE | Test Idle MAE | Test MAE |
|---|---:|---:|---:|
| training block only | 2.346 | 0.39 | 0.767 |
| **all pre-test data (shipped)** | **2.338** | **0.369** | **0.748** |

On the held-out test the shipped model beats persistence on Active MAE and beats persistence on overall MAE. State both facts in the viva.

## Place in the IoT workflow

Company A CSV replay (sensor simulator) -> MQTT -> Node-RED validation -> SQLite. After a successful write, Node-RED republishes the validated record to MQTT for analytics. Analytics builds rolling metrics and past-only features, loads the selected model, and publishes a forecast. Node-RED stores and displays metrics and forecasts; the decision service publishes an operator advisory. A separate virtual-line detector sends bounded MQTT commands to a virtual actuator and receives acknowledgements. The real CSV has no verified stage route, queue, or physical actuator.

`scripts/verify_feature_parity.py` replays real records through the live path and checks every model input against the training table, so the numbers the model sees in the demo are the numbers it was trained on.

## Per-machine held-out test MAE

| Machine | Ridge | Gradient boosting | Neural network | Persistence |
|---:|---:|---:|---:|---:|
| 0 | 0.544 | 0.268 | 0.25 | 0.309 |
| 1 | 0.574 | 0.265 | 0.21 | 0.153 |
| 2 | 2.267 | 1.35 | 2.098 | 1.225 |
| 3 | 2.268 | 1.142 | 1.197 | 1.417 |
| 4 | 3.192 | 1.738 | 1.81 | 1.735 |
| 5 | 1.542 | 1.035 | 1.104 | 0.958 |
| 6 | 0.365 | 0.148 | 0.151 | 0.167 |
| 7 | 1.056 | 0.568 | 0.626 | 0.5 |
| 8 | 0.616 | 0.492 | 0.546 | 0.457 |

These scores are produced by this repository's code on the fixed Company A file, not copied from a paper. Timings depend on the computer.
