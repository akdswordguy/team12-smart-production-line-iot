# Two-laptop Team 12 demonstration

**No-payment alternative:** [PUBLIC_BROKER_DEMO.md](PUBLIC_BROKER_DEMO.md) uses HiveMQ's shared test broker without an account. The steps below use a private HiveMQ Cloud broker, whose Starter trial requests payment details and can incur charges after the trial.

This is the teacher's requested deployment. Both laptops use the **same online HiveMQ Cloud MQTT broker**. The provided fixed Company A CSV and Company B ZIP are copied with the project to both machines; the device laptop only needs the prepared replay slices. No real factory hardware is claimed.

## Who runs what

| Device laptop (IoT node) | Cloud laptop (processing) |
|---|---|
| Replays fixed A and B records with dataset and replay timestamps | Node-RED subscribes, validates, writes SQLite, then republishes validated records |
| Runs the virtual production line and MQTT actuator | A and B analytics, three A models and three separately trained B models |
| Subscribes to `team12/sim/command`, applies bounded virtual rate changes, publishes `team12/sim/ack` | Dashboard and decision engine; operator accepts or rejects a proposed action |

HiveMQ sits between them. The browser dashboard and SQLite file are on the cloud laptop only. The virtual line and its actuator are on the device laptop. The command loop is: device line state → broker → cloud decision and dashboard → operator acceptance → broker command → device actuator → broker acknowledgement → cloud dashboard/database.

## Preparation on both laptops

1. Extract the same `iotproject.zip` to a folder. Keep both laptops online.
2. Create a private HiveMQ Cloud cluster and MQTT access credential. Use its **cluster hostname** (without `mqtts://`), port `8883`, TLS, username and password. HiveMQ Cloud requires TLS. Do not place the password in a shared ZIP or project file.
3. On the cloud laptop, install Python and Node.js, then run `powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1` in the project folder.
4. On the device laptop, install Python, then run `powershell -ExecutionPolicy Bypass -File scripts\setup_device_windows.ps1`. Node.js is not needed there.
5. In **each** PowerShell terminal, set the same broker values below. Replace the examples with your actual values. Do not paste the real password into screenshots or chat.

```powershell
$env:TEAM12_MQTT_HOST = 'your-cluster.s1.eu.hivemq.cloud'
$env:TEAM12_MQTT_PORT = '8883'
$env:TEAM12_MQTT_TLS = 'true'
$env:TEAM12_MQTT_USERNAME = 'your-mqtt-username'
$env:TEAM12_MQTT_PASSWORD = 'your-mqtt-password'
```

The variables apply only to the current PowerShell window. The program checks broker authentication before starting its role. `nodered/flow.local.json` is generated on the cloud laptop and may contain the connection credential; keep it private and never share it. The ZIP excludes this file.

## Demo order

**Cloud laptop first:**

```powershell
.\.venv\Scripts\python.exe scripts\two_laptop.py cloud --reset-db
```

Wait for `Cloud laptop ready`, then open `http://localhost:1880/ui` on that same laptop. Leave this terminal running.

**Device laptop second:**

```powershell
.\.venv\Scripts\python.exe scripts\two_laptop.py device --speed 200 --scenario slowdown
```

The cloud dashboard should show A and B records growing, the A/B monthly graph, A forecasts, B next-state forecasts, virtual queues, model scores, and the proposed action. Accept or reject on the cloud dashboard. If accepted, the device's `logs/line_sim.log` shows the actuator rate change; the cloud dashboard shows acknowledgement. On the cloud laptop, run `python scripts\check_demo.py --require-command --require-review` after accepting to verify stored evidence. Use `python scripts\show_database.py` to inspect SQLite tables.

To stop, press Ctrl+C in each role's terminal. Or run `.\.venv\Scripts\python.exe scripts\stop_services.py` in each extracted folder.

## What to say when comparing companies

The A/B graph compares conditional Alarm share among Production-or-Alarm reports during the nine shared complete months of 2022. A averaged 7.19%; B 8.55%, so A had a lower value for this **specific recorded interruption measure** in seven of nine months. Reporting coverage differs greatly (A 90.46%, B 17.92% of their respective continuous reporting grids). B has no item-count target and the dataset gives no stage routing, queues, or waiting times. Therefore the chart does **not** prove that A has higher total throughput or that the virtual-line improvements happened in either factory.

B's separate next-minute state classifier compares logistic regression, gradient boosting and a neural network by validation macro F1. Gradient boosting won validation (0.962), but its later test macro F1 (0.941) was below the same-state baseline (0.948). Show this honestly; it is a trained model demonstration, not a proven performance gain. A's item forecast uses MAE, which is a different task and metric.

## Network checklist

- Both terminals report `MQTT broker connection accepted`.
- Cloud Node-RED log says `Connected to broker` and the dashboard opens.
- Device logs show both publisher files and line state; cloud SQLite counts rise.
- If the cloud dashboard stays empty, check `logs/nodered.log` and MQTT environment variables on both laptops.
- Keep one cloud and one device instance running. If you restart a laptop, rerun its role command in its own terminal.

The local all-in-one `scripts/run_demo.py` remains available for rehearsal when internet or HiveMQ credentials are unavailable. It does not prove the two-laptop network path.
