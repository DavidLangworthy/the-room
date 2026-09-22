#!/usr/bin/env python3
"""Draw the shape of a Clock run as an SVG: rounds as layers, providers as nodes.

The picture has to be true to the code in site/app.js, so the topology is derived
from the same facts the app enforces:
  * round one receives the question and nothing else — no edges between seats
  * every later round: each seat carries its own memory forward (the straight line)
    and receives every other seat's answer (the curves). Never its own.
  * the synthesizer reads the whole transcript with fresh context of its own.
"""
import os

W, H = 1430, 1470
COLS = [330, 498, 666, 834, 1002]
NODE_W, NODE_H = 150, 56
RAIL_X = 1186
GUT = 44                      # left gutter for round labels

SEATS = [
    ("Claude", "Anthropic", "opus"),
    ("GPT", "OpenAI", "sol"),
    ("Gemini", "Google", "gemini"),
    ("Grok", "xAI", "grok"),
    ("Muse", "Meta", "meta"),
]

ROUNDS = [
    ("01", "Independent", 320,
     ["Each model answers the", "question alone, unaware", "that anyone else exists."],
     ["No lines run between", "these five. Round one", "is blind."]),
    ("02", "Critique", 540,
     ["It now reads what the", "others said and responds —", "checking, not deferring."],
     ["From here on each model", "sees every other one,", "and never its own."]),
    ("03", "Reconsider", 760,
     ["What moved them, what", "they still hold, what is", "still unresolved."], []),
    ("04", "Exchange", 980,
     ["Questions put by name get", "answered. Each says the", "one thing it wants kept."], []),
]
Q_Y = 176
SYNTH_Y = 1200
SYNTH_W, SYNTH_H = 380, 92

ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
def e(s): return "".join(ESC.get(c, c) for c in str(s))

out = []
def add(x): out.append(x)


def node_slots(n):
    """Evenly spread exit/entry positions across a node edge, never on the centre
    line — that belongs to the memory edge."""
    span = NODE_W * 0.82
    return [round(-span / 2 + span * (i + 0.5) / n, 1) for i in range(n)]


def text(x, y, s, cls="", anchor="start", extra=""):
    add(f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}"{extra}>{e(s)}</text>')


# ----------------------------------------------------------------- header --
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'role="img" aria-labelledby="t d" font-family="-apple-system, BlinkMacSystemFont, '
    f'&quot;SF Pro Text&quot;, &quot;Helvetica Neue&quot;, Helvetica, Arial, sans-serif">')
add('<title id="t">How one question becomes one answer in Room of Models</title>')
add('<desc id="d">Five AI models answer a question independently in round one with no '
    'connections between them, then exchange answers across three further rounds, and the '
    'whole transcript flows into a single synthesis node.</desc>')

add('''<style>
  :root{
    --paper:#EFF1EC; --surface:#FAFBF8; --ink:#191C19; --ink2:#454B44; --ink3:#646B62;
    --rule:#D5D9CE; --brass:#6E6A3C;
    --opus:#8F4A18; --sol:#1C6B5C; --gemini:#3A5A99; --grok:#8A3A5E; --meta:#6A3FA0;
    --opusW:#F6EAE0; --solW:#E2EFEB; --geminiW:#E5EAF5; --grokW:#F5E6EC; --metaW:#EDE6F7;
  }
  @media (prefers-color-scheme:dark){
    :root{
      --paper:#14171A; --surface:#1B1F23; --ink:#E7EAE4; --ink2:#AEB5AC; --ink3:#8C938B;
      --rule:#2C3238; --brass:#B5AE72;
      --opus:#E09550; --sol:#54B9A0; --gemini:#88A8E4; --grok:#D68BAD; --meta:#BFA3EC;
      --opusW:#2A2018; --solW:#162925; --geminiW:#1A2130; --grokW:#2A1A22; --metaW:#221A2E;
    }
  }
  .bg{fill:var(--paper)}
  .h1{fill:var(--ink);font-size:27px;font-weight:600;letter-spacing:-.6px}
  .h2{fill:var(--ink2);font-size:14.5px}
  .rnum{fill:var(--brass);font-size:12px;letter-spacing:1px;
        font-family:ui-monospace,"SF Mono",Menlo,monospace}
  .rname{fill:var(--ink);font-size:13px;font-weight:650;letter-spacing:1.6px}
  .rnote{fill:var(--ink3);font-size:11.5px}
  .nname{fill:var(--ink);font-size:14px;font-weight:640;letter-spacing:-.2px}
  .nvend{fill:var(--ink3);font-size:10px;letter-spacing:.4px}
  .card{fill:var(--surface);stroke:var(--rule);stroke-width:1}
  .qcard{fill:var(--surface);stroke:var(--brass);stroke-width:1.4}
  .qtext{fill:var(--ink);font-size:15px;font-weight:600}
  .lbl{fill:var(--ink3);font-size:11px;
       font-family:ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.3px}
  .lblb{fill:var(--ink2);font-size:11.5px;font-weight:600}
  .call{fill:var(--ink2);font-size:12px}
  .callb{fill:var(--ink);font-size:12px;font-weight:650}
  .rail{stroke:var(--ink3);stroke-width:1.6;fill:none;opacity:.5}
  .tap{stroke:var(--ink3);stroke-width:1;fill:none;opacity:.45;stroke-dasharray:3 4}
  .mem{stroke-width:2.4;fill:none;opacity:.95}
  .cross{stroke-width:1.15;fill:none;opacity:.42}
  .qedge{stroke:var(--brass);stroke-width:1.5;fill:none;opacity:.75}
  .divider{stroke:var(--rule);stroke-width:1}
  .legbox{fill:var(--surface);stroke:var(--rule);stroke-width:1}
  .opus{stroke:var(--opus)} .sol{stroke:var(--sol)} .meta{stroke:var(--meta)}
  .gemini{stroke:var(--gemini)} .grok{stroke:var(--grok)}
  .fopus{fill:var(--opus)} .fsol{fill:var(--sol)} .fmeta{fill:var(--meta)}
  .fgemini{fill:var(--gemini)} .fgrok{fill:var(--grok)}
  .wopus{fill:var(--opusW)} .wsol{fill:var(--solW)} .wmeta{fill:var(--metaW)}
  .wgemini{fill:var(--geminiW)} .wgrok{fill:var(--grokW)}
</style>''')

