"""
Tests for the logic that decides things. No MQTT, no database, no files.

These cover the claims we make in the viva:
  * a bad record is rejected and never reaches the metrics
  * a machine stuck in alarm is called an interruption, not a slow machine
  * a HEALTHY virtual line is left alone (no false alarm)
  * a real bottleneck is found, and the action is bounded
  * the same seed gives the same arrivals, so before/after is a fair test
  * no token is lost in the simulator
  * the feature builder cannot see the future

Run:  python tests/test_logic.py      (no pytest needed)
      pytest tests/                   (also works if you have pytest)
"""

import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import analytics          # noqa: E402
import decision           # noqa: E402
from line_sim import Line  # noqa: E402
import line_sim          # noqa: E402
from common import topic # noqa: E402

STAGES = [
    {"name": "Stage 1", "rate_per_min": 0.80},
    {"name": "Stage 2", "rate_per_min": 0.80},
    {"name": "Stage 3", "rate_per_min": 0.60},
]


def test_public_topic_root_keeps_team_traffic_separate():
    before = os.environ.get("TEAM12_TOPIC_ROOT")
    try:
        os.environ["TEAM12_TOPIC_ROOT"] = "team12/demo-7f49e2a163c8b5d0"
        assert topic("observed_machine", 3) == "team12/demo-7f49e2a163c8b5d0/observed/machine/3"
        assert topic("sim_command") == "team12/demo-7f49e2a163c8b5d0/sim/command"
    finally:
        if before is None:
            os.environ.pop("TEAM12_TOPIC_ROOT", None)
        else:
            os.environ["TEAM12_TOPIC_ROOT"] = before


def test_virtual_actuator_rejects_unbounded_public_command():
    from types import SimpleNamespace
    old_line, old_publish = line_sim.line, line_sim.publish
    replies = []
    try:
        line_sim.line = Line(STAGES, 0.5, 42, 100)
        line_sim.publish = lambda _client, _topic, payload: replies.append(payload)
        command = {"command_id": "1234abcd", "action": "increase_rate",
                   "stage_index": 1, "old_rate": 0.8, "new_rate": 999}
        line_sim.on_command(None, None, SimpleNamespace(payload=json.dumps(command).encode()))
        assert replies[-1]["accepted"] is False
        assert line_sim.line.stages[1].rate == 0.8
        command["new_rate"] = 0.88
        line_sim.on_command(None, None, SimpleNamespace(payload=json.dumps(command).encode()))
        assert replies[-1]["accepted"] is True
        assert line_sim.line.stages[1].rate == 0.88
    finally:
        line_sim.line, line_sim.publish = old_line, old_publish


def test_virtual_actuator_acknowledges_late_command_without_changing_rate():
    from types import SimpleNamespace
    old_line, old_publish, old_shift_over = line_sim.line, line_sim.publish, line_sim.shift_over
    replies = []
    try:
        line_sim.line = Line(STAGES, 0.5, 42, 100)
        line_sim.publish = lambda _client, _topic, payload: replies.append(payload)
        line_sim.shift_over = True
        command = {"command_id": "late1234", "action": "increase_rate",
                   "stage_index": 1, "old_rate": 0.8, "new_rate": 0.88}
        line_sim.on_command(None, None, SimpleNamespace(payload=json.dumps(command).encode()))
        assert replies[-1]["accepted"] is False
        assert replies[-1]["reason"] == "shift finished; command not applied"
        assert line_sim.line.stages[1].rate == 0.8
    finally:
        line_sim.line, line_sim.publish, line_sim.shift_over = (
            old_line, old_publish, old_shift_over)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validation_accepts_a_good_record():
    ok, reason = analytics.validate(
        {"asset": 0, "ts_dataset": "2022-03-28T04:00:00+00:00",
         "items": 3.0, "status": 2})
    assert ok, reason


def test_validation_rejects_negative_items():
    ok, reason = analytics.validate(
        {"asset": 0, "ts_dataset": "x", "items": -5, "status": 2})
    assert not ok and "negative" in reason


def test_validation_rejects_unknown_status():
    # The audit found only status 1, 2 and 3 in the file.
    ok, reason = analytics.validate(
        {"asset": 0, "ts_dataset": "x", "items": 1, "status": 99})
    assert not ok and "status" in reason


def test_validation_rejects_missing_field():
    ok, reason = analytics.validate({"asset": 0, "items": 1, "status": 1})
    assert not ok and "ts_dataset" in reason


# ---------------------------------------------------------------------------
# Machine alerts
# ---------------------------------------------------------------------------
def make_metrics(**over):
    base = {
        "coverage": 1.0, "window_slots": 6, "alarm_share": 0.0,
        "baseline_ratio": 1.0, "baseline_items_per_slot": 3.0,
        "items_per_productive_slot": 3.0, "baseline_hour": 4,
    }
    base.update(over)
    return base


def test_low_coverage_does_not_raise_a_false_alarm():
    analytics.low_streak[99] = 0
    analytics.alarm_streak[99] = 0
    a = analytics.classify(make_metrics(coverage=0.2, window_slots=1), 99)
    assert a["kind"] == "insufficient_data"


