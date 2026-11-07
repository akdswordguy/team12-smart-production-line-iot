# Assumptions and limits

Everything we assumed, and why. If a claim is not supported by the data, it
is listed here as an assumption rather than hidden in the code.

## The central limitation

The assignment asks us to find the stage that limits the throughput of a
production **line**. A line has an order of stages, items moving between
them, and queues in between.

**The dataset has none of those.** `company_A.csv` records nine independent
machines. There is no routing, no work-in-progress, no item transfer
events, no waiting time, no demand and no finished-line output. The labelled
subset has a `product` field, but each of its 14 product IDs appears on only
one machine, so it does not establish a shared route either.

So we split the project in two, and label everything:

| Layer | Source | What it can show |
|---|---|---|
| **Observed** | real Company A records | machine output, state, alarms, data coverage, and whether a machine is below **its own** normal |
| **Virtual line** | our simulator | queues, waiting time, starvation, the limiting stage, and the effect of acting on it |

We never present a simulated figure as a factory measurement. The dashboard
labels every panel, the MQTT payloads carry a `source` field, and the
database keeps `machine_*` and `sim_*` tables apart.

---

## Assumptions about the data

**A1. Status codes are 1, 2 and 3 only.**
The README documents `0 = idle`, but the audit found no row with status 0 in
1,520,330 records. *Consequence:* we cannot distinguish "machine idle" from
"machine not reporting", so **starvation cannot be measured on real data**.

**A2. `alarm` carries no information beyond `status`.**
`alarm == (status == 3)` in **every** row. We use only `status`-derived
features; using both would be target leakage.

**A3. Power readings above 2000 kW are sensor faults.**
The file contains 16,777,216 (2^24), while the 99.99th percentile is 32 kW.
Seven rows exceed our limit. They are **flagged, not deleted**
(`power_ok = false`); the raw file is untouched.

**A4. `cycle_time` is not time-per-product.**
The source describes total seconds to produce items, yet values are capped
at 60 s while timestamps are usually five minutes apart. Its exact timing
semantics cannot be verified. 18,687 rows have `items > 0` with
`cycle_time == 0`. We label it a "reported cycle-time indicator" and flag
the inconsistent rows (`cycle_ok = false`).

**A5. The nominal reporting interval is 5 minutes.**
The paper describes 1-minute collection; the measured modal gap is 300 s for
all nine machines. We use 5-minute slots and always publish a **coverage**
figure, so a gap appears as missing data rather than as a machine that
stopped.

**A6. Machines are not comparable with each other.**
They make different products. Every comparison is a machine against its own
history.

**A7. A baseline must be built under comparable conditions.**
Our first attempt used median output per slot per hour and produced a
baseline of 0 for machines 0 and 1 at 04:00 - they are usually stopped then,
so the median of all slots is zero and the ratio is undefined. The baseline
is therefore computed **only over slots where the machine was producing**
(`productive_share > 0.8`), and answers: *how much does this machine make
per slot when it is running at this hour?* An hour with fewer than 20
historical slots falls back to the machine's overall baseline.

**A8. The file differs from the paper.**
We record what we measured on the current repository files
(1,520,330 / 14,492 / 1,568,736 rows) and never quote the paper's scores as
our own.

**A9. Company A and Company B are analysed side by side, never merged.**
They are different companies with different machines and fields. Company B
has richer downtime fields but **no item count**, so only Company A drives
output forecasting and the virtual-line calibration. Company B is replayed
through its own MQTT topics, SQLite tables and analytics (next operating
state, three-model classification study), and the two are compared only on
a like-for-like measure: alarm share among Production-or-Alarm reports.

---

## Assumptions about the virtual line

**V1. Three stages, in a fixed order.** Cutting -> Welding -> Finishing.
This order is **our invention**. The dataset contains no stage map.

**V2. Each stage is a single server.** One token at a time, with a queue in
front. ("One token per stage" in the brief.)

**V3. Queues between stages are unbounded.** A slow stage therefore starves
the stage after it and grows a queue in front of itself, but never blocks
the stage before it. Modelling blocking would need a buffer size the data
cannot give us.

**V4. Arrivals are Poisson at 0.50 tokens/min**, below every stage rate, so
a healthy line is stable and queues stay short until we break something.

**V5. Stage rates are calibrated, not measured.**
From `results/calibration.json`: the **90th percentile** of each machine's
items-per-minute during productive slots - 0.80, 0.80, 0.60 for machines
0, 1 and 8.

We use p90 rather than the mean (0.42, 0.41, 0.37) because **average output
is not capacity**. The average includes slots where the machine was lightly
loaded or changing product. The p90 is closer to "what it manages on a good
run", which is what a stage rate means. This is a judgement call and is
open to challenge; the ratio between stages matters more than the absolute
values.

**V6. Service time is `effort / rate`,** where each token's effort at each
stage is drawn once from an exponential distribution when the token is
created. This is what makes the with-action and no-action runs comparable:
the same tokens need the same relative effort, and only the rate differs.

**V7. The actuator's only action is a bounded rate increase**, at most
+10% per command, never above 1.5x the configured rate, at most 6 commands
per run, with a 30-minute cooldown. A real line cannot be sped up without
limit, and an unbounded engine would prove nothing.

**V8. Optional ML-driven line (off by default).** With `--ml-driven`
each stage keeps the machine its rate was calibrated from (Stage 1, 2, 3 <-
machine 0, 1, 8, as in the rate calibration of V5). The active model's 30-minute forecast for
that machine, divided by 30, is what the stage can make per minute, bounded
between 0.3x and 1.5x of its calibrated rate; an accepted command still
raises the rate on top. Demand is set near capacity (0.62 tokens/min) and
no fault is scripted, so the stage the model expects to be weakest becomes
the bottleneck, and a different model can move it. In a live run the neural
network's lower forecast for machine 0 made Stage 1 Cutting the bottleneck,
then Stage 2 Welding. This links the model to the line decision for
demonstration only; all results in `results/` were produced with it off.

---

## Assumptions about the forecasting

**M1. Only past information is used.** Features come from slots strictly
before the prediction moment; the target from slots strictly after it.
Tested in `tests/test_logic.py`.

**M2. Windows touching a gap are discarded**, rather than treated as
continuous. Tested.

**M3. The split is chronological and made on timestamps**, so one slot
cannot appear in two sets and we never train on the test period.

**M4. Overall MAE is a misleading headline on this data.**
80.7% of test windows have zero output (vs 32.7% in training - the machines
were much less active in the last six weeks of the file). Predicting zero
for an idle machine is free, so overall MAE largely measures idleness
detection. We therefore also report **Active MAE**, over windows where the
machine actually produced, and select the model on validation Active MAE, before examining test results.

**M5. Three model families are compared.**
Ridge (traditional linear ML), histogram gradient boosting (ensemble ML)
and a two-hidden-layer neural network (deep learning) use the same
features and time split. The chosen model is selected on validation
Active MAE, with a model-size tie break within 2%. The later test period
is reserved for final reporting. Persistence remains a reference and
is slightly better on overall test MAE; the selected model is better on
productive test windows.

**M6. We do not train a bottleneck classifier.**
There are no verified bottleneck labels in this dataset, and inventing them
would be fabrication. Bottleneck *detection* is tested against the virtual
line, where we know the answer because we caused it.

---

## What we would need to make the real-data claims stronger

- stage order and routing, or a product ID shared across machines in sequence
- item transfer events, or entry/exit timestamps per station
- a genuine idle state, to separate "slow" from "starved"
- demand or scheduling data, to know whether low output was even a problem
