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

const st = { items: [], filesCache: {}, parsed: null,
             field: "", desc: false, busy: false, settled: true, qtokens: [] };

const normText = eval("(" + extract("normText") + ")");
const bigramsOf = eval("(" + extract("bigramsOf") + ")");
const hasWordEdge = eval("(" + extract("hasWordEdge") + ")");
const formsHit = eval("(" + extract("formsHit") + ")");
const tokenHit = eval("(" + extract("tokenHit") + ")");
const neutralSeed = eval("(" + extract("neutralSeed") + ")");
const heatOf = eval("(" + extract("heatOf") + ")");
const relevance = eval("(" + extract("relevance") + ")");
const CJK_RE = /[\u3400-\u9fff\uf900-\ufaff]/;
const MOD_WEIGHT = { QUALITY: 0.35, CODEC: 0.25, YEAR: 0.15, SEASON: 0.45 };
const SOFT_WEIGHT = 0.2;
const visCache = { key: null, list: null };

const filesOf = (it) => (it.files && it.files.length) ? it.files : (st.filesCache[it.hash] || []);
const fileNames = (it) => filesOf(it).map((f) => (f.n || "").toLowerCase()).join("\n");
const matchText = eval("(" + extract("matchText") + ")");
const contentMiss = eval("(" + extract("contentMiss") + ")");
const computeVisible = eval("(" + extract("computeVisible") + ")");

function score(parsed, item) {
  st.parsed = parsed;
  st.items = [item];
  return relevance(item, neutralSeed());
}

function rank(parsed, items) {
  st.parsed = parsed;
  st.items = items;
  const neutral = neutralSeed();
  return items.map((it) => ({ t: it.title, r: relevance(it, neutral) }))
    .sort((a, b) => b.r - a.r).map((x) => x.t);
}

function visible(parsed, items, field, desc) {
  st.parsed = parsed;
  st.items = items;
  st.field = field || "";
  st.desc = !!desc;
  st.qtokens = parsed.tokens || [];
  st.busy = false;
  st.settled = true;
  visCache.key = null;
  return computeVisible().map((it) => it.title);
}

function miss(parsed, item) {
  st.parsed = parsed;
  st.qtokens = parsed.tokens || [];
  return contentMiss(item);
}

const cases = [];
function check(desc, got, expect) {
  cases.push([desc, got, expect]);
}

const q_4k_movie = {
  subject: [], browse: true,
  mods: [{ role: "QUALITY", forms: ["4k", "2160p", "uhd", "2160"] }],
  soft: [{ kind: "TYPE", forms: ["电影", "影片", "movie", "film"] }],
  season: null, year: null, bigrams: []
};
const q_4k = {
  subject: ["沙丘"], browse: false,
  mods: [{ role: "QUALITY", forms: ["4k", "2160p", "uhd", "2160"] }],
  soft: [], season: null, year: null, bigrams: ["沙丘"]
};
const q_season = {
  subject: ["进击的巨人"], browse: false, mods: [], soft: [], season: null,
  year: null, bigrams: []
};
const q_ep = {
  subject: ["进击的巨人"], browse: false,
  mods: [{ role: "SEASON", forms: ["第12集", "第12话", "第12話", "e12", "ep12"], s: 0, e: 12 }],
  soft: [], season: { s: 0, e: 12 }, year: null, bigrams: []
};

check("4K 查询：2160p 标题排在 1080p 之前",
  rank(q_4k_movie, [
    { title: "Dune 1080p WEB-DL", seeders: 500 },
    { title: "Dune 2160p BluRay", seeders: 500 },
  ])[0], "Dune 2160p BluRay");

check("浏览型查询：命中更多修饰词的排前",
  rank(q_4k_movie, [
    { title: "Some Random Thing", seeders: 10 },
    { title: "电影 2160p 影片", seeders: 10 },
  ])[0], "电影 2160p 影片");

check("主体词命中：完全命中的排前",
  rank(q_4k, [
    { title: "别的电影 4K", seeders: 10 },
    { title: "沙丘 4K", seeders: 10 },
  ])[0], "沙丘 4K");

check("中文主体词：完整写法高于插字写法",
  score({ subject: ["流浪地球"], browse: false, mods: [], soft: [], season: null, year: null },
    { title: "流浪地球 4K", seeders: 10 }) >
  score({ subject: ["流浪地球"], browse: false, mods: [], soft: [], season: null, year: null },
    { title: "流浪的地球 4K", seeders: 10 }), true);

check("未知做种不被沉底（用中性值）",
  score(q_4k, { title: "沙丘 4K", seeders: null }) >
  score(q_4k, { title: "完全不相关的东西", seeders: null }), true);

check("0 做种不因做种被沉底到底",
  score(q_4k, { title: "沙丘 4K", seeders: 0 }) >
  score(q_4k, { title: "沙丘 unrelated", seeders: 0 }), true);

