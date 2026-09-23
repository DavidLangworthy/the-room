#!/usr/bin/env python3
"""
Clock — four frontier AI models from four different companies, in one room,
arguing about the same question until they've pressured each other's answers.

    python3 clock.py                      show the included sample discussion
    python3 clock.py "your question"      run a fresh four-vendor deliberation
    python3 clock.py -q "..." --quick     one round only, no critique

The room is Claude (Anthropic), GPT (OpenAI), Gemini (Google) and Grok (xAI).
Round 1 they answer alone, with no sight of each other — that independence is the
whole point, and it is enforced by construction, not by instruction. Then they read
each other and argue for three more rounds, every model keeping its own memory of
the conversation. A synthesizer writes the combined answer at the end; it is
deliberately not the model that hosts the run.

Everything is written to disk as it happens, so a seat that dies at 90% costs you
that seat, not the run. The transcript opens in your browser when it finishes.

REQUIREMENTS
    Python 3.9+. No packages to install — standard library only.
    An OpenRouter API key, which is what reaches all four vendors through one door:

        export OPENROUTER_API_KEY=sk-or-...

    Get one at https://openrouter.ai/keys. A four-round run of four models costs
    roughly $2-3 at current prices; the script prints the exact figure when it ends.
    You are billed by OpenRouter, not by this script.

    No key? Run it with no arguments and read the included discussion instead.
"""
import argparse, base64, gzip, html, json, os, re, sys, time, webbrowser
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

API = "https://openrouter.ai/api/v1/chat/completions"

SEATS = {"opus": "anthropic/claude-opus-5", "sol": "openai/gpt-5.6-sol",
         "gemini": "google/gemini-3.1-pro-preview", "grok": "x-ai/grok-4.6"}
LABELS = {"opus": "Claude (Anthropic)", "sol": "GPT (OpenAI)",
          "gemini": "Gemini (Google)", "grok": "Grok (xAI)"}
VENDOR = {"opus": "Anthropic", "sol": "OpenAI", "gemini": "Google", "grok": "xAI"}
SHORT = {"opus": "Claude", "sol": "GPT", "gemini": "Gemini", "grok": "Grok"}
ORDER = ["opus", "sol", "gemini", "grok"]
SYNTHESIZER = "sol"

SYSTEM = """You are {SEAT}, one of four AI models from four different companies \
sitting in one room and thinking together. The room is Claude (Anthropic), GPT (OpenAI), \
Gemini (Google) and Grok (xAI). Today is {DATE}.

Talk like a person in a good conversation. Prose, your own voice, no headings, no bullet \
lists, no section labels, no restating the question back. Address the others directly by \
name when you are responding to them.

You are not here to be agreeable. Say what you actually think, disagree plainly when you \
disagree, and say plainly when you don't know or when you were wrong. You have web search: \
use it to check a claim rather than deferring to whoever sounded most confident. Never \
invent agreement that isn't there, and never manufacture disagreement that isn't there \
either. Be concise — a few tight paragraphs at most."""

ROUNDS = {
 "independent": ("Independent",
  "Asked alone. No participant can see another's answer before committing to its own — the "
  "property that keeps the room from collapsing into an echo of whoever spoke first.",
  "{Q}\n\nThis is the first round and you are answering alone — you have not seen and will "
  "not see what the others said before you commit to this. Give your own answer, on the record."),
 "critique": ("Critique",
  "Each model now reads the other three and responds. Web search stays on, so a shaky number "
  "can be checked rather than deferred to.",
  "The room has now spoken. Here is what each of the others said, independently, to the same "
  "question:\n\n{OTHERS}\n\nRespond to them. Where do you agree, where do you think one of "
  "them is wrong or is missing something that matters, and what did someone surface that you "
  "didn't? Go check the specific factual claims that look shaky rather than smoothing them "
  "over. Name names."),
 "reconsider": ("Reconsider",
  "Where everyone stands after being argued with, what moved them, and what they still hold. "
  "Direct questions to a named participant are allowed here.",
  "Here is how everyone responded to everyone:\n\n{OTHERS}\n\nWhere do you stand now? Say what "
  "you've changed your mind about and why, what you still hold to and why the objections didn't "
  "move you, and what you think is genuinely still unresolved. If you want an answer from "
  "someone specific, ask them directly by name — they will see it."),
 "exchange": ("Exchange",
  "Questions put by name get answered, and each model says the one thing it wants the room to keep.",
  "Here is the last round:\n\n{OTHERS}\n\nAnswer any question that was put to you by name, and "
  "say the one thing you most want the room to take away. Short."),
}
PIPELINE = ["independent", "critique", "reconsider", "exchange"]