add('<defs>')
for key in ("opus", "sol", "gemini", "grok", "meta"):
    add(f'<marker id="a-{key}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,1 L7,4 L0,7 z" class="f{key}"/></marker>')
add('<marker id="a-q" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" '
    'orient="auto-start-reverse"><path d="M0,1 L7,4 L0,7 z" fill="var(--brass)"/></marker>')
add('<marker id="a-n" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" '
    'orient="auto-start-reverse"><path d="M0,1 L7,4 L0,7 z" fill="var(--ink3)"/></marker>')
add('</defs>')

add(f'<rect class="bg" width="{W}" height="{H}"/>')

# ------------------------------------------------------------------ title --
text(GUT, 62, "How one question becomes one answer", "h1")
text(GUT, 88, "Five frontier models, four rounds, one synthesis — the shape of a single run.", "h2")
add(f'<line class="divider" x1="{GUT}" y1="108" x2="{W-GUT}" y2="108"/>')

# --------------------------------------------------------------- question --
qw, qh = 470, 54
qx = COLS[0] - NODE_W / 2 + ((COLS[-1] + NODE_W / 2) - (COLS[0] - NODE_W / 2) - qw) / 2
add(f'<rect class="qcard" x="{qx:.1f}" y="{Q_Y - qh/2}" width="{qw}" height="{qh}" rx="27"/>')
text(qx + qw / 2, Q_Y + 5, "Your question", "qtext", "middle")
text(GUT, Q_Y - 6, "INPUT", "rnum")
text(GUT, Q_Y + 12, "one question", "rnote")

# --------------------------------------------------- rounds: labels + nodes --
def node_xy(col, cy):
    return COLS[col] - NODE_W / 2, cy - NODE_H / 2

for rnum, rname, cy, note, callout in ROUNDS:
    text(GUT, cy - 22, rnum, "rnum")
    text(GUT, cy - 4, rname.upper(), "rname")
    for i, ln in enumerate(note):
        text(GUT, cy + 16 + i * 14, ln, "rnote")
    for i, ln in enumerate(callout):
        text(GUT, cy + 30 + len(note) * 14 + i * 14, ln, "callb")
    for col, (name, vendor, key) in enumerate(SEATS):
        x, y = node_xy(col, cy)
        add(f'<rect class="card w{key}" x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="10"/>')
        add(f'<rect class="f{key}" x="{x}" y="{y}" width="3.5" height="{NODE_H}" rx="1.75"/>')
        text(COLS[col], cy - 2, name, "nname", "middle")
        text(COLS[col], cy + 15, vendor.upper(), "nvend", "middle")

# ------------------------------------------------------- question -> round 1 --
r1 = ROUNDS[0][2]
for col in range(4):
    sx, sy = qx + qw / 2, Q_Y + qh / 2
    tx, ty = COLS[col], r1 - NODE_H / 2
    add(f'<path class="qedge" marker-end="url(#a-q)" d="M{sx:.1f},{sy:.1f} '
        f'C{sx:.1f},{sy+52:.1f} {tx:.1f},{ty-56:.1f} {tx:.1f},{ty-7:.1f}"/>')
