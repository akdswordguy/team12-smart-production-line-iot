# Repair notes for the supplied Team 12 ZIP

The original archive was preserved. This project copy contains the changes
below.

- **Data:** Fixed the slow slot aggregation in `src/clean.py` and counted
  distinct five-minute slots in the replay audit. Rebuilt the audit,
  cleaned replay, baselines and calibration from the fixed Company A CSV.
  The fetch script now pins a repository revision and checks Company A's
  SHA-256 before reporting results.
- **Live analytics:** Aggregated duplicate records into time slots, made
  gaps lower coverage, and prevented repeated rows in one slot from
  advancing a sustained alert. Live forecast features now use the same
  prediction origin as offline training.
- **ML:** Purged target windows across chronological split boundaries,
  retrained Ridge, gradient boosting and a two-hidden-layer neural
  network on the same features. Gradient boosting was selected using
  validation Active MAE (1.698), before the later test was opened. Its
  held-out Active MAE is 2.346 against 3.109 for persistence.
- **Decision:** Added an explicit forecast-based recommendation on
  `team12/decision/forecast_advisory`. It is only advice about recorded
  machines. Virtual-line MQTT commands remain bounded and acknowledged.
- **Node-RED:** Corrected SQLite parameter binding, separated advisories
  from the forecast subscription, tightened input validation, and added
  an advisory dashboard display. Node-RED now forwards an observed record
  to analytics only after SQLite successfully stores it. The full flow now writes all eight
  database tables without SQLite errors.
- **Run path:** Added pinned Node-RED and Python dependencies, a Windows
  setup script, a portable runner that starts the whole demo, a safe stop
  request, and a database integration checker.
- **Verification:** 29 logic tests pass. The live normal and bad-record
  runs are recorded in `results/LIVE_INTEGRATION.md`. The offline
  same-arrivals scenario comparison was rerun. A team roadmap and an AI
  handoff prompt are included.

The raw dataset, large feature table and installed dependencies are not
bundled in the ZIP. The replay slice, baseline, trained model and results
are bundled for immediate demonstration after setup.