SYNTH_PROMPT = (
 "You are the synthesizer for this run. Four models — Claude, GPT, Gemini and Grok — were "
 "asked: \"{Q}\"\n\nHere is the entire conversation, in order:\n\n{ALL}\n\nWrite the strongest "
 "combined answer the room can support. Do not take a majority vote and do not average anyone "
 "into blandness. Say what they agreed on, what they disagreed on and why, what evidence would "
 "settle it, what one of them saw that the others missed, where confidence is high and where it "
 "isn't. If a claim was made and nobody checked it, say so rather than passing it on. Prose, no "
 "headings. Then, as the very last line and nothing after it, write: CONFIDENCE: <0.0-1.0>")


# ----------------------------------------------------------------- the room --
def call(model, messages, max_tokens=8000):
    """One request to one vendor. Returns (text, meta). Never raises."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens,
                       "plugins": [{"id": "web", "max_results": 6}]}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "X-Title": "clock"})
    t0 = time.time()
    meta = {"model_requested": model, "ok": False}
    text = ""
    try:
        d = json.load(urllib.request.urlopen(req, timeout=600))
        ch = (d.get("choices") or [{}])[0]
        m = ch.get("message") or {}
        text = (m.get("content") or "").strip()
        meta.update(model_served=d.get("model"), provider=d.get("provider"),
                    finish_reason=ch.get("finish_reason"), usage=d.get("usage"),
                    citations=[a.get("url_citation", {}).get("url")
                               for a in (m.get("annotations") or [])
                               if a.get("type") == "url_citation"])
    except urllib.error.HTTPError as e:
        meta["error"] = e.read().decode(errors="replace")[:500]
    except Exception as e:
        meta["error"] = "%s: %s" % (type(e).__name__, e)
    meta["latency_s"] = round(time.time() - t0, 2)
    # A reply cut off at the token cap is a partial failure, not a success, and must
    # never quietly become part of a seat's memory of the conversation.
    meta["ok"] = bool(text) and meta.get("finish_reason") != "length"
    return text, meta


def compose(seat, kind, question, prev):
    """Build one seat's prompt for this round from what the others actually said."""
    _, _, tmpl = ROUNDS[kind]
    if kind == "independent":
        return tmpl.replace("{Q}", question)
    parts = ["--- %s said ---\n%s" % (LABELS[o], prev[o])
             for o in ORDER if o != seat and prev.get(o)]
    return tmpl.replace("{OTHERS}", "\n\n".join(parts))


def run_round(store, run, kind, question, prev):
    """Fan the round out to every seat at once. Each seat's result lands on disk."""
    idx = len(run["rounds"]) + 1
    key = "%02d-%s" % (idx, kind)
    os.makedirs(os.path.join(store, "rounds", key), exist_ok=True)
    sys.stderr.write("  %s %-12s " % (key.split("-")[0], ROUNDS[kind][0].lower()))
    sys.stderr.flush()

    def one(seat):
        msgs = run["memory"].setdefault(seat, [
            {"role": "system", "content": SYSTEM.replace("{SEAT}", LABELS[seat])
                                                .replace("{DATE}", run["date"])}])
        send = msgs + [{"role": "user", "content": compose(seat, kind, question, prev)}]
        text, meta = call(run["seats"][seat], send)
        if meta["ok"]:
            run["memory"][seat] = send + [{"role": "assistant", "content": text}]
        with open(os.path.join(store, "rounds", key, seat + ".md"), "w") as f:
            f.write(text + "\n")
        with open(os.path.join(store, "seats.jsonl"), "a") as f:
            meta.update(seat=seat, round=key)
            f.write(json.dumps(meta) + "\n")
        sys.stderr.write("+" if meta["ok"] else "!")
        sys.stderr.flush()
        return seat, text, meta

    with ThreadPoolExecutor(max_workers=len(ORDER)) as ex:
        results = list(ex.map(one, ORDER))
    ok = {s: t for s, t, m in results if m["ok"]}
    metas = {s: m for s, t, m in results}
    sys.stderr.write("  %d/%d\n" % (len(ok), len(ORDER)))
    run["rounds"].append({"key": key, "name": ROUNDS[kind][0], "note": ROUNDS[kind][1],
                          "turns": [{"seat": s, "text": t,
                                     "latency": metas[s].get("latency_s"),
                                     "tokens": (metas[s].get("usage") or {}).get("total_tokens"),
                                     "cost": (metas[s].get("usage") or {}).get("cost"),
                                     "cites": len(metas[s].get("citations") or [])}
                                    for s, t, m in results if m["ok"]]})
    save(store, run)
    return ok


