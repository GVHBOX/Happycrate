const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");

const START = "  var LOOK_DEFAULTS = {";
const END = "  HC.lookShade = shade;";
const i = html.indexOf(START);
const j = html.indexOf(END);
if (i < 0 || j < 0) {
  console.error("在 index.html 里找不到 LOOK 段落，锚点需要更新");
  process.exit(2);
}
const src = html.slice(i, j + END.length);

const written = {};
const removed = [];
const styleStub = {
  setProperty(k, v) { written[k] = String(v); },
  removeProperty(k) { delete written[k]; removed.push(k); },
  getPropertyValue() { return ""; }
};
const sandbox = {
  console,
  document: {
    documentElement: { style: styleStub },
    body: {
      setAttribute() {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } }
    }
  },
  HC: {}
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);

const HC = sandbox.HC;
const D = HC.LOOK_DEFAULTS;
const R = HC.LOOK_RANGE;
const readLook = HC.readLook;

let pass = 0;
const fails = [];
function check(name, ok, detail) {
  if (ok) { pass++; return; }
  fails.push(name + "  " + (detail === undefined ? "" : String(detail)));
}

function lum(hex) {
  const h = String(hex).replace("#", "");
  const v = [0, 2, 4].map(function (k) { return parseInt(h.substr(k, 2), 16) / 255; })
    .map(function (c) { return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); });
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}

check("空串回默认", JSON.stringify(readLook("")) === JSON.stringify(D), readLook(""));
check("undefined 回默认", JSON.stringify(readLook(undefined)) === JSON.stringify(D));
check("坏 JSON 回默认而不是抛错", JSON.stringify(readLook("{oops")) === JSON.stringify(D), readLook("{oops"));
check("顶层不是对象也回默认", JSON.stringify(readLook("[1,2]")) === JSON.stringify(D), readLook("[1,2]"));

const hi = readLook(JSON.stringify({ h: 999 }));
check("超出上限被夹取", hi.h === R.h[1], "h=" + hi.h + " 上限=" + R.h[1]);
const lo = readLook(JSON.stringify({ h: -5 }));
check("低于下限被夹取", lo.h === R.h[0], "h=" + lo.h + " 下限=" + R.h[0]);
const nan = readLook(JSON.stringify({ h: "abc" }));
check("非数字回默认值", nan.h === D.h, "h=" + nan.h);
const half = readLook(JSON.stringify({ radius: 9 }));
check("每项按自己的范围夹取", half.radius === R.radius[1] && half.h === D.h,
  "radius=" + half.radius + " h=" + half.h);

const colorOk = readLook(JSON.stringify({ on: "#8B7FE0", err: "#D4676E" }));
check("合法颜色原样保留", colorOk.on === "#8B7FE0" && colorOk.err === "#D4676E", colorOk.on + "/" + colorOk.err);
const colorBad = readLook(JSON.stringify({ on: "red", warn: "  " }));
check("颜色字符串在读取层不校验（按原样带回，供面板回显）",
  colorBad.on === "red" && colorBad.warn === "", colorBad.on + "/" + colorBad.warn);

written && Object.keys(written).forEach(function (k) { delete written[k]; });
removed.length = 0;
HC.applyProgressLook(JSON.stringify({ on: "red", err: "#D4676E" }));
check("非法颜色在落盘层被丢掉（不写变量、并清掉旧值）",
  written["--prog-on"] === undefined && removed.indexOf("--prog-on") >= 0,
  "written=" + written["--prog-on"] + " removed=" + removed.indexOf("--prog-on"));
check("同批里的合法颜色照常落地", written["--prog-err"] === "#D4676E", written["--prog-err"]);

Object.keys(written).forEach(function (k) { delete written[k]; });
HC.applyProgressLook(JSON.stringify({ h: 8, skew: 20, glow: 6, on: "#8B7FE0" }));
check("条高写进 CSS 变量", written["--prog-h"] === "8px", written["--prog-h"]);
check("斜切按反向系数写", written["--prog-skew"] === "-20deg", written["--prog-skew"]);
check("辉光写进 CSS 变量", written["--prog-glow"] === "6px", written["--prog-glow"]);
check("已返回色写进 CSS 变量", written["--prog-on"] === "#8B7FE0", written["--prog-on"]);
check("条纹色自动派生且比主色暗",
  /^#[0-9a-f]{6}$/.test(written["--prog-on-stripe"] || "") &&
  lum(written["--prog-on-stripe"]) < lum("#8B7FE0"), written["--prog-on-stripe"]);

Object.keys(written).forEach(function (k) { delete written[k]; });
HC.applyProgressLook("");
check("跟随主题时不写颜色变量", written["--prog-on"] === undefined && written["--prog-err"] === undefined,
  JSON.stringify(written));
check("形状变量仍按默认值落盘", written["--prog-h"] === D.h + "px" && written["--prog-skew"] === "-" + D.skew + "deg",
  written["--prog-h"] + "/" + written["--prog-skew"]);

check("曝光默认值与范围给设置页复用", !!HC.LOOK_DEFAULTS && !!HC.LOOK_RANGE && !!HC.readLook && !!HC.lookShade);

console.log("look_check: " + pass + " 项通过 · " + fails.length + " 项失败");
fails.forEach(function (f) { console.log("  FAIL " + f); });
console.log(fails.length ? "RESULT: FAIL" : "RESULT: PASS");
process.exit(fails.length ? 1 : 0);
