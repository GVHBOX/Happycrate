const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");

function el(tag) {
  const node = {
    tagName: (tag || "div").toUpperCase(),
    className: "", innerHTML: "", textContent: "", value: "",
    hidden: false, disabled: false, isConnected: true, parentNode: null, firstChild: null,
    dataset: {}, children: [],
    style: new Proxy({}, {
      get: (t, k) => (k === "setProperty" || k === "removeProperty") ? () => {} : (t[k] || ""),
      set: (t, k, v) => { t[k] = v; return true; },
    }),
    offsetWidth: 900, clientWidth: 900, offsetHeight: 500,
    scrollTop: 0, scrollLeft: 0,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, f) { f ? this._s.add(c) : this._s.delete(c); return f; },
      contains(c) { return this._s.has(c); },
    },
    appendChild(c) { this.children.push(c); return c; },
    insertBefore(c) { return c; }, removeChild(c) { return c; }, remove() {},
    focus() {}, select() {}, blur() {}, click() {},
    setPointerCapture() {}, releasePointerCapture() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    getBoundingClientRect() { return {left:0, top:0, right:900, bottom:500, width:900, height:500}; },
    querySelector() { return el("div"); }, querySelectorAll() { return []; },
    closest() { return null; }, matches() { return false; },
  };
  return node;
}

let backdropPresent = false;
let toneCalls = [];

function makeSandbox() {
  const body = el("body");
  const document = {
    body,
    documentElement: el("html"),
    createElement: (t) => el(t),
    createTextNode: (t) => ({ text: t }),
    getElementById: () => el("div"),
    querySelector: (sel) => {
      if (sel === ".backdrop") return backdropPresent ? el("div") : null;
      return el("div");
    },
    querySelectorAll: () => [],
    addEventListener() {}, removeEventListener() {}, execCommand() { return true; },
  };
  const sandbox = {
    document, console,
    navigator: { clipboard: null, userAgent: "node" },
    location: { hash: "", search: "", href: "" },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    performance: { now: () => Date.now() },
    setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
    Promise, Date, Math, JSON, Number, String, Boolean, Array, Object, RegExp, Error,
    MutationObserver: function () { this.observe = () => {}; },
    requestAnimationFrame: (fn) => setTimeout(fn, 16), cancelAnimationFrame: clearTimeout,
    ResizeObserver: undefined, URLSearchParams,
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    innerWidth: 1400, innerHeight: 900,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  return vm.createContext(sandbox);
}

const FRONTEND = [
  "web/js/api.js", "web/js/store.js", "web/js/motion.js",
  "web/js/views/sources.js", "web/js/views/search.js",
  "web/js/views/settings.js", "web/js/diagnostics.js",
];

function boot() {
  const box = makeSandbox();
  for (const rel of FRONTEND) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, rel), "utf8"), box, { filename: rel });
  }
  box.window.pywebview = {
    api: {
      set_window_tone: (c) => { toneCalls.push(c); return Promise.resolve(true); },
      start_search: () => Promise.resolve({ ok: true, token: 1, total: 0, error: "" }),
      get_settings: () => Promise.resolve({
        min_query_len: 2, max_workers: 8, timeout: 15, retries: 1,
        default_downloader: "", proxy: "", user_agent: "",
        ui_font_size: 18, selbar: true, theme: "light", auto_files: true,
      }),
      app_info: () => Promise.resolve({ version: "1.0.22", autoOrder: true }),
      list_sources: () => Promise.resolve([]),
    },
  };
  return box;
}

let failures = 0, checks = 0;
function report(name, ok, detail) {
  checks++;
  if (ok) console.log("  [ok]   " + name);
  else { failures++; console.log("  [FAIL] " + name + (detail ? "  -> " + detail : "")); }
}

// 从 index.html 抽取并执行内联启动脚本（applyTheme / syncWindowTone）
const html = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
const inline = html.split("<script>")[1].split("</script>")[0];

function runIndexInline(box, dark, dim) {
  toneCalls = [];
  backdropPresent = dim;
  vm.runInContext(inline, box, { filename: "index-inline.js" });
  box.HC.applyTheme(dark ? "dark" : "light");
  return toneCalls;
}

console.log("== 窗口底色跟随主题与弹窗状态 ==");

{
  const box = boot();
  const tones = runIndexInline(box, false, false);
  report("浅色 + 无弹窗 -> 白", tones[tones.length - 1] === "#FFFFFF", JSON.stringify(tones));
}

{
  const box = boot();
  const tones = runIndexInline(box, true, false);
  report("暗色 + 无弹窗 -> 深", tones[tones.length - 1] === "#131419", JSON.stringify(tones));
}

{
  const box = boot();
  const tones = runIndexInline(box, false, true);
  const last = tones[tones.length - 1];
  report("浅色 + 弹窗压暗 -> 遮罩色（不是纯白）", last !== "#FFFFFF" && /^#[0-9A-Fa-f]{6}$/.test(last), last);
}

{
  const box = boot();
  const tones = runIndexInline(box, true, true);
  const last = tones[tones.length - 1];
  report("暗色 + 弹窗压暗 -> 更深", last !== "#131419" && /^#[0-9A-Fa-f]{6}$/.test(last), last);
}

// 遮罩色必须等于「页面底色 上叠 遮罩 alpha」的真实结果，
// 否则窗口留白与页面之间会出现色差缝
console.log("");
console.log("== 遮罩色与 CSS 实际叠加一致 ==");

function hex2rgb(h) {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}
function over(fg, bg, alpha) {
  const a = hex2rgb(fg), b = hex2rgb(bg);
  return a.map((v, i) => Math.round(v * alpha + b[i] * (1 - alpha)));
}

const tokens = fs.readFileSync(path.join(ROOT, "web", "styles", "tokens.css"), "utf8");
const idx = inline.indexOf("var DIMMED");
const expected = {
  light: over("#0D0D1F", "#FFFFFF", 0.38),
  dark: over("#FFFFFF", "#131419", 0.38),
};
const tonesSrc = inline.match(/var DIMMED = \{[^}]*\}/)[0];
const dimLight = tonesSrc.match(/light:\s*"(#[0-9A-Fa-f]{6})"/)[1];
const dimDark = tonesSrc.match(/dark:\s*"(#[0-9A-Fa-f]{6})"/)[1];

{
  const got = hex2rgb(dimLight);
  const want = expected.light;
  const d = Math.max(...got.map((v, i) => Math.abs(v - want[i])));
  report("浅色遮罩色 = 白底叠 rgba(13,13,31,.38)", d <= 1,
    `填 ${dimLight} 应为 rgb(${want}) ，偏差 ${d}`);
}
{
  const got = hex2rgb(dimDark);
  const want = expected.dark;
  const d = Math.max(...got.map((v, i) => Math.abs(v - want[i])));
  report("暗色遮罩色 = 深底叠 rgba(255,255,255,.38)", d <= 1,
    `填 ${dimDark} 应为 rgb(${want}) ，偏差 ${d}`);
}

console.log("");
console.log(failures === 0
  ? "RESULT: PASS  (" + checks + " 项)"
  : "RESULT: FAIL  " + failures + "/" + checks);
process.exit(failures === 0 ? 0 : 1);