def synthesize(store, run, question):
    sys.stderr.write("  ..  synthesis    ")
    sys.stderr.flush()
    blocks = []
    for rd in run["rounds"]:
        blocks.append("===== ROUND: %s =====" % rd["name"])
        for t in rd["turns"]:
            blocks.append("--- %s ---\n%s" % (LABELS[t["seat"]], t["text"]))
    prompt = SYNTH_PROMPT.replace("{Q}", question).replace("{ALL}", "\n\n".join(blocks))
    # Fresh context on purpose: the synthesizer reads the record, it does not carry its own side.
    text, meta = call(run["seats"][SYNTHESIZER],
                      [{"role": "user", "content": prompt}])
    sys.stderr.write(("+" if meta["ok"] else "!") + "\n")
    with open(os.path.join(store, "seats.jsonl"), "a") as f:
        meta.update(seat=SYNTHESIZER, round="synthesis")
        f.write(json.dumps(meta) + "\n")
    run["synthesis"] = text
    run["synthesized_by"] = LABELS[SYNTHESIZER]
    save(store, run)


def save(store, run):
    out = {k: v for k, v in run.items() if k != "memory"}
    with open(os.path.join(store, "run.json"), "w") as f:
        json.dump(out, f, indent=1)
    with open(os.path.join(store, "memory.json"), "w") as f:
        json.dump(run["memory"], f, indent=1)


def tally(run):
    per, tot = {}, {"turns": 0, "tokens": 0, "cost": 0.0, "cites": 0}
    for rd in run["rounds"]:
        for t in rd["turns"]:
            p = per.setdefault(t["seat"], {"turns": 0, "tokens": 0, "cost": 0.0, "cites": 0})
            for k, v in (("turns", 1), ("tokens", t.get("tokens") or 0),
                         ("cost", t.get("cost") or 0), ("cites", t.get("cites") or 0)):
                p[k] += v
                tot[k] += v
    run["per_seat"], run["totals"] = per, tot


# ------------------------------------------------------------------ the page --
CSS = """{{CSS}}"""

EXTRA = """
  .tabs-wrap{display:none}
  html.js .tabs-wrap{display:block}
  .panel-title{font-size:12px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;
               color:var(--ink-3);margin:64px 0 0;padding-top:30px;border-top:1px solid var(--rule)}
  html.js .panel-title{display:none}
  .howto{margin-top:34px;padding:18px 20px;background:var(--surface);border:1px solid var(--rule);
         border-radius:4px;max-width:64ch;font-size:13.5px;color:var(--ink-2)}
  .howto b{color:var(--ink);font-weight:600}
  .howto code{font-family:var(--mono);font-size:12px;background:var(--sunk);
              padding:1px 5px;border-radius:3px}
  @media print{
    :root{--paper:#fff;--surface:#fff;--sunk:#eee;--ink:#000;--ink-2:#333;--ink-3:#666;
          --rule:#ccc;--opus:#8A4718;--sol:#12564A;--gemini:#2C4780;--grok:#6E2C4A;
          --opus-wash:#fff;--sol-wash:#fff;--gemini-wash:#fff;--grok-wash:#fff;--brass:#5A5630}
    .tabs-wrap,.seats,.howto,.ask{display:none!important}
    .panel[hidden]{display:block!important}
    .panel-title{display:block!important;break-before:page}
    .turn,.tp{break-inside:avoid}
    .turn{background:none}
    body{font-size:11pt}
    a{text-decoration:none}
    sup.cite a{background:none;border:1px solid #bbb}
    @page{margin:16mm}
  }
"""