check("季集命中加分",
  score(q_ep, { title: "进击的巨人 第12话", seeders: 10 }) >
  score(q_ep, { title: "进击的巨人 第13话", seeders: 10 }), true);

check("季集 word-edge：第12话 不误伤 第112话",
  hasWordEdge("第112话 x", "第12话"), false);

check("同源标题：做种多的排前",
  rank(q_4k, [
    { title: "沙丘 4K", seeders: 1 },
    { title: "沙丘 4K", seeders: 900 },
  ])[0], "沙丘 4K");

check("无解析结果时退化为热度",
  score(null, { title: "x", seeders: 900 }) > score(null, { title: "x", seeders: 1 }), true);

check("normText 全角转半角", normText("４Ｋ"), "4k");
check("normText 保留版本号", normText("Ubuntu 22.04"), "ubuntu 22.04");
check("bigramsOf", JSON.stringify(bigramsOf("流浪地球")), JSON.stringify(["流浪", "浪地", "地球"]));
check("tokenHit 完整命中", tokenHit("沙丘", "沙丘 4k", ""), 1);
check("tokenHit 顺序无关的部分命中",
  tokenHit("射击游戏", "第三人称射击游戏", "") > 0.5, true);

const q_movie = {
  text: "电影", tokens: ["电影"], subject: [],
  mods: [], soft: [{ kind: "TYPE", forms: ["电影", "影片", "movie", "film"] }]
};
const q_dune = {
  text: "沙丘 4k", tokens: ["沙丘", "4k"], subject: ["沙丘"],
  mods: [{ role: "QUALITY", forms: ["4k", "2160p", "uhd", "2160"] }], soft: []
};
const junk = [
  { title: "BurnAware Professional 12.1 FULL [TechTools]", seeders: 18145, size: 12e9 },
  { title: "Backrooms.2026.2160p.iT.WEB-DL.DDP5.1.Atmos", seeders: 9000, size: 9.8e9 },
];
const movieRows = [
  { title: "漫威电影合集 52部电影 BluRay 1080P", seeders: 12, size: 364e9 },
  { title: "[哆啦A梦 电影剧场版合集][2000-2018]", seeders: 3, size: 190e9 },
];

check("零命中行不因热度排到命中行前面",
  visible(q_movie, junk.concat(movieRows))[0], "漫威电影合集 52部电影 BluRay 1080P");
check("按体积降序：零命中行拿不到第一名",
  visible(q_movie, junk.concat(movieRows), "size", true)[0],
  "漫威电影合集 52部电影 BluRay 1080P");
check("按体积降序：命中行内部仍按体积排",
  visible(q_movie, movieRows, "size", true)[0],
  "漫威电影合集 52部电影 BluRay 1080P");
check("按体积升序：零命中行仍然沉底",
  visible(q_movie, junk.concat(movieRows), "size", false)[0],
  "[哆啦A梦 电影剧场版合集][2000-2018]");
check("零命中行整体沉底但保住各自的体积序",
  JSON.stringify(visible(q_movie, junk.concat(movieRows), "size", true)),
  JSON.stringify(["漫威电影合集 52部电影 BluRay 1080P",
                  "[哆啦A梦 电影剧场版合集][2000-2018]",
                  "BurnAware Professional 12.1 FULL [TechTools]",
                  "Backrooms.2026.2160p.iT.WEB-DL.DDP5.1.Atmos"]));

check("主体词命中行压过同体积的零命中行",
  visible(q_dune, [
    { title: "别的电影 2160p", seeders: 9999, size: 50e9 },
    { title: "沙丘 2160p", seeders: 1, size: 50e9 },
  ], "size", true)[0], "沙丘 2160p");
check("命中判定包含文件清单",
  miss(q_movie, Object.assign({}, movieRows[0],
    { title: "合集", files: [{ n: "漫威电影合集 01.mp4" }] })), 0);
check("收藏型查询：不含任一形式就算 miss",
  miss(q_movie, { title: "BurnAware Professional 12.1 FULL [TechTools]" }), 1);
check("收藏型查询：命中任一近义词就不算 miss",
  miss(q_movie, { title: "Scary Movie (2026) [1080p]" }), 0);
check("全部命中时 miss 为 0",
  miss(q_dune, { title: "沙丘 2160p" }), 0);
check("未解析出分组时退回原始词",
  (function(){
    st.parsed = null; st.qtokens = ["沙丘"];
    return contentMiss({ title: "沙丘 4k" });
  })(), 0);

st.items = [{ seeders: 1 }, { seeders: 5 }, { seeders: 900 }];
check("neutralSeed 取中位数", neutralSeed.call(null), 5);
st.items = [];

let bad = 0;
for (const [desc, got, expect] of cases) {
  if (got !== expect) {
    bad++;
    console.log("  [FAIL] " + desc + "  got=" + JSON.stringify(got) + " want=" + JSON.stringify(expect));
  } else {
    console.log("  [ok]   " + desc);
  }
}
console.log(JSON.stringify({ total: cases.length, bad }));
process.exit(bad ? 1 : 0);
