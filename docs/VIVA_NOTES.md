# Viva notes

Answers to the questions you are most likely to be asked. Every number here
is reproducible by running the commands shown.

---

## The one-minute summary

> We built the full loop the brief asks for: real machine records replayed
> over MQTT, validated and stored by Node-RED in SQLite, then
> forwarded to analytics for rolling indicators and a 30-minute forecast.
> We trained and compared a linear model, an ensemble and a neural network.
>
> The dataset records nine **independent machines** - no stage order, no
> queues, no waiting times - so a real line bottleneck cannot be verified
> from it. We say that openly. Real data gives us machine-level
> under-performance; a clearly labelled **virtual line** gives us queues,
> the limiting stage, a control command, an acknowledgement, and a
> measurable before/after. Nothing simulated is ever presented as a factory
> measurement.

---

## Q: What is a bottleneck, exactly?

The stage whose effective capacity limits the rate of the whole line. In a
line with capacities 12, 9 and 11 units/hour, the middle stage caps the line
at 9.

**Low output alone does not identify it.** A machine can be producing little
because it is slow, because it is stopped, or because nothing is arriving
for it to work on. Those need different responses, which is why our engine
distinguishes them.

## Q: Why can't you find the bottleneck in the real data?

Three things are missing: the **order** of the stages, the **movement of
items** between them, and the **queues**. `company_A.csv` has
`ts, asset, items, status, status_time, power_avg, cycle_time, alarm` and
nothing about flow. Machine 4 produced 752,754 items and machine 6 produced
133,526, but that is because they make different products, not because one
feeds the other.

So on real data we report a *capacity-constraint candidate*, and we test
*bottleneck detection* on the virtual line, where we know the right answer
because we caused the problem.

## Q: Then what does the real data actually prove?

- each machine's output, state mix, alarm share and data coverage
- whether a machine is below **its own** normal for that hour of day
- that a machine stuck in alarm needs a different response from a slow one
- an end-to-end pipeline that handles real, messy data without corrupting

## Q: How do you know your detector works?

We break a stage on purpose and check that it finds that stage.
`python src/scenario_compare.py`:

| Scenario | What the engine did | Completed (no action -> with action) | Avg wait (s) |
|---|---|---|---|
| healthy | **nothing** | 223 -> 223 | 357 -> 357 |
| slowdown on Stage 2 | 6 rate commands to **Stage 2** | 202 -> **223** | 1805 -> **829** |
| alarm on Stage 2 | advice, then 2 commands to **Stage 3** | 223 -> 224 | 1003 -> 897 |

The healthy row matters as much as the slowdown row: a detector that flags
a healthy line is useless.

## Q: In the alarm scenario, why did it send commands to Stage 3?

Follow the timeline:

| t (sim) | event |
|---|---|
| 7200 s | Stage 2 **stops** (alarm) |
| 7801 s | engine: *"investigate interruption"* - and **no rate command** |
| 10800 s | Stage 2 restarts, its backlog floods downstream |
| 12601 s | command to **Stage 3**: 0.60 -> 0.66 |
| 15001 s | command to **Stage 3**: 0.66 -> 0.73 |

The point is that it never tried to speed up the **stopped** stage.
Speeding up a stopped machine achieves nothing; it needs restarting. Once
Stage 2 came back, the real constraint moved downstream to Stage 3, and the
engine helped it clear the backlog. Same detector, different cause,
different action - which is exactly what the brief asks for.

## Q: Why did the healthy line need no action, when Stage 3 is the busiest?

Stage 3 runs at about 83% busy by design (0.60/min capacity against
0.50/min arrivals). Being busiest is not being a bottleneck. We require
three things together: **busy**, **queue growing**, and **sustained**. A
healthy stage catches up, so its queue does not trend upward.

Set `require_queue_growth: false` in the config and the engine starts
"fixing" the healthy line - that is a good thing to demonstrate.

## Q: Why a warm-up period?

When the line starts, every queue grows from empty. That is the line
filling, not a bottleneck. Without `warmup_seconds` the engine fired a
command at t=2101s on a perfectly healthy line. We found this by running
the comparison and seeing a command we could not justify.

## Q: Walk me through the architecture.