def test_sustained_alarm_is_called_an_interruption():
    analytics.low_streak[98] = 0
    analytics.alarm_streak[98] = 0
    m = make_metrics(alarm_share=0.9, baseline_ratio=None,
                     items_per_productive_slot=None)
    got = [analytics.classify(m, 98) for _ in range(4)]
    assert got[0] is None and got[1] is None          # not yet sustained
    assert got[2]["kind"] == "interruption"
    assert got[2]["recommendation"] == "investigate interruption"


def test_sustained_low_output_is_called_underperformance():
    analytics.low_streak[97] = 0
    analytics.alarm_streak[97] = 0
    m = make_metrics(baseline_ratio=0.3, items_per_productive_slot=0.9)
    got = [analytics.classify(m, 97) for _ in range(4)]
    assert got[2]["kind"] == "underperformance"
    # We must NOT claim to know the cause - the dataset cannot tell us.
    assert "not determinable" in got[2]["recommendation"]


def test_one_bad_slot_is_not_enough_to_alert():
    analytics.low_streak[96] = 0
    analytics.alarm_streak[96] = 0
    assert analytics.classify(make_metrics(baseline_ratio=0.1), 96) is None


# ---------------------------------------------------------------------------
# Decision engine
# ---------------------------------------------------------------------------
def state(second, stages):
    return {"sim_second": second, "stages": stages}


def stage(i, busy, queue, rate=0.8, configured=0.8, down=False, starved=0.0):
    return {"stage_index": i, "stage_name": f"Stage {i + 1}",
            "busy_share": busy, "queue_length": queue,
            "starved_share": starved, "rate_per_min": rate,
            "configured_rate": configured, "is_down": down}


def test_healthy_line_gets_no_command():
    """The single most important negative test: a line that is fine must be
    left alone. Stage 3 is the busiest at 83% but its queue is stable."""
    memory = decision.new_memory()
    actions = []
    for k in range(20):
        s = state(5000 + k * 300,
                  [stage(0, 0.62, 1), stage(1, 0.62, 1), stage(2, 0.83, 4,
                                                               rate=0.6,
                                                               configured=0.6)])
        actions.append(decision.choose_action(s, memory))
    assert all(a is None for a in actions), [a for a in actions if a]


def test_warmup_blocks_early_action():
    memory = decision.new_memory()
    for k in range(5):
        s = state(k * 300, [stage(0, 1.0, 20), stage(1, 0.5, 0),
                            stage(2, 0.5, 0)])
        assert decision.choose_action(s, memory) is None


def test_growing_queue_on_a_busy_stage_is_flagged():
    memory = decision.new_memory()
    action = None
    for k in range(8):
        s = state(5000 + k * 300,
                  [stage(0, 0.6, 0), stage(1, 1.0, 5 + k * 3), stage(2, 0.3, 0,
                                                                     starved=0.6)])
        action = decision.choose_action(s, memory) or action
    assert action is not None, "a growing queue on a busy stage was missed"
    assert action["type"] == "command"
    assert action["stage_index"] == 1, "flagged the wrong stage"


def test_action_is_bounded_by_the_ceiling():
    """The engine may never raise a stage above max_rate_multiplier."""
    memory = decision.new_memory()
    ceiling = 0.8 * decision.DEC["max_rate_multiplier"]
    last = None
    for k in range(40):
        rate = last["new_rate"] if last else 0.8
        s = state(5000 + k * 300,
                  [stage(0, 0.6, 0),
                   stage(1, 1.0, 10 + k * 2, rate=rate, configured=0.8),
                   stage(2, 0.3, 0)])
        a = decision.choose_action(s, memory)
        if a and a["type"] == "command":
            last = a
            assert a["new_rate"] <= ceiling + 1e-9, "went past the ceiling"
    assert memory["commands_sent"] <= decision.DEC["max_commands"]


def test_a_stopped_stage_gets_advice_not_more_capacity():
    """The alarm case. Speeding up a stopped machine achieves nothing."""
    memory = decision.new_memory()
    action = None
    for k in range(8):
        s = state(5000 + k * 300,
                  [stage(0, 0.6, 0), stage(1, 0.0, 10 + k, down=True),
                   stage(2, 0.1, 0)])
        action = decision.choose_action(s, memory) or action
    assert action is not None
    assert action["type"] == "advice"
    assert action["recommendation"] == "investigate interruption"


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
def test_same_seed_gives_the_same_arrivals():
    """This is what makes the before/after comparison fair."""
    a = Line(STAGES, 0.5, seed=42, duration=3600)
    b = Line(STAGES, 0.5, seed=42, duration=3600)
    assert a.arrivals == b.arrivals


def test_different_seed_gives_different_arrivals():
    a = Line(STAGES, 0.5, seed=1, duration=3600)
    b = Line(STAGES, 0.5, seed=2, duration=3600)
    assert a.arrivals != b.arrivals


def test_no_token_is_lost():
    """Everything that arrived is either finished or still somewhere."""
    line = Line(STAGES, 0.5, seed=7, duration=7200)
    while line.second < line.duration:
        line.step()

    in_queues = sum(len(s.queue) for s in line.stages)
    in_service = sum(1 for s in line.stages if s.token is not None)
    assert line.next_arrival == len(line.finished) + in_queues + in_service


