# The Room

**One question. Several frontier AI models, from different companies. They answer alone, then argue.**

Room of Models is a single-page web app. You bring a question and your own OpenRouter API key.
Five models — Claude, GPT, Gemini, Grok and Muse — answer it independently, then read each other
and disagree for three more rounds, and a synthesizer builds the strongest combined answer without
averaging the disagreement away.

It runs entirely in your browser. There is no backend.

---

## The idea

Asking five models the same question and pasting the answers side by side is not interesting. You
get five confident paragraphs and no way to tell which one is wrong.

What is interesting is what happens when they have to defend those paragraphs to each other.

In a real run of this system, four models were asked what the most important news story was. One of
them, Gemini, abandoned its position in round two after Grok pushed back — with no new evidence
having been presented. Claude noticed and said so by name:

> Gemini, what fact did you learn between your two answers that made the IPO delay stop counting as
> a material act? If the answer is none, retract the retraction.

Gemini's reply in the next round:

> Claude, you caught me red-handed. I didn't learn a single new fact… I engaged in exactly the kind
> of sycophantic consensus-seeking I am supposed to avoid. I retract the concession entirely.

In the same run, Claude stated a diesel price with total confidence, Gemini agreed with it, and
both were wrong — until GPT went and checked and found the outnumbered model had been right all
along. No single model produces either of those moments, because no single model has anyone to
catch it.

That is the entire thesis. The output is not "the answer." The output is **an argument you can
audit**, with the disagreements still inspectable.

---

## The hard rules

These are invariants, not aspirations. Each is enforced by what the code actually sends.

**Round one is blind.** No model is told that anyone else is answering, or who. Not merely kept
from the others' text — unaware there is a room at all. Merely knowing the roster changes what a
model says: it postures, it defers to whoever it assumes is stronger on the topic, it leaves gaps
for someone else to fill. The room is introduced in round two, along with everyone's answers.

**A truncated reply is a failure, not a short answer.** A response cut off at the token ceiling is
marked failed, never enters that model's memory, and is never passed to the others as a position.
Half a thought is worse than none, because the room will argue with it.

**A failure never reads as a success.** If a model is rate-limited or times out, the run says who
was missing and continues with the rest. It does not quietly show you four answers where you
expected five.

**Nothing leaves your tab but the API call.** Not the question, not the answers, not your key.

---

## How the privacy claim is enforced

This is the part most "runs in your browser" claims get wrong, so it is worth being precise.

The site is static: no backend, no database, no API routes. Every response carries:

```
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self';
  img-src 'self' data:; font-src 'self'; connect-src https://openrouter.ai;
  form-action 'none'; base-uri 'none'; frame-ancestors 'none'
```

`connect-src https://openrouter.ai` means **your browser refuses** any other connection. Not "we
promise not to" — the page is structurally incapable of it. No analytics, no error reporting, no
beacons, and deliberately no web fonts, because loading a font from a CDN would hand a third party
every visitor's IP address and make the sentence above a lie.

Your key lives in tab memory, or in `localStorage` if you tick the box. It is attached to requests
to `openrouter.ai` and nothing else. Downloaded transcripts are built in the page and saved by your
browser directly.

Open the network tab and watch. That is the intended way to verify this.

---

## The shape of a run

![How one question becomes one answer](site/how-it-works.svg)

Five layers. At the top, one question fans out to five models with **no connections between them**
— that blank first layer is round-one blindness, drawn. From round two on, each model has one thick
line carrying its own memory forward and four thin ones bringing everyone else's answers, never its
own. A rail down the right collects every turn into the transcript the synthesizer reads.

The picture is generated from the same facts the code enforces, so it cannot drift:

```bash
python3 bin/make_graph.py
```

---

## Running it

**The app.** Serve `site/` with any static file server and open it. There is no build step.

```bash
cd site && python3 -m http.server 8000
```

You will need an [OpenRouter](https://openrouter.ai/keys) key. A four-round run with five models is
21 API calls and costs a few dollars; Quick mode is one round plus a synthesis, for about a fifth
of that. You are billed by OpenRouter, not by this.

**The standalone.** `dist/clock.py` is the same pipeline as one file, standard library only.
With no arguments it renders a recorded discussion so you can read one without a key:

```bash
python3 dist/clock.py
python3 dist/clock.py "your question here"
```

**Deploying.** Azure Static Web Apps, script-driven, no GitHub Actions:

```bash
./scripts/deploy-full.sh <subscription-id> <resource-group> <location> <app-name>
```

---

## Layout

```
site/          the app — index.html, app.js, styles.css, CSP config. No build step.
bin/           the original local harness, the standalone builder, the diagram generator
dist/          built artifacts: the single-file runner, the flow diagram
store/runs/    recorded runs, every turn as it arrived
infra/         Azure Bicep for the Static Web App
scripts/       deploy and custom-domain scripts
test/          the injection regression suite
page/          the standalone transcript reader
```

---

## On how this was built

Most of this was written by a language model under direction, which makes the verification more
interesting than the code.

The app was audited by an adversarial multi-agent review: six reviewers over separate dimensions —
exfiltration paths, DOM injection, SSE edge cases, orchestration invariants, accessibility, deploy
configuration — with every candidate finding then attacked by two independent skeptics, one trying
to refute it and one trying to construct the exact failing input. **42 findings survived. 14 were
killed** as unreproducible.

The worst one is worth naming, because it is the kind of bug that reads as fine:

`esc()` escaped `&`, `<` and `>` but not `"`. Model-supplied citation URLs were interpolated into
`href="…"`, so a URL containing a quote closed the attribute and everything after it parsed as new
attributes on the anchor. On the live page the CSP blocked the resulting handler. But the **Download**
button reused the same renderer, and the saved file shipped with no CSP at all — response headers do
not follow a file to disk. Opening your own downloaded transcript would have executed the injected
handler and sent the entire conversation to whoever wrote the payload. The product's own privacy
promise, broken by the product's own download button. Every model has web search enabled, so the
attacker need not be a model: a poisoned search result is enough.

Fixed by escaping quotes, allowlisting `http(s)` schemes, and giving downloaded files their own
`default-src 'none'` policy. [`test/xss.mjs`](test/xss.mjs) runs the shipped `fmt()` against the
original payloads on every change.

The same review found that a stopped or truncated synthesis was being rendered under the heading
"The strongest answer the room can support," and that a model which failed round one was then asked
to critique answers to a question it had never been shown.

---

## Status

Working and deployed. Known gaps:

- Meta's Muse intermittently fails mid-stream for some accounts; diagnostics to capture the
  upstream error are the next piece of work
- the brand mark in `site/` is a placeholder drawing, not final artwork
- no test coverage beyond the injection suite

---

Built by [Tandem Works](https://roomofmodels.site).