1. **IoT node** - `publisher.py` replays real records, each with the
   original timestamp **and** today's timestamp.
2. **MQTT broker** - Mosquitto, or `scripts/run_broker.py`.
3. **Node-RED** - validates, stores to SQLite, draws the dashboard. A bad
   record goes to `rejected_records` and never reaches the metrics.
4. **Database** - `machine_*` tables for observed, `sim_*` for simulated.
   No table holds both.
5. **Analytics and ML** - `analytics.py` computes rolling indicators
   against each machine's own baseline, raises explainable alerts, and
   publishes a 30-minute forecast.
6. **Decision and automation** - `decision.py` watches the virtual line and
   publishes a bounded command.
7. **MQTT -> actuator** - the virtual line applies the command and
   **acknowledges** it, accepted or refused.

## Q: Why three machines and that particular 4-hour window?

`src/audit.py` searched 2022 for windows where three densely-reporting
machines all had at least 90% of expected records, and found 1,664. We took
the one with the most output and some alarm activity:
2022-03-28 04:00-08:00, machines 0, 1 and 8, 146 records, 600 items,
5 records in alarm. Those five alarm records are real, and they trigger a
real "investigate interruption" alert in the demo.

## Q: Why is `alarm` not one of your features?

Because `alarm == (status == 3)` in all 1,520,330 rows. The two columns are
the same information. Feeding both into a model that predicts anything
alarm-related would leak the answer.

## Q: What is `cycle_time`?

We cannot treat it as a reliable time per finished product. It is capped
at 60 s although records are usually five minutes apart. 18,687 rows
have items produced with `cycle_time == 0`, which is inconsistent. We flag
those (`cycle_ok = false`) and label it on the dashboard as a "reported
cycle-time indicator" rather than a cycle time.

## Q: Why compare a machine only with itself?

The machines make different products, so their item counts are not
comparable. Machine 1 making 8 items in a slot and machine 8 making 3 says
nothing about which is doing better.

## Q: Your baseline was broken at first. What happened?

Our first baseline was median items per slot per hour. For machines 0 and 1
at 04:00 that median is **0**, because they are usually stopped at that
hour - so the ratio was undefined and the alerts were nonsense. The fix was
to compute the baseline **only over slots where the machine was producing**.
It now answers "how much does this machine make per slot when it is
running at this hour", which is the question we actually want.

## Q: Which three models did you train, and why did you choose one?

We trained Ridge regression (traditional ML), histogram gradient boosting
(ensemble ML), and a two-hidden-layer MLP neural network (deep learning)
on the same 45 features and the same fixed Company A examples. The
forecast target is **items produced by one machine in the next 30 minutes**.

| Algorithm | Validation Active MAE (mean of 4 folds) | Test Active MAE | Test Idle MAE | Test overall MAE |
|---|---:|---:|---:|---:|
| Ridge | 2.010 | 2.936 | 1.009 | 1.380 |
| **Gradient boosting — selected** | **1.739** | **2.338** | 0.369 | **0.748** |
| Neural network | 1.764 | 2.392 | 0.519 | 0.879 |
| Persistence reference | 2.067 | 3.109 | **0.201** | 0.761 |

We fixed the selection rule **before opening the held-out test**, and we
select on **four rolling-origin validation folds** rather than one
validation block. The shipped model beats persistence on both Active MAE
and overall MAE. Training time, prediction latency and model size are in
results/MODEL_RESULTS.md.

## Q: Gradient boosting only beat the neural network by about 2%. Is that real?

Good question, and on one validation block it was not safe to claim. The
single-block gap was 1.698 vs 1.735 - **2.2%, when our tie-break rule fires
at 2%**. The whole choice of model hung on 0.2 of a percentage point
measured on one seven-week window.

So we re-ran the selection over **four rolling-origin folds** (each trains
on an expanding prefix and scores the period right after it):

| Model | fold 1 | fold 2 | fold 3 | fold 4 | mean |
|---|---:|---:|---:|---:|---:|
| gradient boosting | 2.139 | 1.693 | **1.556** | **1.568** | **1.739** |
| neural network | **2.072** | **1.671** | 1.661 | 1.653 | 1.764 |
| Ridge | 2.231 | 2.001 | 1.886 | 1.921 | 2.010 |

