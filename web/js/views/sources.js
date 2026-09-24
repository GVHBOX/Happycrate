(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var api = HC.api, store = HC.store, M = HC.motion;
  var esc = M.esc;

  var ICON = {
    drag:'<svg width="12" height="16" viewBox="-2 0 16 16" fill="none"><circle cx="3" cy="3" r="1.2" fill="currentColor"/><circle cx="9" cy="3" r="1.2" fill="currentColor"/><circle cx="3" cy="8" r="1.2" fill="currentColor"/><circle cx="9" cy="8" r="1.2" fill="currentColor"/><circle cx="3" cy="13" r="1.2" fill="currentColor"/><circle cx="9" cy="13" r="1.2" fill="currentColor"/></svg>',
    info:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><circle cx="7" cy="7" r="5.4" stroke="currentColor" stroke-width="1.3"/><path d="M7 6.3v3.4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="7" cy="4.3" r=".8" fill="currentColor"/></svg>',
    bolt:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M7.7 1.4L3.1 7.8h3.2l-.5 4.8 4.9-6.6H7.4l.3-4.6Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    load:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><circle cx="7" cy="7" r="5.2" stroke="currentColor" stroke-width="1.6" stroke-dasharray="25 8" stroke-linecap="round"/></svg>',
    close:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    list:'<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4.6 4.4h9M4.6 8h9M4.6 11.6h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="2.3" cy="4.4" r="1" fill="currentColor"/><circle cx="2.3" cy="8" r="1" fill="currentColor"/><circle cx="2.3" cy="11.6" r="1" fill="currentColor"/></svg>',
    copy:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><rect x="4.6" y="4.6" width="7" height="7" rx="1.4" stroke="currentColor" stroke-width="1.3"/><path d="M9.4 4.6V3.6a1 1 0 0 0-1-1H3.6a1 1 0 0 0-1 1v4.8a1 1 0 0 0 1 1h1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    chev:'<svg width="10" height="10" viewBox="-3 -3 16 16" fill="none"><path d="M2 3.5 L5 6.5 L8 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };

  function healthClass(s){
    if (s.probing) return "na";
    return s.health.state || "na";
  }

  function healthText(s){
    if (s.probing) return '<span class="d">·</span><span class="d">·</span><span class="d">·</span>';
    var h = s.health;
    if (h.state === "err") return esc(h.err || "异常");
    if (h.state === "empty") return esc(h.err || "无结果");
    if (h.err && h.state !== "na") return esc(h.err);
    if (h.state === "na" || !h.ms) return "—";
    return h.ms >= 1000 ? (h.ms / 1000).toFixed(1) + "s" : h.ms + "ms";
  }

  function rowHtml(s, i, st){
    var anim = st.firstPaint
      ? "animation:rowIn .3s var(--land) both " + Math.min(i, 10) * 28 + "ms;"
      : "";

    return '<div class="row' + (s.enabled ? "" : " off") + '" data-key="' + esc(s.key) + '" style="' + anim + '">' +
      '<span class="handle" data-drag="' + esc(s.key) + '">' + ICON.drag + '</span>' +
      '<span><button class="sw ' + (s.enabled ? "" : "off") + '" aria-pressed="' + (s.enabled ? "true" : "false") + '" aria-label="' + esc(s.label) + '" data-sw="' + esc(s.key) + '"></button></span>' +
      '<span class="namecell"><span class="name">' + esc(s.label) + '</span>' +
        '<div class="addr">' + esc(s.addr) + '</div></span>' +
      '<span class="health"><span class="ms ' + healthClass(s) + (s.just ? " up" : "") + '">' +
        healthText(s) + '</span><span class="hd ' + healthClass(s) + '"></span></span>' +
      '</div>';
  }

  var openModal = HC.motion.openModal;
  var closeModal = HC.motion.closeModal;

  var SEMANTIC = {
    ok: "ok", slow: "ok", http429: "warn", http4xx: "warn",
    empty: "empty", na: "na",
    timeout: "err", net: "err", http403: "err", http5xx: "err",
    err: "err", warn: "warn", cancel: "na", fail: "err", parse: "warn",
    http451: "err", blocked: "err", shape: "warn", unknown: "warn"
  };

  function highlightJson(text){
    return esc(text).replace(
      /(&quot;(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\])*?&quot;(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
      function(match, _all, colon){
        if (match.indexOf("&quot;") === 0){
          if (colon) return '<span class="jk">' + match + '</span>';
          var inner = match.slice(6, -6);
          var tone = SEMANTIC[inner];
          return '<span class="' + (tone ? "js js-" + tone : "js") + '">' + match + '</span>';
        }
        if (/^(?:true|false|null)$/.test(match)) return '<span class="jb">' + match + '</span>';
        return '<span class="jn">' + match + '</span>';
      });
  }

  function showBadModal(){
    Promise.all([api.sourceIssues(), api.diagnostics([])]).then(function(res){
      var issues = res[0] || [];
      var detail = res[1] || "";
      if (!issues.length && !detail){ M.toast("没有异常源"); return; }

      var body = issues.map(function(it){
        return '<div class="issue"><span class="ib ' + esc(it.kind) + '"></span>' +
          '<div class="ibody"><div class="ihead">' + esc(it.label) +
            '<span class="iaddr">' + esc(it.addr) + '</span></div>' +
          '<div class="iline">' + esc(it.detail) + '</div></div></div>';
      }).join("");

      var logBlock = detail
        ? '<details class="logbox"><summary>' + ICON.chev + '诊断原文</summary>' +
          '<pre class="term selectable scroll-slim">' + highlightJson(detail) + '</pre></details>'
        : "";

      var m = openModal(
        '<div class="dhead"><div class="tile">' + ICON.info + '</div>' +
        '<div class="dtitle">异常详情</div><div class="spacer"></div>' +
        '<button class="iconbtn" data-close>' + ICON.close + '</button></div>' +
        '<div class="div"></div>' +
        '<div class="mbody"><div class="issues">' + body + '</div>' + logBlock + '</div>' +
        '<div class="mfoot"><div class="spacer"></div>' +
          '<button class="btn btn-ghost" data-close>关闭</button>' +
          '<button class="btn btn-brand" id="mCopy">' + ICON.copy + '复制诊断信息</button></div>',
        true
      );
      m.querySelector("#mCopy").onclick = function(){
        var btn = this;
        M.copy(detail).then(function(ok){
          if (ok) M.morph(btn, "已复制");
          else M.toast("复制失败", "err");
        });
      };
    }).catch(function(e){
      M.toast(String(e && e.message ? e.message : e), "err");
    });
  }

  var root = null, rowsEl = null, autoOrder = true;

  function paintAuto(){
    var b = root && root.querySelector("#btnAuto");
    if (b) b.classList.toggle("on", autoOrder);
  }

  function reload(){
    api.listSources().then(function(list){
      store.set({sources: list});
    });
  }

  function renderRows(){
    var st = store.get();
    var list = store.visible();
    rowsEl.innerHTML = "";
    list.forEach(function(s, i){
      var wrap = document.createElement("div");
      wrap.innerHTML = rowHtml(s, i, st);
      rowsEl.appendChild(wrap.firstChild);
    });
    if (!list.length){
      var empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = st.filter ? "没有匹配的数据源" : "还没有数据源";
      rowsEl.appendChild(empty);
    }
    st.firstPaint = false;
  }

  function updateStatus(){
    var st = store.get();
    var list = store.visible();
    var badge = store.badCount();

    var statusEl = root.querySelector("#status");
    if (st.probing){
      statusEl.innerHTML = "正在测速… " + st.probeDone + "/" + st.probeTotal;
    } else {
      var prefix = st.filter
        ? "匹配 " + list.length + " / " + st.sources.length + " 个源"
        : "共 " + st.sources.length + " 个源";
      var emptyN = store.emptyCount();
      statusEl.innerHTML = prefix + " · 已启用 " + store.enabledCount() + " 个" +
        (badge ? ' · <a class="badlink" href="#">' + badge + " 个异常</a>" : "") +
        (emptyN ? ' · <span class="muted">' + emptyN + " 个无结果</span>" : "");
    }
  }

  function render(){
    if (!root) return;
    renderRows();
    updateStatus();
  }

  function mount(mountEl){
    root = document.createElement("div");
    root.className = "app";
    root.innerHTML =
      '<div class="card">' +
        '<div class="dhead"><div class="tile">' + ICON.list + '</div>' +
          '<div class="dtitle">数据源管理</div><div class="spacer"></div>' +
          '<button class="iconbtn" id="btnClose" title="关闭">' + ICON.close + '</button></div>' +
        '<div class="div"></div>' +
        '<div class="bar">' +
          '<div class="group">' +
            '<button class="btn btn-ghost" id="btnProbe"><span class="i-bolt">' + ICON.bolt + '</span><span class="i-load">' + ICON.load + '</span>测速</button>' +
            '<button class="btn btn-ghost" id="btnAuto">自动排序</button>' +
          '</div>' +
          '<div class="spacer"></div>' +
          '<div class="search"><svg width="14" height="14" viewBox="-1 -1 16 16" fill="none">' +
            '<circle cx="6" cy="6" r="4.6" stroke="currentColor" stroke-width="1.4"/>' +
            '<path d="M9.6 9.6L12.6 12.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>' +
            '<input id="search" placeholder="搜索源名称或地址" autocomplete="off"></div>' +
        '</div>' +
        '<div class="thead"><span></span><span>启用</span><span>数据源</span>' +
          '<span class="r">状态</span></div>' +
        '<div class="rows" id="rows"></div>' +
        '<div class="dfoot"><div class="dot"></div><span class="status" id="status"></span>' +
          '<div class="spacer"></div>' +
        '</div>' +
      '</div>' +
      '<div class="caption" id="caption"></div>';

    mountEl.appendChild(root);
    rowsEl = root.querySelector("#rows");

    api.appInfo().then(function(info){
      root.querySelector("#caption").textContent =
        "happycrate v" + info.version + " · 数据源管理 · " +
        (api.mode() === "mock" ? "原型模式（mock 数据）" : "数据目录 " + info.dataDir);
      autoOrder = info.autoOrder !== false;
      paintAuto();
    }).catch(function(e){
      root.querySelector("#caption").textContent =
        "版本信息读取失败 · " + String(e && e.message ? e.message : e);
    });

    api.selftest().then(function(r){
      if (!r.ok && r.missing && r.missing.length){
        M.toast("后端返回结构不匹配 · 缺少 " + r.missing.join("、"), "long");
      }
    }).catch(function(){});

    root.querySelector("#search").addEventListener("input", function(){
      store.set({filter: this.value});
    });

    root.querySelector("#btnAuto").onclick = function(){
      autoOrder = !autoOrder;
      paintAuto();
      api.setAutoOrder(autoOrder);
    };

    root.querySelector("#btnProbe").onclick = function(){
      var st = store.get();
      if (st.probing) return;
      var targets = st.sources.filter(function(s){ return s.enabled; });
      if (!targets.length){ M.toast("没有启用的数据源可测"); return; }
      store.set({probing: true, probeDone: 0, probeTotal: targets.length});
      root.querySelector("#btnProbe").classList.add("busy");
      targets.forEach(function(s){ s.probing = true; });
      render();

      api.onProbeDone(function(){
        store.set({probing: false});
        root.querySelector("#btnProbe").classList.remove("busy");
        render();
      });

      api.probeSources(null, function(key, res){
        var s = store.byKey(key);
        if (!s) return;
        s.probing = false;
        s.just = true;
        s.health = {state: res.state, ms: res.ms, err: res.err, times: s.health.times};
        store.set({probeDone: store.get().probeDone + 1});
      });
    };

    rowsEl.addEventListener("click", function(e){
      var sw = e.target.closest("[data-sw]");
      if (!sw) return;
      var key = sw.dataset.sw, s = store.byKey(key);
      if (!s) return;
      s.enabled = !s.enabled;
      sw.classList.toggle("off", !s.enabled);
      sw.closest(".row").classList.toggle("off", !s.enabled);
      api.toggleSource(key, s.enabled);
      updateStatus();
    });

    M.dragRows(rowsEl, {
      blocked: function(){ return !!store.get().filter.trim(); },
      onDrop: function(key, target){
        var st = store.get();
        var from = st.sources.findIndex(function(s){ return s.key === key; });
        if (from < 0) return;
        var next = st.sources.slice();
        var item = next.splice(from, 1)[0];
        var to = target > from ? target - 1 : target;
        next.splice(to, 0, item);
        store.set({sources: next});
        api.reorderSources(next.map(function(s){ return s.key; }));
      }
    });

    if (mount._docKey) document.removeEventListener("keydown", mount._docKey);
    mount._docKey = function(e){
      if (e.key !== "Escape") return;
      if (!root || !root.isConnected) return;
      if (document.querySelector(".backdrop")){ closeModal(); return; }
      var tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      location.hash = "search";
    };
    document.addEventListener("keydown", mount._docKey);

    root.addEventListener("click", function(e){
      if (!e.target.closest(".badlink")) return;
      e.preventDefault();
      showBadModal();
    });

    root.querySelector("#btnClose").onclick = function(){
      location.hash = "search";
    };

    store.subscribe(render);
    api.onLive(reload);
    reload();
  }

  HC.views.sources = {mount: mount};
})();
