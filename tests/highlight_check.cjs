// 高亮正确性校验：把渲染结果还原成纯文本，必须与原文逐字符相同。
// 用于护栏——高亮若在「转义后的串」上匹配，查询含 a/s/p 等字母时
// 会插进 &amp; / &#39; 这类实体名中间。

const fs = require("fs");
const path = require("path");

const BS = String.fromCharCode(92);
const AMP = "&";
const LT = "<";
const GT = ">";
const QUOT = String.fromCharCode(34);
const APOS = String.fromCharCode(39);

const src = fs.readFileSync(
  path.join(__dirname, "..", "web", "js", "views", "search.js"), "utf8");
const start = src.indexOf("function hlTitle(");
if (start < 0) {
  console.log(JSON.stringify({ error: "找不到 hlTitle", total: 0, bad: 0 }));
  process.exit(1);
}
const lines = src.slice(start).split("\n");
const body = [];
let depth = 0;
for (const line of lines) {
  body.push(line);
  depth += (line.match(/{/g) || []).length - (line.match(/}/g) || []).length;
  if (body.length > 1 && depth === 0) break;
}
const hlBody = body.join("\n");
if (!hlBody.includes("mark")) {
  console.log(JSON.stringify({ error: "hlTitle 片段不完整", total: 0, bad: 0 }));
  process.exit(1);
}

const esc = (s) => String(s)
  .split(AMP).join("&amp;").split(LT).join("&lt;")
  .split(GT).join("&gt;").split(QUOT).join("&quot;").split(APOS).join("&#39;");

const reEscape = (t) => {
  const special = new Set([".", "*", "+", "?", "^", "$", "{", "}", "(", ")",
                           "|", "[", "]", BS]);
  return [...t].map((c) => (special.has(c) ? BS + c : c)).join("");
};

const factory = new Function("esc", "reEscape", "st", hlBody + "; return hlTitle;");

function makeHl(tokens) {
  const st = { hlRe: null };
  if (tokens.length) {
    const pattern = tokens.slice()
      .sort((a, b) => b.length - a.length)
      .map(reEscape).join("|");
    st.hlRe = new RegExp(pattern, "gi");
  }
  return factory(esc, reEscape, st);
}

// 模拟浏览器：HTML 是「先按标签切分，再对各段解实体」。
// 关键点：标签插进实体名中间（&<mark>a</mark>mp;）时，
// 浏览器看到的是三段独立文本，解实体后 & 与 amp; 各自留下，
// 于是页面上会多出 "amp;" 字样。若还原时按整串先解实体，
// 反而会把被拆坏的实体拼回去，掩盖缺陷。
function toPlainText(html) {
  return html
    .split(/<mark class="hl">|<\/mark>/)
    .map((seg) => seg
      .split("&amp;").join(AMP).split("&lt;").join(LT)
      .split("&gt;").join(GT).split("&quot;").join(QUOT)
      .split("&#39;").join(APOS))
    .join("");
}

// 另需检查：不能出现「实体被标签截断」的形状。
const SPLIT_ENTITY = /&(?:amp|lt|gt|quot|#39|)$|^(?:amp|lt|gt|quot|39);/;

function entitySplit(html) {
  const segs = html.split(/<mark class="hl">|<\/mark>/);
  for (let i = 1; i < segs.length; i += 1) {
    if (SPLIT_ENTITY.test(segs[i - 1]) || SPLIT_ENTITY.test(segs[i])) return true;
  }
  return false;
}

const titles = [
  "A" + AMP + "B 1080p",
  "Tom " + AMP + " Jerry " + "合集",
  APOS + "O" + APOS + "Brien " + LT + "HD" + GT,
  "AC/DC Live " + LT + "1979" + GT,
  "1" + AMP + "2" + AMP + "3",
  "normal title without entities 720p",
];

const queries = [
  ["a"], ["s"], ["p"], ["amp"], ["lt"], ["gt"], ["quot"], ["39"],
  [AMP], ["1080p"], ["o"], ["m"], ["3"], ["9"], ["AC"],
];

let total = 0;
const bad = [];
for (const title of titles) {
  for (const q of queries) {
    total++;
    const hl = makeHl(q);
    let out;
    try {
      out = hl(title);
    } catch (e) {
      bad.push({ title, q, why: "抛异常 " + e.message });
      continue;
    }
    const back = toPlainText(out);
    if (back !== title) {
      bad.push({ title, q, why: "文字被改坏", got: back, html: out });
    } else if (entitySplit(out)) {
      bad.push({ title, q, why: "实体被标记截断", html: out });
    }
  }
}

console.log(JSON.stringify({ total, bad: bad.length, cases: bad.slice(0, 3) }));
process.exit(bad.length ? 1 : 0);