**The ranking flips.** The neural network wins folds 1 and 2; gradient
boosting wins folds 3 and 4. Say that plainly - it is the honest answer and
it is much stronger than pretending to a decisive win.

What settles it is *which* folds each one wins. The idle share rises
steadily through the file (14%, 34%, 38%, 72% across the folds, 81% in the
test period), so the **latest fold is the best guide to the near future**.
Gradient boosting is 1.45% ahead on the mean - still a tie by our rule -
and **5.43% ahead on the most recent fold**, which is decisive.

Our rule therefore breaks a tie on the most recent fold *before* it ever
considers model size. Accuracy evidence should answer an accuracy
question; size is only a deployment convenience.

## Q: What is "Idle MAE" and why did you add it?

Active MAE only looks at windows where the machine produced something. A
model could score well there and still promise output from a machine that
is switched off - which in a factory means sending someone to chase work
that is never coming. Nothing in our old table could see that.

Idle MAE is the output a model wrongly predicts on windows where the
machine produced nothing:

| Model | Test Idle MAE | promises >1 item while idle |
|---|---:|---:|
| gradient boosting (shipped) | 0.369 | 6.1% |
| neural network | 0.519 | 13.8% |
| Ridge | 1.009 | **37.0%** |
| persistence | **0.201** | 1.0% |

Two results worth volunteering. **Ridge wrongly promises production on more
than a third of idle windows** - a serious operational flaw that the
accuracy-only table hid completely. And **persistence is the best model at
knowing a stopped machine stays stopped**; it just cannot forecast a
running one. That is exactly the trade-off the two columns are there to
expose.

## Q: Why "Active MAE" and not plain MAE?

**80.7% of the test windows have zero output.** Predicting zero for an idle
machine is free, so overall MAE mostly measures how well a model spots
idleness. "Always predict zero" scores 6.19 MAE without learning anything.
Active MAE is the error over the 19,826 windows where the machine actually
produced, and that is what a forecast is for.

Note also that the test period is much quieter than the training period
(80.7% zeros vs 32.7%). That is a real distribution shift in the file, and
it is why we report the split's zero shares.

## Q: Persistence is nearly as good as your models. Doesn't that undermine them?

It is a strong reference and we keep it in the table for exactly that
reason. Output is strongly autocorrelated, so "the next 30 minutes look
like the last 30" is hard to beat, and it is unbeatable at spotting an idle
machine (Idle MAE 0.201 against our 0.369).

Where it fails is the case the forecast exists for. On **Active MAE** -
windows where the machine is actually running - persistence scores 3.109
against our 2.338. It cannot tell you how much a running machine will make;
it can only repeat the last half hour.

An earlier version of this project also lost to persistence on overall MAE
(0.767 against 0.761). After refitting the selected model on all pre-test
data it now wins that comparison too (**0.748** against 0.761). We mention
the earlier result because the honest summary used to be "we win on one
measure and lose on another", and it is worth knowing why that changed.

## Q: How did you avoid leakage?

- features from slots strictly before the prediction moment, target from
  strictly after
- chronological split with a 25-minute embargo so target windows cannot cross boundaries
- Ridge's regularization chosen on validation; the three-family winner
  chosen on validation before test predictions were evaluated
- windows that touch a data gap are dropped, not bridged
- every cross-validation fold trains only on origins *before* the block it
  scores, with the same embargo at every boundary
- the model we ship is refit on training + validation data, which is decided
  and done **after** selection is locked, so it cannot influence the choice
- tests check offline/live feature parity, gaps, split-boundary embargo and
  that no fold trains on its own future

## Q: How do you know the live service feeds the model the right numbers?

Because we checked it on real data, not just in principle. Training
features and live features are built by different code:

```
TRAINING   company_A.csv -> clean.to_slots()          -> build_for_asset()
LIVE       MQTT records  -> analytics.update_history() -> features_from_live_rows()
```

`scripts/verify_feature_parity.py` replays real Company A records through
the live path and compares all 45 model inputs against the training table
at the same origin. Latest run: **1,500 real windows, 67,500 feature
comparisons, zero mismatches** - including 113 slots holding more than one
record and 50 with a flagged power or cycle reading, which the synthetic
unit test never exercises. Run it live in the viva; it takes under a minute.