def test_slowing_a_stage_makes_its_queue_grow():
    """Ground truth: we break stage 2, so stage 2 must be the one backing up."""
    scenario = {"kind": "slowdown", "stage_index": 1, "start_second": 1800,
                "severity": 0.4, "alarm_duration_seconds": 0}
    line = Line(STAGES, 0.5, seed=42, duration=14400)
    while line.second < line.duration:
        line.apply_scenario(scenario)
        line.step()

    queues = [len(s.queue) for s in line.stages]
    assert queues[1] == max(queues), f"expected stage 2 to back up, got {queues}"
    assert queues[1] > 5


def test_a_healthy_line_keeps_its_queues_small():
    line = Line(STAGES, 0.5, seed=42, duration=14400)
    while line.second < line.duration:
        line.step()
    assert all(len(s.queue) < 15 for s in line.stages)
    assert len(line.finished) > 50


def test_busy_share_is_recent_not_cumulative():
    """A stage that breaks late must look busy quickly, not slowly."""
    line = Line(STAGES, 0.5, seed=42, duration=10000, metrics_window=900)
    for s in line.stages:
        assert s.recent_busy.maxlen == 900


# ---------------------------------------------------------------------------
# Features - the leakage tests
# ---------------------------------------------------------------------------
def test_features_use_only_the_past_and_target_only_the_future():
    import pandas as pd
    import ml_features

    # 40 slots, items = 0,1,2,...  so we can check the arithmetic by eye.
    n = 40
    g = pd.DataFrame({
        "slot": pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC"),
        "items": range(n),
        "productive_share": [1.0] * n,
        "alarm_share": [0.0] * n,
        "power_mean": [1.0] * n,
        "cycle_time_mean": [30.0] * n,
    })
    out = ml_features.build_for_asset(g, asset=0, all_assets=[0])
    row = out.iloc[0]
    now = int(row["items_lag1"]) + 1      # the slot being predicted FROM

    # lag1 is the previous slot, lag2 the one before it, and so on.
    for lag in range(1, ml_features.LOOKBACK + 1):
        assert row[f"items_lag{lag}"] == now - lag

    # The target is the sum of the CURRENT and following slots, never a lag.
    expected = sum(range(now, now + ml_features.HORIZON))
    assert row["target_items_next30"] == expected


def test_windows_touching_a_gap_are_dropped():
    import pandas as pd
    import ml_features

    n = 60
    g = pd.DataFrame({
        "slot": pd.date_range("2022-01-01", periods=n, freq="5min", tz="UTC"),
        "items": [5] * n,
        "productive_share": [1.0] * n,
        "alarm_share": [0.0] * n,
        "power_mean": [1.0] * n,
        "cycle_time_mean": [30.0] * n,
    })
    full = ml_features.build_for_asset(g, 0, [0])

    # Punch a hole in the middle and rebuild.
    holed = g.drop(index=range(28, 32))
    gapped = ml_features.build_for_asset(holed, 0, [0])

    assert len(gapped) < len(full), "a gap must remove some windows"
    # Nothing that survived may span the hole.
    hole_start = g["slot"].iloc[28]
    hole_end = g["slot"].iloc[31]
    for ts in gapped["slot"]:
        window_start = ts - pd.Timedelta(minutes=5 * ml_features.LOOKBACK)
        window_end = ts + pd.Timedelta(minutes=5 * ml_features.HORIZON)
        assert not (window_start <= hole_start and window_end >= hole_end)


def test_live_features_match_the_training_column_order():
    import ml_features

    columns = (
        [f"{c}_lag{l}" for c in ml_features.LAG_SOURCES
         for l in range(1, ml_features.LOOKBACK + 1)]
        + ["items_sum_last30", "items_mean_last30", "items_max_last30",
           "hour", "dayofweek", "is_weekend", "asset_0", "asset_1"]
    )
    rows = [
        {"items": 3.0, "status": 2, "power_avg": 1.0, "cycle_time": 30.0,
         "ts_dataset": f"2022-03-28T04:{m:02d}:00+00:00"}
        for m in range(0, 30, 5)
    ]
    vec = ml_features.features_from_live_rows(1, rows, columns)

    assert len(vec) == len(columns)
    assert vec[columns.index("asset_1")] == 1
    assert vec[columns.index("asset_0")] == 0
    assert vec[columns.index("items_sum_last30")] == 18.0
    # lag1 must be the MOST RECENT row.
    assert vec[columns.index("items_lag1")] == 3.0


# ---------------------------------------------------------------------------
def test_live_coverage_tracks_distinct_recent_slots():
    from datetime import datetime, timedelta, timezone

    asset = 901
    analytics.history.pop(asset, None)
    start = datetime(2022, 3, 28, 4, tzinfo=timezone.utc)
    def event(minutes):
        return {"asset": asset, "ts_dataset": (start + timedelta(minutes=minutes)).isoformat(),
                "items": 2, "status": 2, "power_avg": 10, "cycle_time": 30}
    for minute in (0, 5, 10, 15, 20, 25):
        assert analytics.update_history(asset, event(minute))[0]
    assert analytics.compute_metrics(asset)["coverage"] == 1.0
    assert analytics.update_history(asset, event(25)) == (True, False)
    assert analytics.compute_metrics(asset)["coverage"] == 1.0
    assert analytics.update_history(asset, event(120)) == (True, True)
    assert analytics.compute_metrics(asset)["coverage"] == 0.167
    analytics.history.pop(asset, None)


