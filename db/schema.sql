-- ===========================================================================
-- Team 12 - SQLite schema
--
-- The single most important rule in this file:
--   OBSERVED data and SIMULATED data live in SEPARATE TABLES.
-- There is no table that mixes them, so no query can accidentally report a
-- simulated improvement as a real factory measurement.
--
--   machine_events, machine_metrics, machine_alerts  -> REAL (replayed 2022)
--   sim_state, sim_commands                          -> VIRTUAL LINE
--   forecasts                                        -> MODEL PREDICTIONS
--   rejected_records                                 -> data that failed checks
--
-- Create with:  python scripts/init_db.py
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. OBSERVED: raw machine records that passed validation.
--    ts_dataset = when the factory recorded it (2021-2022)
--    ts_replay  = when our publisher sent it (today)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machine_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL DEFAULT 'observed',
    run_id        TEXT,            -- which replay run this came from
    seq           INTEGER,         -- position within that run
    asset         INTEGER NOT NULL,
    ts_dataset    TEXT    NOT NULL,
    ts_replay     TEXT    NOT NULL,
    items         REAL,
    status        INTEGER,
    status_time   REAL,
    power_avg     REAL,
    cycle_time    REAL,
    power_ok      INTEGER,         -- 0 = power reading not trusted
    cycle_ok      INTEGER,         -- 0 = cycle_time reading not trusted
    -- A replay can be restarted safely: the same record is not stored twice.
    UNIQUE (run_id, asset, ts_dataset)
);

CREATE INDEX IF NOT EXISTS idx_events_asset_ts
    ON machine_events (asset, ts_dataset);


-- ---------------------------------------------------------------------------
-- 2. OBSERVED: anything that failed validation.
--    Stored, never silently dropped - and never fed into the metrics.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rejected_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_replay   TEXT NOT NULL,
    topic       TEXT,
    reason      TEXT NOT NULL,
    raw_payload TEXT
);


-- ---------------------------------------------------------------------------
-- 3. OBSERVED: rolling indicators, one row per machine per update.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machine_metrics (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    asset                     INTEGER NOT NULL,
    ts_dataset                TEXT,
    ts_replay                 TEXT NOT NULL,
    window_slots              INTEGER,
    rolling_items             REAL,
    items_per_slot            REAL,
    items_per_productive_slot REAL,
    productive_share          REAL,
    alarm_share               REAL,
    cycle_time_indicator      REAL,
    coverage                  REAL,
    baseline_items_per_slot   REAL,
    baseline_ratio            REAL,
    baseline_hour             INTEGER
);

CREATE INDEX IF NOT EXISTS idx_metrics_asset
    ON machine_metrics (asset, ts_replay);


-- ---------------------------------------------------------------------------
-- 4. OBSERVED: explainable alerts about real machines.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machine_alerts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_replay      TEXT NOT NULL,
    ts_dataset     TEXT,
    asset          INTEGER,
    level          TEXT,
    kind           TEXT,       -- interruption | underperformance | ...
    recommendation TEXT,
    message        TEXT
);


-- ---------------------------------------------------------------------------
-- 5. SIMULATED: state of the virtual production line.
--    Everything in this table is produced by src/line_sim.py.
--    It is NOT a measurement of any factory.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sim_state (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL DEFAULT 'simulated',
    run_label           TEXT,       -- e.g. 'with_action' / 'no_action'
    ts_replay           TEXT NOT NULL,
    sim_second          INTEGER NOT NULL,
    stage_index         INTEGER NOT NULL,
    stage_name          TEXT,
    rate_per_min        REAL,       -- current (possibly adjusted) rate
    configured_rate     REAL,       -- rate before any slowdown or command
    queue_length        INTEGER,
    busy_share          REAL,
    starved_share       REAL,
    completed           INTEGER,    -- tokens finished by this stage
    avg_wait_seconds    REAL,
    is_bottleneck       INTEGER     -- 1 when the detector flagged this stage
);

CREATE INDEX IF NOT EXISTS idx_sim_state_second
    ON sim_state (run_label, sim_second, stage_index);


