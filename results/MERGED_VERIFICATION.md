# Final merged project verification — 2026-11-06

This record is chronological. The first sections describe the 2026-11-06
merged test; the **current** saved `db/team12.db` is described in
"Closed-loop performance build" at the end, and the full HiveMQ public-broker
run in the section before it.

The 2026-11-06 test was a complete two-role run on one computer. The cloud and
device roles ran from separate project folders and exchanged MQTT messages
through a local broker.

## 2026-11-06 database evidence

| Table | Rows | Meaning |
| --- | ---: | --- |
| `machine_events` | 146 | Company A replay observations |
| `machine_metrics` | 146 | Company A rolling metrics |
| `forecasts` | 129 | Company A predictions |
| `forecast_advisories` | 129 | Company A model advice |
| `company_b_events` | 1,526 | Company B replay observations |
| `company_b_metrics` | 1,526 | Company B rolling metrics |
| `company_b_forecasts` | 299 | Company B prediction snapshots |
| `sim_state` | 1,443 | Virtual line states |
| `sim_commands` | 2 | One outbound command and its accepted ACK |
| `sim_reviews` | 2 | One accepted and one rejected operator proposal |
| `ml_demo_runs` | 3 | Ridge, boosting and neural demo training |

The accepted virtual action changed Stage 2 from 0.36 to 0.396 tokens/min.
The device acknowledged that it applied the rate change. A later proposal was
rejected without a second command. The virtual shift completed at 28,800
simulated seconds, with 212 completed tokens, 26.5 tokens/hour and 1,481.1
seconds average wait. These values describe the **simulated** line, not measured
factory throughput.

The demo models' saved MAE values were Ridge 2.407, boosting 2.499 and neural
3.005. Their comparison is visible on the dashboard and in the database. The
quick-demo models serve interactive training; the offline study and model choice
are documented separately in `MODEL_RESULTS.md`.

The project checker passed with `--require-command --require-review`, including
the database, model, replay and Node-RED checks. The unit suite passed 46/46.
The saved dashboard view is `docs/merged_verified_dashboard.png`.

## Public-broker limitation

The final merged project also connected using the free public HiveMQ broker.
During that test Node-RED disconnected briefly, leaving 136/146 A and
1,500/1,526 B observations in that run's database. This is why the ZIP carries
the complete **local-broker** database. Public-broker delivery and physical
laptop connectivity should be rehearsed on the presentation network.

Late action handling was also checked: once the simulated shift has finished,
the virtual device refuses a command and returns an explanatory negative ACK.

## Separate A/B start controls

After the completed run, the dashboard gained separate Company A and B start
buttons. In a short local MQTT test, the device role was started with
`--manual-replay --limit 10`. Before a request, neither replay had inserted a
record and the virtual line had not started. Sending the A start request stored
10 A and 0 B observations. Sending the B request next stored 10 A and 10 B;
both corresponding metrics tables gained 10 rows. The device published ready,
running and completed status on MQTT. The new control route and live comparison
SQL passed syntax and query checks; the project unit suite passed 47/47.

The new controls were verified with a short local broker run at the time.

## Full HiveMQ public-broker run — 2026-11-07

Both roles ran on one Windows laptop from two separate project folders and
communicated only through `ws://broker.hivemq.com:8000/mqtt`. The dashboard's
Start buttons started Company A and then Company B; both completed with
**146/146** and **1,526/1,526** records stored (no loss). Three demo models
were trained. Two operator-approved Stage 2 commands (0.36 → 0.396 and
0.396 → 0.436) were acknowledged in about 0.39 s and 0.36 s; one proposal was
rejected and nothing was sent. `check_demo.py --require-command
--require-review` passed every check. The run also showed that
`setup_device_windows.ps1` must prefer Python 3.12 (PyYAML 6.0.2 has no wheel
for Python 3.14); the script now does.

## Closed-loop performance build — 2026-11-07

This build adds the `loop_metrics` table and the dashboard's
**Closed-loop performance** panel, replay-again and **Restart virtual shift**
controls, an immediate re-forecast when the live model is switched, and an
optional `--ml-arrivals` mode (off by default). The standard virtual-line
results are unchanged: `scenario_compare.py` reproduces 229 arrivals and
202 → 223 completed items exactly.

The saved `db/team12.db` is now from a complete two-folder run of this build
on a local broker: 146 A and 1,526 B records, 129 A forecasts, 299 B forecast
snapshots, three demo models trained before the replay, one accepted command
(Stage 2, 0.36 → 0.396, acknowledged) and one rejected proposal, and a full
simulated shift (28,800 s, 212 completed tokens). `loop_metrics` holds 259
timings; the command round trip was 1.4 ms on the local broker.
Record-to-forecast latency is machine-dependent; quote the values from your
own rehearsal. All 13 checks of `check_demo.py --require-command
--require-review` passed, and the unit suite passed 56/56.