def test_live_features_align_with_offline_origin():
    import pandas as pd
    import ml_features
    slots = pd.date_range("2022-03-28 23:20", periods=20, freq="5min", tz="UTC")
    frame = pd.DataFrame({
        "slot": slots, "items": list(range(20)),
        "productive_share": [1.0] * 20, "alarm_share": [0.0] * 20,
        "power_mean": [10.0] * 20, "cycle_time_mean": [30.0] * 20,
    })
    offline = ml_features.build_for_asset(frame, 0, [0])
    origin = slots[6]
    row = offline.loc[offline["slot"] == origin].iloc[0]
    columns = ml_features.feature_columns(offline)
    live = ml_features.features_from_live_rows(
        0, frame.iloc[:6].to_dict("records"), columns)
    assert live == [float(row[c]) for c in columns]
    assert row["hour"] == 23


def test_split_purges_targets_at_boundaries():
    import pandas as pd
    import ml_train
    slots = pd.date_range("2022-01-01", periods=100, freq="5min", tz="UTC")
    frame = pd.DataFrame({"slot": slots, "target_items_next30": [1] * 100})
    train, valid, test = ml_train.chronological_split(frame)
    horizon = pd.Timedelta(minutes=25)
    assert max(train["slot"] + horizon) < min(valid["slot"])
    assert max(valid["slot"] + horizon) < min(test["slot"])


def test_forecast_produces_explicit_advisory():
    import json
    from types import SimpleNamespace
    class Client:
        def __init__(self):
            self.sent = []
        def publish(self, name, payload, qos=0):
            self.sent.append((name, json.loads(payload)))
    asset = 902
    client = Client()
    metrics = {"asset": asset, "baseline_items_per_slot": 3.0,
               "productive_share": 1.0, "coverage": 1.0}
    decision.on_message(client, None, SimpleNamespace(
        topic=decision.topic("observed_metrics", asset),
        payload=json.dumps(metrics).encode()))
    decision.on_message(client, None, SimpleNamespace(
        topic=decision.topic("forecast", asset),
        payload=json.dumps({"asset": asset, "predicted_items": 2,
                            "model": "test", "ts_dataset": "2022-01-01"}).encode()))
    assert client.sent[-1][0] == decision.topic("forecast_advisory")
    assert client.sent[-1][1]["recommendation"] == "inspect machine or replan workload"
    decision.recent_machine_metrics.pop(asset, None)

def test_audit_coverage_ignores_duplicate_records():
    import pandas as pd
    import audit
    slots = pd.date_range("2022-03-28 04:00", periods=12, freq="5min", tz="UTC")
    rows = [{"ts": ts, "asset": asset, "items": 1, "status": 2}
            for ts in slots for asset in (0, 1, 8)]
    rows.append({"ts": slots[0], "asset": 0, "items": 1, "status": 2})
    windows = audit.find_replay_windows(
        pd.DataFrame(rows), [0, 1, 8], hours=1, min_coverage=1.0)
    assert windows and windows[0]["coverage_per_asset"]["0"] == 1.0

def test_validation_rejects_boolean_status():
    ok, reason = analytics.validate(
        {"asset": 0, "ts_dataset": "2022-03-28T04:00:00+00:00",
         "items": 3, "status": True})
    assert not ok and "status" in reason

def test_command_round_trip_is_timed_on_one_clock():
    import decision
    decision.command_sent_at.clear()
    decision.command_sent_at["abcd1234"] = 100.0
    metric = decision.round_trip_metric("abcd1234", True, now=100.4)
    assert metric["metric"] == "command_round_trip_ms" and metric["value"] == 400.0
    assert "accepted" in metric["detail"]
    assert decision.round_trip_metric("abcd1234", True) is None   # counted once
    assert decision.round_trip_metric("unknown1", True) is None   # never sent here


def test_new_seed_is_random_but_default_seed_is_reproducible():
    import ml_demo
    import ml_train
    from common import CONFIG
    assert ml_demo.resolve_seed(None) == CONFIG["ml"]["random_state"]
    assert ml_demo.resolve_seed(7) == 7
    assert ml_demo.resolve_seed("junk") == CONFIG["ml"]["random_state"]
    seeds = {ml_demo.resolve_seed("new") for _ in range(20)}
    assert len(seeds) > 1 and all(1 <= s <= 99999 for s in seeds)
    nn = ml_train.model_specs(1.0, seed=123)["neural_network"]["build"]()
    assert nn.steps[-1][1].random_state == 123
    gb = ml_train.model_specs(1.0)["gradient_boosting"]["build"]()
    assert gb.random_state == CONFIG["ml"]["random_state"]


def test_seed_controls_store_the_seed_and_show_the_spread():
    import json
    from common import ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text(encoding="utf-8"))}
    assert "$seed" in nodes["fn_ml_train"]["func"]
    assert "body.seed='new'" in nodes["fn_ui_action"]["func"]
    assert "AS n_seeds" in nodes["fn_db_queries"]["func"]
    card = nodes["ui_overview"]["format"]
    assert "Train with new seed" in card and "across {{msg.payload.demoModels[m.id].n_seeds}} seeds" in card
    assert "seed INTEGER" in (ROOT / "db" / "schema.sql").read_text()


