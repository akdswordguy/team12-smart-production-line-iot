"""Add "Train with new seed" and the across-seeds spread to the Interactive ML lab.

Idempotent: running it again changes nothing. It edits nodered/flow.json in
place, keeping its formatting (2-space JSON, CRLF endings).

"Train demo model" keeps the fixed study seed, so its score is reproducible.
"Train with new seed" retrains with a random seed. The card then shows the
seed used and, once several seeds exist, the mean and range of the score
across them. Picking the luckiest seed would be cherry-picking; the range
shows how much of a difference is just randomness.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common import CONFIG  # noqa: E402

FLOW = ROOT / "nodered" / "flow.json"
MARK = "Train with new seed"


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one match for {old[:60]!r}")
    return text.replace(old, new)


def main():
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in flow}
    template = nodes["ui_overview"]
    if MARK in template["format"]:
        print("Seed controls already installed; nothing to do.")
        return
    crlf = b"\r\n" in FLOW.read_bytes()
    default_seed = int(CONFIG["ml"]["random_state"])

    # 1. Store the seed of every training run.
    t = nodes["fn_ml_train"]
    t["func"] = replace_once(t["func"], "overall_mae,train_seconds) VALUES ($ts,$m,$tr,$vr,$av,$a,$i,$o,$s)'",
                             "overall_mae,train_seconds,seed) VALUES ($ts,$m,$tr,$vr,$av,$a,$i,$o,$s,$seed)'",
                             "fn_ml_train sql")
    t["func"] = replace_once(t["func"], "$s:p.train_seconds}",
                             "$s:p.train_seconds,$seed:Number.isInteger(p.seed)?p.seed:null}",
                             "fn_ml_train params")

    # 2. Forward an optional new-seed request from the dashboard.
    a = nodes["fn_ui_action"]
    a["func"] = replace_once(a["func"], "dest='team12/ml/train/request';body={model:p.model};",
                             "dest='team12/ml/train/request';body={model:p.model};if(p.seed==='new')body.seed='new';",
                             "fn_ui_action")

    # 3. Latest run per model plus the score spread across distinct seeds.
    q = nodes["fn_db_queries"]
    old_models = ('const models={topic:"SELECT r.* FROM ml_demo_runs r JOIN (SELECT model,MAX(id) AS last_id '
                  'FROM ml_demo_runs GROUP BY model) latest ON r.id=latest.last_id",payload:[]};')
    new_models = ('const models={topic:"SELECT r.*, COALESCE(r.seed,' + str(default_seed) + ') AS seed_used, '
                  's.n_seeds, s.mean_mae, s.min_mae, s.max_mae FROM ml_demo_runs r '
                  'JOIN (SELECT model,MAX(id) AS last_id FROM ml_demo_runs GROUP BY model) latest ON r.id=latest.last_id '
                  'JOIN (SELECT model, COUNT(*) AS n_seeds, ROUND(AVG(mae),3) AS mean_mae, MIN(mae) AS min_mae, MAX(mae) AS max_mae '
                  'FROM (SELECT model, COALESCE(seed,' + str(default_seed) + ') AS sd, MAX(active_mae) AS mae '
                  'FROM ml_demo_runs GROUP BY model, sd) GROUP BY model) s ON s.model=r.model",payload:[]};')
    q["func"] = replace_once(q["func"], old_models, new_models, "fn_db_queries models")

    # 4. Card: seed, spread and the new button.
    f = template["format"]
    f = replace_once(
        f,
        "· {{msg.payload.demoModels[m.id].train_seconds}}s</div>",
        "· {{msg.payload.demoModels[m.id].train_seconds}}s</div>\n"
        "        <div class='muted' ng-if='msg.payload.demoModels[m.id].status===\"trained\"'>"
        "Seed {{msg.payload.demoModels[m.id].seed_used || msg.payload.demoModels[m.id].seed}}"
        "<span ng-if='m.id===\"ridge\"'> (Ridge has no randomness, so its score never changes)</span>"
        "<span ng-if='msg.payload.demoModels[m.id].n_seeds > 1'> · across {{msg.payload.demoModels[m.id].n_seeds}} seeds: "
        "mean {{msg.payload.demoModels[m.id].mean_mae}}, range {{msg.payload.demoModels[m.id].min_mae}}–{{msg.payload.demoModels[m.id].max_mae}}</span></div>",
        "card spread")
    f = replace_once(
        f,
        "<button class='btn' ng-click='send({payload:{kind:\"train\",model:m.id}})'>Train demo model</button>",
        "<button class='btn' ng-click='send({payload:{kind:\"train\",model:m.id}})'>Train demo model</button>"
        "<button class='btn secondary' ng-click='send({payload:{kind:\"train\",model:m.id,seed:\"new\"}})'>Train with new seed</button>",
        "card button")
    f = replace_once(
        f,
        "These quick-run scores are separate from the full 681,935-example evaluation above.",
        "These quick-run scores are separate from the full 681,935-example evaluation above. "
        "<b>Train demo model</b> uses the fixed seed, so it repeats exactly; <b>Train with new seed</b> shows how much "
        "of a score difference is just randomness. Choosing the luckiest seed would be cherry-picking.",
        "lab intro")
    template["format"] = f

    text = json.dumps(flow, indent=2, ensure_ascii=False) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    FLOW.write_bytes(text.encode("utf-8"))
    print("Installed seed controls and the across-seeds spread.")


if __name__ == "__main__":
    main()
