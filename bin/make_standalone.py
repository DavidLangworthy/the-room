#!/usr/bin/env python3
"""Bake the template, the stylesheet and one run into a single runnable clock.py.

Usage: make_standalone.py <run_dir> <out.py>
"""
import base64, glob, gzip, json, os, re, sys

run_dir, out_path = sys.argv[1], sys.argv[2]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

src = json.load(open(f"{run_dir}/run.json"))
ORDER = src["order"]
NAMES = {"01-independent": ("Independent",
          "Asked alone. No participant can see another's answer before committing to its own — "
          "the property that keeps the room from collapsing into an echo of whoever spoke first."),
         "02-critique": ("Critique",
          "Each model now reads the other three and responds. Web search stays on, so a shaky "
          "number can be checked rather than deferred to."),
         "03-reconsider": ("Reconsider",
          "Where everyone stands after being argued with, what moved them, and what they still "
          "hold. Direct questions to a named participant are allowed here."),
         "04-exchange": ("Exchange",
          "Questions put by name get answered, and each model says the one thing it wants the "
          "room to keep.")}

meta = {}
for f in glob.glob(f"{run_dir}/seats/*.meta.jsonl"):
    for line in open(f):
        d = json.loads(line)
        meta[(d["seat"], d["round"])] = d          # last write wins = the turn that stuck

rounds = []
for rd in sorted(glob.glob(f"{run_dir}/rounds/*")):
    key = os.path.basename(rd)
    if not os.path.isdir(rd) or key.startswith("zz-"):
        continue
    turns = []
    for s in ORDER:
        p = f"{rd}/{s}.md"
        if not (os.path.exists(p) and open(p).read().strip()):
            continue
        d = meta.get((s, key), {})
        u = d.get("usage") or {}
        turns.append({"seat": s, "text": open(p).read().strip(),
                      "latency": d.get("latency_s"), "tokens": u.get("total_tokens"),
                      "cost": u.get("cost"), "cites": len(d.get("citations") or [])})
    if turns:
        name, note = NAMES.get(key, (key.split("-")[-1].title(), ""))
        rounds.append({"key": key, "name": name, "note": note, "turns": turns})

syn = open(f"{run_dir}/synthesis.md").read().strip() if os.path.exists(f"{run_dir}/synthesis.md") else ""
by = (re.match(r"_synthesized by ([^_]+)_", syn) or [None, "—"])[1]

run = {"run_id": src["run_id"], "question": src["prompt"], "date": src["date"],
       "seats": src["seats"], "order": ORDER, "rounds": rounds,
       "synthesis": re.sub(r"^_synthesized by [^_]+_\s*", "", syn), "synthesized_by": by}

blob = base64.b64encode(gzip.compress(json.dumps(
    {"run": run, "turning_points": json.load(open(f"{ROOT}/page/turning-points.json"))},
    separators=(",", ":")).encode(), 9)).decode()

css = open(f"{ROOT}/page/clock-room.html").read()
css = css[css.index("<style>") + 7:css.index("</style>")]
assert '"""' not in css and "\\" not in css, "stylesheet would break the triple-quoted literal"

tpl = open(f"{ROOT}/bin/_clock_template.py").read()
tpl = tpl.replace("{{CSS}}", css).replace("{{DATA}}", blob)
open(out_path, "w").write(tpl)
os.chmod(out_path, 0o755)

import py_compile
py_compile.compile(out_path, doraise=True)
print("%s  %.0f KB  (%d rounds, %d turns, sample %.0f KB compressed)"
      % (out_path, os.path.getsize(out_path) / 1024, len(rounds),
         sum(len(r["turns"]) for r in rounds), len(blob) / 1024))
