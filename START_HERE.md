# Team 12: teacher demo in five steps

**For the presentation, follow [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)** (two laptops, or one laptop with two folders). **For the free, no-payment broker setup, see [docs/PUBLIC_BROKER_DEMO.md](docs/PUBLIC_BROKER_DEMO.md).** For a private HiveMQ Cloud trial, use [docs/TWO_LAPTOP_DEMO.md](docs/TWO_LAPTOP_DEMO.md). The steps below are for a local rehearsal on one laptop.

This folder contains the unchanged Company A CSV and Company B ZIP, prepared training features,
three-model evaluation, selected trained model, Node-RED flow and a working
SQLite dashboard. Use **this folder**, not an older ZIP.

## Before the presentation

On this Windows laptop, the Desktop copy includes `.venv` and
`nodered/node_modules`. If you move the folder to another computer, run
`powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1` there
before the demo. Check that `python`, Node.js and npm are installed.

Run the logic check once:

```powershell
.\.venv\Scripts\python.exe scripts\verify_project.py
.\.venv\Scripts\python.exe tests\test_logic.py
```

## Live demonstration

1. Open PowerShell in this folder and run:

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_demo.py slowdown --reset-db --speed 200
   ```

   Leave this terminal open. `--reset-db` is for a clean presentation only.
   Omit it if you want to preserve data across later runs.
2. Open <http://localhost:1880/ui>. The dashboard reads both companies' saved
   SQLite records every four seconds. The A/B chart compares nine shared
   months using alarm share among Production-or-Alarm reports. It does not
   claim one company has higher throughput; B has no item-count field.
3. Point to **Why this model was selected**: Ridge, gradient boosting and a
   two-layer neural network were trained on the same fixed dataset. The
   validation-fold chart determines the winner; later test errors and
   training/runtime costs are also shown.
4. In **Interactive ML lab**, click **Train demo model** for Ridge, boosting,
   and neural network, one at a time. Each button fits a real model on the
   same chronological Company A subset and shows its validation MAE. Click
   **Use for live forecasts** to switch subsequent predictions. Click
   **Restore full-study winner** to return to the validated boosting model.
   The quick demo scores can rank differently from the full four-fold study.
5. Point to live machine forecasts and the virtual queue/busy graphs. After
   the Stage 2 slowdown, the **Approve a proposed bottleneck action** card
   shows the evidence. Click **Accept and send command** to update the
   virtual machine, or **Reject action** to leave it unchanged. Show the
   MQTT command, actuator acknowledgement and later rate in the stage table.
   **Restart virtual shift** starts a new simulated shift if you want to show
   the bottleneck again.
6. Point to **Closed-loop performance**: command round trip, record-to-forecast
   latency, acknowledgements, operator decisions, command spacing and the
   simulated control effect, all read from SQLite.
7. Open a second PowerShell terminal in this folder and run:

   ```powershell
   .\.venv\Scripts\python.exe scripts\show_database.py
   .\.venv\Scripts\python.exe scripts\check_demo.py --require-command --require-review
   ```

The database is `db/team12.db`. Press Ctrl+C in the first terminal to stop
the demo. Read `docs/PRESENTATION_RUNBOOK.md` and `docs/WORKFLOW_CHECK.md`
before the viva.

**State the limit clearly:** the fixed Company A dataset has machine counts
but no product route or measured line queues. The bottleneck and control
improvement are from a labelled virtual production line. The observed
machine forecast produces an operator advisory, not a physical actuator
command.

