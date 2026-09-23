const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");

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
    replaceChild(c) { return c; },
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
report("HC.esc 共享转义", typeof sandbox.HC?.esc === "function");
{
  let escErr = "";
  try {
    const v = sandbox.HC.esc('<a b="c">d\'e</a>');
    if (v !== "&lt;a b=&quot;c&quot;&gt;d&#39;e&lt;/a&gt;") {
      escErr = "转义结果不符：" + v;
    }
  } catch (e) {
    escErr = e.constructor.name + ": " + e.message;
  }
  report("HC.esc 覆盖五种字符", !escErr, escErr);
}

console.log("== 3. api.js 必须先于其它脚本提供 HC.esc ==");
report("api.js 是第一个脚本",
       FRONTEND[0] === "web/js/api.js",
       "HC.esc 由 api.js 定义，若它不在最前，后面的视图会拿到 undefined");

console.log("== 4. 每个视图 mount 不抛异常（作用域回归护栏）==");
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

console.log("== 5. 搜索态数据结构自洽 ==");
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

console.log("== 6. 加载顺序与 index.html 一致 ==");
{
  let orderErr = "";
  try {
    const html = fs.readFileSync(path.join(ROOT, "web/index.html"), "utf8");
    const tags = [...html.matchAll(/<script\s+src="([^"]+)"/g)].map(m => m[1]);
    const fromHtml = tags.map(s => "web/" + s.replace(/^\.\//, ""));
    if (fromHtml.join(",") !== FRONTEND.join(",")) {
      orderErr = "index.html: " + fromHtml.join(" -> ") +
                 " ；冒烟列表: " + FRONTEND.join(" -> ");
    }
  } catch (e) {
    orderErr = e.constructor.name + ": " + e.message;
  }
  report("冒烟列表 == index.html 脚本顺序", !orderErr, orderErr);
}

console.log("== 7. 桥接就绪前刷的 mock 源列表，必须在 live 后被真实数据替换 ==");
{
  const box = makeSandbox();
  for (const f of FRONTEND) load(box, f);
  box.HC.views.search.mount(el("div"));
  setTimeout(function(){
    const before = box.HC.views.search.st.srcList.map(s => s.key);
    report("桥接前是 mock 源", before.length > 1 && before.indexOf("nyaa") >= 0,
           JSON.stringify(before));
    box.window.pywebview = { api: {
      start_search: function(){
        return Promise.resolve({ok:true, token:0, total:0, error:"",
                                query:{subject:[],browse:true}});
      },
      get_settings: function(){ return Promise.resolve({}); },
      list_sources: function(){
        return Promise.resolve([
          {key:"nyaa", label:"Nyaa", type:"builtin", enabled:true, timeout:15,
           health:{state:"ok", ms:30, err:"", times:["ok"], outcomes:["ok"]}}
        ]);
      }
    }};
    setTimeout(function(){
      const after = box.HC.views.search.st.srcList.map(s => s.key);
      report("live 后 mock 源被替换", after.length === 1 && after[0] === "nyaa",
             JSON.stringify(after));
      report("live 后源列表来自后端", after.indexOf("nyaa") >= 0,
             JSON.stringify(after));
      report("live 后不残留 mock 源", after.length === 1, "数量 " + after.length);

      console.log("");
      console.log(failures === 0
        ? "RESULT: PASS  (" + checks + " 项)"
        : "RESULT: FAIL  " + failures + "/" + checks + " 项未通过");
      process.exit(failures === 0 ? 0 : 1);
    }, 600);
  }, 60);
}
