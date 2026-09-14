#!/usr/bin/env python3
"""Clock, inline. Four vendors in one room, holding an actual conversation.

  clock.py new "<question>"        start a run, hold round 1 (independent)
  clock.py round <run_dir> <name>  run the next round
  clock.py synth <run_dir> [seat]  build the synthesis
  clock.py transcript <run_dir>    rebuild transcript.md

Rounds are composed here, in code, from files on disk. A model decides what goes in
a turn; it never carries the turns. (agent-skills/agent-fleet-ops)
"""
import json, os, sys, subprocess, datetime, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date.today().strftime("%A %-d %B %Y")

SEATS = {"opus": "anthropic/claude-opus-5", "sol": "openai/gpt-5.6-sol",
         "gemini": "google/gemini-3.1-pro-preview", "grok": "x-ai/grok-4.6"}
LABELS = {"opus": "Claude (Anthropic)", "sol": "GPT (OpenAI)",
          "gemini": "Gemini (Google)", "grok": "Grok (xAI)"}
ORDER = ["opus", "sol", "gemini", "grok"]

SYSTEM = f"""You are {{SEAT}}, one of four AI models from four different companies \
sitting in one room and thinking together. The room is Claude (Anthropic), GPT (OpenAI), \
Gemini (Google) and Grok (xAI). Today is {TODAY}.

Talk like a person in a good conversation. Prose, your own voice, no headings, no bullet \
lists, no section labels, no restating the question back. Address the others directly by \
name when you are responding to them.

You are not here to be agreeable. Say what you actually think, disagree plainly when you \
disagree, and say plainly when you don't know or when you were wrong. You have web search: \
use it to check a claim rather than deferring to whoever sounded most confident. Never \
invent agreement that isn't there, and never manufacture disagreement that isn't there \
either. Be concise — a few tight paragraphs at most."""

ROUNDS = {
 "independent":
  "{Q}\n\nThis is the first round and you are answering alone — you have not seen and will "
  "not see what the others said before you commit to this. Give your own answer, on the "
  "record.",
 "critique":
  "The room has now spoken. Here is what each of the others said, independently, to the "
  "same question:\n\n{OTHERS}\n\nRespond to them. Where do you agree, where do you think "
  "one of them is wrong or is missing something that matters, and what did someone surface "
  "that you didn't? Several of you picked different stories entirely and gave the same "
  "story different meanings — go check the specific factual claims that look shaky rather "
  "than smoothing it over. Name names.",
 "reconsider":
  "Here is how everyone responded to everyone:\n\n{OTHERS}\n\nWhere do you stand now? Say "
  "what you've changed your mind about and why, what you still hold to and why the "
  "objections didn't move you, and what you think is genuinely still unresolved. If you "
  "want an answer from someone specific, ask them directly by name — they will see it.",
 "exchange":
  "Here is the last round:\n\n{OTHERS}\n\nAnswer any question that was put to you by name, "
  "and say the one thing you most want the room to take away. Short.",
}

SYNTH = (
 "You are the synthesizer for this run. Four models — Claude, GPT, Gemini and Grok — were "
 "asked: \"{Q}\"\n\nHere is the entire conversation, in order:\n\n{ALL}\n\nWrite the "
 "strongest combined answer the room can support. Do not take a majority vote and do not "
 "average anyone into blandness. Say what they agreed on, what they disagreed on and why, "
 "what evidence would settle it, what one of them saw that the others missed, where "
 "confidence is high and where it isn't. If a claim was made and nobody checked it, say so "
 "rather than passing it on. Prose, no headings. Then, as the very last line and nothing "
 "after it, write: CONFIDENCE: <0.0-1.0>")


def round_dirs(run_dir):
    return [d for d in sorted(glob.glob(f"{run_dir}/rounds/*"))
            if os.path.isdir(d) and not os.path.basename(d).startswith("zz-")]


def compose(run_dir, rnd, q, exclude_self=True):
    """Build each seat's prompt for this round from what is already on disk."""
    prev = [d for d in sorted(glob.glob(f"{run_dir}/rounds/*"))
            if os.path.isdir(d) and not os.path.basename(d).startswith("zz-")]
    src = prev[-1] if prev else None
    for seat in ORDER:
        kind = rnd.split("-", 1)[-1]
        if kind == "independent":
            body = ROUNDS[kind].format(Q=q)
        else:
            parts = []
            for other in ORDER:
                if exclude_self and other == seat:
                    continue
                f = f"{src}/{other}.md"
                if os.path.exists(f) and open(f).read().strip():
                    parts.append(f"--- {LABELS[other]} said ---\n{open(f).read().strip()}")
            body = ROUNDS[kind].format(OTHERS="\n\n".join(parts))
        os.makedirs(f"{run_dir}/rounds/{rnd}", exist_ok=True)
        open(f"{run_dir}/rounds/{rnd}/{seat}.prompt.md", "w").write(body)


