(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var GRID = "var(--cw-idx) var(--cw-size) var(--cw-time) var(--cw-seed) minmax(0,1fr) var(--cw-src)";
  var SORTS = {size:"体积", added:"时间", seeders:"做种"};

  var ICONS = {
    search: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<circle cx="6" cy="6" r="4.6" stroke="currentColor" stroke-width="1.4"/>' +
      '<path d="M9.6 9.6L12.6 12.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    gear: '<svg width="15" height="15" viewBox="0 0 15 15" fill="none">' +
      '<circle cx="7.5" cy="7.5" r="2.2" stroke="currentColor" stroke-width="1.3"/>' +
      '<path d="M7.5 1.6v1.7M7.5 11.7v1.7M1.6 7.5h1.7M11.7 7.5h1.7M3.4 3.4l1.2 1.2M10.4 10.4l1.2 1.2M11.6 3.4l-1.2 1.2M4.6 10.4l-1.2 1.2" ' +
      'stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    check: '<svg width="10" height="10" viewBox="0 0 14 14" fill="none">' +
      '<path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    copy: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<rect x="4.6" y="4.6" width="7" height="7" rx="1.4" stroke="currentColor" stroke-width="1.3"/>' +
      '<path d="M9.4 2.6H3.4A1.4 1.4 0 0 0 2 4v6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    dl: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<path d="M7 2.4v6.4M4.4 6.4L7 9l2.6-2.6" stroke="currentColor" stroke-width="1.3" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="M2.6 11.4h8.8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
  };

  var st = {
    items: [], sel: {}, anchor: "",
    field: "", desc: false,
    busy: false, searched: false,
    token: 0, done: 0, total: 0,
    errors: {}, names: {},
    enabledCount: 0, totalSources: 0,
    lines: [], flash: false, flashT: null
  };

  var root, rowsEl, badgeEl, chipEl, tipEl, ckAllEl, inp, goBtn, headEl;

  function esc(t){
    return String(t === undefined || t === null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

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
    if (!st.field) return st.items;
    return st.items.slice().sort(function(a, b){
      var x = Number(a[st.field]) || 0, y = Number(b[st.field]) || 0;
      return st.desc ? y - x : x - y;
    });
  }

  function selList(){
    return visible().filter(function(it){ return st.sel[it.hash]; });
  }

  function selCount(){ return selList().length; }

  function badgeText(){
    var n = selCount(), total = st.items.length;
    return n ? "已选中 " + n + " 条 / 共 " + total + " 条" : "共 " + total + " 条";
  }

  function paintBadge(){
    if (st.flash) return;
    badgeEl.className = "badge";
    badgeEl.textContent = badgeText();
  }

  function flash(text, kind){
    badgeEl.textContent = text;
    badgeEl.className = "badge " + (kind || "");
    st.flash = true;
    clearTimeout(st.flashT);
    st.flashT = setTimeout(function(){
      st.flash = false;
      paintBadge();
    }, 2500);
  }

  function setChip(text, kind){
    chipEl.textContent = text;
    chipEl.className = "chipbtn" + (kind ? " " + kind : "");
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

  function rowHtml(it, i, animate){
    var cls = "srow" + (st.sel[it.hash] ? " sel" : "");
    var anim = animate
      ? ' style="animation:rowIn .46s var(--land) both ' + Math.min(i, 12) * 38 + 'ms"'
      : "";
    var src = (it.sources || []).map(function(k){
      return st.names[k] || k;
    }).join(" · ");
    return '<div class="' + cls + '" data-hash="' + esc(it.hash) + '"' + anim + '>' +
      '<span class="c-idx">' + pad(i) + '</span>' +
      '<span class="c-size">' + esc(it.sizeText) + '</span>' +
      '<span class="c-time">' + esc(it.addedText) + '</span>' +
      '<span class="c-seed ' + tier(it.seeders) + '">' + fmtCount(it.seeders) + '</span>' +
      '<span class="c-title" title="' + esc(it.title) + '">' + esc(it.title) + '</span>' +
      '<span class="c-src" title="' + esc(src) + '">' + esc(src) + '</span></div>';
  }

  function renderRows(){
    var list = visible();
    if (!list.length){
      rowsEl.innerHTML = '<div class="empty">' +
        (st.busy ? "正在搜索…"
          : (st.searched ? "没有搜到相关结果" : "输入关键词开始搜索")) +
        '</div>';
      return;
    }
    rowsEl.innerHTML = list.map(function(it, i){
      return rowHtml(it, i, false);
    }).join("");
  }

  function appendRows(count){
    var empty = rowsEl.querySelector(".empty");
    if (empty) empty.remove();
    var list = visible();
    var start = Math.max(0, list.length - count);
    var frag = document.createElement("div");
    frag.innerHTML = list.slice(start).map(function(it, i){
      return rowHtml(it, i, true);
    }).join("");
    while (frag.firstChild) rowsEl.appendChild(frag.firstChild);
    renumber();
  }

  function renumber(){
    [].slice.call(rowsEl.querySelectorAll(".srow .c-idx")).forEach(function(el, i){
      el.textContent = pad(i);
    });
  }

  function updateSelUI(){
    [].slice.call(rowsEl.querySelectorAll(".srow")).forEach(function(row){
      row.classList.toggle("sel", !!st.sel[row.dataset.hash]);
    });
    var n = selCount(), list = visible();
    ckAllEl.classList.toggle("on", n > 0 && n === list.length);
    ckAllEl.innerHTML = (n > 0 && n === list.length) ? ICONS.check : "";
    paintBadge();
  }

  function arrow(k){
    return st.field === k
      ? '<span class="up">' + (st.desc ? "↓" : "↑") + '</span>'
      : "";
  }

  function headHtml(){
    return '<span class="r">序号</span>' +
      '<span class="sort r" data-sort="size">体积' + arrow("size") + '</span>' +
      '<span class="sort r" data-sort="added">时间' + arrow("added") + '</span>' +
      '<span class="sort r" data-sort="seeders">做种' + arrow("seeders") + '</span>' +
      '<span class="r">文件名称</span>' +
      '<span class="r">来源</span>';
  }

  var ctxEl = null;

  function closeCtx(){
    if (ctxEl){
      ctxEl.remove();
      ctxEl = null;
    }
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
    st.errors = {};
    st.lines = [];
    st.done = 0;
    st.searched = false;
    renderTip();
  }

  function go(){
    if (st.busy){
      HC.api.cancelSearch(st.token);
      st.busy = false;
      goBtn.textContent = "搜索";
      goBtn.classList.remove("stop");
      chipIdle();
      flash("已停止搜索", "warn");
      renderRows();
      paintBadge();
      return;
    }
    var q = inp.value.trim();
    if (!q) return;
    reset();
    st.busy = true;
    renderRows();
    paintBadge();
    setChip("搜索中…", "busy");
    goBtn.textContent = "停止";
    goBtn.classList.add("stop");
    HC.api.startSearch(q).then(function(res){
      if (!res || !res.ok){
        st.busy = false;
        goBtn.textContent = "搜索";
        goBtn.classList.remove("stop");
        chipIdle();
        if (res && res.error) HC.motion.toast(res.error, "err");
        renderRows();
        return;
      }
      st.token = res.token;
      st.total = res.total;
      setChip("搜索中 0/" + res.total + "…", "busy");
    });
  }

  function searchDone(){
    st.busy = false;
    st.searched = true;
    goBtn.textContent = "搜索";
    goBtn.classList.remove("stop");
    st.errors = st.errors || {};
    var fails = Object.keys(st.errors).length;
    var total = st.items.length;
    if (fails) setChip(total + " 条 · " + fails + " 个源失败", "warn");
    else setChip("搜索完成 · " + total + " 条", "ok");
    renderRows();
    paintBadge();
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
            '<input id="inp" placeholder="输入关键字，空格分隔多个词" autocomplete="off">' +
            '<button class="gobtn" id="goBtn">搜索</button>' +
          '</div>' +
          '<button class="iconbtn" id="btnCfg" title="设置">' + ICONS.gear + '</button>' +
        '</div>' +
        '<div class="div"></div>' +
        '<div class="shead" id="shead" style="grid-template-columns:' + GRID + '">' + headHtml() + '</div>' +
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

    function refreshSources(){
      HC.api.listSources().then(function(list){
        st.names = {};
        st.enabledCount = 0;
        (list || []).forEach(function(s){
          st.names[s.key] = s.label;
          if (s.enabled) st.enabledCount++;
        });
        st.totalSources = (list || []).length;
        if (!st.busy) chipIdle();
      });
    }

    refreshSources();
    if (HC.api.mode() === "mock"){
      var tries = 0;
      var chipTimer = setInterval(function(){
        tries++;
        if (HC.api.mode() === "live" || tries > 20){
          clearInterval(chipTimer);
          refreshSources();
        }
      }, 500);
    }

    HC.api.onSearch({
      source: function(d){
        if (!st.busy || d.token !== st.token) return;
        st.done += 1;
        var name = st.names[d.key] || d.key;
        if (d.err){
          st.lines.push({text: name + "：失败（" + d.err + "）", bad: true});
          setChip(name + " 失败", "warn");
        } else {
          st.lines.push({text: name + "：" + d.count + " 条", bad: false});
          setChip(name + " " + d.count + " 条", "busy");
        }
        renderTip();
      },
      batch: function(d){
        if (!st.busy || d.token !== st.token) return;
        d.items.forEach(function(it){ st.items.push(it); });
        if (st.field){
          renderRows();
          updateSelUI();
        } else {
          appendRows(d.items.length);
        }
        paintBadge();
      },
      done: function(d){
        if (d.token !== st.token) return;
        st.errors = d.errors || {};
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
      var row = e.target.closest(".srow");
      if (!row) return;
      var hash = row.dataset.hash;
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
        var only = selCount() === 1 && st.sel[hash];
        st.sel = only ? {} : {};
        if (!only) st.sel[hash] = true;
        st.anchor = hash;
      }
      updateSelUI();
    });

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
      var tag = (e.target && e.target.tagName || "").toLowerCase();
      if (e.key === "Escape"){
        if (ctxEl){ closeCtx(); return; }
        if (tag === "input" || tag === "textarea") return;
        st.sel = {};
        updateSelUI();
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")){
        if (tag === "input" || tag === "textarea") return;
        e.preventDefault();
        if (!visible().length) return;
        st.sel = {};
        visible().forEach(function(it){ st.sel[it.hash] = true; });
        updateSelUI();
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
    if (window.ResizeObserver) new ResizeObserver(syncScrollbar).observe(rowsBox);

    HC.views.search.st = st;
  }

  HC.views.search = { mount: mount };
})();