def test_live_model_view_is_wired():
    import json
    from common import ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text(encoding="utf-8"))}
    q = nodes["fn_db_queries"]
    assert q["outputs"] == 7 and q["wires"][4:] == [["db_live"], ["db_b_hits"], ["db_history"]]
    for name in ("live", "b_hits", "history"):
        assert nodes[f"db_{name}"]["wires"] == [[f"fn_db_{name}"]]
        assert nodes[f"fn_db_{name}"]["wires"] == [["fn_overview"]]
    assert "$tsd" in nodes["fn_forecast"]["func"]
    assert "body.use=true" in nodes["fn_ui_action"]["func"]
    panel = nodes["ui_overview"]["format"]
    for text in ("id='live-forecast-check'", "Train and use", "current bottleneck",
                 "Live forecasts switched to", "Red dashed line", "Same-state guess"):
        assert text in panel, text


def test_command_gap_is_measured_within_one_shift():
    import decision
    memory = decision.new_memory()
    assert decision.command_gap_metric(memory, 11160) is None          # first command
    gap = decision.command_gap_metric(memory, 13260)
    assert gap["metric"] == "command_gap_s" and gap["value"] == 2100.0
    fresh = decision.new_memory()                                       # restarted shift
    assert decision.command_gap_metric(fresh, 11160) is None


def test_forecast_latency_uses_node_red_receive_stamp():
    import time
    started = time.perf_counter()
    metrics = dict(analytics.latency_metrics(started, received_ms=1000.0, now_ms=1085.0))
    assert metrics["ingest_to_forecast_ms"] == 85.0
    assert metrics["forecast_compute_ms"] >= 0
    # A missing or impossible stamp gives no end-to-end figure, never a wrong one.
    assert "ingest_to_forecast_ms" not in dict(analytics.latency_metrics(started))
    assert "ingest_to_forecast_ms" not in dict(
        analytics.latency_metrics(started, received_ms=5000.0, now_ms=1000.0))


def test_new_replay_run_restarts_a_machines_window():
    old = (dict(analytics.history), dict(analytics.last_run_id), dict(analytics.low_streak))
    try:
        analytics.history.clear(); analytics.last_run_id.clear()
        assert analytics.start_new_run_if_needed(5, "run1") is False   # first run
        analytics.history[5] = ["old window"]
        analytics.low_streak[5] = 3
        assert analytics.start_new_run_if_needed(5, "run1") is False   # same run
        assert analytics.history[5] == ["old window"]
        assert analytics.start_new_run_if_needed(5, "run2") is True    # replayed again
        assert 5 not in analytics.history and 5 not in analytics.low_streak
    finally:
        analytics.history.clear(); analytics.history.update(old[0])
        analytics.last_run_id.clear(); analytics.last_run_id.update(old[1])
        analytics.low_streak.clear(); analytics.low_streak.update(old[2])


def test_restarted_virtual_shift_resets_the_detector():
    import json
    import decision

    class Msg:
        def __init__(self, topic, payload):
            self.topic, self.payload = topic, json.dumps(payload).encode()
    decision.memory["commands_sent"] = 4
    decision.last_check_second = 20000
    decision.pending = {"command_id": "deadbeef"}
    decision.on_message(None, None, Msg(decision.topic("sim_state"),
                                        {"sim_second": 60, "stages": []}))
    assert decision.memory["commands_sent"] == 0
    assert decision.pending is None and decision.last_check_second == 60


def test_ml_driven_line_is_off_by_default_and_follows_forecasts():
    import line_sim
    from common import CONFIG
    sim = CONFIG["simulation"]
    plain = line_sim.Line(sim["stages"], sim["arrival_rate_per_min"], sim["seed"], 7200)
    again = line_sim.Line(sim["stages"], sim["arrival_rate_per_min"], sim["seed"], 7200)
    assert plain.arrivals == again.arrivals          # identical-arrivals comparison kept
    assert all(s.ml_factor == 1.0 for s in plain.stages)
    for _ in range(3600):
        plain.step()
    assert plain.tokens_arrived == plain.next_arrival
    snap = plain.snapshot()["stages"][0]
    assert snap["ml_forecast"] is None and snap["effective_rate"] == snap["rate_per_min"]

    line = line_sim.Line(sim["stages"], 0.62, sim["seed"], 7200)
    stage1 = line.stages[0]                          # calibrated 0.8 tokens/min
    assert line.set_ml_forecast(0, 0, 12.0, "demo_ridge") == 0.5      # 12/30 = 0.4 = 50%
    assert line.set_ml_forecast(0, 0, 1000.0, "demo_ridge") == line_sim.ML_DRIVEN["factor_max"]
    assert line.set_ml_forecast(0, 0, 0.0, "demo_ridge") == line_sim.ML_DRIVEN["factor_min"]
    line.set_ml_forecast(0, 0, 12.0, "demo_ridge")
    snap = line.snapshot()
    assert snap["ml_model"] == "demo_ridge" and snap["stages"][0]["effective_rate"] == 0.4
    assert stage1.rate == 0.8                         # the operator-set rate is untouched


