const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = "D:\\AI\\happycrate";

function el(tag) {
  const node = {
    tagName: (tag || "div").toUpperCase(),
    className: "", innerHTML: "", textContent: "", value: "",
    hidden: false, disabled: false, checked: false,
    isConnected: true, parentNode: null, firstChild: null,
    dataset: {}, children: [],
    style: new Proxy({}, {
      get: (t, k) => (k === "setProperty" || k === "removeProperty") ? () => {} : (t[k] || ""),
      set: (t, k, v) => { t[k] = v; return true; }
    }),
    offsetWidth: 900, clientWidth: 900, offsetHeight: 500,
    scrollTop: 0, scrollLeft: 0,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; },
    insertBefore(c) { return c; },
    removeChild(c) { return c; },
    remove() {},
    focus() {}, select() {}, blur() {}, click() {},
    setPointerCapture() {}, releasePointerCapture() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    getBoundingClientRect() { return { left: 0, top: 0, right: 900, bottom: 500, width: 900, height: 500 }; },
    querySelector() { return el("div"); },
    querySelectorAll() { return []; },
    closest() { return null; },
    matches() { return false; }
  };
  return node;
}

function makeSandbox() {
  const document = {
    body: el("body"),
    documentElement: el("html"),
    createElement: (t) => el(t),
    createTextNode: (t) => ({ text: t }),
    getElementById: () => el("div"),
    querySelector: () => el("div"),
    querySelectorAll: () => [],
    addEventListener() {}, removeEventListener() {},
    execCommand() { return true; }
  };
  const sandbox = {
    document, console,
    navigator: { clipboard: null, userAgent: "node-smoke" },
    location: { hash: "", search: "", href: "" },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    performance: { now: () => Date.now() },
    setTimeout, clearTimeout, setInterval, clearInterval,
    Promise, Date, Math, JSON, Number, String, Boolean, Array, Object, RegExp, Error,
    requestAnimationFrame: (fn) => setTimeout(fn, 16),
    cancelAnimationFrame: clearTimeout,
    ResizeObserver: undefined,
    URLSearchParams,
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    innerWidth: 1400, innerHeight: 900, devicePixelRatio: 1
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  return vm.createContext(sandbox);
}

function load(sandbox, rel) {
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  vm.runInContext(src, sandbox, { filename: rel });
}

const FRONTEND = [
  "web/js/api.js",
  "web/js/store.js",
  "web/js/motion.js",
  "web/js/views/sources.js",
  "web/js/views/search.js",
  "web/js/views/settings.js",
  "web/js/diagnostics.js"
];

const VIEWS = [
  ["search", "web/js/views/search.js"],
  ["sources", "web/js/views/sources.js"],
  ["settings", "web/js/views/settings.js"]
];

let failures = 0;
let checks = 0;

function report(name, ok, detail) {
  checks++;
  if (ok) {
    console.log("  [ok]   " + name);
  } else {
    failures++;
    console.log("  [FAIL] " + name + (detail ? "  -> " + detail : ""));
  }
}

console.log("== 1. 全部前端脚本可加载 ==");
const sandbox = makeSandbox();
for (const rel of FRONTEND) {
  try {
    load(sandbox, rel);
    report(rel, true);
  } catch (e) {
    report(rel, false, e.constructor.name + ": " + e.message);
  }
}

console.log("== 2. HC 命名空间齐备 ==");
report("window.HC", !!sandbox.HC);
report("HC.api.startSearch", typeof sandbox.HC?.api?.startSearch === "function");
report("HC.views.search.mount", typeof sandbox.HC?.views?.search?.mount === "function");
report("HC.views.sources.mount", typeof sandbox.HC?.views?.sources?.mount === "function");
report("HC.views.settings.mount", typeof sandbox.HC?.views?.settings?.mount === "function");

console.log("== 3. 每个视图 mount 不抛异常（作用域回归护栏）==");
for (const [name, rel] of VIEWS) {
  const box = makeSandbox();
  let err = null;
  try {
    for (const f of FRONTEND) load(box, f);
    box.HC.views[name].mount(el("div"));
  } catch (e) {
    err = e;
  }
  report("mount " + name, !err, err ? err.constructor.name + ": " + err.message : "");
}

console.log("== 4. 搜索态数据结构自洽 ==");
{
  const box = makeSandbox();
  let err = null;
  try {
    for (const f of FRONTEND) load(box, f);
    const search = box.HC.views.search;
    const probe = el("div");
    search.mount(probe);
    if (search.st === undefined) {
      throw new Error("mount 正常返回但未导出 st —— 检查 mount 是否存在提前 return");
    }
  } catch (e) {
    err = e;
  }
  report("HC.views.search.st 已导出", !err, err ? err.constructor.name + ": " + err.message : "");
}

console.log("");
console.log(failures === 0
  ? "RESULT: PASS  (" + checks + " 项)"
  : "RESULT: FAIL  " + failures + "/" + checks + " 项未通过");

process.exit(failures === 0 ? 0 : 1);