PAGE_JS = """
(function(){
 var on={};
 document.querySelectorAll(".seat-chip").forEach(function(b){
   on[b.dataset.seat]=true;
   b.addEventListener("click",function(){
     var s=b.dataset.seat;on[s]=!on[s];b.setAttribute("aria-pressed",String(on[s]));
     document.querySelectorAll('.turn[data-seat="'+s+'"]').forEach(function(t){t.hidden=!on[s]});
   });
 });
 var views=[].map.call(document.querySelectorAll(".panel"),function(p){return p.id});
 views.forEach(function(v,i){document.getElementById(v).hidden=(i!==0)});
 document.querySelectorAll(".tab").forEach(function(tab){
   tab.addEventListener("click",function(){
     document.querySelectorAll(".tab").forEach(function(o){
       o.setAttribute("aria-selected",String(o===tab));
     });
     views.forEach(function(v){
       document.getElementById(v).hidden=(v!=="view-"+tab.dataset.view);
     });
     window.scrollTo({top:0,behavior:"smooth"});
   });
 });
})();
"""


def fmt(t):
    h = html.escape(t, quote=False)
    h = re.sub(r"\[\[(\d+)\]\]\((\S+?)\)",
               lambda m: '<sup class="cite"><a href="%s">%s</a></sup>' % (m.group(2), m.group(1)), h)
    h = re.sub(r"\(\[([^\]]+)\]\((\S+?)\)\)",
               lambda m: '<sup class="cite"><a href="%s">%s</a></sup>'
                         % (m.group(2), m.group(1).replace("www.", "").split(".")[0]), h)
    h = re.sub(r"\[([^\]]+)\]\((\S+?)\)", r'<a href="\2">\1</a>', h)
    h = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", h)
    h = re.sub(r"(^|[\s(])\*([^*\n]+)\*", r"\1<em>\2</em>", h)
    return "".join("<p>%s</p>" % p.strip().replace("\n", " ")
                   for p in re.split(r"\n{2,}", h) if p.strip())