## Q: Why didn't you train a bottleneck classifier?

There are no verified bottleneck labels in this dataset. We would have had
to invent them, and a model trained on invented labels proves nothing. The
forecast gives early warning; the virtual line gives known-answer scenarios
for testing detection.

## Q: What happens if I send a bad record?

```bash
python src/publisher.py --inject-bad 5
```

Every 5th record goes out with `items: -5` and `status: 99`. It is rejected,
stored in `rejected_records` with the reason, the REJECTED counter rises,
and the metrics do not move. Verified: 57 accepted records produced exactly
57 metric rows while 3 were rejected.

## Q: Is the before/after comparison fair?

Both runs use the same seed, so the arrival times are identical. More than
that, each token's **effort** at each stage is drawn once when it is
created, and service time is `effort / rate`. Re-running with a different
rate changes only the stage's speed, never which tokens arrive or how hard
they are. `test_same_seed_gives_the_same_arrivals` asserts the first part.

## Q: What would you do with more time or better data?

- stage order and item transfer events, so the bottleneck analysis could run
  on real data instead of a simulator
- a genuine idle state, to separate "slow" from "starved"
- blocking with finite buffers in the simulator
- walk-forward validation instead of a single chronological split
- calibrate the arrival rate from real demand, which this dataset lacks

---

## Q: How fast is the closed loop?

The **Closed-loop performance** panel answers this from the database. The
command round trip is timed from the operator's Accept until the device's
acknowledgement returns, with both timestamps taken on the processing
laptop, so a clock difference between laptops cannot distort it. Over the
HiveMQ public broker it was about 0.4 s; on a local broker about 2 ms.
Record-to-forecast latency is timed from Node-RED receiving a record to the
forecast being published, again on one clock.

## Q: The quick models give the same score on every click. Are they real?

Yes. Each click fits a new model; the fit time changes and a new row is
written to `ml_demo_runs`. The score repeats because the data slice, the
chronological split and the random seed are fixed. That is reproducibility.
**Train with new seed** shows the other side: on the quick slice, gradient
boosting moved between about 2.34 and 2.74 across six seeds and the neural
network between 2.80 and 3.02, while Ridge never moved. A difference
smaller than that range between two models is not meaningful, and we never
keep the luckiest seed, because that would tune to the validation data.

## Q: Does the chosen model affect the bottleneck decision?

By default, no, and on purpose: the bottleneck detector works on the
virtual line, and the dataset has no stage order or bottleneck labels to
train on. The chosen model drives the machine forecasts and their advisory.
With the optional `--ml-arrivals` mode, the active model's forecasts scale
how much material reaches the line (0.7-1.3x), so a different model can
move the bottleneck. The published results were produced without it.

## Things to volunteer before you are asked

These show judgement, and each one is a point you control:

1. **The dataset cannot prove a line bottleneck.** Say it first.
2. **The README is out of date** - it omits `status_time` and `alarm`.
3. **`alarm` duplicates `status == 3`** in all 1.52M rows.
4. **Status 0 never occurs**, so starvation is not measurable on real data.
5. **Our own baseline was wrong at first**, and here is how we found it.
6. **The engine fired on a healthy line** until we added queue-growth and
   warm-up rules.
7. **Overall MAE flatters everything** because 80.7% of test windows are
   idle - so we report Active MAE and Idle MAE as well.
8. **Our model comparison was not safe at first.** One validation block put
   the top two families 2.2% apart with a 2% tie-break rule. We re-ran the
   selection over four rolling-origin folds, and the ranking turns out to
   **flip between folds** - so we say the two are close, and explain that
   the most recent fold (the one that looks most like the test period)
   is what settles it.
9. **Ridge promises production on 37% of idle windows.** We only found that
   after adding Idle MAE; accuracy-only tables hide it.
10. **We tried adding six more features** (volatility, idle run length,
    trends) and they moved validation Active MAE by 0.57% - noise. The
    trees already derive them from the lags, so we left them out rather
    than carry code we could not justify.
