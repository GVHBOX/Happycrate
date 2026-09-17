const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const src = fs.readFileSync(path.join(ROOT, "web", "js", "views", "search.js"), "utf8");

function extract(name) {
  const i = src.indexOf("function " + name + "(");
  if (i < 0) throw new Error("not found: " + name);
  let depth = 0, started = false;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") { depth++; started = true; }
    else if (src[j] === "}") { depth--; if (started && depth === 0) return src.slice(i, j + 1); }
  }
  throw new Error("unbalanced: " + name);
}

const st = { qtokens: [], filesCache: {} };
const filesOf = (it) => (it.files && it.files.length) ? it.files : (st.filesCache[it.hash] || []);
const fileNames = (it) => filesOf(it).map((f) => (f.n || "").toLowerCase()).join("\n");
const fileReveals = eval("(" + extract("fileReveals") + ")");

function run(tokens, title, files) {
  st.qtokens = tokens;
  return fileReveals({ hash: "h", title, files: files.map((n) => ({ n })) });
}

const cases = [
  [["1080p"], "Movie 1080p WEB-DL", ["Movie.1080p.mkv"], false, "标题已含关键词"],
  [["中文字幕"], "Movie 2024", ["Movie.中文字幕.srt"], true, "只在文件里有"],
  [["1080p", "中文字幕"], "Movie 1080p", ["M.1080p.中文字幕.srt"], true, "多词之一只在文件里"],
  [["1080p"], "Movie 1080p", ["a.mkv"], false, "标题有文件无"],
  [["1080p"], "Movie WEB-DL", ["a.mkv"], false, "两边都无"],
  [["中文字幕"], "带中文字幕的片子", ["x.mkv"], false, "标题已有文件无"],
  [[], "Anything", ["a.mkv"], false, "无关键词"],
  [["1080p"], "Movie", [], false, "无文件清单"],
  [["NEW"], "Movie new release", ["Movie.NEW.mkv"], false, "大小写不同"],
  [["x265"], "Movie 1080p", ["M.1080p.x265.mkv"], true, "标题未写的编码"],
];

let bad = 0;
for (const [tokens, title, files, expect, desc] of cases) {
  const got = run(tokens, title, files);
  if (got !== expect) {
    bad++;
    console.log("FAIL " + desc + ": 得到 " + got + " 期望 " + expect);
  }
}
console.log(JSON.stringify({ total: cases.length, bad }));
process.exit(bad ? 1 : 0);
