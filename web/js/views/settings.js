(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var FIELDS = [
    {key:"min_query_len", label:"最短关键词", group:"检索", min:1, max:20, step:1},
    {key:"max_workers", label:"并发数", group:"检索", min:1, max:32, step:1},
    {key:"timeout", label:"投递/清单超时", group:"检索", min:1, max:120, step:1, unit:"秒"},
    {key:"retries", label:"重试次数", group:"检索", min:0, max:5, step:1},
    {key:"proxy", label:"代理", group:"网络", ph:"http://127.0.0.1:7890"},
    {key:"user_agent", label:"User-Agent", group:"网络", ph:"留空用内置"},
    {key:"ui_font_size", label:"界面字号", group:"外观",
      seg:[{key:"14", label:"小"}, {key:"18", label:"标准"}, {key:"22", label:"大"}]}
  ];

  var root = null;
  var dlKey = "";
  var selbarOn = true;
  var themeOn = false;
  var autoFilesOn = true;
  var brandKey = "";

  var STEP_BTN = {
    minus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 7h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 7h7M7 3.5v7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
  };

  var esc = HC.esc;

  var netEl = null;
  var netBusy = false;

  function netState(data){
    if (!data) return {busy:true, dot:"busy", note:"检测中", muted:true};
    if (data.mode === "manual"){
      if (!data.portOk){
        return {dot:"err", title:"手动设置", addr:data.addr || "",
                note:"代理端口无响应"};
      }
      return data.works
        ? {dot:"ok", title:"手动设置", addr:data.addr || ""}
        : {dot:"err", title:"手动设置", addr:data.addr || "",
           note:"端口能连上，但代理没有转发请求"};
    }
    if (data.mode === "system"){
      if (!data.systemOn){
        return {dot:"err", title:"跟随系统", addr:data.addr || "",
                note:"系统代理已关闭", off:true};
      }
      if (!data.portOk){
        return {dot:"err", title:"跟随系统", addr:data.addr || "",
                note:"代理端口无响应"};
      }
      return data.works
        ? {dot:"ok", title:"跟随系统", addr:data.addr || ""}
        : {dot:"err", title:"跟随系统", addr:data.addr || "",
           note:"端口能连上，但代理没有转发请求"};
    }
    return {dot:"", note:"未检测到代理", muted:true};
  }

  function netPaint(data){
    if (!netEl) return;
    var s = netState(data);
    netEl.hidden = false;
    netEl.querySelector(".netdot").className = "netdot" + (s.dot ? " " + s.dot : "");
    netEl.querySelector(".nettitle").textContent = s.title || "";
    var addr = netEl.querySelector(".netaddr");
    addr.textContent = s.addr || "";
    addr.className = "netaddr" + (s.off ? " off" : "");
    var note = netEl.querySelector(".netnote");
    note.textContent = s.note || "";
    note.className = "netnote" + (s.muted ? " muted" : "");
    netEl.querySelector("#btnNetRecheck").disabled = !!s.busy;
  }

  function netCheck(){
    if (!netEl) return;
    if (typeof HC.api.proxyStatus !== "function"){
      netEl.hidden = true;
      return;
    }
    if (netBusy) return;
    netBusy = true;
    netPaint(null);
    HC.api.proxyStatus().then(function(d){
      netBusy = false;
      netPaint(d || {mode:"none"});
    }).catch(function(){
      netBusy = false;
      netEl.hidden = true;
    });
  }

  function netPlace(){
    if (!netEl) return;
    var host = root.querySelector('.sgroup[data-group="网络"]');
    if (host){
      var grid = host.querySelector(".mapgrid");
      if (grid){ host.insertBefore(netEl, grid); return; }
    }
    root.querySelector("#fields").appendChild(netEl);
  }

  function clamp(v, min, max){
    v = parseInt(v, 10);
    if (isNaN(v)) v = min;
    return Math.max(min, Math.min(max, v));
  }

  function fieldHtml(f, v){
    var id = "s_" + f.key;
    if (f.seg){
      return '<div class="field"><label for="' + id + '" id="lb_' + f.key + '">' + esc(f.label) + '</label>' +
        '<div class="seg" id="' + id + '" role="group" aria-labelledby="lb_' + f.key + '">' +
        f.seg.map(function(o){
          return '<button type="button" data-font="' + o.key + '">' + esc(o.label) + '</button>';
        }).join("") +
        '</div></div>';
    }
    if (f.min === undefined){
      return '<div class="field wide"><label for="' + id + '">' + esc(f.label) + '</label>' +
        '<input class="input' + (f.ph ? "" : " mono") + '" id="' + id +
        '" value="' + esc(v) + '" placeholder="' + esc(f.ph || "") +
        '"></div>';
    }
    return '<div class="field"><label for="' + id + '">' + esc(f.label) + '</label>' +
      '<div class="stepper numfield" data-field="' + f.key + '">' +
        '<button type="button" data-step="-1">' + STEP_BTN.minus + '</button>' +
        '<input class="val mono" id="' + id + '" inputmode="numeric" value="' + esc(v) + '">' +
        (f.unit ? '<span class="unit">' + f.unit + '</span>' : '') +
        '<button type="button" data-step="1">' + STEP_BTN.plus + '</button>' +
      '</div></div>';
  }

  function fieldsHtml(settings){
    var order = [];
    FIELDS.forEach(function(f){ if (order.indexOf(f.group) < 0) order.push(f.group); });
    return order.map(function(g){
      var list = FIELDS.filter(function(f){ return f.group === g; });
      return '<div class="sgroup g' + list.length + '" data-group="' + esc(g) + '">' +
        '<div class="sgroup-t">' + esc(g) + '</div>' +
        '<div class="mapgrid">' +
        list.map(function(f){
          return fieldHtml(f, settings[f.key]);
        }).join("") + '</div></div>';
    }).join("");
  }

  function wireSteppers(){
    root.querySelectorAll(".numfield").forEach(function(box){
      var input = box.querySelector("input");
      var min = 1, max = 100, step = 1, key = box.dataset.field;
      FIELDS.forEach(function(f){
        if (f.key === key){ min = f.min; max = f.max; step = f.step || 1; }
      });
      var btns = box.querySelectorAll("[data-step]");
      function sync(){
        var v = clamp(input.value, min, max);
        btns[0].disabled = v - step < min;
        btns[1].disabled = v + step > max;
        return v;
      }
      btns.forEach(function(b){
        b.onclick = function(){
          input.value = clamp(parseInt(input.value, 10) + parseInt(b.dataset.step, 10) * step, min, max);
          sync();
          input.dispatchEvent(new Event("input", {bubbles: true}));
        };
      });
      input.addEventListener("input", function(){
        sync();
      });
      input.addEventListener("change", function(){
        input.value = clamp(input.value, min, max);
        sync();
      });
      input.addEventListener("blur", function(){
        input.value = clamp(input.value, min, max);
        sync();
      });
      sync();
    });
  }

  function segHtml(opts, current, attr){
    return opts.map(function(o){
      var on = o.key === current;
      return '<button type="button" data-' + attr + '="' + esc(o.key) +
        '" class="' + (on ? "on" : "") + '" aria-pressed="' + (on ? "true" : "false") +
        '">' + esc(o.label) + '</button>';
    }).join("");
  }

  function syncSeg(box, attr, current){
    [].slice.call(box.querySelectorAll("button")).forEach(function(x){
      var on = x.dataset[attr] === current;
      x.classList.toggle("on", on);
      x.setAttribute("aria-pressed", String(on));
    });
  }

  function paintDl(list, current){
    var box = root.querySelector("#s_dl");
    if (!box) return;
    var opts = [{key:"", label:"自动"}].concat((list || []).map(function(d){
      return {key:d.key, label:d.label};
    }));
    box.innerHTML = segHtml(opts, current, "dl");
  }

  var BRAND_OPTS = [
    {key:"", label:"默认"},
    {key:"teal", label:"青碧"},
    {key:"slate", label:"石墨蓝"}
  ];

  function paintBrand(current){
    var box = root.querySelector("#s_brand");
    if (!box) return;
    box.innerHTML = BRAND_OPTS.map(function(o){
      var on = o.key === current;
      return '<button type="button" class="swatch" data-brand="' + o.key + '"' +
        ' aria-pressed="' + (on ? "true" : "false") + '" aria-label="' + esc(o.label) + '"></button>';
    }).join("");
  }

  var fontKey = "18";

  function snapFont(v){
    var n = parseInt(v, 10);
    if (n === 14 || n === 18 || n === 22) return String(n);
    if (n <= 15) return "14";
    if (n >= 20) return "22";
    return "18";
  }

  function readFields(){
    var out = {};
    FIELDS.forEach(function(f){
      if (f.seg){ out[f.key] = parseInt(fontKey, 10); return; }
      var el = root.querySelector("#s_" + f.key);
      if (!el) return;
      if (f.min === undefined){
        out[f.key] = el.value.trim();
      } else {
        out[f.key] = clamp(el.value, f.min, f.max);
      }
    });
    out.default_downloader = dlKey;
    out.selbar = selbarOn;
    out.theme = themeOn ? "dark" : "light";
    out.brand = brandKey;
    out.auto_files = autoFilesOn;
    return out;
  }

  var applyFont = function(v){ if (HC.applyFont) HC.applyFont(v); };

  var baseline = "";

  function snapshot(){
    return JSON.stringify(readFields());
  }

  function onEdit(){
    var dirty = snapshot() !== baseline;
    var st = root.querySelector("#st");
    if (st){
      st.textContent = dirty ? "未保存" : "";
      st.className = "status" + (dirty ? " dirty" : "");
    }
    var sv = root.querySelector("#btnSave");
    if (sv) sv.className = dirty ? "btn btn-brand" : "btn btn-ghost";
  }

  function setSw(sel, on){
    var el = root.querySelector(sel);
    if (!el) return;
    el.classList.toggle("off", !on);
    el.setAttribute("aria-pressed", String(on));
  }

  function markErrors(errors){
    root.querySelectorAll(".input.err,.val.err").forEach(function(el){
      el.classList.remove("err");
    });
    (errors || []).forEach(function(msg){
      FIELDS.forEach(function(f){
        if (msg.indexOf(f.label) === 0){
          var el = root.querySelector("#s_" + f.key);
          if (el) el.classList.add("err");
        }
      });
    });
    var first = root.querySelector(".input.err,.val.err");
    if (first) first.focus();
  }

  function mount(mountEl){
    root = document.createElement("div");
    root.className = "app settings";
    root.innerHTML =
      '<div class="card">' +
        '<div class="dhead"><span class="dtitle">设置</span><div class="spacer"></div>' +
          '<button class="iconbtn" id="btnClose" title="关闭">' +
            '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
              '<path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" ' +
              'stroke-width="1.5" stroke-linecap="round"/></svg></button></div>' +
        '<div class="div"></div>' +
        '<div class="mbody">' +
          '<div id="fields"></div>' +
          '<div class="netbar" id="netbar" role="status" aria-live="polite" hidden>' +
            '<span class="netdot"></span>' +
            '<span class="nettitle"></span>' +
            '<span class="netaddr"></span>' +
            '<span class="netnote muted"></span>' +
            '<span class="spacer"></span>' +
            '<button type="button" class="btn btn-ghost" id="btnNetRecheck">重新检测</button>' +
          '</div>' +
          '<div class="field inline"><span class="lbl" id="lb_dl">默认下载工具</span>' +
            '<div class="seg" id="s_dl" role="group" aria-labelledby="lb_dl"></div></div>' +
          '<div class="field inline"><label for="s_selbar">浮动选择条</label>' +
            '<button type="button" class="sw" id="s_selbar" role="switch"></button></div>' +
          '<div class="field inline"><label for="s_theme">暗夜主题</label>' +
            '<button type="button" class="sw" id="s_theme" role="switch"></button></div>' +
          '<div class="field inline"><span class="lbl" id="lb_brand">主题色</span>' +
            '<div class="swatches" id="s_brand" role="group" aria-labelledby="lb_brand"></div></div>' +
          '<div class="field inline"><label for="s_autofiles">文件命中时自动展开</label>' +
            '<button type="button" class="sw" id="s_autofiles" role="switch"></button></div>' +
        '</div>' +
        '<div class="dfoot"><span class="status" id="st"></span>' +
          '<div class="spacer"></div>' +
          '<button class="btn btn-ghost" id="btnReset">恢复默认</button>' +
          '<button class="btn btn-brand" id="btnSave">保存</button></div>' +
      '</div>' +
      '<div class="card">' +
        '<div class="dhead"><span class="dtitle">关于</span></div>' +
        '<div class="div"></div>' +
        '<div class="mbody" id="about"></div>' +
        '<div class="dfoot"><div class="spacer"></div>' +
          '<button class="btn btn-ghost" id="btnLogs">打开日志目录</button></div>' +
      '</div>';

    mountEl.appendChild(root);

    netEl = root.querySelector("#netbar");
    netBusy = false;
    root.querySelector("#btnNetRecheck").onclick = netCheck;

    function fill(settings, list){
      root.querySelector("#fields").innerHTML = fieldsHtml(settings);
      netPlace();
      netCheck();
      wireSteppers();
      fontKey = snapFont(settings.ui_font_size);
      syncSeg(root.querySelector("#s_ui_font_size"), "font", fontKey);
      applyFont(fontKey);

      dlKey = settings.default_downloader || "";
      paintDl(list, dlKey);
      selbarOn = settings.selbar !== false;
      setSw("#s_selbar", selbarOn);
      themeOn = settings.theme === "dark";
      setSw("#s_theme", themeOn);
      autoFilesOn = settings.auto_files !== false;
      setSw("#s_autofiles", autoFilesOn);
      brandKey = settings.brand || "";
      paintBrand(brandKey);
      if (HC.applyTheme) HC.applyTheme(settings.theme || "light");
      if (HC.applyBrand) HC.applyBrand(brandKey);
      baseline = snapshot();
      onEdit();
    }

    root.addEventListener("input", onEdit);

    root.querySelector("#fields").addEventListener("click", function(e){
      var b = e.target.closest("[data-font]");
      if (!b) return;
      fontKey = b.dataset.font;
      syncSeg(root.querySelector("#s_ui_font_size"), "font", fontKey);
      applyFont(fontKey);
      onEdit();
    });

    Promise.all([HC.api.getSettings(), HC.api.downloaders(), HC.api.appInfo()])
      .then(function(res){
        fill(res[0] || {}, res[1] || []);
        var info = res[2] || {};

        var lines = [
          ["版本", info.version, false],
          ["数据目录", info.dataDir, true],
          ["运行模式", info.mode, false],
          ["日志", info.logFile, true]
        ];
        if (info.proxy) lines.push(["网络出口", info.proxy, true]);
        if (info.migratedFrom) lines.push(["配置来源", info.migratedFrom, true]);

        root.querySelector("#about").innerHTML = lines.map(function(p){
          return '<div class="kv"><span class="k">' + esc(p[0]) + '</span>' +
            '<span class="v">' + esc(p[1] || "") + '</span>' +
            (p[2] ? '<button type="button" class="cp" data-cp="' + esc(p[1] || "") + '">复制</button>' : '') +
            '</div>';
        }).join("");
      })
      .catch(function(err){
        root.querySelector("#about").innerHTML =
          '<div style="color:var(--err)">设置加载失败：' +
          esc(err && err.message ? err.message : String(err)) + '</div>';
      });

    root.querySelector("#s_dl").addEventListener("click", function(e){
      var b = e.target.closest("[data-dl]");
      if (!b) return;
      dlKey = b.dataset.dl;
      syncSeg(root.querySelector("#s_dl"), "dl", dlKey);
      onEdit();
    });

    root.querySelector("#s_brand").addEventListener("click", function(e){
      var b = e.target.closest("[data-brand]");
      if (!b) return;
      brandKey = b.dataset.brand;
      [].slice.call(this.querySelectorAll(".swatch")).forEach(function(x){
        x.setAttribute("aria-pressed", String(x.dataset.brand === brandKey));
      });
      if (HC.applyBrand) HC.applyBrand(brandKey);
      onEdit();
    });

    root.querySelector("#about").addEventListener("click", function(e){
      var b = e.target.closest("[data-cp]");
      if (!b) return;
      HC.motion.copy(b.dataset.cp).then(function(ok){
        HC.motion.toast(ok ? "已复制" : "复制失败", ok ? "ok" : "err");
      });
    });

    root.querySelector("#s_selbar").onclick = function(){
      selbarOn = !selbarOn;
      setSw("#s_selbar", selbarOn);
      onEdit();
    };

    root.querySelector("#s_autofiles").onclick = function(){
      autoFilesOn = !autoFilesOn;
      setSw("#s_autofiles", autoFilesOn);
      onEdit();
    };

    root.querySelector("#s_theme").onclick = function(){
      themeOn = !themeOn;
      setSw("#s_theme", themeOn);
      if (HC.applyTheme) HC.applyTheme(themeOn ? "dark" : "light");
      onEdit();
    };

    root.querySelector("#btnSave").onclick = function(){
      var btn = this;
      btn.disabled = true;
      HC.api.saveSettings(readFields()).then(function(r){
        btn.disabled = false;
        if (r && r.ok){
          baseline = snapshot();
          onEdit();
          HC.motion.toast("设置已保存", "ok");
        } else {
          var errors = (r && r.errors) || [];
          markErrors(errors);
          HC.motion.toast(errors[0] || "有设置项不合法", "err");
        }
      }).catch(function(e){
        btn.disabled = false;
        HC.motion.toast(String(e && e.message ? e.message : e), "err");
      });
    };

    root.querySelector("#btnReset").onclick = function(){
      HC.motion.confirm("恢复默认设置", "恢复默认", function(){
        HC.api.defaultSettings().then(function(d){
          return HC.api.saveSettings(d);
        }).then(function(){
          return Promise.all([HC.api.getSettings(), HC.api.downloaders()]);
        }).then(function(res){
          fill(res[0] || {}, res[1] || []);
          HC.motion.toast("已恢复默认设置", "ok");
        }).catch(function(e){
          HC.motion.toast(String(e && e.message ? e.message : e), "err");
        });
      });
    };

    function leave(){
      location.hash = "search";
    }

    function tryClose(){
      if (snapshot() !== baseline){
        HC.motion.confirm("有未保存的改动", "放弃并关闭", leave);
        return;
      }
      leave();
    }

    root.querySelector("#btnClose").onclick = tryClose;

    if (mount._docKey) document.removeEventListener("keydown", mount._docKey);
    mount._docKey = function(e){
      if (e.key !== "Escape") return;
      if (!root || !root.isConnected) return;
      if (document.querySelector(".backdrop")) return;
      var tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      tryClose();
    };
    document.addEventListener("keydown", mount._docKey);

    root.querySelector("#btnLogs").onclick = function(){
      HC.api.openLogs();
    };
  }

  HC.views.settings = { mount: mount };
})();
