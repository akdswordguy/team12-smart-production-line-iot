# Virtual-line scenario results

> **Every number on this page is SIMULATED.** The fixed dataset contains
> no stage order, no queues and no waiting times, so these figures test
> our detection and control logic. They are not measurements of any
> factory, and no improvement here describes a real production line.

Both runs in each scenario use the same seed, so arrivals and token
efforts are identical. The only difference is whether the decision
engine was allowed to act.

## Summary

| Scenario | Arrivals | Completed (no action) | Completed (with action) | Throughput /h | Avg wait (s) | Commands |
|---|---|---|---|---|---|---|
| healthy | 229 | 223 | 223 | 27.88 -> 27.88 (+0.0) | 357.2 -> 357.2 (+0.0) | 0 |
| slowdown | 229 | 202 | 223 | 25.25 -> 27.88 (+2.63) | 1805.1 -> 829.4 (-975.7) | 6 |
| alarm | 229 | 223 | 224 | 27.88 -> 28.0 (+0.12) | 1003.0 -> 897.2 (-105.8) | 2 |

## Scenario: healthy

A healthy line. Nothing is broken.

| Stage | Configured | Final rate (with action) | Queue at end (no action) | Queue at end (with action) | Busy (no action) |
|---|---|---|---|---|---|
| Stage 1 - Cutting | 0.8 | 0.8 | 0 | 0 | 48% |
| Stage 2 - Welding | 0.8 | 0.8 | 1 | 1 | 74% |
| Stage 3 - Finishing | 0.6 | 0.6 | 3 | 3 | 83% |


## Scenario: slowdown

Stage 2 is slowed to 45% of its rate at t=7200s. Its capacity drops below the arrival rate, so its queue grows without limit - a capacity constraint.

| Stage | Configured | Final rate (with action) | Queue at end (no action) | Queue at end (with action) | Busy (no action) |
|---|---|---|---|---|---|
| Stage 1 - Cutting | 0.8 | 0.8 | 0 | 0 | 48% |
| Stage 2 - Welding | 0.8 | 0.581 | 22 | 1 | 100% |
| Stage 3 - Finishing | 0.6 | 0.66 | 3 | 3 | 100% |

**What the engine did:**

- `t=7200s` SCENARIO at t=7200s: Stage 2 - Welding slowed from 0.80 to 0.36 tokens/min
- `t=11401s` **command** to Stage 2 - Welding: 0.36 -> 0.396 tokens/min, actuator **accepted**. Stage 2 - Welding is the limiting stage (busy 100%, queue 5, starved 0%, for 3 checks). Raising its rate by 10% to 0.40 tokens/min (ceiling 1.20).
- `t=13201s` **command** to Stage 2 - Welding: 0.396 -> 0.436 tokens/min, actuator **accepted**. Stage 2 - Welding is the limiting stage (busy 100%, queue 8, starved 0%, for 4 checks). Raising its rate by 10% to 0.44 tokens/min (ceiling 1.20).
- `t=17701s` **command** to Stage 2 - Welding: 0.436 -> 0.48 tokens/min, actuator **accepted**. Stage 2 - Welding is the limiting stage (busy 100%, queue 6, starved 0%, for 3 checks). Raising its rate by 10% to 0.48 tokens/min (ceiling 1.20).
- `t=19501s` **command** to Stage 2 - Welding: 0.48 -> 0.528 tokens/min, actuator **accepted**. Stage 2 - Welding is the limiting stage (busy 100%, queue 12, starved 0%, for 3 checks). Raising its rate by 10% to 0.53 tokens/min (ceiling 1.20).
- `t=21301s` **command** to Stage 2 - Welding: 0.528 -> 0.581 tokens/min, actuator **accepted**. Stage 2 - Welding is the limiting stage (busy 100%, queue 14, starved 0%, for 3 checks). Raising its rate by 10% to 0.58 tokens/min (ceiling 1.20).
- `t=24301s` **command** to Stage 3 - Finishing: 0.6 -> 0.66 tokens/min, actuator **accepted**. Stage 3 - Finishing is the limiting stage (busy 100%, queue 5, starved 0%, for 3 checks). Raising its rate by 10% to 0.66 tokens/min (ceiling 0.90).


## Scenario: alarm

Stage 2 stops completely at t=7200s for 3600s. The correct response is different: a stopped stage must be restarted, not sped up.

| Stage | Configured | Final rate (with action) | Queue at end (no action) | Queue at end (with action) | Busy (no action) |
|---|---|---|---|---|---|
| Stage 1 - Cutting | 0.8 | 0.8 | 0 | 0 | 48% |
| Stage 2 - Welding | 0.8 | 0.8 | 1 | 1 | 74% |
| Stage 3 - Finishing | 0.6 | 0.726 | 3 | 2 | 83% |

**What the engine did:**

- `t=7200s` SCENARIO at t=7200s: Stage 2 - Welding STOPPED until t=10800s (alarm)
- `t=7801s` **advice**: investigate interruption. Stage 2 - Welding is STOPPED, not slow (busy 5%, queue 6, starved 28%, for 3 checks). Adding capacity to a stopped stage achieves nothing - restart it first.
- `t=12601s` **command** to Stage 3 - Finishing: 0.6 -> 0.66 tokens/min, actuator **accepted**. Stage 3 - Finishing is the limiting stage (busy 100%, queue 11, starved 0%, for 3 checks). Raising its rate by 10% to 0.66 tokens/min (ceiling 0.90).
- `t=15001s` **command** to Stage 3 - Finishing: 0.66 -> 0.726 tokens/min, actuator **accepted**. Stage 3 - Finishing is the limiting stage (busy 100%, queue 6, starved 0%, for 3 checks). Raising its rate by 10% to 0.73 tokens/min (ceiling 0.90).
