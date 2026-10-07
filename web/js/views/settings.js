(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var esc = HC.esc;

  var NAV = [
    {key:"personalize", label:"个性化", d:"M8 1.5A6.5 6.5 0 1 1 1.5 8H8V1.5z"},
    {key:"search", label:"搜索", d:"M7 2a5 5 0 1 0 0 10A5 5 0 0 0 7 2zm7 12l-3.2-3.2"},
    {key:"network", label:"网络", d:"M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM1.5 8h13M8 1.5c2 1.8 3 4 3 6.5s-1 4.7-3 6.5c-2-1.8-3-4-3-6.5s1-4.7 3-6.5z"},
    {key:"about", label:"关于", d:"M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM8 7v4M8 4.5v.01"}
  ];

  var THEME_OPTS = [{key:"light", label:"浅色"}, {key:"dark", label:"深色"}];
  var FONT_OPTS = [{key:"14", label:"小"}, {key:"18", label:"标准"}, {key:"22", label:"大"}];
  var DENSITY_OPTS = [{key:"compact", label:"紧凑"}, {key:"comfort", label:"舒适"}];
  var PROG_OPTS = [
    {key:"segment", label:"分段"},
    {key:"flow", label:"连续"}
  ];
  var BRAND_OPTS = [
    {key:"", label:"默认"},
    {key:"teal", label:"青碧"},
    {key:"slate", label:"石墨蓝"},
    {key:"lilac", label:"薰衣草"}
  ];

  var NUMS = {
    min_query_len:{min:1, max:20, step:1},
    max_workers:{min:1, max:32, step:1},
    timeout:{min:1, max:120, step:1, unit:"s"},
    retries:{min:0, max:5, step:1},
    soft_deadline_ms:{min:0, max:60000, step:500, unit:"ms"},
    hard_timeout_ms:{min:0, max:180000, step:1000, unit:"ms"}
  };
  var NUM_FALLBACKS = {min_query_len:2, max_workers:12, timeout:15, retries:1,
                       soft_deadline_ms:3000, hard_timeout_ms:45000};

  var SOUND_VOLUME_DEFAULT = HC.SOUND_VOLUME_DEFAULT || 80;

  var ERROR_FIELDS = [
    {key:"min_query_len", sel:"#s_min_query_len", label:"最短关键词"},
    {key:"max_workers", sel:"#s_max_workers", label:"并发数"},
    {key:"timeout", sel:"#s_timeout", label:"投递/清单超时"},
    {key:"retries", sel:"#s_retries", label:"重试次数"},
    {key:"soft_deadline_ms", sel:"#s_soft_deadline_ms", label:"软截止"},
    {key:"hard_timeout_ms", sel:"#s_hard_timeout_ms", label:"搜索时限"},
    {key:"sound_volume", sel:"#sldVolume", label:"总音量"},
    {key:"ui_font_size", sel:"#s_font", label:"界面字号"}
  ];

  var REFRESH_SVG = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none">' +
    '<path d="M13.8 3.2A7 7 0 1 0 15 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
    '<path d="M14.5 1.8v3.4h-3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>' +
  '</svg>';

  var FOLDER_SVG = '<svg viewBox="0 0 16 16" fill="none">' +
    '<path d="M1.5 3.5A1.5 1.5 0 0 1 3 2h3.2a1.5 1.5 0 0 1 1.06.44l1.3 1.3A1.5 1.5 0 0 0 9.62 4.2H13a1.5 1.5 0 0 1 1.5 1.5v6.8a1.5 1.5 0 0 1-1.5 1.5H3a1.5 1.5 0 0 1-1.5-1.5V3.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
  '</svg>';

  var GITHUB_SVG = '<svg viewBox="0 0 16 16" fill="currentColor">' +
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>' +
  '</svg>';

  var FOLD_CHEV = '<svg viewBox="0 0 12 12" fill="none"><path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  var root = null;
  var dlKey = "";
  var selbarOn = false;
  var soundOn = true;
  var SFX_ROWS = [
    {key:"start", label:"搜索开始提示音"},
    {key:"done", label:"搜索完成提示音"},
    {key:"select", label:"勾选提示音"},
    {key:"copy", label:"复制提示音"},
    {key:"deliver", label:"投递提示音"},
    {key:"fail", label:"失败提示音"}
  ];
  var sfxOn = {};
  var volumeVal = SOUND_VOLUME_DEFAULT;
  var themeKey = "light";
  var fontKey = "18";
  var densityKey = localStorage.getItem("hc_row_density") || "compact";
  var autoFilesOn = true;
  var progStyleKey = "segment";
  var brandKey = "";
  var proxyVal = "";
  var uaVal = "";
  var baseline = "";

  var netEl = null;
  var netBusy = false;
  var netGen = 0;

  function netPaint(data){
    if (!netEl) return;
    var s = HC.netState(data);
    netEl.hidden = false;
    netEl.querySelector(".netdot").className = "netdot" + (s.dot ? " " + s.dot : "");
    netEl.querySelector(".nettitle").textContent = s.title || "";
    var addr = netEl.querySelector(".netaddr");
    addr.textContent = s.addr || "";
    addr.className = "netaddr" + (s.off ? " off" : "");
    var note = netEl.querySelector(".netnote");
    note.textContent = s.note || "";
    note.className = "netnote" + (s.muted ? " muted" : "");
    var rBtn = netEl.querySelector("#btnNetRecheck");
    if (rBtn){
      rBtn.classList.toggle("spinning", !!s.busy);
      rBtn.disabled = !!s.busy;
    }
  }

  function netCheck(force){
    if (!netEl) return;
    if (typeof HC.api.proxyStatus !== "function"){
      netEl.hidden = true;
      return;
    }
    if (netBusy) return;
    netBusy = true;
    var gen = netGen;
    netPaint(null);
    HC.api.proxyStatus(force).then(function(d){
      if (gen !== netGen) return;
      netBusy = false;
      if (HC.setNetStatus) HC.setNetStatus(d);
      netPaint(d || {mode:"none"});
    }).catch(function(){
      if (gen !== netGen) return;
      netBusy = false;
      netEl.hidden = true;
    });
  }

  function clamp(v, min, max){
    v = parseInt(v, 10);
    if (isNaN(v)) v = min;
    return Math.max(min, Math.min(max, v));
  }

  function numOr(v, fb){
    var n = parseInt(v, 10);
    return isNaN(n) ? fb : n;
  }

  var applyFont = function(v){ if (HC.applyFont) HC.applyFont(v); };

  function snapFont(v){
    var n = parseInt(v, 10);
    if (n === 14 || n === 18 || n === 22) return String(n);
    if (n <= 15) return "14";
    if (n >= 20) return "22";
    return "18";
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

  function setSw(sel, on){
    var el = root.querySelector(sel);
    if (!el) return;
    el.classList.toggle("off", !on);
    el.setAttribute("aria-checked", String(on));
  }

  var activePane = "personalize";

  function paneHtml(key, title, body){
    return '<section class="spane' + (key === activePane ? " on" : "") +
      '" data-pane="' + key + '">' +
      '<div class="spane-t">' + esc(title) + '</div>' + body + '</section>';
  }

  function sectHtml(t, first){
    return '<div class="ssect' + (first ? " first" : "") + '">' + esc(t) + '</div>';
  }

  function rowHtml(labelHtml, ctlHtml){
    return '<div class="prow">' + labelHtml +
      '<div class="pctl">' + ctlHtml + '</div></div>';
  }

  function lblText(id, text){
    return '<label class="lbl" for="' + id + '">' + esc(text) + '</label>';
  }

  function lblGroup(key, text){
    return '<span class="lbl" id="lb_' + key + '">' + esc(text) + '</span>';
  }

  function swHtml(id){
    return '<button type="button" class="sw" id="' + id + '" role="switch"></button>';
  }

  var PV_ICON = '<svg viewBox="0 0 16 16" fill="none" width="11" height="11"><path d="M5.5 3.5v9l7-4.5z" fill="currentColor"/></svg>';

  function sfxRowHtml(r){
    return rowHtml(lblText("s_" + r.key, r.label),
      swHtml("s_" + r.key) +
      '<button type="button" class="btn btn-ghost sfxpv" data-sfx="' + r.key +
      '" aria-label="试听">' + PV_ICON + '</button>');
  }


  function foldHtml(key, title, body){
    return '<button type="button" class="foldbtn" id="fold_' + key +
      '" aria-expanded="false" aria-controls="foldbody_' + key + '">' + FOLD_CHEV + '<span>' + esc(title) +
      '</span></button>' +
      '<div class="foldbody" id="foldbody_' + key + '" hidden>' + body + '</div>';
  }

  function personalizePane(){
    return paneHtml("personalize", "个性化",
      sectHtml("界面", true) +
      rowHtml(lblGroup("theme", "主题"),
        '<div class="seg" id="s_theme" role="group" aria-labelledby="lb_theme">' +
        segHtml(THEME_OPTS, "light", "theme") + '</div>') +
      rowHtml(lblGroup("brand", "主题色"),
        '<div class="swatches" id="s_brand" role="group" aria-labelledby="lb_brand"></div>') +
      rowHtml(lblGroup("font", "界面字号"),
        '<div class="seg" id="s_font" role="group" aria-labelledby="lb_font">' +
        segHtml(FONT_OPTS, "18", "font") + '</div>') +
      rowHtml(lblGroup("density", "行高"),
        '<div class="seg" id="s_density" role="group" aria-labelledby="lb_density">' +
        segHtml(DENSITY_OPTS, densityKey, "density") + '</div>') +
      rowHtml(lblText("s_selbar", "悬浮底栏"), swHtml("s_selbar")) +
      sectHtml("音效") +
      rowHtml(lblText("s_sound", "音效反馈"), swHtml("s_sound")) +
      rowHtml(lblText("sldVolume", "总音量"),
        '<div class="rngpair"><input type="range" class="rng" id="sldVolume" min="0" max="100" step="1">' +
        '<span class="rv" id="rvVolume"></span></div>') +
      foldHtml("sfx", "音效细项",
        SFX_ROWS.map(sfxRowHtml).join("")) +
      sectHtml("进度条") +
      lookPreviewHtml() +
      rowHtml(lblGroup("prog", "样式"),
        '<div class="seg" id="s_progstyle" role="group" aria-labelledby="lb_prog"></div>'));
  }

  function searchPane(){
    return paneHtml("search", "搜索",
      sectHtml("检索", true) +
      rowHtml(lblText("s_autofiles", "文件命中时自动展开"), swHtml("s_autofiles")) +
      sectHtml("投递") +
      rowHtml(lblGroup("dl", "投递工具"),
        '<div class="seg" id="s_dl" role="group" aria-labelledby="lb_dl"></div>'));
  }

  function networkPane(){
    return paneHtml("network", "网络",
      sectHtml("网络状态", true) +
      '<div class="netbar" id="netbar" role="status" aria-live="polite" hidden>' +
        '<span class="netdot"></span>' +
        '<span class="nettitle"></span>' +
        '<span class="netaddr"></span>' +
        '<span class="netnote muted"></span>' +
        '<span class="spacer"></span>' +
        '<button type="button" class="btn-refresh" id="btnNetRecheck" title="重新检测">' + REFRESH_SVG + '</button>' +
      '</div>');
  }

  var SHORTCUTS = [
    {name:"聚焦搜索", keys:'<kbd class="kbd">Ctrl</kbd><span class="kbd-sep">+</span><kbd class="kbd">K</kbd>'},
    {name:"移动焦点", keys:'<kbd class="kbd">↑</kbd><span class="kbd-sep">/</span><kbd class="kbd">↓</kbd>'},
    {name:"切换勾选", keys:'<kbd class="kbd">Space</kbd>'},
    {name:"展开折叠", keys:'<kbd class="kbd">Enter</kbd>'},
    {name:"全选条目", keys:'<kbd class="kbd">Ctrl</kbd><span class="kbd-sep">+</span><kbd class="kbd">A</kbd>'},
    {name:"清除选择", keys:'<kbd class="kbd">Esc</kbd>'},
    {name:"复制磁力", keys:'<kbd class="kbd">双击条目</kbd>'}
  ];

  function aboutPane(){
    return paneHtml("about", "关于",
      '<div class="about-hero">' +
        '<div class="about-app">' +
          '<span class="about-name">happycrate</span>' +
          '<span class="about-tag" id="aboutVer">v1.0.4</span>' +
        '</div>' +
        '<div class="about-actions">' +
          '<button type="button" class="btn-octo" id="btnRepo" title="GitHub 仓库" aria-label="GitHub 仓库">' + GITHUB_SVG + '</button>' +
        '</div>' +
      '</div>' +
      sectHtml("本地存储", true) +
      '<div id="about"></div>' +
      sectHtml("快捷键") +
      '<div class="sc-grid">' +
        SHORTCUTS.map(function(s){
          return '<div class="sc-item">' +
            '<span class="sc-name">' + esc(s.name) + '</span>' +
            '<span class="sc-keys">' + s.keys + '</span>' +
          '</div>';
        }).join("") +
      '</div>');
  }

  var lookRaf = 0;
  var lookTimes = [];
  var lookTimer = [];

  function lookPreviewHtml(){
    return '<div class="lookprev">' +
        '<div class="progress" id="lookBar"><div class="track" id="lookTrack"></div></div>' +
        '<div class="lookrow"><button type="button" class="btn btn-ghost" id="btnLookPlay">播放一轮</button>' +
          '<span class="lookst" id="lookSt">9 个源 · 最快 0.4s · 最慢 4.0s</span></div>' +
      '</div>';
  }

  function lookStop(){
    cancelAnimationFrame(lookRaf);
    lookTimer.forEach(clearTimeout);
    lookTimer = [];
    lookRaf = 0;
  }

  function lookResetPreview(){
    var track = root.querySelector("#lookTrack");
    var bar = root.querySelector("#lookBar");
    if (!track || !bar) return;
    bar.classList.remove("slow", "receding");
    bar.classList.toggle("style-flow", progStyleKey === "flow");
    bar.style.setProperty("--p", "0");
    track.innerHTML = "";
    if (progStyleKey === "flow"){
      var f = document.createElement("div");
      f.className = "fill";
      f.innerHTML = '<div class="tex"></div>';
      track.appendChild(f);
    } else {
      for (var i = 0; i < 9; i++){
        var s = document.createElement("div");
        s.className = "pseg";
        var sub = document.createElement("div");
        sub.className = "sub-fill";
        sub.style.width = "0%";
        sub.style.opacity = "0";
        s.appendChild(sub);
        track.appendChild(s);
      }
    }

  }

  function lookDeadlineSecs(){
    var raw = (HC.settings || {}).soft_deadline_ms;
    var d = parseInt(raw, 10) / 1000;
    if (!d || d <= 0 || isNaN(d)) d = 3;
    return d;
  }

  function lookPlay(){
    var track = root.querySelector("#lookTrack");
    var st = root.querySelector("#lookSt");
    var bar = root.querySelector("#lookBar");
    if (!track || !bar) return;
    lookStop();
    lookResetPreview();
    var deadline = lookDeadlineSecs();
    lookTimes = [];
    for (var j = 0; j < 9; j++) lookTimes.push(0.4 + Math.random() * 3.6);
    lookTimes.sort(function(a, b){ return a - b; });
    var t0 = performance.now();
    (function frame(now){
      var el = (now - t0) / 1000;
      var done = 0, warned = 0;
      var segs = track.querySelectorAll(".pseg");
      for (var i = 0; i < segs.length; i++){
        var back = lookTimes[i] <= el;
        var sub = segs[i].querySelector(".sub-fill");
        if (back){
          done++;
          segs[i].className = "pseg on";
          if (sub){
            sub.style.width = "100%";
            sub.style.opacity = "1";
          }
        } else {
          var ratio = Math.min(0.985, el / lookTimes[i]);
          if (sub){
            sub.style.width = (ratio * 100).toFixed(1) + "%";
            sub.style.opacity = ratio > 0 ? "1" : "0";
          }
          if (el > deadline){
            warned++;
            segs[i].className = "pseg warned";
          } else {
            segs[i].className = "pseg running";
          }
        }
      }
      if (progStyleKey === "flow"){
        bar.style.setProperty("--p", String(Math.min(1, el / lookTimes[8])));
        done = lookTimes.filter(function(t){ return t <= el; }).length;
        warned = el > deadline ? 9 - done : 0;
      }

      if (st) st.textContent = done + "/9 源" + (warned ? " · 越过软截止 " + warned + " 个" : "");
      if (el >= lookTimes[8] + 0.3){ lookFinish(); return; }
      lookRaf = requestAnimationFrame(frame);
    })(t0);
  }

  function lookFinish(){
    var st = root.querySelector("#lookSt");
    var bar = root.querySelector("#lookBar");
    if (st) st.textContent = "完成 · 9/9";
    lookTimer.push(setTimeout(function(){
      var defer = function(fn, ms){
        var t = setTimeout(fn, ms);
        lookTimer.push(t);
        return t;
      };
      var rest = function(){ if (st) st.textContent = "完成 · 已回退到空槽"; };
      bar.classList.add("receding");
      defer(function(){
        if (!bar.isConnected) return;
        bar.classList.remove("receding");
        lookResetPreview();
        rest();
      }, 360);
    }, 280));
  }

  function paintDl(list, current){
    var box = root.querySelector("#s_dl");
    if (!box) return;
    var cur = current || "";
    if (!cur && list && list.length){
      var firstAvail = list.find(function(d){ return d.available; });
      cur = firstAvail ? firstAvail.key : list[0].key;
    }
    box.innerHTML = (list || []).map(function(d){
      var on = d.key === cur;
      return '<button type="button" data-dl="' + esc(d.key) +
        '" class="' + (on ? "on" : "") + '" aria-pressed="' + (on ? "true" : "false") +
        '"' + (d.available ? "" : " disabled") + '>' + esc(d.label) + '</button>';
    }).join("");
    dlKey = cur;
  }

  function paintProg(current){
    var box = root.querySelector("#s_progstyle");
    if (!box) return;
    box.innerHTML = segHtml(PROG_OPTS, current, "ps");
    syncSeg(box, "ps", current);
  }

  function paintBrand(current){
    var box = root.querySelector("#s_brand");
    if (!box) return;
    box.innerHTML = BRAND_OPTS.map(function(o){
      var on = o.key === current;
      return '<button type="button" class="swatch" data-brand="' + o.key + '"' +
        ' aria-pressed="' + (on ? "true" : "false") + '" aria-label="' + esc(o.label) + '"></button>';
    }).join("");
  }



  function readFields(){
    var out = {};
    Object.keys(NUMS).forEach(function(k){
      var el = root.querySelector("#s_" + k);
      var spec = NUMS[k];
      if (!el){
        out[k] = clamp(numOr((HC.settings || {})[k], NUM_FALLBACKS[k]),
                       spec.min, spec.max);
        return;
      }
      out[k] = clamp(el.value, spec.min, spec.max);
    });
    out.proxy = proxyVal;
    out.user_agent = uaVal;
    out.ui_font_size = parseInt(fontKey, 10);
    out.default_downloader = dlKey;
    out.selbar = selbarOn;
    out.sound = soundOn;
    SFX_ROWS.forEach(function(r){
      out["sound_" + r.key] = sfxOn[r.key];
    });
    out.sound_volume = volumeVal;
    out.theme = themeKey;
    out.brand = brandKey;
    out.auto_files = autoFilesOn;
    out.progress_style = progStyleKey;
    out.progress_line = true;
    out.keep_duplicates = false;
    out.progress_look = "";
    return out;
  }

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

  var ERR_SEL = ".input.err,.val.err,.rng.err,.seg.err";

  function revealField(el){
    var pane = el.closest(".spane");
    if (pane && !pane.classList.contains("on")){
      var nav = root.querySelector('.snav-i[data-pane="' + pane.dataset.pane + '"]');
      if (nav) nav.click();
    }
    var fold = el.closest(".foldbody");
    if (fold && fold.hidden){
      var btn = root.querySelector('[aria-controls="' + fold.id + '"]');
      if (btn) btn.click();
    }
  }

  function markErrors(errors){
    root.querySelectorAll(ERR_SEL).forEach(function(el){
      el.classList.remove("err");
    });
    var first = null;
    (errors || []).forEach(function(msg){
      ERROR_FIELDS.forEach(function(f){
        if (msg.indexOf(f.label) < 0) return;
        var el = root.querySelector(f.sel);
        if (!el) return;
        el.classList.add("err");
        if (!first) first = el;
      });
    });
    if (!first) return;
    revealField(first);
    first.focus();
  }

  function mount(mountEl){
    activePane = HC.settingsDefaultPane || "personalize";
    HC.settingsDefaultPane = null;
    root = document.createElement("div");
    root.className = "app settings";
    root.innerHTML =
      '<aside class="snav">' +
        '<div class="snav-t"><span>设置</span></div>' +
        NAV.map(function(n){
          return '<button type="button" class="snav-i' +
            (n.key === activePane ? " on" : "") + '" data-pane="' + n.key + '">' +
            '<svg viewBox="0 0 16 16" fill="none"><path d="' + n.d +
            '" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
            '<span>' + esc(n.label) + '</span></button>';
        }).join("") +
      '</aside>' +
      '<div class="smain">' +
        '<button type="button" class="iconbtn sclose-btn" id="btnSettingsClose" title="关闭">' +
          '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>' +
        '</button>' +
        '<div class="spanes scroll-slim">' +
          personalizePane() + searchPane() + networkPane() + aboutPane() +
        '</div>' +
        '<div class="sfoot">' +
          '<span class="status" id="st"></span>' +
          '<div class="spacer"></div>' +
          '<button class="btn btn-ghost" id="btnReset">恢复默认</button>' +
          '<button class="btn btn-ghost" id="btnSave">保存</button>' +
        '</div>' +
      '</div>';

    mountEl.appendChild(root);

    netEl = root.querySelector("#netbar");
    netBusy = false;
    netGen += 1;
    root.querySelector("#btnNetRecheck").onclick = function(){
      this.classList.add("spinning");
      netCheck(true);
    };
    root.querySelector("#btnSettingsClose").onclick = tryClose;

    function fill(settings, list){
      Object.keys(NUMS).forEach(function(k){
        var el = root.querySelector("#s_" + k);
        if (!el) return;
        el.value = clamp(numOr(settings[k], NUM_FALLBACKS[k]), NUMS[k].min, NUMS[k].max);
      });
      proxyVal = settings.proxy || "";
      uaVal = settings.user_agent || "";
      fontKey = snapFont(settings.ui_font_size);
      syncSeg(root.querySelector("#s_font"), "font", fontKey);
      applyFont(fontKey);
      themeKey = settings.theme === "dark" ? "dark" : "light";
      syncSeg(root.querySelector("#s_theme"), "theme", themeKey);
      if (HC.applyTheme) HC.applyTheme(themeKey);
      volumeVal = clamp(numOr(settings.sound_volume, SOUND_VOLUME_DEFAULT), 0, 100);
      var vld = root.querySelector("#sldVolume");
      if (vld) vld.value = volumeVal;
      var rvv = root.querySelector("#rvVolume");
      if (rvv) rvv.textContent = volumeVal + "%";
      soundOn = settings.sound !== false;
      setSw("#s_sound", soundOn);
      SFX_ROWS.forEach(function(r){
        sfxOn[r.key] = settings["sound_" + r.key] !== false;
        setSw("#s_" + r.key, sfxOn[r.key]);
      });
      autoFilesOn = settings.auto_files !== false;
      setSw("#s_autofiles", autoFilesOn);
      selbarOn = settings.selbar === true;
      setSw("#s_selbar", selbarOn);
      densityKey = localStorage.getItem("hc_row_density") || "compact";
      syncSeg(root.querySelector("#s_density"), "density", densityKey);
      progStyleKey = settings.progress_style === "flow" ? "flow" : "segment";
      paintProg(progStyleKey);

      dlKey = settings.default_downloader || "";
      paintDl(list, dlKey);
      brandKey = settings.brand || "";
      paintBrand(brandKey);
      if (HC.applyBrand) HC.applyBrand(brandKey);
      if (HC.applyProgressLook) HC.applyProgressLook("");
      lookResetPreview();
      baseline = snapshot();
      onEdit();
      setTimeout(netCheck, 60);
    }

    function aboutKvHtml(info){
      var verEl = root.querySelector("#aboutVer");
      if (verEl && info.version) verEl.textContent = "v" + info.version;
      var lines = [
        ["数据目录", info.dataDir, "data"],
        ["日志文件", info.logFile, "logs"]
      ];
      if (info.recovered && info.recovered.length){
        lines.push(["已恢复默认", info.recovered.join(" · "), ""]);
      }
      return lines.map(function(p, i){
        var val = p[1] || "";
        var openBtn = p[2] ? '<button type="button" class="btn-folder" data-open="' + p[2] + '" title="打开目录">' + FOLDER_SVG + '</button>' : '';
        return rowHtml(lblGroup("info" + i, p[0]),
          '<span class="v" title="' + esc(val) + '">' + esc(val) + '</span>' + openBtn);
      }).join("");
    }

    function aboutFail(prefix, err){
      root.querySelector("#about").innerHTML =
        '<div style="color:var(--err)">' + esc(prefix) + '：' +
        esc(err && err.message ? err.message : String(err)) + '</div>';
    }

    Promise.all([HC.api.getSettings(), HC.api.downloaders()])
      .then(function(res){
        fill(res[0] || {}, res[1] || []);
      })
      .catch(function(err){
        aboutFail("设置加载失败", err);
      });

    HC.api.appInfo().then(function(info){
      root.querySelector("#about").innerHTML = aboutKvHtml(info || {});
    }).catch(function(err){
      aboutFail("版本信息读取失败", err);
    });

    root.querySelector(".snav").addEventListener("click", function(e){
      var b = e.target.closest(".snav-i");
      if (!b) return;
      root.querySelectorAll(".snav-i").forEach(function(x){
        x.classList.toggle("on", x.dataset.pane === b.dataset.pane);
      });
      root.querySelectorAll(".spane").forEach(function(p){
        p.classList.toggle("on", p.dataset.pane === b.dataset.pane);
      });
      var spanes = root.querySelector(".spanes");
      if (spanes) spanes.scrollTop = 0;
    });

    function wireFold(btnId, bodyId){
      var btn = root.querySelector("#" + btnId);
      if (!btn) return;
      btn.onclick = function(){
        var body = root.querySelector("#" + bodyId);
        var open = body.hidden;
        body.hidden = !open;
        btn.classList.toggle("open", open);
        btn.setAttribute("aria-expanded", String(open));
      };
    }
    wireFold("fold_sfx", "foldbody_sfx");
    var btnPlay = root.querySelector("#btnLookPlay");
    if (btnPlay) btnPlay.onclick = lookPlay;



    root.addEventListener("input", onEdit);

    root.querySelector("#sldVolume").addEventListener("input", function(){
      volumeVal = clamp(this.value, 0, 100);
      var rv = root.querySelector("#rvVolume");
      if (rv) rv.textContent = volumeVal + "%";
    });

    root.querySelector("#s_theme").addEventListener("click", function(e){
      var b = e.target.closest("[data-theme]");
      if (!b) return;
      themeKey = b.dataset.theme;
      syncSeg(this, "theme", themeKey);
      if (HC.applyTheme) HC.applyTheme(themeKey);
      lookResetPreview();
      onEdit();
    });

    root.querySelector("#s_font").addEventListener("click", function(e){
      var b = e.target.closest("[data-font]");
      if (!b) return;
      fontKey = b.dataset.font;
      syncSeg(this, "font", fontKey);
      applyFont(fontKey);
      onEdit();
    });

    root.querySelector("#s_dl").addEventListener("click", function(e){
      var b = e.target.closest("[data-dl]");
      if (!b || b.disabled) return;
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
      lookResetPreview();
      onEdit();
    });

    root.querySelector("#s_progstyle").addEventListener("click", function(e){
      var b = e.target.closest("button[data-ps]");
      if (!b) return;
      progStyleKey = b.dataset.ps;
      syncSeg(this, "ps", progStyleKey);
      lookResetPreview();
      onEdit();
    });

    root.querySelector("#about").addEventListener("click", function(e){
      var op = e.target.closest("[data-open]");
      if (!op) return;
      if (op.dataset.open === "data"){
        if (HC.api.openDataDir) HC.api.openDataDir();
      } else if (op.dataset.open === "logs"){
        if (HC.api.openLogs) HC.api.openLogs();
      }
    });

    root.querySelector("#s_density").addEventListener("click", function(e){
      var b = e.target.closest("button[data-density]");
      if (!b) return;
      densityKey = b.dataset.density;
      syncSeg(this, "density", densityKey);
      try{ localStorage.setItem("hc_row_density", densityKey); }catch(err){}
      document.documentElement.classList.toggle("density-comfort", densityKey === "comfort");
      document.body.classList.toggle("density-comfort", densityKey === "comfort");
    });

    root.querySelector("#s_selbar").onclick = function(){
      selbarOn = !selbarOn;
      setSw("#s_selbar", selbarOn);
      onEdit();
    };

    root.querySelector("#s_sound").onclick = function(){
      soundOn = !soundOn;
      setSw("#s_sound", soundOn);
      onEdit();
    };

    SFX_ROWS.forEach(function(r){
      root.querySelector("#s_" + r.key).onclick = function(){
        sfxOn[r.key] = !sfxOn[r.key];
        setSw("#s_" + r.key, sfxOn[r.key]);
        onEdit();
      };
    });

    root.querySelectorAll("[data-sfx]").forEach(function(b){
      b.onclick = function(){ HC.sfx.preview(b.dataset.sfx); };
    });

    root.querySelector("#s_autofiles").onclick = function(){
      autoFilesOn = !autoFilesOn;
      setSw("#s_autofiles", autoFilesOn);
      onEdit();
    };



    function saveChanges(onSuccess){
      var btn = root.querySelector("#btnSave");
      if (btn) btn.disabled = true;
      var fields = readFields();
      return HC.api.saveSettings(fields).then(function(r){
        if (btn) btn.disabled = false;
        if (r && r.ok){
          HC.settings = Object.assign({}, HC.settings, fields);
          if (HC.applyProgressLook) HC.applyProgressLook("");
          baseline = snapshot();
          onEdit();
          if (HC.sfx && HC.sfx.play) HC.sfx.play("done");
          HC.motion.toast("设置已保存", "ok");
          if (onSuccess) onSuccess();
          return true;
        } else {
          var errors = (r && r.errors) || [];
          markErrors(errors);
          if (HC.sfx && HC.sfx.play) HC.sfx.play("fail");
          HC.motion.toast(errors[0] || "有设置项不合法", "err");
          return false;
        }
      }).catch(function(e){
        if (btn) btn.disabled = false;
        if (HC.sfx && HC.sfx.play) HC.sfx.play("fail");
        HC.motion.toast(String(e && e.message ? e.message : e), "err");
        return false;
      });
    }

    root.querySelector("#btnSave").onclick = function(){
      saveChanges();
    };

    root.querySelector("#btnReset").onclick = function(){
      HC.motion.confirm("恢复默认设置", "恢复默认", function(){
        HC.api.defaultSettings().then(function(d){
          return HC.api.saveSettings(d);
        }).then(function(){
          return Promise.all([HC.api.getSettings(), HC.api.downloaders()]);
        }).then(function(res){
          HC.settings = Object.assign({}, res[0] || {});
          try{ localStorage.removeItem("hc_row_density"); }catch(e){}
          densityKey = "compact";
          document.documentElement.classList.remove("density-comfort");
          document.body.classList.remove("density-comfort");
          fill(res[0] || {}, res[1] || []);
          if (HC.sfx && HC.sfx.play) HC.sfx.play("done");
          HC.motion.toast("已恢复默认设置", "ok");
        }).catch(function(e){
          if (HC.sfx && HC.sfx.play) HC.sfx.play("fail");
          HC.motion.toast(String(e && e.message ? e.message : e), "err");
        });
      });
    };

    function revertApplied(){
      if (HC.applySettings) HC.applySettings(HC.settings || {});
    }

    function goSearch(){
      lookStop();
      location.hash = "search";
    }

    function promptUnsaved(onProceed){
      if (snapshot() === baseline){
        onProceed();
        return;
      }
      HC.motion.confirmUnsaved(function(){
        saveChanges(onProceed);
      }, function(){
        baseline = snapshot();
        lookStop();
        revertApplied();
        onProceed();
      });
    }

    function tryClose(){
      promptUnsaved(goSearch);
    }

    var leaveGuard = function(action){
      if (!root || !root.isConnected) return false;
      if (snapshot() === baseline) return false;
      promptUnsaved(action);
      return true;
    };
    HC.leaveGuard = leaveGuard;

    if (mount._clkKey) document.removeEventListener("click", mount._clkKey, true);
    mount._clkKey = function(e){
      if (!root || !root.isConnected) return;
      var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
      if (!a) return;
      if (snapshot() === baseline) return;
      e.preventDefault();
      e.stopPropagation();
      var href = a.getAttribute("href");
      promptUnsaved(function(){
        location.hash = href;
      });
    };
    document.addEventListener("click", mount._clkKey, true);

    if (mount._hashKey) window.removeEventListener("hashchange", mount._hashKey);
    mount._hashKey = function(){
      if (root && root.isConnected) return;
      lookStop();
      if (HC.leaveGuard === leaveGuard) HC.leaveGuard = null;
      if (mount._clkKey) document.removeEventListener("click", mount._clkKey, true);
      if (mount._docKey) document.removeEventListener("keydown", mount._docKey);
      window.removeEventListener("hashchange", mount._hashKey);
    };
    window.addEventListener("hashchange", mount._hashKey);

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

    root.querySelector("#btnRepo").onclick = function(){
      HC.api.openRepo();
    };
  }

  HC.views.settings = { mount: mount };
})();