# --------------------------------------- between rounds: memory + cross edges --
N = len(SEATS)
slots = node_slots(N - 1)          # one slot per peer
for r in range(len(ROUNDS) - 1):
    sy_c, ty_c = ROUNDS[r][2], ROUNDS[r + 1][2]
    sy = sy_c + NODE_H / 2
    ty = ty_c - NODE_H / 2
    dy = ty - sy
    # cross edges first, so the memory lines sit on top of them
    for si, (_, _, skey) in enumerate(SEATS):
        peers = [t for t in range(N) if t != si]
        for slot_i, ti in enumerate(peers):
            back = [t for t in range(N) if t != ti]     # where si sits among ti's peers
            x1 = COLS[si] + slots[slot_i]
            x2 = COLS[ti] + slots[back.index(si)]
            add(f'<path class="cross {skey}" marker-end="url(#a-{skey})" '
                f'd="M{x1:.1f},{sy:.1f} C{x1:.1f},{sy+dy*0.42:.1f} '
                f'{x2:.1f},{ty-dy*0.42:.1f} {x2:.1f},{ty-7:.1f}"/>')
    for si, (_, _, skey) in enumerate(SEATS):
        x = COLS[si]
        add(f'<path class="mem {skey}" marker-end="url(#a-{skey})" '
            f'd="M{x},{sy:.1f} L{x},{ty-7:.1f}"/>')

# ------------------------------------------------- transcript rail -> synth --
rail_top = ROUNDS[0][2]
rail_bot = SYNTH_Y - 150
add(f'<path class="rail" d="M{RAIL_X},{rail_top} L{RAIL_X},{rail_bot} '
    f'C{RAIL_X},{rail_bot+70} {COLS[-1]},{SYNTH_Y-70} '
    f'{W/2 + SYNTH_W/2 - 14:.1f},{SYNTH_Y - SYNTH_H/2 - 6:.1f}"/>')
for _, _, cy, _, _ in ROUNDS:
    add(f'<path class="tap" marker-end="url(#a-n)" '
        f'd="M{COLS[-1] + NODE_W/2 + 4},{cy} L{RAIL_X - 4},{cy}"/>')
    add(f'<circle cx="{RAIL_X}" cy="{cy}" r="3" fill="var(--ink3)" opacity=".55"/>')
text(RAIL_X - 6, Q_Y - 34, "THE TRANSCRIPT", "rname", "start")
for i, ln in enumerate(["Every turn joins it,", "in order. The", "synthesizer reads", "all of it."]):
    text(RAIL_X - 6, Q_Y - 12 + i * 14, ln, "rnote")

# --------------------------------------------------------------- synthesis --
sx0 = W / 2 - SYNTH_W / 2
add(f'<rect class="card" x="{sx0}" y="{SYNTH_Y - SYNTH_H/2}" width="{SYNTH_W}" '
    f'height="{SYNTH_H}" rx="14" stroke="var(--sol)" stroke-width="1.6"/>')
add(f'<rect class="fsol" x="{sx0}" y="{SYNTH_Y - SYNTH_H/2}" width="4" height="{SYNTH_H}" rx="2"/>')
text(W / 2, SYNTH_Y - 20, "SYNTHESIS", "rname", "middle")
text(W / 2, SYNTH_Y + 2, "GPT (OpenAI)", "nname", "middle")
text(W / 2, SYNTH_Y + 22, "fresh context — it reads the record, it does not carry its own side",
     "rnote", "middle")
text(GUT, SYNTH_Y - 20, "05", "rnum")
text(GUT, SYNTH_Y - 2, "SYNTHESIS", "rname")
for i, ln in enumerate(["The strongest combined", "answer, preserving the",
                        "disagreement rather than", "averaging it away."]):
    text(GUT, SYNTH_Y + 18 + i * 14, ln, "rnote")

# a single answer leaves
add(f'<path class="qedge" marker-end="url(#a-q)" d="M{W/2},{SYNTH_Y + SYNTH_H/2} '
    f'L{W/2},{SYNTH_Y + SYNTH_H/2 + 46}"/>')
text(W / 2, SYNTH_Y + SYNTH_H / 2 + 68, "One answer, with the disagreements still inspectable",
     "callb", "middle")




# ------------------------------------------------------------------ legend --
ly = H - 108
add(f'<line class="divider" x1="{GUT}" y1="{ly - 28}" x2="{W-GUT}" y2="{ly - 28}"/>')
items = [
    ("mem opus", "carries its own memory forward — the same conversation, one turn longer"),
    ("cross opus", "receives every other model's answer — never its own"),
    ("tap", "every turn joins the transcript the synthesizer reads"),
]
for i, (cls, label) in enumerate(items):
    y = ly + i * 24
    if cls == "tap":
        add(f'<path class="tap" d="M{GUT},{y} L{GUT+46},{y}"/>')
    else:
        add(f'<path class="{cls}" d="M{GUT},{y} L{GUT+46},{y}"/>')
    text(GUT + 58, y + 4, label, "call")
text(W - GUT, ly + 4, "Colour is the model that spoke.", "lbl", "end")
text(W - GUT, ly + 22, "Every arc is one API call, made from the browser.", "lbl", "end")
text(W - GUT, ly + 40, "21 calls in a four-round run.", "lbl", "end")

add("</svg>")

dest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "dist", "clock-flow.svg")
os.makedirs(os.path.dirname(dest), exist_ok=True)
open(dest, "w").write("\n".join(out) + "\n")
print(dest, "%.1f KB" % (os.path.getsize(dest) / 1024))