def render(run, tp=None):
    tally(run)
    B = []
    w = B.append
    w('<!doctype html><html lang="en"><head><meta charset="utf-8">')
    w('<meta name="viewport" content="width=device-width,initial-scale=1">')
    w("<title>The Clock Room — %s</title>" % html.escape(run["date"]))
    w("<style>*{box-sizing:border-box}body{margin:0}img{max-width:100%}[hidden]{display:none}")
    w(CSS + EXTRA + "</style>")
    w('<script>document.documentElement.className="js"</script></head><body>')
    w('<div class="shell"><header class="mast"><div class="mast-top">')
    w('<div class="wordmark"><b>Clock.</b> &nbsp;the room</div>')
    w('<div class="stamp">%s</div></div>' % html.escape(run["date"]))
    w('<p class="kicker">One question · four vendors · %d rounds</p>' % len(run["rounds"]))
    w("<h1>%s</h1>" % html.escape(run["question"]))
    w('<p class="standfirst">Four frontier models from four different companies were asked this '
      'at the same moment. Each answered alone first, with no sight of the others, then read each '
      'other and argued for three more rounds — every model keeping its own memory of the '
      'conversation. Nothing below was edited or reordered. The disagreements are the point.</p>')
    w('<div class="seats">')
    for s in ORDER:
        w('<button class="seat-chip" type="button" data-seat="%s" aria-pressed="true" '
          'style="--c:var(--%s)"><span class="dot"></span><span class="who">%s</span>'
          '<span class="vendor">%s</span></button>' % (s, s, SHORT[s], VENDOR[s]))
    w("</div>")
    w('<div class="howto"><b>Reading this.</b> Click a name above to mute that model and follow '
      'one voice through every round. The tabs switch between the transcript, the synthesis and '
      'the run\'s cost. Printing gives you every section in order. To run your own question, see '
      '<code>clock.py --help</code>.</div>')

    panels = [("transcript", "Transcript", sum(len(r["turns"]) for r in run["rounds"]))]
    if tp:
        panels.append(("turns", "Turning points", len(tp)))
    panels += [("synthesis", "Synthesis", None), ("ledger", "What it cost", None)]
    w('<div class="tabs-wrap"><nav class="views" role="tablist">')
    for i, (v, label, n) in enumerate(panels):
        w('<button class="tab" type="button" role="tab" data-view="%s" aria-selected="%s">%s%s'
          "</button>" % (v, "true" if i == 0 else "false", label,
                         '<span class="n">%d</span>' % n if n else ""))
    w("</nav></div></header><main>")

    w('<h2 class="panel-title">The transcript</h2><section class="panel" id="view-transcript">')
    for i, rd in enumerate(run["rounds"], 1):
        w('<section class="round"><div class="round-head"><span class="round-num">%02d</span>'
          '<h3 class="round-name">%s</h3><span class="round-rule"></span></div>' % (i, rd["name"]))
        w('<p class="round-note">%s</p>' % rd["note"])
        for t in rd["turns"]:
            bits = []
            if t.get("latency"):
                bits.append("%ss" % t["latency"])
            if t.get("tokens"):
                bits.append("{:,} tok".format(t["tokens"]))
            bits.append("%d source%s" % (t["cites"], "" if t["cites"] == 1 else "s")
                        if t.get("cites") else "no sources")
            if t.get("cost") is not None:
                bits.append("$%.3f" % t["cost"])
            w('<article class="turn" data-seat="%s" style="--c:var(--%s);--w:var(--%s-wash)">'
              % (t["seat"], t["seat"], t["seat"]))
            w('<div class="turn-head"><span class="turn-who">%s</span>'
              '<span class="turn-meta">%s</span></div>' % (LABELS[t["seat"]], "  ·  ".join(bits)))
            w('<div class="turn-body">%s</div></article>' % fmt(t["text"]))
        w("</section>")
    w("</section>")

    if tp:
        w('<h2 class="panel-title">Turning points</h2><section class="panel" id="view-turns">')
        w('<p class="tp-intro">The answer the room reached is in the synthesis. This is the part '
          "a single model cannot produce: %d moments where one participant moved another, or "
          "caught it, or was caught. Every quote was checked against the transcript.</p>" % len(tp))
        for x in tp:
            q = x["quote"].replace("<said>", '<span class="said">').replace("</said>", "</span>")
            w('<div class="tp" style="--c:var(--%s)"><div class="tp-when">%s<br>%s</div><div>'
              % (x["seat"], x["round"], SHORT[x["seat"]]))
            w('<div class="tp-kind">%s</div><blockquote>%s</blockquote>' % (x["kind"], q))
            w('<p class="tp-gloss">%s</p></div></div>' % x["gloss"])
        w("</section>")

    syn = run.get("synthesis") or ""
    conf = (re.search(r"CONFIDENCE:\s*([\d.]+)", syn) or [None, None])[1]
    syn = re.sub(r"\n*CONFIDENCE:\s*[\d.]+\s*$", "", syn)
    w('<h2 class="panel-title">Synthesis</h2><section class="panel" id="view-synthesis">'
      '<div class="synth">')
    w('<div class="by">Synthesized by %s — deliberately not the host model. The role is a flag, '
      "not a fixture.</div>" % html.escape(run.get("synthesized_by", "—")))
    w("<h2>The strongest answer the room can support</h2>")
    w('<div class="synth-body">%s</div>' % fmt(syn))
    if conf:
        w('<div class="conf"><span class="conf-label">Stated confidence</span>'
          '<span class="conf-bar"><span class="conf-fill" style="width:%s%%"></span></span>'
          '<span class="conf-num">%s</span></div>' % (float(conf) * 100, conf))
    w("</div></section>")

    per, tot = run["per_seat"], run["totals"]
    w('<h2 class="panel-title">What it cost</h2><section class="panel" id="view-ledger">'
      '<div class="ledger"><div class="ledger-grid">')
    for s in ORDER:
        d = per.get(s, {"turns": 0, "tokens": 0, "cost": 0.0, "cites": 0})
        w('<div class="lcell" style="--c:var(--%s)"><div class="who"><span class="dot"></span>%s'
          "</div><dl><dt>turns</dt><dd>%d</dd><dt>tokens</dt><dd>{:,}</dd>"
          "<dt>sources</dt><dd>%d</dd><dt>cost</dt><dd>$%.2f</dd></dl></div>"
          .format(d["tokens"]) % (s, SHORT[s], d["turns"], d["cites"], d["cost"]))
    w("</div>")
    w('<p class="ledger-note">{} turns, {:,} tokens and {} web sources, for <strong>${:.2f}'
      "</strong> all in.</p>".format(tot["turns"], tot["tokens"], tot["cites"], tot["cost"]))
    maxc = max([per.get(s, {}).get("cites", 0) for s in ORDER] + [1])
    w('<div class="bars">')
    for s in ORDER:
        c = per.get(s, {}).get("cites", 0)
        w('<div class="bar-row" style="--c:var(--%s)"><span class="lbl">%s · sources</span>'
          '<span class="bar-track"><span class="bar-fill" style="width:%.1f%%"></span></span>'
          '<span class="bar-val">%d</span></div>' % (s, SHORT[s], c / maxc * 100, c))
    w("</div></div></section>")

    w("</main><footer><span>Produced by Clock. Every turn is a real API call to the named "
      "vendor; nothing here is illustrative. Any factual claims are the models' own, from their "
      "own web searches.</span><span><code>%s</code></span></footer></div>" % run["run_id"])
    w("<script>%s</script></body></html>" % PAGE_JS)
    return "\n".join(B)


