# Final merged project verification — 2026-11-06

The saved `db/team12.db` is from a complete two-role test on one computer. The
cloud and device roles ran from separate project folders and exchanged MQTT
messages through a local broker. It is evidence for the software workflow; a
two-physical-laptop run still needs a classroom rehearsal.

## Saved database evidence

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

The saved `db/team12.db` remains the earlier complete A+B run. The new controls
were verified with a short local broker run. The public HiveMQ broker and the
rendered browser view were not retested after this control change; browser
inspection was stopped by the computer-use tool before navigation.
