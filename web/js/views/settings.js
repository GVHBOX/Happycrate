(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var FIELDS = [
    {key:"min_query_len", label:"最短关键词", min:1, max:20, step:1},
    {key:"max_workers", label:"并发数", min:1, max:32, step:1},
    {key:"timeout", label:"超时", min:1, max:120, step:1, unit:"秒"},
    {key:"retries", label:"重试次数", min:0, max:5, step:1},
    {key:"proxy", label:"代理", ph:"http://127.0.0.1:7890"},
    {key:"user_agent", label:"User-Agent", ph:"留空用内置"},
    {key:"ui_font_size", label:"界面字号", min:12, max:24, step:1, unit:"px"}
  ];

  var root = null;
  var dlKey = "";
  var selbarOn = true;
  var themeOn = false;

  var STEP_BTN = {
    minus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 7h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus:'<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3.5 7h7M7 3.5v7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
  };

  function esc(v){
    return String(v === undefined || v === null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function clamp(v, min, max){
    v = parseInt(v, 10);
    if (isNaN(v)) v = min;
    return Math.max(min, Math.min(max, v));
  }

  function fieldHtml(f, v){
    if (f.min === undefined){
      return '<div class="field"><label>' + esc(f.label) + '</label>' +
        '<input class="input' + (f.ph ? "" : " mono") + '" id="s_' + f.key +
        '" value="' + esc(v) + '" placeholder="' + esc(f.ph || "") +
        '" style="margin-top:8px"></div>';
    }
    return '<div class="field"><label>' + esc(f.label) + (f.unit ? "（" + f.unit + "）" : "") + '</label>' +
      '<div class="stepper numfield" data-field="' + f.key + '" style="margin-top:8px">' +
        '<button type="button" data-step="-1">' + STEP_BTN.minus + '</button>' +
        '<input class="val mono" id="s_' + f.key + '" inputmode="numeric" value="' + esc(v) + '">' +
        (f.unit ? '<span class="unit">' + f.unit + '</span>' : '') +
        '<button type="button" data-step="1">' + STEP_BTN.plus + '</button>' +
      '</div></div>';
  }

  function wireSteppers(){
    root.querySelectorAll(".numfield").forEach(function(box){
      var input = box.querySelector("input");
      var min = 1, max = 100, step = 1;
      FIELDS.forEach(function(f){
        if (f.key === box.dataset.field){ min = f.min; max = f.max; step = f.step || 1; }
      });
      box.querySelectorAll("[data-step]").forEach(function(b){
        b.onclick = function(){
          input.value = clamp(parseInt(input.value, 10) + parseInt(b.dataset.step, 10) * step, min, max);
          input.dispatchEvent(new Event("input"));
        };
      });
      input.addEventListener("change", function(){
        input.value = clamp(input.value, min, max);
      });
      input.addEventListener("blur", function(){
        input.value = clamp(input.value, min, max);
      });
    });
  }

  function paintDl(list, current){
    var box = root.querySelector("#s_dl");
    if (!box) return;
    var opts = [{key:"", label:"自动"}].concat((list || []).map(function(d){
      return {key:d.key, label:d.label};
    }));
    box.innerHTML = opts.map(function(o){
      return '<button data-dl="' + esc(o.key) + '" class="' +
        (o.key === current ? "on" : "") + '">' + esc(o.label) + '</button>';
    }).join("");
  }

  function readFields(){
    var out = {};
    FIELDS.forEach(function(f){
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
    return out;
  }

  function applyFont(v){
    var n = parseInt(v, 10);
    if (n >= 12 && n <= 24) document.documentElement.style.setProperty("--fr", String(n / 13));
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
          '<div class="mapgrid" id="fields"></div>' +
          '<div class="field"><label>默认下载工具</label>' +
            '<div class="seg" id="s_dl" style="margin-top:8px"></div></div>' +
          '<div class="field"><label>浮动选择条</label>' +
            '<button type="button" class="sw" id="s_selbar" style="margin-top:8px"></button></div>' +
          '<div class="field"><label>暗夜主题</label>' +
            '<button type="button" class="sw" id="s_theme" style="margin-top:8px"></button></div>' +
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

    Promise.all([HC.api.getSettings(), HC.api.downloaders(), HC.api.appInfo()])
      .then(function(res){
        var settings = res[0] || {};
        var list = res[1] || [];
        var info = res[2] || {};

        root.querySelector("#fields").innerHTML = FIELDS.map(function(f){
          return fieldHtml(f, settings[f.key]);
        }).join("");
        wireSteppers();
        applyFont(settings.ui_font_size);

        dlKey = settings.default_downloader || "";
        paintDl(list, dlKey);
        selbarOn = settings.selbar !== false;
        var sb = root.querySelector("#s_selbar");
        if (sb) sb.classList.toggle("off", !selbarOn);
        themeOn = settings.theme === "dark";
        var th = root.querySelector("#s_theme");
        if (th) th.classList.toggle("off", !themeOn);

        var lines = [
          ["版本", info.version],
          ["数据目录", info.dataDir],
          ["运行模式", info.mode],
          ["日志", info.logFile]
        ];
        if (info.migratedFrom) lines.push(["配置来源", info.migratedFrom]);

        root.querySelector("#about").innerHTML = lines.map(function(p){
          return '<div style="display:flex;gap:12px;padding:5px 0">' +
            '<span style="width:72px;flex:none;color:var(--t3)">' + esc(p[0]) + '</span>' +
            '<span class="mono" style="flex:1;word-break:break-all">' + esc(p[1]) + '</span>' +
            '</div>';
        }).join("");
      });

    root.querySelector("#s_dl").addEventListener("click", function(e){
      var b = e.target.closest("[data-dl]");
      if (!b) return;
      dlKey = b.dataset.dl;
      var cur = root.querySelector("#s_dl");
      [].slice.call(cur.querySelectorAll("button")).forEach(function(x){
        x.classList.toggle("on", x.dataset.dl === dlKey);
      });
    });

    root.querySelector("#s_selbar").onclick = function(){
      selbarOn = !selbarOn;
      this.classList.toggle("off", !selbarOn);
    };

    root.querySelector("#s_theme").onclick = function(){
      themeOn = !themeOn;
      this.classList.toggle("off", !themeOn);
      if (HC.applyTheme) HC.applyTheme(themeOn ? "dark" : "light");
    };

    root.querySelector("#btnSave").onclick = function(){
      var st = root.querySelector("#st");
      HC.api.saveSettings(readFields()).then(function(r){
        if (r && r.ok){
          st.textContent = "已保存";
          applyFont(root.querySelector("#s_ui_font_size").value);
          HC.motion.toast("设置已保存");
        } else {
          var first = ((r && r.errors) || [])[0] || "有设置项不合法";
          st.textContent = first;
          HC.motion.toast(first, "err");
        }
      });
    };

    root.querySelector("#btnReset").onclick = function(){
      HC.api.saveSettings({
        min_query_len: 2, max_workers: 8, timeout: 15, retries: 1,
        default_downloader: "", proxy: "", user_agent: "",
        ui_font_size: 18, selbar: true, theme: "light"
      }).then(function(){
        dlKey = "";
        selbarOn = true;
        themeOn = false;
        if (HC.applyTheme) HC.applyTheme("light");
        applyFont(18);
        mountEl.innerHTML = "";
        mount(mountEl);
        HC.motion.toast("已恢复默认设置");
      });
    };

    root.querySelector("#btnClose").onclick = function(){
      location.hash = "search";
    };

    if (mount._docKey) document.removeEventListener("keydown", mount._docKey);
    mount._docKey = function(e){
      if (e.key !== "Escape") return;
      if (!root || !root.isConnected) return;
      if (document.querySelector(".backdrop")) return;
      var tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      location.hash = "search";
    };
    document.addEventListener("keydown", mount._docKey);

    root.querySelector("#btnLogs").onclick = function(){
      HC.api.openLogs();
    };
  }

  HC.views.settings = { mount: mount };
})();