# ------------------------------------------------------------------- sample --
SAMPLE = "{{DATA}}"


def load_sample():
    d = json.loads(gzip.decompress(base64.b64decode(SAMPLE)).decode())
    return d["run"], d["turning_points"]


def show(path):
    print("\n  wrote %s" % path)
    try:
        webbrowser.open("file://" + os.path.abspath(path))
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(
        description="Four AI models from four companies argue about your question.",
        epilog="Needs OPENROUTER_API_KEY for a live run. With no question, shows the "
               "included sample discussion.")
    ap.add_argument("question", nargs="?", help="what the room should think about")
    ap.add_argument("-q", "--question", dest="q", help=argparse.SUPPRESS)
    ap.add_argument("--quick", action="store_true", help="independent round only, then synthesize")
    ap.add_argument("-o", "--out", help="where to write the HTML (default: alongside the run)")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser at the end")
    a = ap.parse_args()
    question = a.question or a.q

    if not question:
        run, tp = load_sample()
        out = a.out or "clock-sample.html"
        open(out, "w").write(render(run, tp))
        print("Showing the included discussion of %s." % run["date"])
        print("To run your own:  python3 %s \"your question\"" % os.path.basename(sys.argv[0]))
        if not a.no_open:
            show(out)
        return

    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("No OPENROUTER_API_KEY set. Get a key at https://openrouter.ai/keys, then:\n"
                 "    export OPENROUTER_API_KEY=sk-or-...\n"
                 "Or run with no question to read the included discussion.")

    rid = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    store = os.path.join("clock-runs", rid)
    os.makedirs(os.path.join(store, "rounds"), exist_ok=True)
    run = {"run_id": rid, "question": question, "seats": dict(SEATS), "order": ORDER,
           "date": datetime.now().strftime("%A %d %B %Y").replace(" 0", " "),
           "rounds": [], "memory": {}, "synthesis": "", "synthesized_by": ""}

    print("\n  Clock — %s\n  %s\n" % (run["date"], question), flush=True)
    prev = {}
    for kind in (["independent"] if a.quick else PIPELINE):
        prev = run_round(store, run, kind, question, prev) or prev
        if not prev:
            sys.exit("  every seat failed this round; stopping. See %s" % store)
    synthesize(store, run, question)

    tally(run)
    save(store, run)
    out = a.out or os.path.join(store, "transcript.html")
    open(out, "w").write(render(run))
    print("\n  %d turns · %s tokens · $%.2f"
          % (run["totals"]["turns"], "{:,}".format(run["totals"]["tokens"]),
             run["totals"]["cost"]))
    print("  full run saved in %s/" % store)
    if not a.no_open:
        show(out)


if __name__ == "__main__":
    main()
