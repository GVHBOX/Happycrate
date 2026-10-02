(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var SORTS = {size:"体积", added:"时间", seeders:"做种"};
  var PROG_TAIL_MS = 560;
  HC.PROG_TAIL_MS = PROG_TAIL_MS;

  var ICONS = {
    search: '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none">' +
      '<circle cx="6" cy="6" r="4.6" stroke="currentColor" stroke-width="1.4"/>' +
      '<path d="M9.6 9.6L12.6 12.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    gear: '<svg width="15" height="15" viewBox="-1 -1 16 16" fill="none">' +
      '<path d="M8.37 12.94L5.63 12.94L5.44 11.06A4.35 4.35 0 0 1 4.26 10.38L2.54 11.16L1.17 8.78L2.7 7.68A4.35 4.35 0 0 1 2.7 6.32L1.17 5.22L2.54 2.84L4.26 3.62A4.35 4.35 0 0 1 5.44 2.94L5.63 1.06L8.37 1.06L8.56 2.94A4.35 4.35 0 0 1 9.74 3.62L11.46 2.84L12.83 5.22L11.3 6.32A4.35 4.35 0 0 1 11.3 7.68L12.83 8.78L11.46 11.16L9.74 10.38A4.35 4.35 0 0 1 8.56 11.06Z" ' +
      'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
      '<circle cx="7" cy="7" r="1.9" stroke="currentColor" stroke-width="1.3"/></svg>',
    check: '<svg width="10" height="10" viewBox="-1 -1 16 16" fill="none">' +
      '<path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    copy: '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none">' +
      '<rect x="4.6" y="4.6" width="7" height="7" rx="1.4" stroke="currentColor" stroke-width="1.3"/>' +
      '<path d="M9.4 2.6H3.4A1.4 1.4 0 0 0 2 4v6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    dl: '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none">' +
      '<path d="M7 2.4v6.4M4.4 6.4L7 9l2.6-2.6" stroke="currentColor" stroke-width="1.3" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="M2.6 11.4h8.8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    arw: '<svg class="arw" width="9" height="9" viewBox="-3 -3 16 16" fill="none">' +
      '<path d="M5 8V2M2.4 4.6L5 2l2.6 2.6" stroke="currentColor" stroke-width="1.4" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    srclist: '<svg width="15" height="15" viewBox="0 0 16 16" fill="none">' +
      '<path d="M4.6 4.4h9M4.6 8h9M4.6 11.6h9" stroke="currentColor" stroke-width="1.4" ' +
      'stroke-linecap="round"/><circle cx="2.3" cy="4.4" r="1" fill="currentColor"/>' +
      '<circle cx="2.3" cy="8" r="1" fill="currentColor"/>' +
      '<circle cx="2.3" cy="11.6" r="1" fill="currentColor"/></svg>'
  };

  var autoFiles = true;

  var st = {
    items: [], sel: {}, anchor: "",
    rev: 0,
    pendingBumped: {}, pendingFresh: 0, pendingArrived: [],
    field: "", desc: false,
    busy: false, settled: false, searched: false, hero: true,
    token: 0, done: 0, total: 0, startSeq: 0,
    errors: {}, names: {},
    rawTotal: 0, dupCount: 0, dupKept: false,
    enabledCount: 0, totalSources: 0,
    netState: null, speed: 0, failed: 0,
    lines: [],
    srcList: [], strip: {}, cursor: -1,
    query: "", qtokens: [], qphrase: "", hlRe: null, parsed: null,
    open: {}, userShut: {},
    filesCache: {}, filesLoading: {}, filesErr: {}, autoBudget: 0, autoTried: {},
    selbarOn: false, progStyle: "segment", progLineOn: true,
    filterSource: "",
    segOrder: [], t0: 0, deadline: 3000,
    renderedCount: 0
  };

  var CHUNK_SIZE = 100;

  var GO_BTN_INNER = '<span class="gico">' + ICONS.search + '</span>' +
    '<span class="gtx">搜索</span>';
  var CHEV = '<svg class="chev" viewBox="0 0 16 16" fill="none"><path d="M6.2 4l4 4-4 4" ' +
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var root, rowsEl, tipEl, ckAllEl, inp, goBtn, headEl, progEl, stripEl, selbarEl;
  var crewRes, rsCount, rsSrcs, rsRailBox, rsRail, drwWrap, drw, dwName, dwVal;
  var crewNet, ntExit, ntSpeed;
  var dlRaf = 0;
  var speedTimer = 0;
  var railT1 = null;
  var railT2 = null;
  var marquee = null;
  var justMarqueed = false;
  var nohashSeq = 0;
  var selSig = "";
  var hashIdx = {};

  var esc = HC.esc;

  function fmtCount(n){
    if (n === null || n === undefined) return "—";
    n = Number(n) || 0;
    if (n < 1000) return String(n);
    if (n < 1000000) return (n / 1000).toFixed(1).replace(".0", "") + "k";
    return (n / 1000000).toFixed(1).replace(".0", "") + "M";
  }

  function tier(n){
    if (n === null || n === undefined) return "na";
    n = Number(n) || 0;
    return n >= 1000 ? "hi" : (n >= 100 ? "mid" : "lo");
  }

  function pad(i){
    return (i + 1 < 10 ? "0" : "") + (i + 1);
  }

  function normText(s){
    return String(s || "").normalize("NFKC").toLowerCase()
      .replace(/[_+,/|]+/g, " ").replace(/\s+/g, " ").trim();
  }

  function bigramsOf(s){
    var t = String(s || "").replace(/\s+/g, "");
    if (t.length < 2) return t ? [t] : [];
    var out = [], i, g;
    for (i = 0; i < t.length - 1; i++){
      g = t.substr(i, 2);
      if (out.indexOf(g) < 0) out.push(g);
    }
    return out;
  }

  var CJK_RE = /[\u3400-\u9fff\uf900-\ufaff]/;

  function hasWordEdge(text, word){
    var i = text.indexOf(word);
    if (i < 0) return false;
    var before = i > 0 ? text.charAt(i - 1) : " ";
    var after = text.charAt(i + word.length) || " ";
    return !/[a-z0-9]/.test(before) && !/[a-z0-9]/.test(after);
  }

  function formsHit(forms, title, files){
    for (var i = 0; i < forms.length; i++){
      var f = forms[i];
      if (!f) continue;
      if (hasWordEdge(title, f)) return true;
      if (files && files.indexOf(f) >= 0) return true;
    }
    return false;
  }

  function tokenHit(tk, title, files){
    if (!tk) return 0;
    if (title.indexOf(tk) >= 0) return 1;
    if (files && files.indexOf(tk) >= 0) return 0.8;
    if (!CJK_RE.test(tk)) return 0;
    var grams = bigramsOf(tk);
    if (!grams.length) return 0;
    var hit = 0;
    for (var i = 0; i < grams.length; i++){
      if (title.indexOf(grams[i]) >= 0) hit++;
      else if (files && files.indexOf(grams[i]) >= 0) hit += 0.5;
    }
    return hit / grams.length;
  }

  function neutralSeed(){
    var nums = [], i, s;
    for (i = 0; i < st.items.length; i++){
      s = st.items[i].seeders;
      if (typeof s === "number") nums.push(s);
    }
    if (!nums.length) return 0;
    nums.sort(function(a, b){ return a - b; });
    return nums[Math.floor(nums.length / 2)];
  }

  function heatOf(it, neutral){
    var s = typeof it.seeders === "number" ? it.seeders : neutral;
    var l = typeof it.leechers === "number" ? it.leechers : 0;
    return Math.min(Math.log(s + 1) * 6, 40) + Math.min(Math.log(l + 1) * 2, 10);
  }

  var MOD_WEIGHT = {QUALITY: 0.35, CODEC: 0.25, YEAR: 0.15, SEASON: 0.45};
  var SOFT_WEIGHT = 0.2;

  function relevance(it, neutral){
    var title = normText(it.title);
    var files = normText(fileNames(it));
    var heat = heatOf(it, neutral);
    var p = st.parsed;

    if (!p) return heat;

    var rel = 0, i, sum;

    if (p.subject.length){
      sum = 0;
      for (i = 0; i < p.subject.length; i++){
        sum += tokenHit(p.subject[i], title, files);
      }
      rel += sum / p.subject.length;
    }

    for (i = 0; i < p.mods.length; i++){
      var mod = p.mods[i];
      if (formsHit(mod.forms || [], title, files)){
        rel += MOD_WEIGHT[mod.role] || 0.25;
      }
    }

    for (i = 0; i < p.soft.length; i++){
      if (formsHit(p.soft[i].forms || [], title, files)) rel += SOFT_WEIGHT;
    }

    var relMax = 1 + (p.mods.length ? 1.2 : 0) + p.soft.length * SOFT_WEIGHT;
    var relPart = relMax ? rel / relMax : 0;

    return !p.subject.length ? 50 * relPart + 50 * (heat / 50)
                             : 70 * relPart + 30 * (heat / 50);
  }

  function matchText(it){
    return normText(it.title) + "\n" + normText(fileNames(it));
  }

  function contentMiss(it){
    var p = st.parsed;
    var text = matchText(it);
    var groups = 0, miss = 0, i;
    if (p){
      for (i = 0; i < p.subject.length; i++){
        groups++;
        if (tokenHit(p.subject[i], text, "") < 0.5) miss++;
      }
      for (i = 0; i < p.soft.length; i++){
        groups++;
        if (!formsHit(p.soft[i].forms || [], text, "")) miss++;
      }
    }
    if (!groups){
      for (i = 0; i < st.qtokens.length; i++){
        groups++;
        if (text.indexOf(normText(st.qtokens[i])) < 0) miss++;
      }
    }
    return groups ? miss : 0;
  }

  var visCache = { key: null, list: null };

  function computeVisible(){
    var baseItems = st.items;
    if (st.filterSource){
      baseItems = baseItems.filter(function(it){
        return it.sources && it.sources.indexOf(st.filterSource) >= 0;
      });
    }
    if (!st.field){
      if ((st.busy && !st.settled) || !st.qtokens.length) return baseItems;
      var neutral = neutralSeed();
      var scored = baseItems.map(function(it){
        return { it: it, m: contentMiss(it), r: relevance(it, neutral) };
      });
      scored.sort(function(a, b){
        return a.m !== b.m ? a.m - b.m : b.r - a.r;
      });
      return scored.map(function(s){ return s.it; });
    }
    var neutral = neutralSeed();
    var rows = baseItems.map(function(it){
      return { it: it, m: contentMiss(it) };
    });
    rows.sort(function(a, b){
      if (a.m !== b.m) return a.m - b.m;
      var x = typeof a.it[st.field] === "number" ? a.it[st.field] : neutral;
      var y = typeof b.it[st.field] === "number" ? b.it[st.field] : neutral;
      return st.desc ? y - x : x - y;
    });
    return rows.map(function(r){ return r.it; });
  }

  function visible(){
    if (marquee && marquee.active && marquee.visList) return marquee.visList;
    var key = st.rev + "|" + st.field + "|" + (st.desc ? 1 : 0) +
      "|" + (st.busy ? 1 : 0) + (st.settled ? 1 : 0) + "|" + st.qphrase +
      "|" + (st.filterSource || "");
    if (visCache.key !== key){
      visCache.key = key;
      visCache.list = computeVisible();
    }
    return visCache.list;
  }

  function fileNames(it){
    return (filesOf(it) || []).map(function(f){ return (f.n || "").toLowerCase(); }).join("\n");
  }

  function filesOf(it){
    if (it.files && it.files.length) return it.files;
    return st.filesCache[it.hash] || [];
  }

  function fileReveals(it){
    if (!st.qtokens.length) return false;
    var files = filesOf(it);
    if (!files.length) return false;
    var fns = fileNames(it);
    var title = (it.title || "").toLowerCase();
    for (var i = 0; i < st.qtokens.length; i++){
      var tk = st.qtokens[i];
      if (fns.indexOf(tk) >= 0 && title.indexOf(tk) < 0) return true;
    }
    return false;
  }

  function selList(){
    return visible().filter(function(it){ return st.sel[it.hash]; });
  }

  function selCount(){
    var n = 0;
    for (var h in st.sel) if (st.sel[h]) n++;
    return n;
  }

  function badgeHtml(){
    var n = selCount(), total = st.items.length;
    var merged = st.rawTotal && st.dupCount
      ? '（<b>' + st.rawTotal + '</b> 条合并 <b>' + st.dupCount + '</b>）'
      : (st.dupKept ? "（重复已保留）" : "");
    var lax = st.relaxed ? " · 已放宽：去掉 " + esc(st.relaxed) : "";
    return n ? '已选中 <b>' + n + '</b> 条 / 共 ' + total + ' 条' + merged + lax
             : '共 ' + total + ' 条' + merged + lax;
  }

  var popT = null;

  function paintBadge(still){
    var t = badgeHtml();
    if (rsCount.innerHTML === t) return;
    rsCount.innerHTML = t;
    if (still) return;
    rsCount.classList.remove("pop");
    void rsCount.offsetWidth;
    rsCount.classList.add("pop");
    clearTimeout(popT);
    popT = setTimeout(function(){ rsCount.classList.remove("pop"); }, 300);
  }

  function flash(text, kind){
    HC.motion.toast(text, kind);
  }

  function rateText(bps){
    var k = bps / 1024;
    if (k < 1) return "↓0";
    if (k < 1024) return "↓" + Math.round(k) + "K";
    return "↓" + (k / 1024).toFixed(2) + "M";
  }

  function paintSrcWarn(){
    if (crewNet.classList.contains("err")){
      crewRes.classList.remove("warn");
      return;
    }
    crewRes.classList.toggle("warn",
      st.failed > 0 || (st.searched && !st.busy && !st.items.length));
  }

  function paintSrcs(){
    var done = st.busy || st.searched ? st.done : st.enabledCount;
    rsSrcs.innerHTML = esc(done + "/" + st.totalSources + " 源") + CHEV;
    if (st.busy && st.totalSources){
      rsRailBox.classList.add("on");
      rsRail.style.width = Math.min(100, done / st.totalSources * 100) + "%";
    }
    paintSrcWarn();
  }

  function resetRail(){
    clearTimeout(railT1);
    clearTimeout(railT2);
    rsRailBox.classList.remove("on");
    rsRail.style.transition = "none";
    rsRail.style.width = "0%";
    void rsRail.offsetWidth;
    rsRail.style.transition = "";
  }

  function finishRail(){
    rsRail.style.width = "100%";
    clearTimeout(railT1);
    clearTimeout(railT2);
    railT1 = setTimeout(function(){
      rsRailBox.classList.remove("on");
      railT2 = setTimeout(resetRail, 300);
    }, 700);
  }

  function drawerShow(name, value, bad){
    dwName.textContent = name;
    dwVal.textContent = value;
    drw.classList.toggle("bad", !!bad);
    drwWrap.classList.add("on");
  }

  function drawerHide(){
    drwWrap.classList.remove("on");
    drw.classList.remove("bad");
  }

  function paintNetCrew(){
    var ns = st.netState || (HC.netState ? HC.netState(null) : null);
    var dot = ns ? ns.dot : "busy";
    var label = dot === "ok" ? (ns.title || "网络")
      : dot === "busy" ? "检测中" : (ns.note || "网络不可用");
    crewNet.className = "crew net " + dot + (st.speed >= 1024 ? " live" : "");
    ntExit.innerHTML = '<span class="ndot"></span><span class="tx">' +
      esc(label) + '</span>' + CHEV;
    crewNet.title = ns ? [ns.title, ns.addr, ns.note].filter(Boolean).join(" · ") : "";
    ntSpeed.hidden = dot === "busy";
    ntSpeed.textContent = rateText(st.speed);
    paintSrcWarn();
  }

  function refreshSources(){
    HC.api.listSources().then(function(list){
      st.names = {};
      st.enabledCount = 0;
      (list || []).forEach(function(s){
        st.names[s.key] = s.label;
        if (s.enabled) st.enabledCount++;
      });
      st.totalSources = (list || []).length;
      st.srcList = (list || []).filter(function(s){ return s.enabled; })
        .map(function(s){ return {key:s.key, label:s.label}; });
      var srcs = root ? root.querySelector("#heroSrcs") : null;
      if (srcs){
        srcs.innerHTML = (list || []).map(function(s){
          var hst = HC.stateOf(s);
          var dot = (hst === "err" || hst === "warn" || hst === "empty") ? " " + hst : "";
          return '<button class="srcdot' + dot +
            (s.enabled ? "" : " off") + '" data-key="' + esc(s.key) + '">' +
            '<span class="sdot"></span>' + esc(s.label) + '</button>';
        }).join("");
      }
      paintSrcs();
      if (st.searched || st.busy){
        renderRows();
        updateSelUI(true);
        paintStrip();
        paintBadge(true);
        paintCursor();
        if (st.busy){
          goBtn.textContent = "停止";
          goBtn.classList.add("stop");
          progEl.classList.add("on");
          paintSrcs();
        }
      }
    }).catch(function(err){ console.warn("listSources failed", err); });
  }

  function tickSpeed(){
    if (!crewNet) return;
    if (!root || !root.isConnected){
      clearInterval(speedTimer);
      speedTimer = 0;
      return;
    }
    if (document.hidden || typeof HC.api.netThroughput !== "function") return;
    HC.api.netThroughput().then(function(d){
      st.speed = (d && d.down) || 0;
      paintNetCrew();
    }).catch(function(){});
  }

  function checkNetwork(force){
    if (typeof HC.api.proxyStatus !== "function"){
      if (crewNet) crewNet.hidden = true;
      return;
    }
    HC.api.proxyStatus(force).then(function(d){
      if (HC.setNetStatus) HC.setNetStatus(d);
      st.netState = HC.netState ? HC.netState(d) : null;
      if (crewNet) crewNet.hidden = false;
      paintNetCrew();
    }).catch(function(){
      st.netState = null;
      if (crewNet) crewNet.hidden = true;
    });
  }

  function renderTip(){
    if (!st.lines.length){
      tipEl.classList.remove("show");
      return;
    }
    tipEl.innerHTML = st.lines.map(function(l){
      return '<div' + (l.bad ? ' class="bad"' : '') + '>' + esc(l.text) + '</div>';
    }).join("");
  }

  function reEscape(t){
    return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function hlTitle(raw){
    var text = String(raw === undefined || raw === null ? "" : raw);
    var re = st.hlRe;
    if (!re) return esc(text);
    re.lastIndex = 0;
    var out = "", last = 0, m;
    while ((m = re.exec(text)) !== null){
      if (!m[0].length){ re.lastIndex += 1; continue; }
      out += esc(text.slice(last, m.index)) +
        '<mark class="hl">' + esc(m[0]) + '</mark>';
      last = m.index + m[0].length;
    }
    return last ? out + esc(text.slice(last)) : esc(text);
  }

  var FCHEV = '<svg width="10" height="10" viewBox="-3 -3 16 16"><path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function itemByHash(h){
    var i = hashIdx[h];
    return i === undefined ? null : st.items[i];
  }

  function indexOfHash(h){
    var i = hashIdx[h];
    return i === undefined ? -1 : i;
  }

  function fileSizeBytes(str){
    if (!str) return 0;
    var m = /^([0-9.]+)\s*([A-Za-z]+)?$/.exec(String(str).trim());
    if (!m) return 0;
    var n = parseFloat(m[1]) || 0;
    var u = (m[2] || "").toUpperCase();
    if (u === "GB" || u === "GIB") return n * 1073741824;
    if (u === "MB" || u === "MIB") return n * 1048576;
    if (u === "KB" || u === "KIB") return n * 1024;
    if (u === "TB" || u === "TIB") return n * 1099511627776;
    return n;
  }

  function fpanelInner(it){
    var files = (it.files && it.files.length) ? it.files : st.filesCache[it.hash];
    if (files && files.length){
      var smart = localStorage.getItem("hc_smart_files") === "1";
      var maxIdx = -1;
      if (smart && files.length > 1){
        var maxBytes = -1;
        files.forEach(function(f, idx){
          var name = (f.n || "").toLowerCase();
          var isVid = /\.(mp4|mkv|avi|mov|wmv|iso|ts)$/i.test(name);
          var bytes = fileSizeBytes(f.s);
          if (isVid && bytes > maxBytes){
            maxBytes = bytes;
            maxIdx = idx;
          }
        });
      }
      return files.map(function(f, idx){
        var isMain = idx === maxIdx;
        var tag = isMain ? '<span class="fmain-tag">主视频</span>' : '';
        return '<div class="fline' + (isMain ? " main" : "") + '"><span class="fname">' + hlTitle(f.n) + tag +
          '</span><span class="fsize">' + esc(f.s || "") + '</span></div>';
      }).join("");
    }
    if (st.filesLoading[it.hash]) return '<div class="fline muted">加载中…</div>';
    if (st.filesErr[it.hash]) return '<div class="fline muted">' + esc(st.filesErr[it.hash]) + '</div>';
    return "";
  }

  function loadFiles(h, cb, quiet){
    if (st.filesCache[h] || st.filesLoading[h] || st.filesErr[h]){ if (cb) cb(); return; }
    var it = itemByHash(h);
    if (!it || !it.fetch || !it.fetch.url){ if (cb) cb(); return; }
    st.filesLoading[h] = true;
    if (st.open[h]) renderPanels();
    HC.api.torrentFiles({url: it.fetch.url}).then(function(res){
      delete st.filesLoading[h];
      if (res && res.ok && res.files && res.files.length){
        st.filesCache[h] = res.files;
      }
      else if (!quiet) st.filesErr[h] = (res && res.error) || "获取文件清单失败";
      if (st.open[h]) renderPanels();
      if (cb) cb();
    }, function(){
      delete st.filesLoading[h];
      if (!quiet) st.filesErr[h] = "获取文件清单失败";
      if (st.open[h]) renderPanels();
      if (cb) cb();
    });
  }

  var fetchQ = [], fetchActive = 0;

  function pumpFetch(){
    if (fetchActive >= 3 || !fetchQ.length) return;
    var job = fetchQ.shift();
    if (st.filesCache[job.h] || st.filesLoading[job.h] || st.filesErr[job.h]){
      pumpFetch();
      return;
    }
    fetchActive++;
    loadFiles(job.h, function(){
      if (job.cb) job.cb();
      setTimeout(function(){
        fetchActive--;
        pumpFetch();
      }, 400);
    }, true);
  }

  function queueLoad(h, cb, urgent){
    var job = {h: h, cb: cb || null};
    if (urgent) fetchQ.unshift(job);
    else fetchQ.push(job);
    pumpFetch();
  }

  var AUTO_EARLY = 6, AUTO_TOTAL = 18;

  function titleMiss(it){
    var title = (it.title || "").toLowerCase();
    var miss = 0;
    for (var i = 0; i < st.qtokens.length; i++){
      if (title.indexOf(st.qtokens[i]) < 0) miss++;
    }
    return miss;
  }

  function autoExpand(total, urgent, only){
    if (!st.qtokens.length) return;
    if (!autoFiles) return;
    var pending = [];
    (only && only.length ? only : visible()).forEach(function(it){
      var h = it.hash;
      if (st.userShut[h]) return;
      if (!titleMiss(it)) return;
      if (filesOf(it).length){
        if (fileReveals(it)) st.open[h] = true;
        return;
      }
      if (!it.fetch || !it.fetch.url) return;
      if (st.filesLoading[h] || st.filesErr[h] || st.autoTried[h]) return;
      pending.push(it);
    });
    pending.sort(function(a, b){ return titleMiss(b) - titleMiss(a); });
    for (var i = 0; i < pending.length && st.autoBudget < total; i++){
      (function(it){
        var h = it.hash;
        st.autoBudget++;
        st.autoTried[h] = true;
        queueLoad(h, function(){
          if (st.userShut[h] || st.open[h]) return;
          var cur = itemByHash(h);
          if (cur && fileReveals(cur)){
            st.open[h] = true;
            renderPanels();
          }
        }, urgent);
      })(pending[i]);
    }
    renderPanels();
  }

  function renderPanels(){
    if (!rowsEl || !rowsEl.isConnected) return;
    var openKeys = Object.keys(st.open);
    if (!openKeys.length){
      [].slice.call(rowsEl.querySelectorAll(".fpanel")).forEach(function(p){ p.remove(); });
      [].slice.call(rowsEl.querySelectorAll(".srow.open")).forEach(function(row){
        row.classList.remove("open");
        var chev = row.querySelector(".fchev.on");
        if (chev) chev.classList.remove("on");
      });
      return;
    }
    var keep = {};
    openKeys.forEach(function(h){
      var safeH = window.CSS && CSS.escape ? CSS.escape(h) : h;
      var row = rowsEl.querySelector('.srow[data-hash="' + safeH + '"]');
      var it = itemByHash(h);
      var lazy = it && it.fetch && it.fetch.url;
      var has = it && ((it.files && it.files.length) || lazy);
      if (!row || !it || !has){
        delete st.open[h];
        return;
      }
      keep[h] = true;
      var next = row.nextElementSibling;
      var p = next && next.classList.contains("fpanel") &&
        next.dataset.hash === h ? next : null;
      var html = fpanelInner(it);
      if (!p){
        p = document.createElement("div");
        p.className = "fpanel";
        p.dataset.hash = h;
        p.innerHTML = html;
        row.parentNode.insertBefore(p, row.nextSibling);
      } else if (p.innerHTML !== html){
        p.innerHTML = html;
      }
      row.classList.add("open");
      var chev = row.querySelector(".fchev");
      if (chev) chev.classList.add("on");
      loadFiles(h, null);
    });
    [].slice.call(rowsEl.querySelectorAll(".fpanel")).forEach(function(p){
      if (!keep[p.dataset.hash]) p.remove();
    });
    [].slice.call(rowsEl.querySelectorAll(".srow.open")).forEach(function(row){
      if (keep[row.dataset.hash]) return;
      row.classList.remove("open");
      var chev = row.querySelector(".fchev.on");
      if (chev) chev.classList.remove("on");
    });
  }

  function rowHtml(it, i, animate){
    var cls = "srow" + (i % 2 ? " alt" : "") + (st.sel[it.hash] ? " sel" : "") + (i === st.cursor ? " cursor" : "");
    var anim = animate
      ? ' style="animation:rowIn .3s var(--land) both ' + Math.min(i, 10) * 28 + 'ms"'
      : "";
    var src = (it.sources || []).map(function(k){
      return st.names[k] || k;
    }).join(" · ");
    var title = hlTitle(it.title);
    var chev = (it.files && it.files.length) || it.fetch
      ? '<button class="fchev" tabindex="-1" data-hash="' + esc(it.hash) + '" title="文件">' + FCHEV + '</button>'
      : "";
    return '<div class="' + cls + '" id="hc-row-' + i + '" data-hash="' + esc(it.hash) + '"' + anim +
      ' role="row" aria-selected="' + (st.sel[it.hash] ? "true" : "false") + '">' +
      '<span class="c-idx" role="gridcell">' + pad(i) + '</span>' +
      '<span class="c-size" role="gridcell">' + esc(it.sizeText) + '</span>' +
      '<span class="c-time" role="gridcell">' + esc(it.addedText) + '</span>' +
      '<span class="c-seed ' + tier(it.seeders) + '" role="gridcell">' + fmtCount(it.seeders) + '</span>' +
      '<span class="c-title" role="gridcell" title="' + esc(it.title) + '">' + title + chev + '</span>' +
      '<span class="c-src" role="gridcell" title="' + esc(src) + '">' + esc(src) + '</span></div>';
  }

  function skelHtml(){
    var left = st.srcList.length - (st.done || 0);
    var n = left > 0 ? Math.max(3, Math.min(8, left)) : 6;
    var sk = '<div class="skel" role="presentation"><div class="col"><i></i><i></i></div></div>';
    var out = "";
    for (var i = 0; i < n; i++) out += sk;
    return out;
  }

  var EMPTY_IC = '<svg viewBox="0 0 34 34" fill="none">' +
    '<circle cx="15" cy="15" r="9" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M22 22l6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>' +
    '<path d="M11 15h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  function renderRows(){
    var list = visible();
    if (!list.length){
      st.renderedCount = 0;
      if (st.busy && !st.settled){
        rowsEl.innerHTML = skelHtml();
      } else {
        rowsEl.innerHTML = '<div class="empty" role="presentation">' + EMPTY_IC +
          (st.searched ? "没有搜到相关结果" : "输入关键词开始搜索") +
          '</div>';
      }
      return;
    }
    st.renderedCount = Math.min(list.length, CHUNK_SIZE);
    var renderList = list.slice(0, st.renderedCount);
    rowsEl.innerHTML = renderList.map(function(it, i){
      return rowHtml(it, i, false);
    }).join("") + (st.busy && !st.settled ? skelHtml() : "");
    paintCursor();
    renderPanels();
  }

  function appendRows(count){
    rowsEl.querySelectorAll(".empty, .skel").forEach(function(n){ n.remove(); });
    var list = visible();
    if (st.renderedCount >= CHUNK_SIZE && list.length > CHUNK_SIZE){
      if (st.busy && !st.settled){
        var tmp = document.createElement("div");
        tmp.innerHTML = skelHtml();
        while (tmp.firstChild) rowsEl.appendChild(tmp.firstChild);
      }
      return;
    }
    var oldRendered = st.renderedCount || 0;
    var nextRendered = Math.min(list.length, CHUNK_SIZE);
    if (nextRendered <= oldRendered) return;
    st.renderedCount = nextRendered;
    var anim = (nextRendered - oldRendered) <= 40;
    var frag = document.createElement("div");
    frag.innerHTML = list.slice(oldRendered, nextRendered).map(function(it, i){
      return rowHtml(it, oldRendered + i, anim);
    }).join("");
    if (st.busy && !st.settled){
      var tmp = document.createElement("div");
      tmp.innerHTML = skelHtml();
      while (tmp.firstChild) frag.appendChild(tmp.firstChild);
    }
    while (frag.firstChild) rowsEl.appendChild(frag.firstChild);
    paintCursor();
  }

  function checkMoreRows(){
    if (!rowsEl || !rowsEl.isConnected) return;
    var list = visible();
    if (st.renderedCount >= list.length) return;
    var distance = rowsEl.scrollHeight - (rowsEl.scrollTop + rowsEl.clientHeight);
    if (distance < 400){
      var from = st.renderedCount;
      var to = Math.min(list.length, from + CHUNK_SIZE);
      st.renderedCount = to;
      var box = document.createElement("div");
      box.innerHTML = list.slice(from, to).map(function(it, i){
        return rowHtml(it, from + i, false);
      }).join("");
      while (box.firstChild) rowsEl.appendChild(box.firstChild);
      rowsEl.setAttribute("aria-rowcount", String(to));
      renderPanels();
    }
  }

  function renumber(){
    [].slice.call(rowsEl.querySelectorAll(".srow")).forEach(function(row, i){
      row.classList.toggle("alt", i % 2 === 1);
      var idx = row.querySelector(".c-idx");
      if (idx) idx.textContent = pad(i);
    });
  }

  function refreshRows(bumped){
    if (!rowsEl || !rowsEl.isConnected) return;
    var list = visible();
    var posOf = {};
    list.forEach(function(it, i){ posOf[it.hash] = i; });
    [].slice.call(rowsEl.querySelectorAll(".srow")).forEach(function(row){
      var pos = posOf[row.dataset.hash];
      if (!bumped[row.dataset.hash] || pos === undefined || !row.parentNode) return;
      var box = document.createElement("div");
      box.innerHTML = rowHtml(list[pos], pos, false);
      var made = box.firstChild;
      if (made) row.parentNode.replaceChild(made, row);
    });
    renumber();
    updateSelUI();
    renderPanels();
    paintCursor();
  }

  function syncSelbar(still){
    var list = visible();
    var n = selCount();
    var all = n > 0 && n === list.length;
    ckAllEl.classList.toggle("on", all);
    ckAllEl.innerHTML = all ? ICONS.check : "";
    paintBadge(still);
    if (selbarEl){
      selbarEl.querySelector("#selN").textContent = n;
      selbarEl.classList.toggle("show", st.selbarOn && n > 0);
      selbarEl.classList.toggle("island", localStorage.getItem("hc_action_island") === "1");
    }
  }

  function updateSelUI(still){
    var sig = Object.keys(st.sel).sort().join(",");
    [].slice.call(rowsEl.querySelectorAll(".srow")).forEach(function(row){
      var on = !!st.sel[row.dataset.hash];
      row.classList.toggle("sel", on);
      row.setAttribute("aria-selected", on ? "true" : "false");
    });
    syncSelbar(still);
    if (sig !== selSig){
      selSig = sig;
      HC.sfx.play("select");
    }
  }

  function paintCursor(){
    if (!rowsEl) return;
    var prev = rowsEl.querySelector(".srow.cursor");
    var cur = st.cursor >= 0 ? document.getElementById("hc-row-" + st.cursor) : null;
    if (prev === cur){
      if (cur) rowsEl.setAttribute("aria-activedescendant", cur.id);
      return;
    }
    if (prev) prev.classList.remove("cursor");
    if (cur){
      cur.classList.add("cursor");
      rowsEl.setAttribute("aria-activedescendant", cur.id);
      cur.scrollIntoView({block:"nearest"});
    } else {
      rowsEl.removeAttribute("aria-activedescendant");
    }
  }

  function stripLabel(ss){
    if (ss.state === "ok") return "<b>" + esc(ss.count) + "</b> 条" +
      (ss.fuzzy ? " · 未使用关键词" : "") +
      (ss.cached ? " · 缓存" : "");
    if (ss.state === "empty") return "无结果";
    if (ss.state === "err") return esc(ss.err || "失败");
    if (ss.state === "warn"){
      if (!ss.count) return esc(ss.err || "提示");
      return "<b>" + esc(ss.count) + "</b> 条" + (ss.err ? " · " + esc(ss.err) : "");
    }
    if (ss.state === "cancel") return "已取消";
    return ss.startedAt ? "进行中" : "排队";
  }

  function secs(ms){
    if (!ms || ms < 0) return "";
    return (ms / 1000).toFixed(1) + "s";
  }

  function runningLabel(ss){
    var out = esc(ss.name || "");
    var used = ss.startedAt ? (performance.now() - ss.startedAt) : 0;
    var typ = ss.typical || 0;
    out += ' <span class="ela">' + secs(used) + "</span>";
    if (typ > 0 && used < typ){
      out += ' <span class="eta">/ 约 ' + secs(typ) + "</span>";
    }
    return out;
  }

  var DONE_STATE = {ok:1, err:1, empty:1, cancel:1, warn:1};

  function tileFor(k){
    var el = stripEl.querySelector('.stile[data-key="' + k + '"]');
    if (el) return el;
    el = document.createElement("span");
    el.dataset.key = k;
    el.innerHTML = '<i class="sdot"></i><span class="stitle"></span>' +
      '<span class="track"><span class="fill"></span></span><span class="wipe"></span>';
    return el;
  }

  function flashTile(el){
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
    setTimeout(function(){ el.classList.remove("flash"); }, 440);
  }

  function paintStrip(){
    if (!stripEl) return;
    if (!st.busy && !st.searched){
      stripEl.hidden = true;
      return;
    }
    var order = st.srcList.map(function(s){ return s.key; });
    Object.keys(st.strip).forEach(function(k){
      if (order.indexOf(k) < 0) order.push(k);
    });
    if (!order.length){
      stripEl.hidden = true;
      return;
    }
    stripEl.hidden = false;

    var done = 0;
    var seen = {};
    order.forEach(function(k, i){
      var ss = st.strip[k] || {state:"pending"};
      var settled = !!DONE_STATE[ss.state];
      if (settled) done++;
      seen[k] = 1;

      var el = tileFor(k);
      var busy = ss.state === "pending" && !!ss.startedAt;
      var cls = busy ? "running" : (settled ? ss.state + " settled" : ss.state);
      if (st.filterSource){
        if (k === st.filterSource) cls += " filter-active";
        else cls += " filter-dim";
      }
      var prevState = el.dataset.ss || "";
      if (el.dataset.st !== cls) el.className = "stile " + cls;
      if (settled && !DONE_STATE[prevState]) flashTile(el);
      el.dataset.st = cls;
      el.dataset.ss = ss.state;
      var name = st.names[k] || k;
      var text = busy
        ? runningLabel({name:name, startedAt:ss.startedAt, typical:ss.typical})
        : esc(name) + " · " + stripLabel(ss);
      if (settled && ss.state !== "cancel" && !el.querySelector(".tick")){
        var tick = document.createElement("span");
        tick.className = "tick";
        el.appendChild(tick);
      }
      var title = el.querySelector(".stitle");
      if (title && title.innerHTML !== text) title.innerHTML = text;
      var at = stripEl.children[i];
      if (at !== el) stripEl.insertBefore(el, at || null);
    });

    [].slice.call(stripEl.querySelectorAll(".stile")).forEach(function(el){
      if (!seen[el.dataset.key]) el.remove();
    });

    var total = st.total || order.length;
    var cnt = stripEl.querySelector(".scount");
    if (!cnt){
      cnt = document.createElement("span");
      cnt.className = "scount";
      stripEl.appendChild(cnt);
    }
    var ctext = "<b>" + done + "</b> / " + total + " 完成";
    if (cnt.innerHTML !== ctext) cnt.innerHTML = ctext;
  }

  function headHtml(){
    function chip(k){
      var on = st.field === k;
      return '<button class="chipbtn' + (on ? " on" : "") + (on && st.desc ? " desc" : "") +
        '" data-sort="' + k + '">' + SORTS[k] + ICONS.arw + '</button>';
    }
    return '<span class="r">序号</span>' +
      '<span class="r">' + chip("size") + '</span>' +
      '<span class="r">' + chip("added") + '</span>' +
      '<span class="r">' + chip("seeders") + '</span>' +
      '<span class="r">文件名称</span>' +
      '<span class="r">来源</span>';
  }

  var ctxEl = null;

  function closeCtx(){
    if (!ctxEl) return;
    var el = ctxEl;
    ctxEl = null;
    el.classList.add("closing");
    setTimeout(function(){ el.remove(); }, 150);
  }

  function openCtx(x, y){
    closeCtx();
    ctxEl = document.createElement("div");
    ctxEl.className = "menu";
    ctxEl.style.left = x + "px";
    ctxEl.style.top = y + "px";
    ctxEl.style.transformOrigin = "top left";
    ctxEl.innerHTML =
      '<button class="mi" data-a="copy">' + ICONS.copy + '复制磁力</button>' +
      '<button class="mi" data-a="title">' + ICONS.copy + '复制标题</button>' +
      '<button class="mi" data-a="dl">' + ICONS.dl + '投递到迅雷</button>';
    document.body.appendChild(ctxEl);
    ctxEl.style.left = Math.max(4, Math.min(x, window.innerWidth - ctxEl.offsetWidth - 8)) + "px";
    ctxEl.style.top = Math.max(4, Math.min(y, window.innerHeight - ctxEl.offsetHeight - 8)) + "px";
    ctxEl.addEventListener("click", function(e){
      var b = e.target.closest("[data-a]");
      if (!b) return;
      closeCtx();
      if (b.dataset.a === "copy") doCopy();
      else if (b.dataset.a === "title") doCopyTitle();
      else doSend();
    });
  }

  function magnetsOf(list){
    return list.map(function(it){ return it.magnet; }).filter(function(m){ return m; });
  }

  function overCap(n){
    if (n <= HC.MAGNET_CAP) return false;
    flash("已选 " + n + " 条，一次最多 " + HC.MAGNET_CAP + " 条", "err");
    return true;
  }

  function doCopy(){
    var list = selList();
    if (!list.length) return;
    var magnets = magnetsOf(list);
    var text = magnets.join("\n");
    if (!text){
      HC.motion.toast("选中项没有可用的磁力链接", "err");
      return;
    }
    if (overCap(magnets.length)) return;
    HC.motion.copy(text).then(function(ok){
      if (ok) HC.sfx.play("copy");
      if (ok) flash(magnets.length > 1 ? "已复制 " + magnets.length + " 条磁力" : "已复制磁力链接", "ok");
      else { HC.sfx.play("fail"); HC.motion.toast("复制失败", "err"); }
    });
  }

  function doCopyTitle(){
    var list = selList();
    if (!list.length) return;
    var text = list.map(function(it){ return it.title; }).filter(function(t){ return t; }).join("\n");
    if (!text){
      HC.motion.toast("选中项没有标题", "err");
      return;
    }
    if (overCap(list.length)) return;
    HC.motion.copy(text).then(function(ok){
      if (ok) HC.sfx.play("copy");
      if (ok) flash(list.length > 1 ? "已复制 " + list.length + " 个标题" : "已复制标题", "ok");
      else { HC.sfx.play("fail"); HC.motion.toast("复制失败", "err"); }
    });
  }

  function doSend(){
    var list = selList();
    if (!list.length) return;
    var magnets = magnetsOf(list);
    if (!magnets.length){
      HC.motion.toast("选中项没有可用的磁力链接", "err");
      return;
    }
    if (overCap(magnets.length)) return;
    HC.api.deliver(magnets).then(function(r){
      if (r && r.ok) HC.sfx.play("deliver");
      else HC.sfx.play("fail");
      flash(r.message || (r.ok ? "已提交" : "投递失败"), r.ok ? "ok" : "err");
    }).catch(function(err){
      HC.sfx.play("fail");
      HC.motion.toast("投递失败：" + String(err && err.message ? err.message : err), "err");
    });
  }

  function reset(){
    cancelPaint();
    st.rev++;
    st.items = [];
    hashIdx = {};
    st.sel = {};
    st.anchor = "";
    st.open = {};
    st.userShut = {};
    st.autoBudget = 0;
    st.autoTried = {};
    fetchQ = [];
    st.filesCache = {};
    st.filesLoading = {};
    st.filesErr = {};
    st.errors = {};
    st.lines = [];
    st.strip = {};
    st.cursor = -1;
    st.parsed = null;
    st.done = 0;
    st.total = 0;
    st.rawTotal = 0;
    st.dupCount = 0;
    st.dupKept = false;
    st.relaxed = "";
    st.settled = false;
    st.searched = false;
    st.token = null;
    st.pending = [];
    nohashSeq = 0;
    renderTip();
  }

  var watchdogTimer = null;
  var WATCHDOG_MS = 60000;

  function clearWatchdog(){
    if (watchdogTimer){
      clearTimeout(watchdogTimer);
      watchdogTimer = null;
    }
  }

  function resetWatchdog(){
    clearWatchdog();
    if (!st.busy) return;
    watchdogTimer = setTimeout(function(){
      if (st.busy){
        abortSearch("搜索超时");
      }
    }, WATCHDOG_MS);
  }

  function dispatch(type, d){
    if (!st.busy) return false;
    resetWatchdog();
    if (st.token === null){
      (st.pending || (st.pending = [])).push({type: type, d: d});
      return false;
    }
    return d.token === st.token;
  }

  var hooks = null;

  function replayPending(){
    var queue = st.pending || [];
    st.pending = [];
    if (!hooks) return;
    queue.forEach(function(p){
      var fn = hooks[p.type];
      if (fn) fn(p.d);
    });
  }

  function setProgress(){
    if (!progEl || !st.total) return;
    progEl.style.setProperty("--p", String(Math.min(1, st.done / st.total)));
  }

  function styleClass(){
    return st.progStyle === "flow" ? "style-flow" : "style-seg";
  }

  function buildProg(){
    if (!progEl) return;
    progEl.className = "progress " + styleClass();
    progEl.innerHTML = "";
    var track = document.createElement("div");
    track.className = "track";
    progEl.appendChild(track);
    if (st.progStyle !== "flow"){
      var order = st.segOrder && st.segOrder.length ? st.segOrder : [];
      order.forEach(function(key, i){
        var seg = document.createElement("div");
        seg.className = "pseg";
        seg.dataset.key = key;
        seg.style.animationDelay = (i * 0.08) + "s";
        track.appendChild(seg);
      });
    } else {
      var fill = document.createElement("div");
      fill.className = "fill";
      fill.innerHTML = '<div class="tex"></div>';
      track.appendChild(fill);
    }
    if (st.progLineOn && st.deadline > 0){
      var dl = document.createElement("div");
      dl.className = "deadline";
      progEl.appendChild(dl);
    }
  }

  function recedeProg(celebrate){
    if (!progEl) return;
    if (dlRaf){ cancelAnimationFrame(dlRaf); dlRaf = 0; }
    var gen = st.progGen;
    var isSeg = st.progStyle !== "flow";
    if (celebrate){
      if (isSeg){
        [].slice.call(progEl.querySelectorAll(".pseg")).forEach(function(seg){
          seg.className = "pseg on";
        });
      } else {
        progEl.classList.remove("slow");
        progEl.style.setProperty("--p", "1");
      }
    } else {
      var dlNow = progEl.querySelector(".deadline");
      if (dlNow) dlNow.classList.remove("show", "passed");
    }
    var hold = celebrate ? HC.lookParam("hold") : 60;
    setTimeout(function(){
      if (gen !== st.progGen) return;
      var dl = progEl.querySelector(".deadline");
      if (dl) dl.classList.remove("show", "passed");
      var tail = PROG_TAIL_MS;
      if (isSeg){
        var u = HC.progUnlight(progEl, {
          lit: ".pseg.on, .pseg.err",
          alive: function(){ return gen === st.progGen; }
        });
        tail += u.count * u.step;
      } else {
        progEl.classList.add("receding");
      }
      var p = progEl;
      setTimeout(function(){
        if (p !== progEl || gen !== st.progGen) return;
        progEl.classList.remove("receding");
        buildProg();
        progEl.style.setProperty("--p", "0");
      }, tail);
    }, hold);
  }

  function paintClock(){
    if (!progEl) return;
    var clk = progEl.parentNode && progEl.parentNode.querySelector(".progclock");
    if (clk){
      var txt = ((performance.now() - st.t0) / 1000).toFixed(1) + "s";
      if (clk.textContent !== txt) clk.textContent = txt;
    }
  }

  function paintRunning(){
    if (!stripEl) return;
    [].slice.call(stripEl.querySelectorAll(".stile.running")).forEach(function(el){
      var ss = st.strip[el.dataset.key];
      if (!ss || ss.state !== "pending" || !ss.startedAt) return;
      var title = el.querySelector(".stitle");
      var text = runningLabel({
        name: st.names[el.dataset.key] || el.dataset.key,
        startedAt: ss.startedAt, typical: ss.typical,
      });
      if (title && title.innerHTML !== text) title.innerHTML = text;
    });
  }

  function dlLoop(){
    if (!st.busy || !progEl){ dlRaf = 0; return; }
    var elapsed = (performance.now() - st.t0) / 1000;
    var dl = st.progStyle === "segment" ? progEl.querySelector(".deadline") : null;
    if (dl && st.deadline > 0){
      var ratio = Math.min(1, elapsed / (st.deadline / 1000));
      dl.style.left = (ratio * 100) + "%";
      dl.classList.add("show");
      dl.classList.toggle("passed", ratio >= 1);
      if (ratio >= 1){
        [].slice.call(progEl.querySelectorAll(".pseg")).forEach(function(seg){
          var one = st.strip[seg.dataset.key];
          if (one && one.state === "pending" &&
              seg.className.indexOf("warned") < 0 && seg.className.indexOf("err") < 0){
            seg.className = "pseg warned";
          }
        });
      }
    }
    if (st.progStyle === "flow"){
      progEl.classList.toggle("slow", st.deadline > 0 &&
        elapsed > st.deadline / 1000 && st.done < st.total);
    }
    paintClock();
    paintRunning();
    dlRaf = requestAnimationFrame(dlLoop);
  }

  function stopProgress(celebrate){
    if (!progEl) return;
    progEl.classList.remove("on");
    progEl.classList.remove("wait");
    recedeProg(celebrate === true);
  }

  function abortSearch(msg){
    clearWatchdog();
    if (st.token) HC.api.cancelSearch(st.token);
    st.startSeq++;
    st.busy = false;
    st.token = 0;
    st.pending = [];
    goBtn.innerHTML = GO_BTN_INNER;
    goBtn.classList.remove("stop");
    stopProgress();
    drawerHide();
    finishRail();
    paintSrcs();
    if (msg) HC.motion.toast(msg, "err");
    renderRows();
  }

  function go(){
    if (st.hero){
      var heroInp = document.getElementById("heroInp");
      if (heroInp && heroInp.value.trim()) inp.value = heroInp.value.trim();
      hideHero();
    }
    if (st.busy){
      clearWatchdog();
      HC.api.cancelSearch(st.token);
      st.startSeq++;
      st.busy = false;
      st.token = 0;
      st.pending = [];
      Object.keys(st.strip).forEach(function(k){
        if (st.strip[k].state === "pending" || st.strip[k].state === "busy") st.strip[k] = {state:"cancel"};
      });
      if (Object.keys(st.strip).length) st.searched = true;
      paintStrip();
      goBtn.innerHTML = GO_BTN_INNER;
      goBtn.classList.remove("stop");
      stopProgress();
      drawerHide();
      finishRail();
      paintSrcs();
      flash("已停止搜索", "warn");
      renderRows();
      paintBadge();
      return;
    }
    var q = inp.value.trim();
    if (!q) return;
    st.filterSource = "";
    st.query = q;
    st.qphrase = q.toLowerCase();
    st.qtokens = st.qphrase.split(/\s+/).filter(Boolean);
    st.hlRe = st.qtokens.length
      ? new RegExp(st.qtokens.slice().sort(function(a, b){ return b.length - a.length; })
          .map(reEscape).join("|"), "gi")
      : null;
    reset();
    st.srcList.forEach(function(s){ st.strip[s.key] = {state:"pending"}; });
    st.segOrder = st.srcList.map(function(s){ return s.key; });
    if (!st.segOrder.length) st.segOrder = Object.keys(st.strip);
    st.t0 = performance.now();
    var dlMs = HC.settings ? parseInt(HC.settings.soft_deadline_ms, 10) : NaN;
    st.deadline = isNaN(dlMs) ? 3000 : dlMs;
    st.progGen = (st.progGen || 0) + 1;
    buildProg();
    progEl.classList.add("on", "wait");
    progEl.style.setProperty("--p", "0");
    if (!dlRaf) dlRaf = requestAnimationFrame(dlLoop);
    st.busy = true;
    resetWatchdog();
    HC.sfx.play("start");
    renderRows();
    paintStrip();
    paintBadge();
    st.failed = 0;
    drawerHide();
    resetRail();
    paintSrcs();
    goBtn.textContent = "停止";
    goBtn.classList.add("stop");
    st.startSeq++;
    var seq = st.startSeq;
    HC.api.startSearch(q).then(function(res){
      if (seq !== st.startSeq) return;
      if (!res || !res.ok){
        abortSearch(res && res.error);
        return;
      }
      st.token = res.token;
      st.total = res.total;
      st.parsed = res.query || null;
      st.rev++;
      setProgress();
      paintSrcs();
      replayPending();
    }).catch(function(err){
      abortSearch(err && err.message ? err.message : String(err));
    });
  }

  function searchDone(){
    clearWatchdog();
    cancelPaint();
    st.busy = false;
    st.searched = true;
    goBtn.innerHTML = GO_BTN_INNER;
    goBtn.classList.remove("stop");
    stopProgress(true);
    st.errors = st.errors || {};
    var fails = Object.keys(st.errors).filter(function(k){ return k; }).length;
    var total = st.items.length;
    st.failed = Math.max(st.failed, fails);
    if (fails) HC.sfx.play("fail");
    else if (total) HC.sfx.play("done");
    paintBadge();
    paintSrcs();
    finishRail();
    drawerHide();
    Object.keys(st.strip).forEach(function(k){
      if (st.strip[k].state === "pending") st.strip[k] = {state:"cancel"};
    });
    paintStrip();
    var curRows = rowsEl.querySelectorAll(".srow");
    var curRow = st.cursor >= 0 ? curRows[st.cursor] : null;
    var curHash = curRow && curRow.dataset ? curRow.dataset.hash : "";
    renderRows();
    autoExpand(AUTO_TOTAL, true);
    if (curHash){
      var list = visible();
      for (var i = 0; i < list.length; i++){
        if (list[i].hash === curHash){ st.cursor = i; break; }
      }
      paintCursor();
    }
    paintBadge();
  }

  function showHero(){
    st.hero = true;
    if (!root || !root.isConnected) return;
    if (root.querySelector(".hero")) return;
    var hero = document.createElement("div");
    hero.className = "hero";
    hero.innerHTML =
      '<div class="hero-in">' +
        '<img class="brandmark" src="assets/app-256.png" alt="">' +
        '<div class="hero-search">' + ICONS.search +
          '<input id="heroInp" placeholder="输入搜索内容" autocomplete="off">' +
          '<button class="gobtn" id="heroGo">' + GO_BTN_INNER + '</button>' +
        '</div>' +
        '<div class="hero-srcs" id="heroSrcs"></div>' +
      '</div>';
    root.appendChild(hero);
    var heroInp = hero.querySelector("#heroInp");
    hero.querySelector("#heroGo").onclick = go;
    heroInp.onkeydown = function(e){
      if (e.key === "Enter") go();
    };
    hero.querySelector("#heroSrcs").addEventListener("click", function(e){
      if (e.target.closest("[data-key]")) location.hash = "sources";
    });
    refreshSources();
    setTimeout(function(){ heroInp.focus(); }, 120);
  }

  function hideHero(){
    st.hero = false;
    var heroEl = root.querySelector(".hero");
    if (!heroEl) return;
    heroEl.classList.add("leave");
    setTimeout(function(){
      if (heroEl.parentNode) heroEl.parentNode.removeChild(heroEl);
    }, 280);
    root.classList.add("card-enter");
  }

  function applySettings(s){
    st.selbarOn = !!s && s.selbar === true;
    autoFiles = !s || s.auto_files !== false;
    var style = s && s.progress_style === "flow" ? "flow" : "segment";
    var line = !s || s.progress_line !== false;
    var dlMs = s ? parseInt(s.soft_deadline_ms, 10) : NaN;
    var deadline = isNaN(dlMs) ? 3000 : dlMs;
    if (st.progStyle !== style || st.progLineOn !== line || st.deadline !== deadline){
      st.progStyle = style;
      st.progLineOn = line;
      st.deadline = deadline;
      buildProg();
    }
    updateSelUI(true);
  }

  var paintT = null;

  function schedulePaint(){
    if (paintT) return;
    paintT = requestAnimationFrame(function(){
      paintT = null;
      var bumped = st.pendingBumped, fresh = st.pendingFresh || 0;
      var arrived = st.pendingArrived;
      st.pendingBumped = {};
      st.pendingFresh = 0;
      st.pendingArrived = [];
      if (!rowsEl || !rowsEl.isConnected) return;
      var hasBumped = false;
      for (var k in bumped){ hasBumped = true; break; }
      if (st.field){
        renderRows();
        updateSelUI();
      } else {
        if (hasBumped) refreshRows(bumped);
        if (fresh && (st.renderedCount || 0) < CHUNK_SIZE) appendRows(fresh);
      }
      paintBadge();
      autoExpand(AUTO_EARLY, false, arrived);
    });
  }

  function cancelPaint(){
    if (paintT){
      cancelAnimationFrame(paintT);
      paintT = null;
    }
    st.pendingBumped = {};
    st.pendingFresh = 0;
    st.pendingArrived = [];
  }

  function buildHooks(){
    return {
      start: function(d){
        if (!dispatch("start", d)) return;
        var one = st.strip[d.key];
        if (!one || one.state !== "pending") return;
        one.startedAt = performance.now();
        one.typical = Number(d.typical_ms) || 0;
        paintStrip();
      },
      source: function(d){
        if (!dispatch("source", d)) return;
        st.done += 1;
        if (progEl) progEl.classList.remove("wait");
        var segRed = d.state === "err" || (!d.state && d.err && d.outcome !== "empty");
        var seg = progEl && progEl.querySelector('.pseg[data-key="' + d.key + '"]');
        if (seg) seg.className = "pseg" + (segRed ? " err" : " on");
        setProgress();
        var name = st.names[d.key] || d.key;
        var ss = d.state || (d.err ? "err" : (d.count ? "ok" : "empty"));
        if (ss === "err"){
          st.lines.push({text: name + "：失败（" + (d.err || "请求失败") + "）", bad: true});
          st.failed += 1;
          drawerShow(name, "失败", true);
          st.strip[d.key] = {state:"err", err:d.err};
        } else if (ss === "empty"){
          st.lines.push({text: name + "：无结果", bad: false});
          drawerShow(name, "无结果", false);
          st.strip[d.key] = {state:"empty"};
        } else if (ss === "warn"){
          var why = d.err || "提示";
          st.lines.push({text: name + "：" + why, bad: false});
          drawerShow(name, why, false);
          st.strip[d.key] = {state:"warn", err:d.err, count:d.count};
        } else {
          st.lines.push({text: name + "：" + d.count + " 条" +
                         (d.fuzzy ? "（未使用关键词）" : ""), bad: false});
          drawerShow(name, d.count + " 条", false);
          st.strip[d.key] = {state:"ok", count:d.count, fuzzy:!!d.fuzzy,
                             cached:!!d.cached};
        }
        renderTip();
        paintStrip();
        paintBadge();
        paintSrcs();
      },
      settled: function(d){
        if (!dispatch("settled", d)) return;
        st.settled = true;
        renderRows();
        paintBadge();
        paintStrip();
        paintSrcs();
      },
      batch: function(d){
        if (!dispatch("batch", d)) return;
        var fresh = 0, bumped = null;
        d.items.forEach(function(it){
          if (!it.hash) it.hash = "nohash-" + (++nohashSeq);
          var pos = indexOfHash(it.hash);
          if (pos >= 0){
            st.items[pos] = it;
            (bumped || (bumped = {}))[it.hash] = true;
          } else {
            hashIdx[it.hash] = st.items.length;
            st.items.push(it);
            fresh++;
          }
        });
        if (st.field || st.settled) st.rev++;
        if (bumped) for (var bk in bumped) st.pendingBumped[bk] = true;
        st.pendingFresh += fresh;
        for (var ai = 0; ai < d.items.length; ai++) st.pendingArrived.push(d.items[ai]);
        schedulePaint();
      },
      done: function(d){
        if (!dispatch("done", d)) return;
        st.errors = d.errors || {};
        st.rawTotal = Number(d.raw) || 0;
        st.dupCount = Number(d.dup) || 0;
        st.relaxed = d.relaxed || "";
        st.dupKept = d.kept === true;
        var fatal = st.errors[""];
        if (fatal){
          st.lines.unshift({text: fatal, bad: true});
          renderTip();
          tipEl.classList.add("show");
        }
        searchDone();
      }
    };
  }

  var autoT = null;


  function stopAuto(){
    if (autoT){
      clearInterval(autoT);
      autoT = null;
    }
  }

  function startAuto(){
    stopAuto();
    autoT = setInterval(function(){
      if (!marquee || !marquee.active){
        stopAuto();
        return;
      }
      var rect = marquee.rect;
      var edge = 24;
      var dir = 0;
      if (marquee.y < rect.top + edge) dir = -1;
      else if (marquee.y > rect.bottom - edge) dir = 1;
      if (dir){
        rowsEl.scrollTop += dir * 12;
        paintMarquee();
      }
    }, 16);
  }

  function collectSpans(rect, sx, sy){
    return [].slice.call(rowsEl.querySelectorAll(".srow")).map(function(row){
      var rc = row.getBoundingClientRect();
      return {
        h: row.dataset.hash, el: row,
        l: rc.left - rect.left + sx, r: rc.right - rect.left + sx,
        t: rc.top - rect.top + sy, b: rc.bottom - rect.top + sy
      };
    });
  }

  function paintMarquee(){
    var rect = marquee.rect;
    var sx = rowsEl.scrollLeft, sy = rowsEl.scrollTop;
    var cx = marquee.x - rect.left + sx, cy = marquee.y - rect.top + sy;
    var l = Math.min(marquee.cx0, cx), t = Math.min(marquee.cy0, cy);
    var r = Math.max(marquee.cx0, cx), b = Math.max(marquee.cy0, cy);
    marquee.el.style.left = l + "px";
    marquee.el.style.top = t + "px";
    marquee.el.style.width = (r - l) + "px";
    marquee.el.style.height = (b - t) + "px";
    marquee.spans.forEach(function(sp){
      var hit = sp.l < r && sp.r > l && sp.t < b && sp.b > t;
      if (hit === !!st.sel[sp.h]) return;
      if (hit) st.sel[sp.h] = true;
      else delete st.sel[sp.h];
      if (sp.el) sp.el.classList.toggle("sel", hit);
    });
    syncSelbar();
  }

  function endMarquee(e){
    if (!marquee || e.pointerId !== marquee.id) return;
    var m = marquee;
    marquee = null;
    rowsEl.classList.remove("mq-ing");
    stopAuto();
    if (m.el) m.el.remove();
    if (m.active){
      justMarqueed = true;
      st.anchor = "";
      updateSelUI();
    }
  }
  function bindMarquee(){
    rowsEl.addEventListener("pointerdown", function(e){
      if (e.button !== 0) return;
      justMarqueed = false;
      if (e.shiftKey || e.ctrlKey || e.metaKey) return;
      if (e.target.closest(".fpanel, .fchev, button, a, input, textarea")) return;
      var rect = rowsEl.getBoundingClientRect();
      if (e.clientX > rect.right - (rowsEl.offsetWidth - rowsEl.clientWidth)) return;
      rowsEl.classList.add("mq-ing");
      marquee = {
        id: e.pointerId, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY,
        cx0: e.clientX - rect.left + rowsEl.scrollLeft,
        cy0: e.clientY - rect.top + rowsEl.scrollTop,
        rect: rect, spans: null, visList: null, active: false, el: null
      };
    });

    rowsEl.addEventListener("pointermove", function(e){
      if (!marquee || e.pointerId !== marquee.id) return;
      marquee.x = e.clientX;
      marquee.y = e.clientY;
      var dx = e.clientX - marquee.x0, dy = e.clientY - marquee.y0;
      if (!marquee.active){
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
        marquee.active = true;
        try{ rowsEl.setPointerCapture(e.pointerId); }catch(err){}
        var el = document.createElement("div");
        el.className = "marquee";
        rowsEl.appendChild(el);
        marquee.el = el;
        st.sel = {};
        marquee.visList = visible();
        marquee.spans = collectSpans(marquee.rect, rowsEl.scrollLeft, rowsEl.scrollTop);
        startAuto();
      }
      paintMarquee();
    });

    rowsEl.addEventListener("pointerup", endMarquee);
    rowsEl.addEventListener("pointercancel", endMarquee);
  }

  function mount(mountEl){
    root = document.createElement("div");
    root.className = "app";

    root.innerHTML =
      '<div class="card">' +
        '<div class="bar">' +
          '<div class="group">' +
            '<button class="cb" id="ckAll"></button>' +
            '<span class="allabel">全选</span>' +
            '<span class="crewwrap">' +
              '<button class="crew res" id="crewRes" type="button">' +
                '<span class="k" id="rsCount">共 0 条</span>' +
                '<span class="k" id="rsSrcs">0/0 源' + CHEV + '</span>' +
                '<span class="rail" id="rsRailBox"><i id="rsRail"></i></span>' +
              '</button>' +
              '<div class="chiptip" id="tip"></div>' +
            '</span>' +
            '<span class="drw-wrap" id="drw"><span class="drw">' +
              '<span class="ar"></span><span class="nm" id="dwName"></span>' +
              '<span class="vl" id="dwVal"></span>' +
            '</span></span>' +
            '<button class="crew net busy" id="crewNet" type="button">' +
              '<span class="k exit" id="ntExit"><span class="ndot"></span>' +
                '<span class="tx">检测中</span>' + CHEV + '</span>' +
              '<span class="k aux" id="ntSpeed">↓0</span>' +
            '</button>' +
          '</div>' +
          '<div class="spacer"></div>' +
          '<div class="sentry">' + ICONS.search +
            '<input id="inp" placeholder="输入搜索内容" autocomplete="off">' +
            '<button class="gobtn" id="goBtn">搜索</button>' +
          '</div>' +
          '<div class="group">' +
            '<button class="iconbtn" id="btnSrc" title="数据源">' + ICONS.srclist + '</button>' +
            '<button class="iconbtn" id="btnCfg" title="设置">' + ICONS.gear + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="progrow">' +
          '<span class="progclock" id="progClock"></span>' +
          '<div class="progress" id="prog"><div class="track"><div class="fill"></div></div></div>' +
        '</div>' +
        '<div class="srcstrip" id="srcstrip" hidden></div>' +
        '<div class="div"></div>' +
        '<div class="shead" id="shead" role="presentation">' + headHtml() + '</div>' +
        '<div class="rows" id="rows" role="grid" tabindex="0" aria-label="搜索结果" aria-rowcount="0"></div>' +
      '</div>';

    mountEl.appendChild(root);
    rowsEl = root.querySelector("#rows");
    var scrollRaf = 0;
    rowsEl.addEventListener("scroll", function(){
      if (scrollRaf) return;
      scrollRaf = requestAnimationFrame(function(){
        scrollRaf = 0;
        checkMoreRows();
      });
    });
    crewRes = root.querySelector("#crewRes");
    rsCount = root.querySelector("#rsCount");
    rsSrcs = root.querySelector("#rsSrcs");
    rsRailBox = root.querySelector("#rsRailBox");
    rsRail = root.querySelector("#rsRail");
    drwWrap = root.querySelector("#drw");
    drw = root.querySelector(".drw");
    dwName = root.querySelector("#dwName");
    dwVal = root.querySelector("#dwVal");
    crewNet = root.querySelector("#crewNet");
    ntExit = root.querySelector("#ntExit");
    ntSpeed = root.querySelector("#ntSpeed");
    tipEl = root.querySelector("#tip");
    ckAllEl = root.querySelector("#ckAll");
    inp = root.querySelector("#inp");
    goBtn = root.querySelector("#goBtn");
    headEl = root.querySelector("#shead");
    progEl = root.querySelector("#prog");
    stripEl = root.querySelector("#srcstrip");
    stripEl.addEventListener("click", function(e){
      var tile = e.target.closest(".stile");
      if (!tile) return;
      var k = tile.dataset.key;
      if (!k) return;
      if (st.filterSource === k){
        st.filterSource = "";
      } else {
        st.filterSource = k;
      }
      paintStrip();
      renderRows();
      updateSelUI();
    });
    paintBadge(true);

    var srcLoaded = false;
    function loadSourcesOnce(){
      if (srcLoaded) return;
      srcLoaded = HC.api.isLive();
      refreshSources();
    }
    loadSourcesOnce();
    var cachedNet = HC.getNetStatus ? HC.getNetStatus() : null;
    st.netState = cachedNet && HC.netState ? HC.netState(cachedNet) : null;
    paintNetCrew();
    checkNetwork(false);
    clearInterval(speedTimer);
    speedTimer = setInterval(tickSpeed, 1000);

    hooks = buildHooks();
    HC.api.onSearch(hooks);

    root.querySelector(".sentry").addEventListener("click", function(e){
      if (e.target === goBtn) return;
      inp.focus();
    });
    goBtn.onclick = go;
    inp.onkeydown = function(e){
      if (e.key === "Enter") go();
    };

    root.querySelector("#btnSrc").onclick = function(){
      location.hash = "sources";
    };
    root.querySelector("#btnCfg").onclick = function(){
      location.hash = "settings";
    };
    crewRes.onclick = function(){
      location.hash = "sources";
    };
    crewNet.onclick = function(){
      HC.settingsDefaultPane = "network";
      location.hash = "settings";
    };
    crewRes.addEventListener("mouseenter", function(){
      if (st.lines.length) tipEl.classList.add("show");
    });
    crewRes.addEventListener("mouseleave", function(){
      tipEl.classList.remove("show");
    });
    crewRes.addEventListener("focus", function(){
      if (st.lines.length) tipEl.classList.add("show");
    });
    crewRes.addEventListener("blur", function(){
      tipEl.classList.remove("show");
    });

    ckAllEl.onclick = function(){
      var on = !(selCount() > 0 && selCount() === visible().length);
      st.sel = {};
      if (on){
        visible().forEach(function(it){ st.sel[it.hash] = true; });
        st.anchor = "";
      }
      updateSelUI();
    };

    headEl.addEventListener("click", function(e){
      var cell = e.target.closest("[data-sort]");
      if (!cell) return;
      var k = cell.dataset.sort;
      if (st.field === k){
        if (!st.desc) st.desc = true;
        else { st.field = ""; st.desc = false; }
      } else {
        st.field = k;
        st.desc = false;
      }
      headEl.innerHTML = headHtml();
      renderRows();
      updateSelUI();
    });

    rowsEl.addEventListener("click", function(e){
      if (justMarqueed){
        justMarqueed = false;
        return;
      }
      var chev = e.target.closest(".fchev");
      if (chev){
        var ch = chev.dataset.hash;
        if (st.open[ch]){ delete st.open[ch]; st.userShut[ch] = true; }
        else { st.open[ch] = true; delete st.userShut[ch]; }
        renderPanels();
        return;
      }
      if (e.target.closest(".fpanel")) return;
      var row = e.target.closest(".srow");
      if (!row){
        st.sel = {};
        st.anchor = "";
        updateSelUI();
        return;
      }
      var hash = row.dataset.hash;
      var vlist = visible(), cIdx = -1;
      vlist.forEach(function(it, i){
        if (it.hash === hash) cIdx = i;
      });
      st.cursor = cIdx;
      paintCursor();
      if (e.shiftKey && st.anchor){
        var list = visible();
        var a = -1, b = -1;
        list.forEach(function(it, i){
          if (it.hash === st.anchor) a = i;
          if (it.hash === hash) b = i;
        });
        if (a >= 0 && b >= 0){
          st.sel = {};
          if (a > b){ var t = a; a = b; b = t; }
          for (var i = a; i <= b; i++) st.sel[list[i].hash] = true;
        }
      } else if (e.ctrlKey || e.metaKey){
        if (st.sel[hash]) delete st.sel[hash];
        else st.sel[hash] = true;
        st.anchor = hash;
      } else {
        st.sel = {};
        st.sel[hash] = true;
        st.anchor = hash;
      }
      updateSelUI();
    });

    bindMarquee();

    rowsEl.addEventListener("dblclick", function(e){
      var row = e.target.closest(".srow");
      if (!row) return;
      st.sel = {};
      st.sel[row.dataset.hash] = true;
      st.anchor = row.dataset.hash;
      updateSelUI();
      row.classList.add("flash");
      setTimeout(function(){ row.classList.remove("flash"); }, 180);
      doCopy();
    });

    rowsEl.addEventListener("contextmenu", function(e){
      var row = e.target.closest(".srow");
      if (!row) return;
      e.preventDefault();
      if (!st.sel[row.dataset.hash]){
        st.sel = {};
        st.sel[row.dataset.hash] = true;
        st.anchor = row.dataset.hash;
        updateSelUI();
      }
      openCtx(e.clientX, e.clientY);
    });

    if (mount._docClick) document.removeEventListener("click", mount._docClick);
    if (mount._docKey) document.removeEventListener("keydown", mount._docKey);

    mount._docClick = function(e){
      if (ctxEl && !e.target.closest(".menu")) closeCtx();
    };
    mount._docKey = function(e){
      if (!root || !root.isConnected) return;
      if (document.querySelector(".backdrop")) return;
      var tag = (e.target && e.target.tagName || "").toLowerCase();
      if (e.key === "Escape"){
        if (ctxEl){ closeCtx(); return; }
        var act = document.activeElement;
        var inSearch = act === inp || (act && act.id === "heroInp");
        if (inSearch){
          if (act.value){
            act.value = "";
            return;
          }
          act.blur();
          return;
        }
        if (selCount()){
          st.sel = {};
          st.anchor = "";
          updateSelUI();
          return;
        }
        if (!st.hero) showHero();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")){
        if (tag === "input" || tag === "textarea") return;
        e.preventDefault();
        if (!visible().length) return;
        st.sel = {};
        visible().forEach(function(it){ st.sel[it.hash] = true; });
        updateSelUI();
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K" || e.key === "f" || e.key === "F")){
        e.preventDefault();
        var heroInp = st.hero ? document.getElementById("heroInp") : null;
        var targetInp = heroInp || inp;
        if (targetInp){
          targetInp.focus();
          targetInp.select();
        }
        return;
      }
      if (st.hero) return;
      var act = document.activeElement;
      var inSearchBox = act === inp || (act && act.id === "heroInp");
      var arrows = e.key === "ArrowDown" || e.key === "ArrowUp";
      if (tag === "textarea") return;
      if (tag === "input" && !(inSearchBox && arrows)) return;
      var list = visible();
      if (!list.length) return;
      if (arrows){
        e.preventDefault();
        var dir = e.key === "ArrowDown" ? 1 : -1;
        if (st.cursor < 0) st.cursor = dir > 0 ? 0 : list.length - 1;
        else st.cursor = Math.max(0, Math.min(list.length - 1, st.cursor + dir));
        paintCursor();
        if (inSearchBox && rowsEl) rowsEl.focus();
        return;
      }
      if (e.key === "Enter" && st.cursor >= 0){
        var crow = rowsEl ? rowsEl.querySelector(".srow.cursor") : null;
        var cbtn = crow && crow.querySelector(".fchev");
        if (cbtn){
          e.preventDefault();
          cbtn.click();
        }
        return;
      }
      if (e.key === " " && st.cursor >= 0){
        e.preventDefault();
        var it = list[st.cursor];
        if (it){
          if (st.sel[it.hash]) delete st.sel[it.hash];
          else st.sel[it.hash] = true;
          st.anchor = it.hash;
          updateSelUI();
        }
      }
    };
    document.addEventListener("click", mount._docClick);
    document.addEventListener("keydown", mount._docKey);

    renderRows();
    paintBadge();

    var rowsBox = root.querySelector(".rows");
    function syncScrollbar(){
      var sbw = rowsBox.offsetWidth - rowsBox.clientWidth;
      root.style.setProperty("--sbw", sbw + "px");
    }
    syncScrollbar();
    if (mount._ro) mount._ro.disconnect();
    if (window.ResizeObserver){
      mount._ro = new ResizeObserver(syncScrollbar);
      mount._ro.observe(rowsBox);
    }

    selbarEl = document.createElement("div");
    selbarEl.id = "selbar";
    selbarEl.className = "selbar";
    selbarEl.innerHTML =
      '<span class="st">已选 <b id="selN">0</b> 条</span>' +
      '<span class="sdiv"></span>' +
      '<button class="sbtn" data-s="copy">复制磁力</button>' +
      '<button class="sbtn" data-s="title">复制标题</button>' +
      '<button class="sbtn primary" data-s="dl">投递迅雷</button>' +
      '<span class="ssp"></span>' +
      '<button class="sclose" data-s="close">' +
        '<svg width="12" height="12" viewBox="-1 -1 16 16" fill="none"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>' +
      '</button>';
    root.appendChild(selbarEl);
    selbarEl.addEventListener("click", function(e){
      var b = e.target.closest("[data-s]");
      if (!b) return;
      if (b.dataset.s === "copy") doCopy();
      else if (b.dataset.s === "title") doCopyTitle();
      else if (b.dataset.s === "dl") doSend();
      else {
        st.sel = {};
        st.anchor = "";
        updateSelUI();
      }
    });

    HC.api.getSettings().then(applySettings);
    HC.api.onLive(function(){
      loadSourcesOnce();
      HC.api.getSettings().then(applySettings);
    });

    if (st.hero) showHero();

    HC.views.search.st = st;
  }

  HC.views.search = {
    mount: mount,
    enterHero: showHero,
    toggleHero: function(){
      if (root && root.querySelector(".hero")) hideHero();
      else showHero();
    }
  };
})();