def test_ml_driven_proposal_explains_the_model_forecast():
    import decision
    stage = {"stage_name": "Stage 1 - Cutting", "ml_machine": 0, "ml_forecast": 12.0,
             "effective_rate": 0.4, "ml_factor": 0.5, "rate_per_min": 0.8}
    text = decision.model_basis(stage, "demo_ridge")
    assert "demo_ridge" in text and "machine 0" in text and "12.0 items" in text and "50%" in text
    assert decision.model_basis({"stage_name": "x", "ml_forecast": None}, None) == ""

def test_closed_loop_panel_and_restart_controls_are_wired():
    import json
    from common import CONFIG, ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text(encoding="utf-8"))}
    assert CONFIG["topics"]["perf_metric"] == "team12/perf/metric"
    assert nodes["in_perf"]["topic"] == "team12/perf/metric"
    assert nodes["in_perf"]["wires"] == [["fn_perf"]] and nodes["fn_perf"]["wires"] == [["sql_bind"]]
    assert "INSERT INTO loop_metrics" in nodes["fn_perf"]["func"]
    assert "'command_gap_s'" in nodes["fn_perf"]["func"]
    assert "m.received_ms = receivedMs" in nodes["fn_validate"]["func"]
    assert "AS rt_avg" in nodes["fn_db_queries"]["func"] and "AS a_run" in nodes["fn_db_queries"]["func"]
    assert "restart_line" in nodes["fn_ui_action"]["func"]
    panel = nodes["ui_overview"]["format"]
    assert "id='closed-loop-performance'" in panel
    assert "Restart virtual shift" in panel and "Replay Company A again" in panel
    assert "CREATE TABLE IF NOT EXISTS loop_metrics" in (ROOT / "db" / "schema.sql").read_text()


def test_switching_model_refreshes_forecasts_immediately():
    # A model switch after the replay ends must still update the forecast panel.
    calls, old = [], (analytics.history, analytics.try_forecast, analytics.compute_metrics, analytics.MODEL)
    try:
        analytics.history = {0: [{"x": 1}], 1: [{"x": 1}], 8: []}
        analytics.compute_metrics = lambda asset: {"coverage": 1.0 if asset == 0 else 0.5}
        analytics.try_forecast = lambda client, asset, **kw: calls.append(asset)
        analytics.MODEL = {"name": "demo_ridge"}
        assert analytics.refresh_forecasts(None) == 1
        assert calls == [0]          # only full-coverage windows are re-forecast
    finally:
        analytics.history, analytics.try_forecast, analytics.compute_metrics, analytics.MODEL = old


def test_ml_receives_only_node_red_stored_records():
    import json
    from common import CONFIG, ROOT
    flow = json.loads((ROOT / "nodered" / "flow.json").read_text())
    nodes = {node["id"]: node for node in flow}
    assert nodes["in_machine"]["wires"] == [["fn_validate"]]
    assert nodes["fn_validate"]["wires"][0][0] == "sql_bind"
    assert nodes["sql_bind"]["wires"][0] == ["db_events"]
    assert nodes["db_events"]["wires"] == [["fn_publish_validated"]]
    assert nodes["fn_publish_validated"]["wires"] == [["out_validated"]]
    assert "validated_payload: m" in nodes["fn_validate"]["func"]
    assert CONFIG["topics"]["observed_validated"] in nodes["fn_publish_validated"]["func"]


def test_model_choice_uses_validation_only():
    import ml_train
    candidates = {
        "linear": {"kind": "model", "valid_active": {"mae": 2.0},
                   "model_size_mb": 0.01},
        "ensemble": {"kind": "model", "valid_active": {"mae": 1.5},
                     "model_size_mb": 1.0},
        "neural": {"kind": "model", "valid_active": {"mae": 1.6},
                   "model_size_mb": 0.05},
    }
    name, _ = ml_train.choose_model(candidates)
    assert name == "ensemble"


def _cv_candidate(mean, folds, size):
    return {"kind": "model", "valid_active": {"mae": mean},
            "cv_active_mae": {"mean": mean, "per_fold": folds},
            "model_size_mb": size}


def test_recent_fold_breaks_a_tie_before_model_size():
    """Two families inside the tie margin on the fold mean. The one that is
    clearly better on the LATEST fold must win, even though it is larger -
    this dataset drifts, so the newest fold is the best guide to next month."""
    import ml_train
    candidates = {
        # mean 1.74 vs 1.76 = within the 2% margin, so the means are a tie.
        "ensemble": _cv_candidate(1.739, [2.139, 1.693, 1.556, 1.568], 1.04),
        "neural": _cv_candidate(1.764, [2.072, 1.671, 1.661, 1.653], 0.07),
    }
    name, _ = ml_train.choose_model(
        candidates,
        metric=lambda r: r["cv_active_mae"]["mean"],
        recent=lambda r: r["cv_active_mae"]["per_fold"][-1])
    assert name == "ensemble", "model size must not outrank accuracy evidence"


def test_model_size_still_breaks_a_genuine_tie():
    """When the latest fold is a tie too, the cheaper model to load wins."""
    import ml_train
    candidates = {
        "ensemble": _cv_candidate(1.700, [1.70, 1.70, 1.70, 1.700], 1.04),
        "neural": _cv_candidate(1.705, [1.70, 1.70, 1.70, 1.701], 0.07),
    }
    name, _ = ml_train.choose_model(
        candidates,
        metric=lambda r: r["cv_active_mae"]["mean"],
        recent=lambda r: r["cv_active_mae"]["per_fold"][-1])
    assert name == "neural"


