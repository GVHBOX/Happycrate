import { spawn, execSync } from "node:child_process";
import { createServer } from "node:http";
import { get as httpGet } from "node:http";
import { existsSync, mkdirSync, readFileSync, rmSync, readdirSync } from "node:fs";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const webRoot = join(projectRoot, "web");
const tmpRoot = join(projectRoot, ".scratch", "tmp");

const BROWSERS = [
  ["Edge", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"],
  ["Edge", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"],
  ["Chrome", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"],
  ["Chrome", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"],
].filter(([, p]) => existsSync(p))
  .filter(([label]) => !process.env.HC_E2E_BROWSER
    || label.toLowerCase() === process.env.HC_E2E_BROWSER.toLowerCase());

const SHARED_PORT = 8123;
const HEADED = process.env.HC_E2E_HEADED === "1";
const CTRL = 2;
const SHIFT = 8;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, timeoutMs, intervalMs, label) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      const v = await fn();
      if (v) return v;
      last = v;
    } catch (e) {}
    await sleep(intervalMs);
  }
  throw new Error("waitFor-timeout:" + label);
}

function fetchOk(url) {
  return new Promise((resolve) => {
    const req = httpGet(url, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => { req.destroy(); resolve(false); });
  });
}

function staticServer(root) {
  const server = createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
    let filePath = normalize(join(root, urlPath === "/" ? "index.html" : urlPath));
    if (!filePath.startsWith(root)) { res.writeHead(403); res.end(); return; }
    try {
      const data = readFileSync(filePath);
      res.writeHead(200, { "Content-Type": MIME[extname(filePath)] || "application/octet-stream" });
      res.end(data);
    } catch (e) {
      res.writeHead(404); res.end();
    }
  });
  return server;
}

