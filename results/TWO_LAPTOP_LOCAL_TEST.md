# Split-role integration check

Date: 2026-11-05. Two **separate project folders** ran the `cloud` and `device` roles against the same local MQTT broker on this Windows computer. This verifies the process split and message round trip; it is not a remote HiveMQ Cloud test because project credentials were not supplied.

- Device role replayed fixed A and B records and ran the virtual line and actuator.
- Cloud role ran Node-RED, SQLite, A/B analytics, model services, decision engine and dashboard.
- Cloud SQLite stored 1,526 B events, 1,526 B rolling metrics and 299 B next-state forecast snapshots.
- The dashboard displayed a Stage 2 virtual bottleneck proposal. Its **Accept and send command** button was clicked.
- Device Stage 2 rate changed from 0.36 to 0.396 tokens/min. The MQTT actuator acknowledgement returned to the cloud dashboard.
- `scripts/check_demo.py --require-command --require-review` passed, including SQLite checks that a review preceded a matching command and that an accepted acknowledgement was stored. Node-RED reported no SQLite errors.

For the classroom, use the remote HiveMQ steps in `docs/TWO_LAPTOP_DEMO.md` and verify both laptop terminals authenticate and the same dashboard/database checks pass. Do not claim a remote network test from this local check.