def test_rolling_origin_folds_never_train_on_the_future():
    """Every fold trains only on origins before the block it scores, and the
    label embargo is applied at each boundary."""
    import pandas as pd
    import ml_train
    slots = pd.date_range("2022-01-01", periods=400, freq="5min", tz="UTC")
    frame = pd.DataFrame({"slot": slots, "target_items_next30": [1] * 400})
    folds = ml_train.rolling_origin_folds(frame, 4)
    embargo = ml_train.label_span()

    assert len(folds) == 4
    previous_train = -1
    for fold_train, fold_valid in folds:
        # no training origin may reach into the validation block
        assert (fold_train["slot"] + embargo).max() < fold_valid["slot"].min()
        # the window expands, never slides backwards
        assert len(fold_train) > previous_train
        previous_train = len(fold_train)
    # each validation block starts after the one before it
    starts = [fold_valid["slot"].min() for _, fold_valid in folds]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)


def test_idle_score_counts_wrongly_promised_output():
    """Idle MAE must measure output predicted for a machine that produced
    nothing - the 'crying wolf' error Active MAE cannot see."""
    import numpy as np
    import ml_train
    actual = np.array([0.0, 0.0, 0.0, 0.0, 5.0])
    predicted = np.array([0.0, 2.0, 0.0, 2.0, 5.0])
    idle = ml_train.idle_scores(actual, predicted)
    assert idle["n"] == 4
    assert idle["mae"] == 1.0              # (0 + 2 + 0 + 2) / 4
    assert idle["over_1_item_share"] == 0.5  # two of the four exceed 1 item
    # a model that never promises phantom output scores zero here
    assert ml_train.idle_scores(actual, np.zeros(5))["mae"] == 0.0


def test_production_monitor_has_models_graphs_tables_and_live_wiring():
    import json
    from common import ROOT
    flow = json.loads((ROOT / "nodered" / "flow.json").read_text())
    nodes = {node["id"]: node for node in flow}
    assert len([n for n in flow if n["type"] == "ui_tab"]) == 1
    assert nodes["ui_tab_present"]["name"].endswith("A + B")
    overview = nodes["ui_overview"]["format"]
    for name in ("Ridge", "Gradient boosting", "Neural network"):
        assert name in overview
    for content in ("<table>", "<svg", "Forecast trend", "Virtual queue trend",
                    "Recorded output trend", "Stage busy time", "Stage status",
                    "Four-fold mean active MAE", "Test idle MAE", "id='database-status'"):
        assert content in overview
    assert "ui_overview" in nodes["fn_overview"]["wires"][0]
    for source in ("in_metrics", "in_forecast", "in_forecast_advisory",
                   "in_sim_state", "in_sim_cmd", "in_sim_ack"):
        assert "fn_overview" in nodes[source]["wires"][0]


def test_dashboard_reads_counts_and_recent_rows_from_sqlite():
    import json
    from common import ROOT
    flow = json.loads((ROOT / "nodered" / "flow.json").read_text())
    nodes = {node["id"]: node for node in flow}
    assert "fn_db_queries" in nodes["db_poll"]["wires"][0]
    assert nodes["db_counts"]["mydb"] == nodes["db_recent"]["mydb"] == "sqlite_db"
    assert "machine_events" in nodes["fn_db_queries"]["func"]
    assert "rejected_records" in nodes["fn_db_queries"]["func"]
    assert "fn_overview" in nodes["fn_db_counts"]["wires"][0]
    assert "fn_overview" in nodes["fn_db_recent"]["wires"][0]


def test_demo_training_uses_forward_time_with_label_embargo():
    from ml_demo import demo_data
    from ml_train import label_span
    train, valid, columns = demo_data()
    assert len(columns) == 45
    assert (train["slot"].max() + label_span()) < valid["slot"].min()
    assert (valid["target_items_next30"] > 0).any()
    assert train["slot"].max().date().isoformat() < "2022-03-28"


def test_demo_forecast_guard_marks_out_of_range_predictions():
    bundle = {"forecast_limit_by_asset": {"1": 30.0}}
    assert analytics.guard_prediction(bundle, 1, 243.0) == (30.0, True, 30.0)
    assert analytics.guard_prediction(bundle, 1, 20.0) == (20.0, False, 30.0)
    assert analytics.guard_prediction({}, 1, -4.0) == (0.0, False, None)


def test_dashboard_controls_reach_trainer_and_approval_topics():
    import json
    from common import ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text())}
    panel = nodes["ui_overview"]["format"]
    assert "Train demo model" in panel and "Use for live forecasts" in panel
    assert "Accept and send command" in panel and "Reject action" in panel
    assert nodes["ui_overview"]["wires"] == [["fn_ui_action"]]
    for name in ("team12/ml/train/request", "team12/ml/select", "team12/sim/approval"):
        assert name in nodes["fn_ui_action"]["func"]
    assert "fn_sim_review" in nodes["in_sim_review"]["wires"][0]
    assert "fn_ml_train" in nodes["in_ml_train"]["wires"][0]
    assert "db_ml_runs" in nodes["fn_db_queries"]["wires"][2]
    assert "fn_overview" in nodes["fn_db_models"]["wires"][0]
    assert "prediction_guarded" in nodes["fn_forecast"]["func"]


