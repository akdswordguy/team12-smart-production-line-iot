# Team 12 project: start here

This ZIP contains the fixed Company A and B datasets, prepared features, trained
models, Node-RED flow, Python services, documentation, and a SQLite database from
the successful full replay. The database is evidence; starting the cloud role
with `--reset-db` clears it for a fresh demonstration.

If this ZIP also has an `original_archive` folder, it holds the unchanged
`.adding` file supplied for comparison. Run the project in `iotproject/`.

## Two-laptop public-broker demo

Extract **the same ZIP** on both laptops. Install Python on both; install Node.js
and npm on the processing laptop. Follow the one-time setup and run commands in
`docs/PUBLIC_BROKER_DEMO.md`. The two folders must have the same
`config/public_broker.json` topic root. Open `http://localhost:1880/ui` on the
processing laptop after its cloud role says it is ready.

For the interactive demonstration, start the device role with
`--manual-replay --line-speed 40`, then use the dashboard's **Start Company A**
and **Start Company B** buttons. Either can start first. Both streams may run
together, and the dashboard shows their separate results and A/B comparison.
The detailed commands are in `docs/PUBLIC_BROKER_DEMO.md`.

The public broker is shared and unencrypted. Send only the supplied public data
and commands for the virtual actuator. Do not use it for a physical machine.

## What the completed run proved

On 2026-11-06, the final merged project completed a full test using two isolated
folders on one computer and a local MQTT broker. Its saved SQLite database has
all 146 Company A and 1,526 Company B observations, 129 A forecasts and 299 B
forecast snapshots. Three A quick-demo models were trained. One operator-approved
virtual bottleneck command changed the Stage 2 rate and received an accepted MQTT
ACK; a later proposal was rejected. `scripts/check_demo.py --require-command
--require-review` passed every check. See `results/MERGED_VERIFICATION.md`.

The merged version also connected through the free HiveMQ public broker, but a
temporary broker disconnect left that particular replay incomplete (136/146 A,
1,500/1,526 B stored). Rehearse the public connection and the two physical
laptops before presenting. The included database is from the complete local
broker test.

For the workflow and explanation, read `START_HERE.md`,
`docs/PRESENTATION_RUNBOOK.md`, and `docs/VIVA_NOTES.md`.