async function main() {
  if (!BROWSERS.length) { console.error("no edge/chrome found"); return 2; }
  mkdirSync(tmpRoot, { recursive: true });
  if (HEADED) {
    console.log("[run] 有头模式：浏览器窗口会在你桌面上出现（已尽量最小化），跑完自动关闭");
  }

  let server = null;
  let pageUrl = "http://127.0.0.1:" + SHARED_PORT + "/index.html";
  if (await fetchOk(pageUrl)) {
    console.log("[srv] reuse shared :" + SHARED_PORT);
  } else {
    server = staticServer(webRoot);
    await new Promise((r) => server.listen(0, "127.0.0.1", r));
    pageUrl = "http://127.0.0.1:" + server.address().port + "/index.html";
    console.log("[srv] own server ->", pageUrl);
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const profileDir = join(tmpRoot, "hc-e2e-" + stamp);
  await sweepStaleProfiles(profileDir);
  mkdirSync(profileDir, { recursive: true });

  try {
    const errors = [];
    for (const [label, exe] of BROWSERS) {
      console.log("[run] browser:", label);
      try {
        const result = await runOnce(exe, profileDir, pageUrl);
        for (const c of result.checks) {
          console.log((c.pass ? "  ok  " : "  FAIL") + " " + c.name + (c.detail ? "  (" + c.detail + ")" : ""));
        }
        const failed = result.checks.filter((c) => !c.pass);
        if (!failed.length) {
          console.log("VERDICT: PASS (" + label + ")");
          return 0;
        }
        console.log("[run] " + label + " failed: " + failed.map((f) => f.name).join("; "));
      } catch (e) {
        const msg = String((e && e.message) || e);
        console.log("[run] " + label + " error: " + msg);
        if (msg.indexOf("browser-exited-early") >= 0 && !HEADED) {
          errors.push(label);
        }
      }
    }
    if (errors.length === BROWSERS.length) {
      console.log("[hint] 每个浏览器都在启动阶段就退出、且没有任何输出。这台机器把 headless Chromium");
      console.log("[hint] 静默拦掉了（关掉沙箱也一样），不是脚本问题。要跑就用有头模式：");
      console.log("[hint]   HC_E2E_HEADED=1 node tests/e2e/hc-e2e-test.mjs   （会短暂出现浏览器窗口）");
    }
    console.log("VERDICT: FAIL");
    return 1;
  } finally {
    if (server) server.close();
    await sweepProfile(profileDir);
  }
}

async function sweepStaleProfiles(keep) {
  let names = [];
  try {
    names = readdirSync(tmpRoot).filter((n) => n.startsWith("hc-e2e-"));
  } catch (e) {
    return;
  }
  for (const name of names) {
    const dir = join(tmpRoot, name);
    if (dir === keep) continue;
    try {
      rmSync(dir, { recursive: true, force: true, maxRetries: 2 });
      console.log("[clean] 清掉上次残留:", name);
    } catch (e) {}
  }
}

async function sweepProfile(dir) {
  if (process.env.HC_KEEP_PROFILE === "1") {
    console.log("[clean] 保留 profile（HC_KEEP_PROFILE=1）:", dir);
    return;
  }
  for (let i = 0; i < 4; i++) {
    try {
      rmSync(dir, { recursive: true, force: true, maxRetries: 3 });
      console.log("[clean] 已删除 profile:", dir);
      return;
    } catch (e) {
      await sleep(700);
    }
  }
  console.log("[clean] profile 仍被占用，稍后清理:", dir);
}

async function runOnce(exe, profileDir, pageUrl) {
  const child = spawn(exe, [
    "--user-data-dir=" + profileDir,
    "--remote-debugging-port=0",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--no-proxy-server",
    "--window-size=1280,1500",
    ...(HEADED
      ? ["--start-minimized", "--window-position=-32000,-32000"]
      : ["--headless"]),
    pageUrl,
  ], { stdio: "ignore" });
  let exited = false;
  child.on("exit", () => { exited = true; });
  let browserPort = 0;
  const killByPort = () => {
    if (!browserPort) return;
    try {
      const out = execSync("netstat -ano", { encoding: "utf8" });
      for (const line of out.split(/\r?\n/)) {
        if (line.indexOf(":" + browserPort) < 0 || !/LISTENING/i.test(line)) continue;
        const cols = line.trim().split(/\s+/);
        const pid = cols[cols.length - 1];
        if (/^\d+$/.test(pid)) execSync("taskkill /PID " + pid + " /T /F", { stdio: "ignore" });
      }
    } catch (e) {}
  };
  const killTree = () => {
    try { execSync("taskkill /PID " + child.pid + " /T /F", { stdio: "ignore" }); } catch (e) {}
    killByPort();
  };

  let ws = null;
  let msgId = 0;
  const pending = new Map();
  const checks = [];

  const check = (name, pass, detail) => checks.push({ name, pass: !!pass, detail: detail === undefined ? "" : String(detail) });

  let evaluate = null;
  let page = null;

  try {
    const portFile = join(profileDir, "DevToolsActivePort");
    const port = await waitFor(() => {
      if (!existsSync(portFile)) return 0;
      const p = Number(readFileSync(portFile, "utf8").split("\n")[0].trim());
      return p > 0 ? p : 0;
    }, 30000, 300, "devtools-port").catch(() => {
      throw new Error(exited ? "browser-exited-early" : "devtools-port-timeout");
    });
    browserPort = port;

    const wsPath = readFileSync(portFile, "utf8").split("\n")[1].trim();
    await new Promise((res, rej) => {
      let tries = 0;
      let timer = null;
      const attempt = () => {
        tries++;
        ws = new WebSocket("ws://127.0.0.1:" + port + wsPath);
        ws.onopen = () => { clearTimeout(timer); res(); };
        ws.onerror = () => {
          if (exited) return rej(new Error("browser-exited-early"));
          if (tries >= 12) return rej(new Error("ws-open-failed"));
          setTimeout(attempt, 500);
        };
      };
      timer = setTimeout(() => rej(new Error("ws-open-timeout")), 30000);
      attempt();
    });
    ws.onmessage = (ev) => {
      const data = JSON.parse(typeof ev.data === "string" ? ev.data : String(ev.data));
      if (data.id && pending.has(data.id)) {
        const { resolve, reject } = pending.get(data.id);
        pending.delete(id2(data));
        if (data.error) reject(new Error(data.error.message || JSON.stringify(data.error)));
        else resolve(data.result);
      }
    };
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      const id = ++msgId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error("timeout:" + method)); } }, 15000);
    });
    evaluate = async (expression, sessionId) => {
      const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
      if (r.exceptionDetails) throw new Error("page-eval: " + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
      return r.result.value;
    };

    const { targetId } = await send("Target.createTarget", { url: pageUrl });
    page = (await send("Target.attachToTarget", { targetId, flatten: true })).sessionId;
    await waitFor(async () => ((await evaluate("location.href", page)) || "").indexOf("127.0.0.1") >= 0, 20000, 200, "page-nav");
    await waitFor(async () => (await evaluate("document.readyState", page)) === "complete", 10000, 200, "page-load");
    const mounted = await waitFor(async () => !!(await evaluate("document.querySelector('#inp')", page)), 10000, 200, "app-mount").catch(async () => {
      const diag = await evaluate("location.href + ' | ' + document.readyState + ' | app:' + document.getElementById('app').childElementCount", page).catch(() => "diag-failed");
      console.log("[diag] mount fail:", diag);
      await send("Page.reload", {}, page).catch(() => {});
      return waitFor(async () => !!(await evaluate("document.querySelector('#inp')", page)), 10000, 200, "app-mount-retry");
    });
    void mounted;
    await sleep(400);
    await evaluate('window.__errs=[];window.addEventListener("error",function(e){window.__errs.push(String(e.message))})', page);

    const rectOf = async (sel, index) => evaluate(
      "(() => { const els = document.querySelectorAll(" + JSON.stringify(sel) + "); const el = els[" + index + "]; if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()",
      page,
    );
    const centerOf = (r) => ({ x: Math.round(r.x + Math.min(90, r.w / 2)), y: Math.round(r.y + r.h / 2) });
    const mouse = (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1, ...extra }, page);
    const realClick = async (x, y, modifiers = 0) => {
      await mouse("mouseMoved", x, y);
      await sleep(40);
      await mouse("mousePressed", x, y, { modifiers });
      await sleep(70);
      await mouse("mouseReleased", x, y, { modifiers });
      await sleep(260);
    };
    const key = async (k, vk, modifiers = 0) => {
      await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: k, code: k, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers }, page);
      await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code: k, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers }, page);
      await sleep(180);
    };
    const focusedTag = () => evaluate("(document.activeElement && document.activeElement.tagName || '').toLowerCase()", page);
    const selCount = () => evaluate("document.querySelectorAll('#rows .srow.sel').length", page);
    const selIdx = () => evaluate("[...document.querySelectorAll('#rows .srow')].map(function(e,i){return e.classList.contains('sel')?i:null}).filter(function(v){return v!==null})", page);
    const badge = () => evaluate("document.querySelector('#badge').textContent", page);
    const rowsElRect = () => rectOf("#rows", 0);
    let skelChecked = false;
    const search = async (q, expect) => {
      const hasHero = await evaluate("!!document.querySelector('#heroGo')", page);
      console.log("[search] q=" + q + " expect=" + expect + " hero=" + hasHero);
      if (hasHero){
        await evaluate("document.getElementById('heroInp').value = " + JSON.stringify(q), page);
        const hg = centerOf(await rectOf("#heroGo", 0));
        await realClick(hg.x, hg.y);
      } else {
        await evaluate("document.querySelector('#inp').value = " + JSON.stringify(q), page);
        const go = centerOf(await rectOf("#goBtn", 0));
        await realClick(go.x, go.y);
      }
      await waitFor(async () => (await evaluate("document.querySelectorAll('#rows .skel').length", page)) > 0, 4000, 100, "skeleton:" + q).catch(() => {});
      if (!skelChecked && expect > 0){
        await waitFor(async () => !!(await evaluate("HC.views.search.st.busy && document.querySelectorAll('#rows .srow').length", page)), 9000, 100, "first-row:" + q);
        check("skel-below-rows", !!(await evaluate("(function(){var r=document.querySelectorAll('#rows .srow');var s=document.querySelectorAll('#rows .skel');return r.length&&s.length&&(r[r.length-1].compareDocumentPosition(s[0])&4)})()", page)));
        skelChecked = true;
      }
      await waitFor(async () => {
        if (await evaluate("HC.views.search.st.busy", page)) return false;
        const n = await evaluate("document.querySelectorAll('#rows .srow').length", page);
        return expect === 0 ? (await badge()).indexOf("共 0 条") >= 0 : n === expect;
      }, 9000, 250, "search-done:" + q);
      await sleep(500);
    };
    const at = async (x, y) => evaluate(
      "(function(){var e=document.elementFromPoint(" + x + "," + y + ");return e?(e.className||e.tagName).toString().slice(0,40):'null'})()",
      page,
    );
    const metrics = (w, h) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false }, page);

    await metrics(1280, 1150);
    check("hero-idle-first-run", !!(await evaluate("document.querySelector('.hero') && document.querySelector('#heroGo')", page)));
    await search("ubuntu", 24);
    check("mock-24-rows", (await evaluate("document.querySelectorAll('#rows .srow').length", page)) === 24, await badge());
    check("hl-count-24", (await evaluate("document.querySelectorAll('#rows .c-title mark.hl').length", page)) === 24, await evaluate("document.querySelectorAll('#rows .c-title mark.hl').length", page));
    check("relevance-order", (await evaluate("document.querySelectorAll('#rows .srow')[1].textContent.indexOf('第 2 话') >= 0", page)), await evaluate("document.querySelectorAll('#rows .srow')[1].textContent.slice(0, 50)", page));
    await sleep(600);
    check("no-auto-expand-when-title-covers-query", (await evaluate("document.querySelectorAll('.fpanel').length", page)) === 0,
      "标题已含关键词时不该自动展开，实际 " + (await evaluate("document.querySelectorAll('.fpanel').length", page)));

    await search("ubuntu 花絮", 24);
    await waitFor(async () => (await evaluate("document.querySelectorAll('.fpanel').length", page)) > 0, 5000, 150, "auto-expand-reveal");
    check("auto-expand-when-file-reveals-token", (await evaluate("document.querySelectorAll('.fpanel').length", page)) > 0,
      "关键词只在文件里出现时应自动展开，实际 " + (await evaluate("document.querySelectorAll('.fpanel').length", page)));
    check("fpanel-auto-hl", !!(await evaluate("document.querySelector('.fpanel .fname mark.hl')", page)));
    await evaluate("document.querySelector('#rows .srow:not(.open) .fchev').click()", page);
    await sleep(350);
    check("fpanel-manual-open", !!(await evaluate("document.querySelector('#rows .srow.open')", page)), await evaluate("document.querySelectorAll('.fpanel').length", page));
    await evaluate("(function(){document.querySelectorAll('#rows .srow.open .fchev').forEach(function(b){b.click()})})()", page);
    await sleep(350);
    check("fpanel-all-closed", (await evaluate("document.querySelectorAll('.fpanel').length", page)) === 0, await evaluate("document.querySelectorAll('.fpanel').length", page));
    check("hero-gone-after-search", !(await evaluate("!!document.querySelector('.hero')", page)));
    check("srcstrip-done", (await evaluate("!document.getElementById('srcstrip').hidden && document.querySelectorAll('#srcstrip .stile.ok').length", page)) >= 3,
      await evaluate("document.getElementById('srcstrip').textContent", page));
    const stripGeo = await evaluate("(function(){var s=document.getElementById('srcstrip');return {ox:s.scrollWidth>s.clientWidth, w:s.scrollWidth, cw:s.clientWidth, n:s.querySelectorAll('.stile').length}})()", page);
    check("srcstrip-no-horizontal-scroll", !stripGeo.ox,
      "逐源条不该出现横向滚动，实际 " + JSON.stringify(stripGeo));

    await evaluate("document.querySelectorAll('#rows .srow')[2].click()", page);
    check("selbar-default-off", !(await evaluate("document.getElementById('selbar').classList.contains('show')", page)));
    await evaluate("HC.views.search.st.selbarOn = true", page);

    let p = centerOf(await rectOf("#rows .srow", 2));
    await realClick(p.x, p.y);
    check("click-row-selects-single", (await selCount()) === 1, "sel=" + JSON.stringify(await selIdx()));
    check("selbar-shows", (await evaluate("document.getElementById('selbar').classList.contains('show') && document.getElementById('selN').textContent", page)) === "1");

    const darkSelCount = await evaluate(`(function(){
      document.body.classList.add("dark");
      var b = document.getElementById("selN");
      function rgb(c){ return c.slice(c.indexOf("(") + 1, c.indexOf(")")).split(",").map(Number); }
      function lum(c){ var f = rgb(c).map(function(x){ x = x / 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]; }
      var fg = getComputedStyle(b).color;
      var bg = getComputedStyle(document.getElementById("selbar")).backgroundColor;
      var hi = Math.max(lum(fg), lum(bg)), lo = Math.min(lum(fg), lum(bg));
      var r = (hi + 0.05) / (lo + 0.05);
      document.body.classList.remove("dark");
      return fg + " on " + bg + " = " + r.toFixed(2) + " darkBack=" + !document.body.classList.contains("dark");
    })()`, page);
    const darkRatio = parseFloat(String(darkSelCount).split(" = ")[1]);
    check("dark-selbar-count-is-readable",
      darkRatio >= 4 && /darkBack=true/.test(darkSelCount), darkSelCount);

    p = centerOf(await rectOf("#rows .srow", 5));
    await realClick(p.x, p.y);
    check("click-another-row-replaces", (await selCount()) === 1, "sel=" + JSON.stringify(await selIdx()));

    p = centerOf(await rectOf("#rows .srow", 7));
    await realClick(p.x, p.y, CTRL);
    check("ctrl-click-adds", (await selCount()) === 2, "sel=" + JSON.stringify(await selIdx()));
    await realClick(p.x, p.y, CTRL);
    check("ctrl-click-removes", (await selCount()) === 1, "sel=" + JSON.stringify(await selIdx()));

    p = centerOf(await rectOf("#rows .srow", 10));
    await realClick(p.x, p.y, SHIFT);
    check("shift-click-range", (await selCount()) === 4, "sel=" + JSON.stringify(await selIdx()));

    await evaluate("(function(){for(var i=0;i<8;i++){var r=document.querySelectorAll('#rows .srow');r[r.length-1].remove()}})()", page);
    await sleep(200);
    const rr = await rowsElRect();
    const geo = await evaluate("JSON.stringify({inner: innerWidth + 'x' + innerHeight, rows: (function(){var r=document.querySelector('#rows').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})(), rowCount: document.querySelectorAll('#rows .srow').length})", page);
    const blankX = Math.round(rr.x + 120);
    const blankY = Math.round(rr.y + rr.h - 24);
    const blankHit = await at(blankX, blankY);
    await realClick(blankX, blankY);
    check("click-blank-clears", (await selCount()) === 0 && !/srow/.test(blankHit), "hit=" + blankHit + " sel=" + (await selCount()) + " geo=" + geo);
    check("selbar-hides-on-clear", !(await evaluate("document.getElementById('selbar').classList.contains('show')", page)));

    const start = centerOf(await rectOf("#rows .srow", 1));
    const end = centerOf(await rectOf("#rows .srow", 8));
    await mouse("mouseMoved", start.x, start.y);
    await sleep(40);
    await mouse("mousePressed", start.x, start.y);
    await sleep(60);
    await mouse("mouseMoved", Math.round((start.x + end.x) / 2), Math.round((start.y + end.y) / 2), { buttons: 1 });
    await sleep(60);
    await mouse("mouseMoved", end.x, end.y, { buttons: 1 });
    await sleep(80);
    const selDuringDrag = await selCount();
    await mouse("mouseReleased", end.x, end.y);
    await sleep(260);
    check("marquee-selects-range", selDuringDrag === 8 && (await selCount()) === 8, "during=" + selDuringDrag + " after=" + (await selCount()));

    p = centerOf(await rectOf("#rows .srow", 12));
    await realClick(p.x, p.y);
    check("click-after-marquee-single", (await selCount()) === 1, "sel=" + JSON.stringify(await selIdx()));
    check("badge-selected-text", (await badge()).indexOf("已选中 1 条") >= 0 && (await badge()).indexOf("共 24 条") >= 0, await badge());

    const ip = centerOf(await rectOf("#inp", 0));
    await realClick(ip.x, ip.y);
    await send("Input.insertText", { text: "ubuntu" }, page);
    await key("Enter", 13);
    await waitFor(async () => !!(await evaluate("HC.views.search.st.busy || document.querySelectorAll('#rows .srow').length !== 24", page)) === false, 9000, 250, "enter-search");
    await sleep(500);
    check("focus-in-input-after-enter", (await focusedTag()) === "input", await focusedTag());
    p = centerOf(await rectOf("#rows .srow", 4));
    await realClick(p.x, p.y);
    await realClick(ip.x, ip.y);
    check("focus-back-in-input-selected", (await selCount()) === 1 && (await focusedTag()) === "input", "sel=" + (await selCount()) + " focus=" + (await focusedTag()));
    await key("Escape", 27);
    check("esc-clears-input-focus", (await selCount()) === 0, "sel=" + (await selCount()));
    check("esc-first-clears-selection-only", !!(await evaluate("!!document.querySelector('#rows .srow')", page)) && !(await evaluate("!!document.querySelector('.hero')", page)));
    await key("Escape", 27);
    check("esc-opens-hero-from-list", !!(await evaluate("!!document.querySelector('.hero')", page)));
    await evaluate("document.getElementById('tbHome').click()", page);
    await sleep(450);
    check("logo-toggles-back-to-list", !(await evaluate("!!document.querySelector('.hero')", page)) && !!(await evaluate("document.querySelector('#rows .srow')", page)));

    p = centerOf(await rectOf("#rows .srow", 6));
    await realClick(p.x, p.y);
    await key("Escape", 27);
    check("esc-clears-body-focus", (await selCount()) === 0, "sel=" + (await selCount()));
    await key("Escape", 27);
    await evaluate("document.getElementById('tbHome').click()", page);
    await sleep(450);
    check("hero-gone-after-toggle", !(await evaluate("!!document.querySelector('.hero')", page)));

    p = centerOf(await rectOf("#rows .srow", 3));
    await realClick(p.x, p.y);
    await key("ArrowDown", 40);
    check("cursor-key-down", (await evaluate("document.querySelectorAll('#rows .srow')[4].classList.contains('cursor')", page)));
    await key(" ", 32);
    check("space-toggles-cursor-row", (await evaluate("document.querySelectorAll('#rows .srow')[4].classList.contains('sel')", page)));
    await key(" ", 32);
    await key("ArrowUp", 38);
    check("cursor-key-up", (await evaluate("document.querySelectorAll('#rows .srow')[3].classList.contains('cursor')", page)));

    p = centerOf(await rectOf("#rows .srow", 3));
    await realClick(p.x, p.y);
    await key("d", 68, CTRL + SHIFT);
    await waitFor(async () => !!(await evaluate("document.querySelector('.backdrop')", page)), 4000, 150, "diag-modal");
    await key("Escape", 27);
    await sleep(320);
    const modalGone = await evaluate("!document.querySelector('.backdrop')", page);
    check("esc-modal-keeps-selection", modalGone && (await selCount()) === 1, "modalGone=" + modalGone + " sel=" + JSON.stringify(await selIdx()));

    const ck = centerOf(await rectOf("#ckAll", 0));
    await realClick(ck.x, ck.y);
    const allOn = (await selCount()) === 24 && (await badge()).indexOf("已选中 24 条") >= 0;
    await realClick(ck.x, ck.y);
    check("select-all-toggle", allOn && (await selCount()) === 0, "on=" + allOn + " off=" + (await selCount()));

    await metrics(1280, 430);
    await sleep(400);
    await search("ubuntu", 24);
    const geoB = await evaluate("JSON.stringify({inner: innerWidth + 'x' + innerHeight, rows: (function(){var r=document.querySelector('#rows').getBoundingClientRect();return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]})(), scrollable: document.querySelector('#rows').scrollHeight - document.querySelector('#rows').clientHeight})", page);
    const topRow = centerOf(await rectOf("#rows .srow", 1));
    const r2 = await rowsElRect();
    const edgeY = Math.round(r2.y + r2.h - 5);
    const preOn = await at(topRow.x, topRow.y);
    await mouse("mouseMoved", topRow.x, topRow.y);
    await sleep(40);
    await mouse("mousePressed", topRow.x, topRow.y);
    await sleep(60);
    await mouse("mouseMoved", topRow.x + 30, edgeY, { buttons: 1 });
    await sleep(200);
    const mq = await evaluate("!!document.querySelector('.marquee')", page);
    const st0 = await evaluate("document.querySelector('#rows').scrollTop", page);
    const sel0 = await selCount();
    await sleep(800);
    await mouse("mouseMoved", topRow.x + 30, edgeY, { buttons: 1 });
    await sleep(700);
    const st1 = await evaluate("document.querySelector('#rows').scrollTop", page);
    const sel1 = await selCount();
    await mouse("mouseReleased", topRow.x + 30, edgeY);
    await sleep(200);
    const marqueeGone = await evaluate("!document.querySelector('.marquee')", page);
    check("marquee-edge-autoscroll", mq && st1 > st0 && sel1 > sel0 && marqueeGone, "preOn=" + preOn + " mq=" + mq + " scroll " + st0 + "->" + st1 + " sel " + sel0 + "->" + sel1 + " marqueeGone=" + marqueeGone + " geo=" + geoB);

    await metrics(1280, 1500);
    await evaluate("document.querySelector('#inp').value = 'ubuntu'", page);
    const goC = centerOf(await rectOf("#goBtn", 0));
    await realClick(goC.x, goC.y);
    await waitFor(async () => /搜索中/.test(await evaluate("document.querySelector('#chip').textContent", page)), 4000, 100, "search-busy");
    await realClick(goC.x, goC.y);
    await waitFor(async () => (await evaluate("document.querySelector('#goBtn').textContent", page)) === "搜索", 4000, 100, "search-stopped");
    await evaluate("window.__onSearchDone({token: HC.views.search.st.token, total: 24, errors: {}})", page);
    await sleep(200);
    const chipAfterDone = await evaluate("document.querySelector('#chip').textContent", page);
    check("stop-state-not-overwritten", chipAfterDone.indexOf("搜索完成") < 0, "chip=" + chipAfterDone);

    await search("空", 0);
    check("mock-empty-scenario", (await evaluate("document.querySelectorAll('#rows .srow').length", page)) === 0 && (await badge()) === "共 0 条", await badge());

    await evaluate("location.hash = 'settings'", page);
    await waitFor(async () => !!(await evaluate("document.querySelector('#netbar') && !document.querySelector('#netbar').hidden", page)), 6000, 150, "netbar");
    const netInfo = await evaluate("(function(){var b=document.querySelector('#netbar');return {dot:b.querySelector('.netdot').className, title:b.querySelector('.nettitle').textContent, addr:b.querySelector('.netaddr').textContent, note:b.querySelector('.netnote').textContent}})()", page);
    check("netbar-shows-system-proxy", netInfo.dot.indexOf("ok") >= 0 && netInfo.title.indexOf("跟随系统") >= 0, JSON.stringify(netInfo));
    await evaluate("location.hash = ''", page);
    await sleep(400);

    await search("断网", 0);
    const fatalTip = await evaluate("(function(){var t=document.querySelector('#tip');return t?{shown:t.classList.contains('show'),text:t.innerText}:{shown:false,text:''}})()", page);
    check("no-proxy-hint-is-visible", fatalTip.shown && fatalTip.text.indexOf("未检测到代理") >= 0, JSON.stringify(fatalTip).slice(0, 160));
    check("no-proxy-hint-not-counted-as-source", (await evaluate("document.querySelector('#chip').textContent", page)).indexOf("个源失败") < 0, await evaluate("document.querySelector('#chip').textContent", page));

    await evaluate("location.hash = 'sources'", page);
    await waitFor(async () => (await evaluate("document.querySelectorAll('#rows .row').length", page)) >= 10, 6000, 150, "sources-mount");
    const srcCount = await evaluate("document.querySelectorAll('#rows .row').length", page);

    const switchCount = await evaluate("document.querySelectorAll('#rows .sw').length", page);
    check("every-row-has-a-switch", switchCount === srcCount,
      "sw=" + switchCount + " rows=" + srcCount);

    const removedControls = await evaluate(`JSON.stringify({
      batch: document.querySelectorAll('#btnBatch').length,
      del: document.querySelectorAll('#btnDel').length,
      reset: document.querySelectorAll('#btnReset').length,
      exp: document.querySelectorAll('#btnExport').length,
      imp: document.querySelectorAll('#btnImport').length,
      edit: document.querySelectorAll('#rows .op[data-edit]').length
    })`, page);
    const rc = JSON.parse(removedControls);
    check("panel-is-switch-only",
      rc.batch + rc.del + rc.reset + rc.exp + rc.imp + rc.edit === 0,
      removedControls);

    const probeBtn = await evaluate("!!document.querySelector('#btnProbe')", page);
    const autoBtn = await evaluate("!!document.querySelector('#btnAuto')", page);
    const searchBox = await evaluate("!!document.querySelector('#search')", page);
    check("panel-keeps-probe-auto-search",
      probeBtn && autoBtn && searchBox,
      "probe=" + probeBtn + " auto=" + autoBtn + " search=" + searchBox);

    const firstSw = centerOf(await rectOf("#rows .sw", 0));
    await realClick(firstSw.x, firstSw.y);
    await sleep(300);
    const firstOff = await evaluate("document.querySelector('#rows .row').classList.contains('off')", page);
    await realClick(firstSw.x, firstSw.y);
    await sleep(300);
    const firstBackOn = await evaluate("!document.querySelector('#rows .row').classList.contains('off')", page);
    check("switch-toggles-source", firstOff && firstBackOn,
      "off=" + firstOff + " backOn=" + firstBackOn);

    await evaluate('location.hash = "search"', page);
    await sleep(400);
    await evaluate('location.hash = "sources"', page);
    await waitFor(async () => !!(await evaluate("document.querySelector('.badlink')", page)), 5000, 150, "badlink");
    const badRect = centerOf(await rectOf(".badlink", 0));
    await realClick(badRect.x, badRect.y);
    await waitFor(async () => !!(await evaluate("document.querySelector('.backdrop .issues')", page)), 4000, 150, "issues-modal");
    const logState = await evaluate(`JSON.stringify({
      hasLog: !!document.querySelector(".backdrop .logbox"),
      closed: !document.querySelector(".backdrop .logbox").open,
      label: (document.querySelector(".backdrop .logbox summary")||{}).textContent,
      termHidden: (function(){
        var t = document.querySelector(".backdrop .logbox .term");
        return !t || t.getBoundingClientRect().height === 0;
      })()
    })`, page);
    const ls = JSON.parse(logState);
    check("issues-log-collapsed-by-default",
      ls.hasLog && ls.closed && ls.label === "诊断原文" && ls.termHidden,
      logState);

    await evaluate("document.querySelector('.backdrop .logbox summary').click()", page);
    await sleep(300);
    const openLog = await evaluate(`JSON.stringify({
      open: document.querySelector(".backdrop .logbox").open,
      h: Math.round(document.querySelector(".backdrop .logbox .term").getBoundingClientRect().height)
    })`, page);
    const ol = JSON.parse(openLog);
    check("issues-log-expands", ol.open && ol.h > 40, openLog);

    const issueText = await evaluate(`[].slice.call(document.querySelectorAll(".backdrop .issue"))
      .map(function(n){ return n.textContent; }).join(" ")`, page);
    const leaked = ["现象", "明细", "建议", "位置", ".py", "http5xx", "试试", "重试"]
      .filter((w) => issueText.indexOf(w) >= 0);
    check("issues-modal-is-facts-only", leaked.length === 0, "leaked=" + JSON.stringify(leaked));

    const logText = await evaluate('document.querySelector(".backdrop .logbox .term").textContent', page);
    check("issues-log-keeps-agent-detail", logText.indexOf("adapter") >= 0 || logText.indexOf(".py") >= 0,
      "log=" + logText.slice(0, 80));

    await evaluate("document.querySelector('.backdrop [data-close]').click()", page);
    await sleep(400);

    await key("Escape", 27);
    await waitFor(async () => !!(await evaluate("document.querySelector('#inp')", page)), 4000, 150, "esc-back-sources");
    check("esc-returns-from-sources", !!(await evaluate("document.querySelector('#inp')", page)));

    const tbTitle = await evaluate("document.querySelector('.tb-title').textContent", page);
    check("titlebar-version-from-api", /^Happycrate v\d/.test(tbTitle), tbTitle);
    check("tbdot-removed", (await evaluate("!document.getElementById('tbDot')", page)),
      await evaluate("!!document.getElementById('tbDot')", page));

    await evaluate("location.hash = 'search'", page);
    await waitFor(async () => !!(await evaluate("document.querySelector('#inp')", page)), 6000, 150, "back-to-search");

    const gearBtn = centerOf(await rectOf("#btnCfg", 0));
    await realClick(gearBtn.x, gearBtn.y);
    await waitFor(async () => !!(await evaluate("document.querySelector('.app.settings')", page)), 4000, 150, "settings-mount");
    const settingsTitle = await evaluate("(document.querySelector('.dtitle')||{}).textContent || ''", page);
    await evaluate("document.getElementById('s_theme').click()", page);
    await sleep(200);
    const darkOn = await evaluate("document.body.classList.contains('dark')", page);
    await evaluate("document.getElementById('s_theme').click()", page);
    await sleep(200);
    const darkOff = await evaluate("!document.body.classList.contains('dark')", page);
    check("theme-toggle-dark", darkOn && darkOff, "on=" + darkOn + " off=" + darkOff);
    await key("Escape", 27);
    await waitFor(async () => !!(await evaluate("document.querySelector('#inp')", page)), 4000, 150, "settings-back");
    check("gear-opens-settings", /设置/.test(settingsTitle), "title=" + settingsTitle);
    check("esc-returns-from-settings", !!(await evaluate("document.querySelector('#inp')", page)));

    await evaluate("document.getElementById('tbHome').click()", page);
    await sleep(450);
    const heroBack = await evaluate("!!document.querySelector('.hero') && !!document.getElementById('heroGo')", page);
    const markTag = await evaluate("(document.querySelector('.brandmark')||{}).tagName + '|' + ((document.querySelector('.brandmark')||{}).src || '')", page);
    check("logo-returns-to-hero", heroBack, "hero=" + heroBack);
    check("hero-brandmark-icon", markTag.indexOf("IMG") === 0 && markTag.indexOf("app-256.png") > 0, markTag);
    await search("ubuntu", 24);

    const errs = await evaluate("window.__errs", page);
    check("no-window-errors", Array.isArray(errs) && errs.length === 0, (errs || []).join(" | "));

    return { checks };
    } catch (e) {
      if (!evaluate) {
        console.log("[diag] error:", String((e && e.message) || e));
        console.log("[diag] 浏览器桥接没建立起来（evaluate 未就绪），"
          + "上面的错误来自启动阶段，不是页面问题");
        throw e;
      }
      const errs = await evaluate("window.__errs", page).catch(() => ["eval-failed"]);
      const state = await evaluate("JSON.stringify({busy: HC.views.search.st.busy, rows: document.querySelectorAll('#rows .srow').length, skels: document.querySelectorAll('#rows .skel').length, chip: (document.getElementById('chip')||{}).textContent, hero: !!document.querySelector('.hero'), inp: (document.getElementById('inp')||{}).value, log: window.__log || []})", page).catch((x) => "state-failed " + x.message);
      console.log("[diag] error:", String((e && e.message) || e));
      console.log("[diag] errs:", (errs || []).join(" | ") || "(none)");
      console.log("[diag] state:", state);
      throw e;
    } finally {
    try { if (ws && ws.readyState === 1) ws.close(); } catch (e) {}
    killTree();
    await sleep(400);
  }
}

function id2(data) { return data.id; }

main().then((code) => process.exit(code)).catch((e) => {
  console.error("FATAL:", e && e.message ? e.message : e);
  process.exit(2);
});
