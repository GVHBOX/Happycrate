(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var api = HC.api, store = HC.store, M = HC.motion;
  var esc = M.esc;

  var ICON = {
    drag:'<svg width="12" height="16" viewBox="0 0 12 16" fill="none"><circle cx="3" cy="3" r="1.2" fill="currentColor"/><circle cx="9" cy="3" r="1.2" fill="currentColor"/><circle cx="3" cy="8" r="1.2" fill="currentColor"/><circle cx="9" cy="8" r="1.2" fill="currentColor"/><circle cx="3" cy="13" r="1.2" fill="currentColor"/><circle cx="9" cy="13" r="1.2" fill="currentColor"/></svg>',
    edit:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9.6 2.1l2.2 2.2L5.2 10.9H3V8.7l6.6-6.6Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    trash:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.5 4h9M5.4 4V2.8h3.2V4M3.6 4l.6 7.2h5.6L10.4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    check:'<svg width="10" height="10" viewBox="0 0 14 14" fill="none"><path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    info:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.4" stroke="currentColor" stroke-width="1.3"/><path d="M7 6.3v3.4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="7" cy="4.3" r=".8" fill="currentColor"/></svg>',
    refresh:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.4 6.2a4.6 4.6 0 1 1 1.3 4.1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M1.6 2.6v3.9h3.9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    bolt:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7.7 1.4L3.1 7.8h3.2l-.5 4.8 4.9-6.6H7.4l.3-4.6Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    load:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.2" stroke="currentColor" stroke-width="1.6" stroke-dasharray="25 8" stroke-linecap="round"/></svg>',
    plus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2.6v8.8M2.6 7h8.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    close:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    list:'<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4.6 4.4h9M4.6 8h9M4.6 11.6h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="2.3" cy="4.4" r="1" fill="currentColor"/><circle cx="2.3" cy="8" r="1" fill="currentColor"/><circle cx="2.3" cy="11.6" r="1" fill="currentColor"/></svg>',
    export:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 9.4V2.4M4.2 5.2L7 2.4l2.8 2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.4 9.4v1.4a1 1 0 0 0 1 1h7.2a1 1 0 0 0 1-1V9.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    import:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2.4v7M4.2 6.6L7 9.4l2.8-2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.4 9.4v1.4a1 1 0 0 0 1 1h7.2a1 1 0 0 0 1-1V9.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    copy:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="4.6" y="4.6" width="7" height="7" rx="1.4" stroke="currentColor" stroke-width="1.3"/><path d="M9.4 4.6V3.6a1 1 0 0 0-1-1H3.6a1 1 0 0 0-1 1v4.8a1 1 0 0 0 1 1h1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    save:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    chev:'<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 3.5 L5 6.5 L8 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
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
    var col2 = st.batch
      ? '<button class="cb ' + (store.isChecked(s.key) ? "on" : "") + '" aria-pressed="' + (store.isChecked(s.key) ? "true" : "false") + '" data-check="' + esc(s.key) + '">' +
        (store.isChecked(s.key) ? ICON.check : "") + '</button>'
      : '<button class="sw ' + (s.enabled ? "" : "off") + '" aria-pressed="' + (s.enabled ? "true" : "false") + '" aria-label="' + esc(s.label) + '" data-sw="' + esc(s.key) +
        '"></button>';

    var ops = '<button class="op" data-edit="' + esc(s.key) + '" title="编辑">' + ICON.edit + '</button>';
    if (st.batch){
      ops += '<button class="op danger" data-del="' + esc(s.key) + '" title="删除">' + ICON.trash + '</button>';
    }

    var cls = "row" + (s.enabled ? "" : " off") +
              (st.batch && store.isChecked(s.key) ? " sel" : "");
    var anim = st.firstPaint
      ? "animation:rowIn .3s var(--land) both " + Math.min(i, 10) * 28 + "ms;"
      : "";

    return '<div class="' + cls + '" data-key="' + esc(s.key) + '" style="' + anim + '">' +
      '<span class="handle" data-drag="' + esc(s.key) + '">' + ICON.drag + '</span>' +
      '<span>' + col2 + '</span>' +
      '<span class="namecell"><span class="name">' + esc(s.label) + '</span>' +
        '<div class="addr">' + esc(s.addr) + '</div></span>' +
      '<span class="health"><span class="ms ' + healthClass(s) + (s.just ? " up" : "") + '">' +
        healthText(s) + '</span><span class="hd ' + healthClass(s) + '"></span></span>' +
      '<span class="ops">' + ops + '</span></div>';
  }

  var openModal = HC.motion.openModal;
  var closeModal = HC.motion.closeModal;

  function stepper(btnRoot, valEl, min, max){
    btnRoot.querySelectorAll("[data-step]").forEach(function(b){
      b.onclick = function(){
        var v = parseInt(valEl.textContent, 10) + parseInt(b.dataset.step, 10);
        valEl.textContent = Math.max(min, Math.min(max, v));
      };
    });
  }

  var STEP_BTN = {
    minus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 7h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 7h7M7 3.5v7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
  };

  function showErr(m, msg, okMsg){
    var el = m.querySelector("#fErr");
    if (!el) return;
    if (okMsg){
      el.style.color = "var(--ok)";
      el.textContent = okMsg;
      setTimeout(function(){ el.textContent = ""; el.style.color = ""; }, 2600);
      return;
    }
    el.style.color = "";
    el.textContent = msg || "";
    var input = m.querySelector(".input");
    if (msg && input){
      input.classList.add("err");
      setTimeout(function(){ input.classList.remove("err"); }, 1400);
    }
  }

  function editorSource(existing){
    var isEdit = !!existing;
    var d = existing || {key:"", label:"", type:"json", timeout:15, addr:"", listPath:"", map:{},
                         hashPattern:"", titlePattern:"", sizePattern:""};
    var TYPE_LABEL = {builtin:"内置", rss:"RSS", json:"JSON", html:"HTML"};
    var isBuiltin = isEdit && d.type === "builtin";
    var types = ["rss", "json", "html"];
    var fields = [["标题 *","title"],["哈希","hash"],["体积","size"],["做种","seeders"],["时间","added"],["链接","magnet"]];
    var map = d.map || {};

    var keyPromise = isEdit ? Promise.resolve(d.key) : Promise.resolve(api.nextCustomKey());

    keyPromise.then(function(newKey){
      var m = openModal(
        '<div class="dhead"><div class="tile">' + (isEdit ? ICON.edit : ICON.plus) + '</div>' +
        '<div class="dtitle">' + (isEdit ? "编辑" : "添加自定义") + '</div>' +
        '<div class="spacer"></div><button class="iconbtn" data-close>' + ICON.close + '</button></div>' +
        '<div class="div"></div>' +
        '<div class="mbody">' +
          '<div style="display:flex;align-items:center;gap:8px">' +
            '<span style="font:500 13px/1 inherit">标识</span>' +
            '<span class="idchip">' + esc(newKey) + '</span></div>' +
          '<div class="field"><label>名称</label>' +
            '<input class="input" id="fLabel" value="' + esc(d.label) + '" placeholder="我的源"></div>' +
          (isBuiltin ? "" :
            '<div class="field"><label>类型</label>' +
            '<div class="seg" id="fType" style="margin-top:8px">' +
              types.map(function(t){
                return '<button data-t="' + t + '" class="' + (d.type === t ? "on" : "") + '">' + TYPE_LABEL[t] + '</button>';
              }).join("") +
            '</div></div>') +
          '<div class="field"><label id="fAddrLabel">URL 模板</label>' +
            '<input class="input mono" id="fUrl" value="' + esc(d.addr) + '" placeholder="https://e.com/api/search?q={query}&p={page}"></div>' +
          '<div class="field" id="wPath"><label>列表路径</label>' +
            '<input class="input mono" id="fPath" value="' + esc(d.listPath) + '" placeholder="data.list"></div>' +
          '<div class="field" id="wMap"><label>字段映射</label><div class="mapgrid">' +
            fields.map(function(f){
              return '<div class="cell"><label>' + f[0] + '</label>' +
                '<input class="input mono" data-map="' + f[1] + '" value="' +
                esc(map[f[1]] || "") + '" placeholder="' + f[1] + '"></div>';
            }).join("") +
          '</div></div>' +
          '<div class="field" id="wPatH"><label>哈希正则</label>' +
            '<input class="input mono" id="fHashPat" value="' + esc(d.hashPattern) + '" placeholder="magnet:\\?xt=urn:btih:([0-9a-fA-F]{40})"></div>' +
          '<div class="field" id="wPatT"><label>标题正则</label>' +
            '<input class="input mono" id="fTitlePat" value="' + esc(d.titlePattern) + '" placeholder="&gt;([^&lt;&gt;]{4,200})\\s*&lt;"></div>' +
          '<div class="field" id="wPatS"><label>体积正则</label>' +
            '<input class="input mono" id="fSizePat" value="' + esc(d.sizePattern) + '" placeholder="&gt;([\\d.]+\\s*[KMGT]i?B)\\s*&lt;"></div>' +
          '<div class="field"><label>超时（秒）</label>' +
            '<div class="stepper" style="margin-top:8px">' +
              '<button data-step="-1">' + STEP_BTN.minus + '</button>' +
              '<span class="val" id="fTo">' + d.timeout + '</span>' +
              '<button data-step="1">' + STEP_BTN.plus + '</button>' +
            '</div></div>' +
          '<div class="ferr" id="fErr"></div>' +
        '</div>' +
        '<div class="mfoot"><div class="spacer"></div>' +
          '<button class="btn btn-ghost" data-close>取消</button>' +
          '<button class="btn btn-ghost" id="mTest">测试</button>' +
          '<button class="btn btn-brand" id="mSave">' + ICON.save + '保存</button></div>',
        true
      );

      var type = d.type;

      function syncFields(){
        var wPath = m.querySelector("#wPath"), wMap = m.querySelector("#wMap");
        var showPath = type === "json";
        var showMap = type === "rss" || type === "json";
        var showPat = type === "html";
        wPath.classList.toggle("hidden", !showPath);
        wMap.classList.toggle("hidden", !showMap);
        ["#wPatH", "#wPatT", "#wPatS"].forEach(function(id){
          m.querySelector(id).classList.toggle("hidden", !showPat);
        });
        var addr = m.querySelector("#fAddrLabel");
        if (addr) addr.textContent = type === "builtin" ? "镜像地址" : "URL 模板";
      }

      var typeBox = m.querySelector("#fType");
      if (typeBox){
        typeBox.querySelectorAll("button").forEach(function(b){
          b.onclick = function(){
            type = b.dataset.t;
            typeBox.querySelectorAll("button").forEach(function(x){ x.classList.remove("on"); });
            b.classList.add("on");
            syncFields();
          };
        });
      }
      syncFields();

      stepper(m, m.querySelector("#fTo"), 1, 120);

      function collect(){
        var out = {
          key: newKey,
          label: m.querySelector("#fLabel").value.trim(),
          type: type,
          addr: m.querySelector("#fUrl").value.trim(),
          timeout: parseInt(m.querySelector("#fTo").textContent, 10),
          enabled: existing ? existing.enabled : true,
          isNew: existing ? false : true
        };
        out.listPath = m.querySelector("#fPath") ? m.querySelector("#fPath").value.trim() : "";
        var mapOut = {};
        m.querySelectorAll("[data-map]").forEach(function(i){
          var v = i.value.trim();
          if (v) mapOut[i.dataset.map] = v;
        });
        out.map = mapOut;
        function pat(id){
          var el = m.querySelector(id);
          return el ? el.value.trim() : "";
        }
        out.hashPattern = pat("#fHashPat");
        out.titlePattern = pat("#fTitlePat");
        out.sizePattern = pat("#fSizePat");
        return out;
      }

      m.querySelector("#mTest").onclick = function(){
        var btn = this;
        btn.classList.add("busy");
        var entry = collect();
        var hard = HC.validateSource(entry, []);
        if (hard.length){
          btn.classList.remove("busy");
          showErr(m, hard[0]);
          return;
        }
        api.testSource(entry).then(function(r){
          btn.classList.remove("busy");
          if (!r.ok){ showErr(m, (r.errors && r.errors[0]) || "测试失败"); return; }
          if (r.count === 0){
            showErr(m, "返回 0 条 —— 关键词可能真无结果，也可能是站点结构或字段映射对不上");
            return;
          }
          showErr(m, "", "测试通过 · 返回 " + r.count + " 条结果");
        });
      };

      m.querySelector("#mSave").onclick = function(){
        var entry = collect();
        api.saveSource(entry).then(function(r){
          if (!r.ok){ showErr(m, r.errors[0]); return; }
          closeModal();
          reload();
          M.toast("已保存 " + entry.label, "ok");
        });
      };
    });
  }

  function confirmModal(question, okLabel, onOk){
    var m = openModal(
      '<div class="dhead"><div class="dtitle">' + esc(question) + '</div></div>' +
      '<div class="div"></div>' +
      '<div class="mfoot"><div class="spacer"></div>' +
        '<button class="btn btn-ghost" data-close>取消</button>' +
        '<button class="btn btn-danger" id="mOk">' + esc(okLabel) + '</button></div>'
    );
    m.querySelector("#mOk").onclick = function(){
      closeModal();
      onOk();
    };
  }

  var SEMANTIC = {
    ok: "ok", slow: "warn", http429: "warn", http4xx: "warn",
    empty: "empty", na: "na",
    timeout: "err", net: "err", http403: "err", http5xx: "err",
    err: "err", warn: "warn", cancel: "na", fail: "err"
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
    });
  }

  var root = null, rowsEl = null, anchor = -1, autoOrder = true;

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

    root.querySelector("#hCol2").textContent = st.batch ? "选择" : "启用";
    root.querySelector("#groupDaily").classList.toggle("hidden", st.batch);
    root.querySelector("#groupBatch").classList.toggle("hidden", !st.batch);
    root.querySelector("#groupBatchOps").classList.toggle("hidden", !st.batch);
    root.querySelector(".search").classList.toggle("hidden", st.batch);

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

    root.querySelector("#batchInfo").textContent = "已选 " + st.checked.length + " 项";
    root.querySelector("#btnDel").disabled = st.checked.length === 0;
  }

  function render(){
    if (!root) return;
    renderRows();
    updateStatus();
  }

  function rowIndexOf(row){
    return [].slice.call(rowsEl.querySelectorAll(".row")).indexOf(row);
  }

  function setChecked(key, on){
    var has = store.isChecked(key);
    if (on && !has) store.get().checked.push(key);
    if (!on && has){
      var i = store.get().checked.indexOf(key);
      store.get().checked.splice(i, 1);
    }
  }

  function paintChecks(){
    var st = store.get();
    [].slice.call(rowsEl.querySelectorAll(".cb")).forEach(function(cb){
      var key = cb.dataset.check;
      var on = store.isChecked(key);
      cb.classList.toggle("on", on);
      cb.innerHTML = on ? ICON.check : "";
      cb.closest(".row").classList.toggle("sel", on);
    });
    root.querySelector("#batchInfo").textContent = "已选 " + st.checked.length + " 项";
    root.querySelector("#btnDel").disabled = st.checked.length === 0;
  }

  function onCheckClick(cb, e){
    var row = cb.closest(".row");
    var key = cb.dataset.check;
    var idx = rowIndexOf(row);
    var list = store.visible();

    if (e.shiftKey && anchor >= 0){
      store.get().checked = [];
      var a = Math.min(anchor, idx), b = Math.max(anchor, idx);
      list.slice(a, b + 1).forEach(function(s){
        setChecked(s.key, true);
      });
    } else {
      setChecked(key, !store.isChecked(key));
      anchor = idx;
    }
    paintChecks();
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
          '<div class="group" id="groupDaily">' +
            '<button class="btn btn-ghost" id="btnProbe"><span class="i-bolt">' + ICON.bolt + '</span><span class="i-load">' + ICON.load + '</span>测速</button>' +
            '<button class="btn btn-ghost" id="btnAuto">自动排序</button>' +
            '<button class="btn btn-ghost" id="btnBatch">批量操作</button>' +
            '<button class="btn btn-ghost" id="btnAdd">' + ICON.plus + '自定义源</button>' +
          '</div>' +
          '<div class="group hidden" id="groupBatch">' +
            '<button class="btn btn-brand" id="btnBatchDone">' + ICON.check + '完成</button>' +
            '<span class="status" id="batchInfo">已选 0 项</span>' +
          '</div>' +
          '<div class="spacer"></div>' +
          '<div class="search"><svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
            '<circle cx="6" cy="6" r="4.6" stroke="currentColor" stroke-width="1.4"/>' +
            '<path d="M9.6 9.6L12.6 12.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>' +
            '<input id="search" placeholder="搜索源名称或地址" autocomplete="off"></div>' +
          '<div class="group hidden" id="groupBatchOps">' +
            '<button class="btn btn-ghost" id="btnDel">删除</button>' +
            '<button class="btn btn-ghost" id="btnReset">' + ICON.refresh + '恢复默认</button>' +
            '<button class="btn btn-ghost" id="btnExport">' + ICON.export + '导出</button>' +
            '<button class="btn btn-ghost" id="btnImport">' + ICON.import + '导入</button>' +
          '</div>' +
        '</div>' +
        '<div class="thead"><span></span><span id="hCol2">启用</span><span>数据源</span>' +
          '<span class="r">状态</span><span class="r">操作</span></div>' +
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
    });

    api.selftest().then(function(r){
      if (!r.ok && r.missing && r.missing.length){
        M.toast("后端返回结构不匹配 · 缺少 " + r.missing.join("、"), "long");
      }
    });

    root.querySelector("#search").addEventListener("input", function(){
      store.set({filter: this.value});
    });

    root.querySelector("#btnAdd").onclick = function(){ editorSource(null); };

    root.querySelector("#btnAuto").onclick = function(){
      autoOrder = !autoOrder;
      paintAuto();
      api.setAutoOrder(autoOrder);
    };

    root.querySelector("#btnBatch").onclick = function(){
      anchor = -1;
      store.set({batch: true, checked: []});
    };
    root.querySelector("#btnBatchDone").onclick = function(){
      anchor = -1;
      store.set({batch: false, checked: []});
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
      if (sw){
        var key = sw.dataset.sw, s = store.byKey(key);
        s.enabled = !s.enabled;
        sw.classList.toggle("off", !s.enabled);
        sw.closest(".row").classList.toggle("off", !s.enabled);
        api.toggleSource(key, s.enabled);
        updateStatus();
        return;
      }

      var cb = e.target.closest("[data-check]");
      if (cb && !cb.disabled){
        onCheckClick(cb, e);
        return;
      }

      var ed = e.target.closest("[data-edit]");
      if (ed){
        editorSource(store.byKey(ed.dataset.edit));
        return;
      }

      var del = e.target.closest("[data-del]");
      if (del && !del.disabled){
        var dk = del.dataset.del, ds = store.byKey(dk);
        var label = ds ? ds.label : dk;
        confirmModal("删除 " + label + "？", "删除", function(){
          api.removeSource(dk).then(function(ok){
            if (!ok){ M.toast("删除失败"); return; }
            reload();
            M.toast("已删除 " + label, "ok");
          });
        });
      }
    });

    rowsEl.addEventListener("dblclick", function(e){
      var row = e.target.closest(".row");
      if (!row || store.get().batch) return;
      editorSource(store.byKey(row.dataset.key));
    });

    M.dragRows(rowsEl, {
      blocked: function(){ return store.get().batch || !!store.get().filter.trim(); },
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
        M.toast("已调整顺序", "ok");
      }
    });

    if (mount._docKey) document.removeEventListener("keydown", mount._docKey);
    mount._docKey = function(e){
      if (e.key === "Escape"){
        if (!root || !root.isConnected) return;
        if (document.querySelector(".backdrop")){ closeModal(); return; }
        var tag = (e.target && e.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        if (store.get().batch){
          anchor = -1;
          store.set({batch: false, checked: []});
          return;
        }
        location.hash = "search";
        return;
      }
      if (!root || !store.get().batch) return;
      if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")){
        var tag = (e.target && e.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        if (document.querySelector(".backdrop")) return;
        e.preventDefault();
        store.get().checked = [];
        store.visible().forEach(function(s){
          setChecked(s.key, true);
        });
        paintChecks();
      }
    };
    document.addEventListener("keydown", mount._docKey);

    root.addEventListener("click", function(e){
      if (!e.target.closest(".badlink")) return;
      e.preventDefault();
      showBadModal();
    });

    root.querySelector("#btnDel").onclick = function(){
      var st = store.get();
      if (!st.checked.length) return;
      var n = st.checked.length;
      var keys = st.checked.slice();
      confirmModal("删除 " + n + " 个源？", "删除", function(){
        Promise.all(keys.map(function(k){ return api.removeSource(k); })).then(function(){
          store.set({checked: []});
          anchor = -1;
          reload();
          M.toast("已删除 " + n + " 个源", "ok");
        }).catch(function(err){
          M.toast(err && err.message ? err.message : String(err), "err");
        });
      });
    };

    root.querySelector("#btnReset").onclick = function(){
      confirmModal("恢复默认会清掉自定义源？", "恢复", function(){
        api.resetSources().then(function(){
          store.set({filter: "", checked: []});
          anchor = -1;
          root.querySelector("#search").value = "";
          reload();
          M.toast("已恢复默认配置", "ok");
        });
      });
    };
    root.querySelector("#btnExport").onclick = function(){
      api.exportSources().then(function(r){
        M.toast(r.ok ? "已导出 " + r.path : "导出失败", "ok");
      });
    };
    root.querySelector("#btnImport").onclick = function(){
      api.importSources().then(function(r){
        if (r.ok){
          reload();
          M.toast("已导入 · 新增 " + r.added + " 个，更新 " + r.updated + " 个", "ok");
        } else {
          M.toast(r.error || "导入失败", "long");
        }
      }, function(e){
        M.toast("导入失败：" + ((e && e.message) || e || "未知错误"), "long");
      });
    };

    root.querySelector("#btnClose").onclick = function(){
      location.hash = "search";
    };

    store.subscribe(render);
    reload();
  }

  HC.views.sources = { mount: mount, reload: reload };
})();
