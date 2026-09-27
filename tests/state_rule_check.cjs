const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const casesPath = process.argv[2];
if (!casesPath) {
  console.error("用法：node tests/state_rule_check.cjs <用例.json>");
  process.exit(2);
}

const src = fs.readFileSync(path.join(ROOT, "web", "js", "store.js"), "utf8");
const win = {};
new Function("window", src)(win);
const mergeState = win.HC && win.HC.mergeState;
if (typeof mergeState !== "function") {
  console.error("store.js 里找不到 HC.mergeState，锚点需要更新");
  process.exit(2);
}

const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const bad = [];
for (const c of cases) {
  const got = mergeState(c.seq);
  if (got !== c.py) bad.push({ seq: c.seq, py: c.py, js: got });
}

const groups = {};
bad.forEach((b) => {
  const k = b.py + " → " + b.js;
  (groups[k] = groups[k] || []).push(b.seq.join(","));
});
const samples = Object.keys(groups).map((k) => ({
  diff: k,
  count: groups[k].length,
  shortest: groups[k].slice().sort((a, b) => a.length - b.length)[0]
}));

console.log(JSON.stringify({ total: cases.length, bad: bad.length, samples }));
process.exit(bad.length ? 1 : 0);
