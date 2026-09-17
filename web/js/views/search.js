(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var SORTS = {size:"体积", added:"时间", seeders:"做种"};

  var ICONS = {
    search: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<circle cx="6" cy="6" r="4.6" stroke="currentColor" stroke-width="1.4"/>' +
      '<path d="M9.6 9.6L12.6 12.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    gear: '<svg width="15" height="15" viewBox="0 0 14 14" fill="none">' +
      '<path d="M8.37 12.94L5.63 12.94L5.44 11.06A4.35 4.35 0 0 1 4.26 10.38L2.54 11.16L1.17 8.78L2.7 7.68A4.35 4.35 0 0 1 2.7 6.32L1.17 5.22L2.54 2.84L4.26 3.62A4.35 4.35 0 0 1 5.44 2.94L5.63 1.06L8.37 1.06L8.56 2.94A4.35 4.35 0 0 1 9.74 3.62L11.46 2.84L12.83 5.22L11.3 6.32A4.35 4.35 0 0 1 11.3 7.68L12.83 8.78L11.46 11.16L9.74 10.38A4.35 4.35 0 0 1 8.56 11.06Z" ' +
      'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
      '<circle cx="7" cy="7" r="1.9" stroke="currentColor" stroke-width="1.3"/></svg>',
    check: '<svg width="10" height="10" viewBox="0 0 14 14" fill="none">' +
      '<path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    copy: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<rect x="4.6" y="4.6" width="7" height="7" rx="1.4" stroke="currentColor" stroke-width="1.3"/>' +
      '<path d="M9.4 2.6H3.4A1.4 1.4 0 0 0 2 4v6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    dl: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<path d="M7 2.4v6.4M4.4 6.4L7 9l2.6-2.6" stroke="currentColor" stroke-width="1.3" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="M2.6 11.4h8.8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    arw: '<svg class="arw" width="9" height="9" viewBox="0 0 10 10" fill="none">' +
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
    field: "", desc: false,
    busy: false, searched: false, hero: true,
    token: 0, done: 0, total: 0,
    errors: {}, names: {},
    enabledCount: 0, totalSources: 0,
    lines: [],
    srcList: [], strip: {}, cursor: -1,
    query: "", qtokens: [], qphrase: "", hlRe: null,
    open: {}, userShut: {},
    filesCache: {}, filesLoading: {}, filesErr: {}, autoBudget: 0, autoTried: {},
    selbarOn: false
  };

  var root, rowsEl, badgeEl, chipEl, tipEl, ckAllEl, inp, goBtn, headEl, progEl, stripEl, selbarEl;
  var marquee = null;
  var justMarqueed = false;
  var nohashSeq = 0;

  var esc = HC.esc;

  function fmtCount(n){
    n = Number(n) || 0;
    if (n < 1000) return String(n);
    if (n < 1000000) return (n / 1000).toFixed(1).replace(".0", "") + "k";
    return (n / 1000000).toFixed(1).replace(".0", "") + "M";
  }

  function tier(n){
    n = Number(n) || 0;
    return n >= 1000 ? "hi" : (n >= 100 ? "mid" : "lo");
  }

  function pad(i){
    return (i + 1 < 10 ? "0" : "") + (i + 1);
  }

  function visible(){
    if (marquee && marquee.active && marquee.visList) return marquee.visList;
    if (!st.field){
      if (st.busy || !st.qtokens.length) return st.items;
      var scored = st.items.map(function(it){ return { it: it, r: relevance(it) }; });
      scored.sort(function(a, b){ return b.r - a.r; });
      return scored.map(function(s){ return s.it; });
    }
    return st.items.slice().sort(function(a, b){
      var x = Number(a[st.field]) || 0, y = Number(b[st.field]) || 0;
      return st.desc ? y - x : x - y;
    });
  }

  var WORD_EDGE = /[\s\[\]()（）·\-_.【】,，、:：;；!！?？'"\/\\|]/;

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

  function hasTok(text, tk){
    return text && text.indexOf(tk) >= 0;
  }

  function relevance(it){
    var tokens = st.qtokens;
    if (!tokens.length) return 0;
    var title = (it.title || "").toLowerCase();
    var fns = fileNames(it);
    var hit = 0, score = 0;

    for (var i = 0; i < tokens.length; i++){
      var tk = tokens[i];
      var pos = title.indexOf(tk);
      if (pos >= 0){
        hit++;
        score += pos === 0 || WORD_EDGE.test(title[pos - 1]) ? 12 : 6;
      } else if (hasTok(fns, tk)){
        hit++;
        score += 4;
      }
    }

    var miss = tokens.length - hit;
    if (miss === 0) score += 1000;
    else if (miss === 1) score += 500;
    else if (miss === 2) score += 200;
    else score += 50;

    if (st.qphrase && title.indexOf(st.qphrase) >= 0) score += 300;
    else if (hasTok(fns, st.qphrase)) score += 60;

    score += Math.min(Math.log((Number(it.seeders) || 0) + 1) * 6, 40);
    return score;
  }

  function selList(){
    return visible().filter(function(it){ return st.sel[it.hash]; });
  }

  function selCount(){ return selList().length; }

  function badgeHtml(){
    var n = selCount(), total = st.items.length;
    return n ? '已选中 <b>' + n + '</b> 条 / 共 ' + total + ' 条'
             : '共 ' + total + ' 条';
  }

  var popT = null;

  function paintBadge(still){
    var t = badgeHtml();
    if (badgeEl.innerHTML === t) return;
    badgeEl.className = "badge";
    badgeEl.innerHTML = t;
    if (still) return;
    badgeEl.classList.remove("pop");
    void badgeEl.offsetWidth;
    badgeEl.classList.add("pop");
    clearTimeout(popT);
    popT = setTimeout(function(){ badgeEl.classList.remove("pop"); }, 300);
  }

  function flash(text, kind){
    HC.motion.toast(text, kind);
  }

  function setChip(text, kind){
    chipEl.textContent = text;
    chipEl.className = "chipbtn" + (kind ? " " + kind : "");
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
          var hst = s.health && s.health.state;
          var dot = (hst === "err" || hst === "warn" || hst === "empty") ? " " + hst : "";
          return '<button class="srcdot' + dot +
            (s.enabled ? "" : " off") + '" data-key="' + esc(s.key) + '">' +
            '<span class="sdot"></span>' + esc(s.label) + '</button>';
        }).join("");
      }
      if (!st.busy) chipIdle();
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
          setChip("搜索中…", "busy");
        }
      }
    });
  }

  function chipIdle(){
    setChip("已启用 " + st.enabledCount + "/" + st.totalSources + " 个源", "");
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

  function hlTitle(escaped){
    if (!st.hlRe) return escaped;
    st.hlRe.lastIndex = 0;
    return escaped.replace(st.hlRe, '<mark class="hl">$&</mark>');
  }

  var FCHEV = '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function itemByHash(h){
    var out = null;
    st.items.some(function(it){ if (it.hash === h){ out = it; return true; } return false; });
    return out;
  }

  function indexOfHash(h){
    for (var i = 0; i < st.items.length; i++){
      if (st.items[i].hash === h) return i;
    }
    return -1;
  }

  function fpanelInner(it){
    var files = (it.files && it.files.length) ? it.files : st.filesCache[it.hash];
    if (files && files.length){
      return files.map(function(f){
        return '<div class="fline"><span class="fname">' + hlTitle(esc(f.n)) +
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
      if (res && res.ok && res.files && res.files.length) st.filesCache[h] = res.files;
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

  function autoExpand(total, urgent){
    if (!st.qtokens.length) return;
    if (!autoFiles) return;
    var pending = [];
    visible().forEach(function(it){
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
    rowsEl.querySelectorAll(".fpanel").forEach(function(n){ n.remove(); });
    rowsEl.querySelectorAll(".fchev.on").forEach(function(n){ n.classList.remove("on"); });
    rowsEl.querySelectorAll(".srow.open").forEach(function(n){ n.classList.remove("open"); });
    var rows = {};
    [].slice.call(rowsEl.querySelectorAll(".srow")).forEach(function(row){
      rows[row.dataset.hash] = row;
    });
    Object.keys(st.open).forEach(function(h){
      var row = rows[h], it = itemByHash(h);
      var lazy = it && it.fetch && it.fetch.url;
      var has = it && ((it.files && it.files.length) || lazy);
      if (!row || !it || !has){
        delete st.open[h];
        return;
      }
      var p = document.createElement("div");
      p.className = "fpanel";
      p.dataset.hash = h;
      p.innerHTML = fpanelInner(it);
      row.parentNode.insertBefore(p, row.nextSibling);
      row.classList.add("open");
      var chev = row.querySelector(".fchev");
      if (chev) chev.classList.add("on");
      loadFiles(h, null);
    });
  }

  function rowHtml(it, i, animate){
    var cls = "srow" + (i % 2 ? " alt" : "") + (st.sel[it.hash] ? " sel" : "");
    var anim = animate
      ? ' style="animation:rowIn .3s var(--land) both ' + Math.min(i, 10) * 28 + 'ms"'
      : "";
    var src = (it.sources || []).map(function(k){
      return st.names[k] || k;
    }).join(" · ");
    var title = hlTitle(esc(it.title));
    var chev = (it.files && it.files.length) || it.fetch
      ? '<button class="fchev" data-hash="' + esc(it.hash) + '" title="文件">' + FCHEV + '</button>'
      : "";
    return '<div class="' + cls + '" data-hash="' + esc(it.hash) + '"' + anim + '>' +
      '<span class="c-idx">' + pad(i) + '</span>' +
      '<span class="c-size">' + esc(it.sizeText) + '</span>' +
      '<span class="c-time">' + esc(it.addedText) + '</span>' +
      '<span class="c-seed ' + tier(it.seeders) + '">' + fmtCount(it.seeders) + '</span>' +
      '<span class="c-title" title="' + esc(it.title) + '">' + title + chev + '</span>' +
      '<span class="c-src" title="' + esc(src) + '">' + esc(src) + '</span></div>';
  }

  function skelHtml(){
    var left = st.srcList.length - (st.done || 0);
    var n = left > 0 ? Math.max(3, Math.min(8, left)) : 6;
    var sk = '<div class="skel"><div class="col"><i></i><i></i></div></div>';
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
      if (st.busy){
        rowsEl.innerHTML = skelHtml();
      } else {
        rowsEl.innerHTML = '<div class="empty">' + EMPTY_IC +
          (st.searched ? "没有搜到相关结果" : "输入关键词开始搜索") +
          '</div>';
      }
      return;
    }
    rowsEl.innerHTML = list.map(function(it, i){
      return rowHtml(it, i, false);
    }).join("") + (st.busy ? skelHtml() : "");
    paintCursor();
    renderPanels();
  }

  function appendRows(count){
    rowsEl.querySelectorAll(".empty, .skel").forEach(function(n){ n.remove(); });
    var list = visible();
    var start = Math.max(0, list.length - count);
    var frag = document.createElement("div");
    frag.innerHTML = list.slice(start).map(function(it, i){
      return rowHtml(it, start + i, true);
    }).join("");
    if (st.busy){
      var tmp = document.createElement("div");
      tmp.innerHTML = skelHtml();
      while (tmp.firstChild) frag.appendChild(tmp.firstChild);
    }
    while (frag.firstChild) rowsEl.appendChild(frag.firstChild);
    renumber();
  }

  function renumber(){
    [].slice.call(rowsEl.querySelectorAll(".srow .c-idx")).forEach(function(el, i){
      el.textContent = pad(i);
    });
  }

  function updateSelUI(still){
    [].slice.call(rowsEl.querySelectorAll(".srow")).forEach(function(row){
      row.classList.toggle("sel", !!st.sel[row.dataset.hash]);
    });
    var list = visible();
    var n = list.filter(function(it){ return st.sel[it.hash]; }).length;
    var all = n > 0 && n === list.length;
    ckAllEl.classList.toggle("on", all);
    ckAllEl.innerHTML = all ? ICONS.check : "";
    paintBadge(still);
    if (selbarEl){
      selbarEl.querySelector("#selN").textContent = n;
      selbarEl.classList.toggle("show", st.selbarOn && n > 0);
    }
  }

  function paintCursor(){
    if (!rowsEl) return;
    var rows = rowsEl.querySelectorAll(".srow");
    if (st.cursor >= rows.length) st.cursor = rows.length - 1;
    [].slice.call(rows).forEach(function(row, i){
      row.classList.toggle("cursor", i === st.cursor);
    });
    if (st.cursor >= 0 && rows[st.cursor]) rows[st.cursor].scrollIntoView({block:"nearest"});
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
    var html = order.map(function(k){
      var ss = st.strip[k] || {state:"pending"};
      if (ss.state === "ok" || ss.state === "err" ||
          ss.state === "empty" || ss.state === "cancel" ||
          ss.state === "warn") done++;
      var label =
        ss.state === "ok" ? "<b>" + ss.count + "</b> 条" :
        ss.state === "empty" ? "无结果" :
        ss.state === "err" ? esc(ss.err || "失败") :
        ss.state === "warn" ? (ss.count
          ? "<b>" + ss.count + "</b> 条" + (ss.err ? " · " + esc(ss.err) : "")
          : esc(ss.err || "提示")) :
        ss.state === "cancel" ? "已取消" : "等待";
      var name = st.names[k] || k;
      return '<span class="stile ' + ss.state + '"><i class="sdot"></i>' + esc(name) + ' · ' + label + '</span>';
    }).join("");
    var total = st.total || order.length;
    html += '<span class="scount"><b>' + done + '</b> / ' + total + ' 完成</span>';
    stripEl.innerHTML = html;
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
      '<button class="mi" data-a="dl">' + ICONS.dl + '发送到下载工具</button>';
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

  function doCopy(){
    var list = selList();
    if (!list.length) return;
    var text = magnetsOf(list).join("\n");
    if (!text){
      HC.motion.toast("选中项没有可用的磁力链接", "err");
      return;
    }
    HC.motion.copy(text).then(function(ok){
      if (ok) flash(list.length > 1 ? "已复制 " + list.length + " 条磁力" : "已复制磁力链接", "ok");
      else HC.motion.toast("复制失败", "err");
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
    HC.motion.copy(text).then(function(ok){
      if (ok) flash(list.length > 1 ? "已复制 " + list.length + " 个标题" : "已复制标题", "ok");
      else HC.motion.toast("复制失败", "err");
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
    HC.api.deliver(magnets).then(function(r){
      flash(r.message || (r.ok ? "已提交" : "投递失败"), r.ok ? "ok" : "err");
    });
  }

  function reset(){
    st.items = [];
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
    st.done = 0;
    st.total = 0;
    st.searched = false;
    nohashSeq = 0;
    renderTip();
  }

  function setProgress(){
    if (!progEl || !st.total) return;
    progEl.style.setProperty("--p", String(Math.min(1, st.done / st.total)));
  }

  function stopProgress(){
    if (!progEl) return;
    progEl.classList.remove("on");
    progEl.classList.remove("wait");
  }

  function go(){
    if (st.hero){
      var heroInp = document.getElementById("heroInp");
      if (heroInp && heroInp.value.trim()) inp.value = heroInp.value.trim();
      hideHero();
    }
    if (st.busy){
      HC.api.cancelSearch(st.token);
      st.busy = false;
      Object.keys(st.strip).forEach(function(k){
        if (st.strip[k].state === "pending" || st.strip[k].state === "busy") st.strip[k] = {state:"cancel"};
      });
      paintStrip();
      goBtn.textContent = "搜索";
      goBtn.classList.remove("stop");
      stopProgress();
      chipIdle();
      flash("已停止搜索", "warn");
      renderRows();
      paintBadge();
      return;
    }
    var q = inp.value.trim();
    if (!q) return;
    st.query = q;
    st.qphrase = q.toLowerCase();
    st.qtokens = st.qphrase.split(/\s+/).filter(Boolean);
    st.hlRe = st.qtokens.length
      ? new RegExp(st.qtokens.slice().sort(function(a, b){ return b.length - a.length; })
          .map(function(t){ return reEscape(esc(t)); }).join("|"), "gi")
      : null;
    reset();
    st.srcList.forEach(function(s){ st.strip[s.key] = {state:"pending"}; });
    st.busy = true;
    renderRows();
    paintStrip();
    paintBadge();
    setChip("搜索中…", "busy");
    goBtn.textContent = "停止";
    goBtn.classList.add("stop");
    progEl.classList.add("on", "wait");
    progEl.style.setProperty("--p", "0");
    HC.api.startSearch(q).then(function(res){
      if (!res || !res.ok){
        st.busy = false;
        goBtn.textContent = "搜索";
        goBtn.classList.remove("stop");
        stopProgress();
        chipIdle();
        if (res && res.error) HC.motion.toast(res.error, "err");
        renderRows();
        return;
      }
      st.token = res.token;
      st.total = res.total;
      progEl.classList.remove("wait");
      setProgress();
      setChip("搜索中 0/" + res.total + "…", "busy");
    }).catch(function(err){
      st.busy = false;
        goBtn.textContent = "搜索";
        goBtn.classList.remove("stop");
        stopProgress();
        chipIdle();
        HC.motion.toast(err && err.message ? err.message : String(err), "err");
      renderRows();
    });
  }

  function searchDone(){
    st.busy = false;
    st.searched = true;
    goBtn.textContent = "搜索";
    goBtn.classList.remove("stop");
    stopProgress();
    st.errors = st.errors || {};
    var fails = Object.keys(st.errors).filter(function(k){ return k; }).length;
    var total = st.items.length;
    if (fails) setChip(total + " 条 · " + fails + " 个源失败", "warn");
    else if (!total) setChip("没有找到结果", "");
    else setChip("搜索完成 · " + total + " 条", "ok");
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
          '<button class="gobtn" id="heroGo">搜索</button>' +
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
    updateSelUI(true);
  }

  function mount(mountEl){
    root = document.createElement("div");
    root.className = "app";

    root.innerHTML =
      '<div class="card">' +
        '<div class="bar">' +
          '<button class="cb" id="ckAll"></button>' +
          '<span class="allabel">全选</span>' +
          '<span class="badge" id="badge" style="margin-left:10px">共 0 条</span>' +
          '<div class="chipwrap" style="margin-left:6px">' +
            '<button class="chipbtn" id="chip">已启用 0/0 个源</button>' +
            '<div class="chiptip" id="tip"></div>' +
          '</div>' +
          '<div class="spacer"></div>' +
          '<div class="sentry">' + ICONS.search +
            '<input id="inp" placeholder="输入搜索内容" autocomplete="off">' +
            '<button class="gobtn" id="goBtn">搜索</button>' +
          '</div>' +
          '<button class="iconbtn" id="btnSrc" title="数据源">' + ICONS.srclist + '</button>' +
          '<button class="iconbtn" id="btnCfg" title="设置">' + ICONS.gear + '</button>' +
        '</div>' +
        '<div class="progress" id="prog"><div class="fill"></div></div>' +
        '<div class="srcstrip" id="srcstrip" hidden></div>' +
        '<div class="div"></div>' +
        '<div class="shead" id="shead">' + headHtml() + '</div>' +
        '<div class="rows" id="rows"></div>' +
      '</div>';

    mountEl.appendChild(root);
    rowsEl = root.querySelector("#rows");
    badgeEl = root.querySelector("#badge");
    chipEl = root.querySelector("#chip");
    tipEl = root.querySelector("#tip");
    ckAllEl = root.querySelector("#ckAll");
    inp = root.querySelector("#inp");
    goBtn = root.querySelector("#goBtn");
    headEl = root.querySelector("#shead");
    progEl = root.querySelector("#prog");
    stripEl = root.querySelector("#srcstrip");
    badgeEl.innerHTML = badgeHtml();

    refreshSources();

    HC.api.onSearch({
      source: function(d){
        if (!st.busy || d.token !== st.token) return;
        st.done += 1;
        setProgress();
        var name = st.names[d.key] || d.key;
        var ss = d.state || (d.err ? "err" : (d.count ? "ok" : "empty"));
        if (ss === "err"){
          st.lines.push({text: name + "：失败（" + (d.err || "请求失败") + "）", bad: true});
          setChip(name + " 失败", "warn");
          st.strip[d.key] = {state:"err", err:d.err};
        } else if (ss === "empty"){
          st.lines.push({text: name + "：无结果", bad: false});
          setChip(name + " 无结果", "");
          st.strip[d.key] = {state:"empty"};
        } else if (ss === "warn"){
          var why = d.err || "提示";
          st.lines.push({text: name + "：" + why, bad: false});
          setChip(name + " " + why, "warn");
          st.strip[d.key] = {state:"warn", err:d.err, count:d.count};
        } else {
          st.lines.push({text: name + "：" + d.count + " 条", bad: false});
          setChip(name + " " + d.count + " 条", "busy");
          st.strip[d.key] = {state:"ok", count:d.count};
        }
        renderTip();
        paintStrip();
      },
      batch: function(d){
        if (!st.busy || d.token !== st.token) return;
        var fresh = 0, touched = false;
        d.items.forEach(function(it){
          if (!it.hash) it.hash = "nohash-" + (++nohashSeq);
          var pos = indexOfHash(it.hash);
          if (pos >= 0){
            st.items[pos] = it;
            touched = true;
          } else {
            st.items.push(it);
            fresh++;
          }
        });
        if (st.field || touched){
          renderRows();
          updateSelUI();
        } else {
          appendRows(fresh);
        }
        paintBadge();
        autoExpand(AUTO_EARLY, false);
      },
      done: function(d){
        if (!st.busy || d.token !== st.token) return;
        st.errors = d.errors || {};
        var fatal = st.errors[""];
        if (fatal){
          st.lines.unshift({text: fatal, bad: true});
          renderTip();
          tipEl.classList.add("show");
        }
        searchDone();
      }
    });

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
    chipEl.onclick = function(){
      location.hash = "sources";
    };
    chipEl.addEventListener("mouseenter", function(){
      if (st.lines.length) tipEl.classList.add("show");
    });
    chipEl.addEventListener("mouseleave", function(){
      tipEl.classList.remove("show");
    });
    chipEl.addEventListener("focus", function(){
      if (st.lines.length) tipEl.classList.add("show");
    });
    chipEl.addEventListener("blur", function(){
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
          h: row.dataset.hash,
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
        if (sp.l < r && sp.r > l && sp.t < b && sp.b > t) st.sel[sp.h] = true;
        else delete st.sel[sp.h];
      });
      updateSelUI();
    }

    rowsEl.addEventListener("pointerdown", function(e){
      if (e.button !== 0) return;
      justMarqueed = false;
      if (e.shiftKey || e.ctrlKey || e.metaKey) return;
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
    rowsEl.addEventListener("pointerup", endMarquee);
    rowsEl.addEventListener("pointercancel", endMarquee);

    rowsEl.addEventListener("dblclick", function(e){
      var row = e.target.closest(".srow");
      if (!row) return;
      if (!st.sel[row.dataset.hash]){
        st.sel = {};
        st.sel[row.dataset.hash] = true;
        st.anchor = row.dataset.hash;
        updateSelUI();
      }
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
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")){
        e.preventDefault();
        var heroInp = st.hero ? document.getElementById("heroInp") : null;
        (heroInp || inp).focus();
        return;
      }
      if (st.hero) return;
      if (tag === "input" || tag === "textarea") return;
      var list = visible();
      if (!list.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp"){
        e.preventDefault();
        var dir = e.key === "ArrowDown" ? 1 : -1;
        if (st.cursor < 0) st.cursor = dir > 0 ? 0 : list.length - 1;
        else st.cursor = Math.max(0, Math.min(list.length - 1, st.cursor + dir));
        paintCursor();
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
      '<button class="sbtn primary" data-s="dl">发送下载</button>' +
      '<span class="ssp"></span>' +
      '<button class="sclose" data-s="close">' +
        '<svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>' +
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
    HC.api.onLive(refreshSources);
    HC.api.onLive(function(){
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