def run_round(run_dir, kind):
    q = open(f"{run_dir}/prompt.txt").read()
    rnd = f"{len(round_dirs(run_dir)) + 1:02d}-{kind}"
    compose(run_dir, rnd, q)
    procs = {s: subprocess.Popen([f"{ROOT}/bin/turn.py", run_dir, s, rnd]) for s in ORDER}
    rc = {s: p.wait() for s, p in procs.items()}
    ok = [s for s in ORDER if rc[s] == 0]
    bad = [s for s in ORDER if rc[s] != 0]
    print(f"round {rnd}: {len(ok)}/{len(ORDER)} ok" + (f" — FAILED: {', '.join(bad)}" if bad else ""))
    transcript(run_dir)
    return bad


def transcript(run_dir):
    run = json.load(open(f"{run_dir}/run.json"))
    meta = {}
    for f in glob.glob(f"{run_dir}/seats/*.meta.jsonl"):
        for line in open(f):
            d = json.loads(line)
            meta[(d["seat"], d["round"])] = d
    L = [f"# Clock — {run['run_id']}\n", f"> **{run['prompt']}**\n",
         f"_Four seats: " + ", ".join(f"{LABELS[s]} `{m}`" for s, m in run["seats"].items()) + "_\n"]
    for rd in round_dirs(run_dir):
        L.append(f"\n---\n\n## {os.path.basename(rd).split('-')[-1].upper()}\n")
        for seat in ORDER:
            f = f"{rd}/{seat}.md"
            if not os.path.exists(f):
                continue
            t = open(f).read().strip()
            d = meta.get((seat, os.path.basename(rd)), {})
            u = (d.get("usage") or {}).get("total_tokens", "?")
            L.append(f"### {LABELS[seat]}\n")
            L.append(f"_{d.get('latency_s','?')}s · {u} tok · {len(d.get('citations') or [])} cites_\n")
            L.append(t if t else f"**unavailable this round** — {str(d.get('error'))[:200]}")
            L.append("")
    s = f"{run_dir}/synthesis.md"
    if os.path.exists(s):
        L.append("\n---\n\n## SYNTHESIS\n")
        L.append(open(s).read().strip())
    open(f"{run_dir}/transcript.md", "w").write("\n".join(L) + "\n")


def main():
    cmd = sys.argv[1]
    if cmd == "new":
        q = sys.argv[2]
        rid = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        run_dir = f"{ROOT}/store/runs/{rid}"
        for d in ("seats", "rounds", "pids"):
            os.makedirs(f"{run_dir}/{d}", exist_ok=True)
        open(f"{run_dir}/prompt.txt", "w").write(q)
        json.dump({"run_id": rid, "prompt": q, "seats": SEATS, "labels": LABELS,
                   "order": ORDER, "system": SYSTEM, "date": TODAY,
                   "transport": "openrouter chat/completions, web plugin, natural prose",
                   "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                  open(f"{run_dir}/run.json", "w"), indent=2)
        print(run_dir)
        run_round(run_dir, "independent")
    elif cmd == "round":
        run_round(sys.argv[2], sys.argv[3])
    elif cmd == "synth":
        run_dir = sys.argv[2]
        seat = sys.argv[3] if len(sys.argv) > 3 else "sol"
        q = open(f"{run_dir}/prompt.txt").read()
        all_txt = []
        for rd in round_dirs(run_dir):
            all_txt.append(f"===== ROUND: {os.path.basename(rd)} =====")
            for s in ORDER:
                f = f"{rd}/{s}.md"
                if os.path.exists(f) and open(f).read().strip():
                    all_txt.append(f"--- {LABELS[s]} ---\n{open(f).read().strip()}")
        os.makedirs(f"{run_dir}/rounds/zz-synth", exist_ok=True)
        open(f"{run_dir}/rounds/zz-synth/{seat}.prompt.md", "w").write(
            SYNTH.format(Q=q, ALL="\n\n".join(all_txt)))
        # fresh context: the synthesizer reads the record, it does not carry its own side
        msp = f"{run_dir}/seats/{seat}.messages.json"
        bak = msp + ".bak"
        os.path.exists(msp) and os.rename(msp, bak)
        rc = subprocess.call([f"{ROOT}/bin/turn.py", run_dir, seat, "zz-synth"])
        os.path.exists(msp) and os.remove(msp)
        os.path.exists(bak) and os.rename(bak, msp)
        out = f"{run_dir}/rounds/zz-synth/{seat}.md"
        if rc == 0:
            txt = open(out).read().strip()
            open(f"{run_dir}/synthesis.md", "w").write(
                f"_synthesized by {LABELS[seat]}_\n\n{txt}\n")
        print(f"synth ({seat}): {'ok' if rc == 0 else 'FAILED'}")
        transcript(run_dir)
    elif cmd == "transcript":
        transcript(sys.argv[2])


main()