def test_mqtt_session_survives_dropouts_and_buttons_use_qos1():
    import json
    from common import ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text(encoding="utf-8"))}
    broker = nodes["mqtt_broker"]
    assert broker["cleansession"] is False      # broker queues QoS 1 messages during a dropout
    assert broker["clientid"]                   # a fixed client ID is needed to resume the session
    assert str(nodes["out_ui_action"]["qos"]) == "1"   # dashboard clicks are not lost
    for node_id in ("in_machine", "in_b_raw"):
        assert nodes[node_id]["qos"] in (1, "1")


def test_company_buttons_route_to_device_and_live_comparison():
    import json
    from common import CONFIG, ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text())}
    panel = nodes["ui_overview"]["format"]
    assert "Start Company A" in panel and "Start Company B" in panel
    assert "id='replay-controls'" in panel
    assert "live-comparison:start" in panel
    assert "team12/replay/control" in nodes["fn_ui_action"]["func"]
    assert nodes["in_replay_status"]["wires"] == [["fn_overview"]]
    assert "AS a_alarm_pct" in nodes["fn_db_queries"]["func"]
    assert "AS b_alarm_pct" in nodes["fn_db_queries"]["func"]
    assert CONFIG["topics"]["replay_control"] == "team12/replay/control"
    assert CONFIG["topics"]["replay_status"] == "team12/replay/status"


def test_company_b_rolling_metric_uses_its_own_status_vocabulary():
    import analytics_b
    analytics_b.history.clear()
    base = {"asset": 999, "ts_dataset": "2022-03-28T04:00:00+00:00"}
    analytics_b.update({**base, "status": "Production"})
    analytics_b.update({**base, "ts_dataset": "2022-03-28T04:01:00+00:00",
                        "status": "Standby"})
    result = analytics_b.update({**base, "ts_dataset": "2022-03-28T04:02:00+00:00",
                                 "status": "Alarm"})
    assert result["company"] == "B"
    assert result["conditional_alarm_pct"] == 50.0
    assert result["production_share"] == .333


def test_company_b_has_separate_storage_and_comparison_chart():
    import json
    from common import ROOT
    nodes = {n["id"]: n for n in json.loads((ROOT / "nodered" / "flow.json").read_text())}
    assert nodes["in_b_raw"]["wires"] == [["fn_b_validate"]]
    assert nodes["db_b_events"]["wires"] == [["fn_b_publish"]]
    assert "in_b_metrics" in nodes
    assert "id='company-comparison'" in nodes["ui_overview"]["format"]
    report = json.loads((ROOT / "results" / "company_comparison.json").read_text())
    assert report["summary"]["A"]["months"] == report["summary"]["B"]["months"] == 9
    assert report["summary"]["A"]["mean_monthly_report_density_pct"] > report["summary"]["B"]["mean_monthly_report_density_pct"]


def test_rejected_virtual_proposal_never_reaches_actuator():
    import json
    from types import SimpleNamespace
    from common import topic
    sent = []
    old_publish = decision.publish
    old_pending = decision.pending
    old_memory = decision.memory
    try:
        decision.publish = lambda client, destination, payload: sent.append(destination)
        decision.memory = decision.new_memory()
        decision.memory["commands_sent"] = 1
        decision.pending = {"command_id": "abcd1234", "sim_second": 7000,
                            "stage_index": 1, "stage_name": "Welding", "old_rate": .4,
                            "new_rate": .44, "reason": "test"}
        msg = SimpleNamespace(topic=topic("sim_approval"),
                              payload=json.dumps({"proposal_id": "abcd1234",
                                                  "decision": "reject"}).encode())
        decision.on_message(None, None, msg)
        assert topic("sim_review") in sent
        assert topic("sim_command") not in sent
        assert decision.memory["commands_sent"] == 0
        assert decision.pending is None
    finally:
        decision.publish = old_publish
        decision.pending = old_pending
        decision.memory = old_memory


def test_approved_proposal_is_logged_before_command():
    import json
    from types import SimpleNamespace
    from common import topic
    sent = []
    old_publish, old_pending, old_memory = decision.publish, decision.pending, decision.memory
    try:
        decision.publish = lambda client, destination, payload: sent.append((destination, payload))
        decision.memory = decision.new_memory()
        decision.memory["commands_sent"] = 1
        decision.pending = {"command_id": "1234abcd", "sim_second": 7000,
                            "stage_index": 1, "stage_name": "Welding", "old_rate": .4,
                            "new_rate": .44, "reason": "test", "ts_replay": "old-proposal-time"}
        msg = SimpleNamespace(topic=topic("sim_approval"),
                              payload=json.dumps({"proposal_id": "1234abcd",
                                                  "decision": "accept"}).encode())
        decision.on_message(None, None, msg)
        assert [t for t, _ in sent] == [topic("sim_review"), topic("sim_command")]
        assert sent[1][1]["ts_replay"] != "old-proposal-time"
    finally:
        decision.publish, decision.pending, decision.memory = old_publish, old_pending, old_memory


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failed.append((name, e))
            print(f"  FAIL  {name}: {e}")

    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())