-- ---------------------------------------------------------------------------
-- 6. SIMULATED: control commands and the actuator's acknowledgement.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sim_commands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id      TEXT,
    direction       TEXT,       -- 'command' (engine -> actuator) or 'ack'
    ts_replay       TEXT NOT NULL,
    sim_second      INTEGER,
    action          TEXT,       -- e.g. 'increase_rate'
    stage_index     INTEGER,
    detail          TEXT,       -- human readable description
    accepted        INTEGER,    -- ack only: 1 accepted, 0 refused
    old_rate        REAL,
    new_rate        REAL,
    reason          TEXT
);


-- ---------------------------------------------------------------------------
-- 7. FORECASTS: model predictions. Never mixed with observed values.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_replay        TEXT NOT NULL,
    asset            INTEGER,
    horizon_minutes  INTEGER,
    predicted_items  REAL,
    model            TEXT NOT NULL,
    prediction_guarded INTEGER NOT NULL DEFAULT 0,
    guard_limit      REAL
);

-- ---------------------------------------------------------------------------
-- 8. FORECAST-BASED ADVISORIES: decisions informed by the ML prediction.
--    These are recommendations about observed machines, not factory actions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecast_advisories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL CHECK (source = 'forecast'),
    ts_replay       TEXT NOT NULL,
    ts_dataset      TEXT,
    asset           INTEGER,
    model           TEXT,
    predicted_items REAL,
    expected_items  REAL,
    recommendation  TEXT,
    reason          TEXT
);

-- Interactive classroom runs. These scores are from a small forward-time
-- demo slice and must not be conflated with the full offline evaluation.
CREATE TABLE IF NOT EXISTS ml_demo_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_replay TEXT NOT NULL,
    model TEXT NOT NULL,
    train_rows INTEGER NOT NULL,
    valid_rows INTEGER NOT NULL,
    active_valid_rows INTEGER NOT NULL,
    active_mae REAL,
    idle_mae REAL,
    overall_mae REAL,
    train_seconds REAL,
    seed INTEGER            -- random seed used; NULL in older runs = config seed
);

CREATE TABLE IF NOT EXISTS sim_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    ts_replay TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('accept','reject')),
    sim_second INTEGER,
    stage_index INTEGER,
    stage_name TEXT,
    old_rate REAL,
    new_rate REAL,
    reason TEXT
);

-- Company B is kept separate because its state vocabulary and one-minute
-- reporting cadence differ from Company A; it has no item-count target.
CREATE TABLE IF NOT EXISTS company_b_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK(source='observed_b'),
    run_id TEXT NOT NULL,
    seq INTEGER,
    asset INTEGER NOT NULL,
    ts_dataset TEXT NOT NULL,
    ts_replay TEXT NOT NULL,
    status TEXT NOT NULL,
    power_avg REAL,
    alarm_time REAL,
    loading_time REAL,
    tooling_time REAL,
    maintenance_time REAL,
    support_time REAL,
    UNIQUE(run_id,asset,ts_dataset)
);

CREATE INDEX IF NOT EXISTS idx_b_events_asset_ts
    ON company_b_events(asset,ts_dataset);

CREATE TABLE IF NOT EXISTS company_b_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset INTEGER NOT NULL,
    ts_dataset TEXT NOT NULL,
    ts_replay TEXT NOT NULL,
    latest_status TEXT,
    reports_30m INTEGER,
    production_share REAL,
    alarm_share REAL,
    conditional_alarm_pct REAL
);

CREATE TABLE IF NOT EXISTS company_b_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset INTEGER NOT NULL,
    ts_dataset TEXT NOT NULL,
    ts_replay TEXT NOT NULL,
    current_status TEXT NOT NULL,
    predicted_next_status TEXT NOT NULL,
    model TEXT NOT NULL,
    condition TEXT NOT NULL
);


-- ---------------------------------------------------------------------------
-- Closed-loop performance (both timings are taken on the processing laptop's
-- own clock, so clock differences between two laptops cannot distort them)
--   command_round_trip_ms : operator Accept -> MQTT command -> device applies
--                           it -> ACK back at the decision engine
--   ingest_to_forecast_ms : Node-RED receives a record -> validates -> SQLite
--                           write -> MQTT -> analytics -> forecast published
--   forecast_compute_ms   : analytics features + model prediction only
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loop_metrics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_replay  TEXT NOT NULL,
    metric     TEXT NOT NULL,
    value      REAL NOT NULL,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_loop_metrics_metric ON loop_metrics (metric);
