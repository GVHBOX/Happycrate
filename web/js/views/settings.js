(function(){
  var HC = window.HC || (window.HC = {});
  HC.views = HC.views || {};

  var FIELDS = [
    {key:"min_query_len", label:"最短关键词", group:"检索", min:1, max:20, step:1},
    {key:"max_workers", label:"并发数", group:"检索", min:1, max:32, step:1},
    {key:"timeout", label:"投递/清单超时", group:"检索", min:1, max:120, step:1, unit:"秒"},
    {key:"soft_deadline_ms", label:"软截止", group:"检索", min:0, max:60000, step:500, unit:"毫秒"},
    {key:"retries", label:"重试次数", group:"检索", min:0, max:5, step:1},
    {key:"proxy", label:"代理", group:"网络", ph:"http://127.0.0.1:7890"},
    {key:"user_agent", label:"User-Agent", group:"网络", ph:"留空用内置"},
    {key:"ui_font_size", label:"界面字号", group:"外观",
      seg:[{key:"14", label:"小"}, {key:"18", label:"标准"}, {key:"22", label:"大"}]}
  ];

  var root = null;
  var dlKey = "";
  var selbarOn = false;
  var themeOn = false;
  var autoFilesOn = true;
  var keepDupOn = false;
  var progStyleKey = "segment";
  var progLineOn = true;
  var brandKey = "";

  var STEP_BTN = {
    minus:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M3.5 7h7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    plus:'<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M3.5 7h7M7 3.5v7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
  };

  var esc = HC.esc;

  var netEl = null;
  var netBusy = false;
  var netGen = 0;

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
    if (data.tun){
      return {dot:"ok", title:"直连 · TUN", addr:"TUN 网卡 " + data.tun};
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
      netPaint(d || {mode:"none"});
    }).catch(function(){
      if (gen !== netGen) return;
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

  var PROG_OPTS = [
    {key:"segment", label:"分段 · 警戒线"},
    {key:"flow", label:"连续斜纹"}
  ];

  function paintProg(current){
    var box = root.querySelector("#s_progstyle");
    if (!box) return;
    box.innerHTML = segHtml(PROG_OPTS, current, "ps");
    syncSeg(box, "ps", current);
  }

  var BRAND_OPTS = [
    {key:"", label:"默认"},
    {key:"teal", label:"青碧"},
    {key:"slate", label:"石墨蓝"},
    {key:"lilac", label:"薰衣草"}
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

  var LOOK_COLORS = [
    {key:"on", label:"已返回"},
    {key:"warn", label:"超期"},
    {key:"line", label:"警戒线"},
    {key:"err", label:"失败"},
    {key:"slot", label:"空槽"},
    {key:"gap", label:"槽底"}
  ];

  var LOOK_NUMS = [
    {key:"h", label:"条高", unit:"px", step:1},
    {key:"radius", label:"圆角", unit:"px", step:0.5},
    {key:"gapx", label:"间距", unit:"px", step:1},
    {key:"skew", label:"斜切", unit:"°", step:1},
    {key:"flow", label:"斜纹周期", unit:"ms", step:50},
    {key:"ang", label:"条纹角度", unit:"°", step:1},
    {key:"sw", label:"亮条宽", unit:"px", step:1},
    {key:"cycle", label:"条纹周期", unit:"px", step:1},
    {key:"alpha", label:"白纹浓度", unit:"%", step:1},
    {key:"glow", label:"辉光", unit:"px", step:1},
    {key:"pulse", label:"脉冲周期", unit:"ms", step:50},
    {key:"dlw", label:"线宽", unit:"px", step:1},
    {key:"dlout", label:"线出头", unit:"px", step:1},
    {key:"hold", label:"完成停顿", unit:"ms", step:30},
    {key:"step", label:"熄灭间隔", unit:"ms", step:5}
  ];

  var LOOK_PRESETS = [
    {key:"", label:"跟随主题"},
    {key:"aubergine", label:"藕紫"},
    {key:"mint", label:"薄荷"},
    {key:"sky", label:"晴空"},
    {key:"matcha", label:"抹茶"}
  ];

  var LOOK_PRESET_COLORS = {
    aubergine:{on:"#8B7FE0", warn:"#6F5CB8", line:"#4C3D8F", err:"#D4676E", slot:"#E3E1F2", gap:"#C5C1DF"},
    mint:{on:"#1F9C82", warn:"#177A63", line:"#0E4F41", err:"#D4676E", slot:"#DCE7E3", gap:"#BDD3CD"},
    sky:{on:"#1C8FC9", warn:"#126B99", line:"#0F4A66", err:"#D4676E", slot:"#DBE6F0", gap:"#B9CDE3"},
    matcha:{on:"#6BA33F", warn:"#4E7B2C", line:"#37581E", err:"#D4676E", slot:"#E4E9DB", gap:"#C6D3B9"}
  };

  var LOOK_FALLBACK_DEFAULTS = {
    on:"", warn:"", line:"", err:"", slot:"", gap:"",
    h:10, radius:2.5, gapx:4, skew:16,
    flow:700, ang:-55, sw:4, cycle:9, alpha:16, glow:8, pulse:550,
    dlw:2, dlout:4, hold:420, step:45
  };

  var LOOK_FALLBACK_RANGE = {
    h:[6,16], radius:[0,6], gapx:[1,8], skew:[0,24],
    flow:[300,2000], ang:[-80,-20], sw:[2,8], cycle:[6,18],
    alpha:[5,40], glow:[0,14], pulse:[300,1200],
    dlw:[1,4], dlout:[0,6], hold:[0,900], step:[15,110]
  };

  var look = null;
  var lookPreset = "";
  var lookRaf = 0;
  var lookTimes = [];
  var lookTimer = [];

  function lookDefaults(){
    var out = {};
    var base = Object.assign({}, LOOK_FALLBACK_DEFAULTS, HC.LOOK_DEFAULTS || {});
    Object.keys(base).forEach(function(k){ out[k] = base[k]; });
    return out;
  }

  function lookRange(key){
    return (HC.LOOK_RANGE || {})[key] || LOOK_FALLBACK_RANGE[key] || null;
  }

  function lookNum(v, key){
    var r = lookRange(key);
    v = parseFloat(v);
    if (isNaN(v)) v = lookDefaults()[key];
    if (r) v = Math.max(r[0], Math.min(r[1], v));
    return v;
  }

  function lookRead(){
    if (!look) return lookDefaults();
    return look;
  }

  var LOOK_VAR = {on:"--prog-on", warn:"--prog-warn", line:"--prog-line",
                  err:"--prog-err", slot:"--prog-slot", gap:"--prog-gap"};

  function rgbToHex(v){
    var m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(String(v || ""));
    if (!m) return "";
    var to = function(n){
      return ("0" + Math.round(Math.max(0, Math.min(255, parseFloat(n)))).toString(16)).slice(-2);
    };
    return "#" + to(m[1]) + to(m[2]) + to(m[3]);
  }

  function lookCurrentColor(key){
    var v = lookRead()[key];
    if (v && /^#[0-9a-fA-F]{6}$/.test(v)) return v;
    var css = (getComputedStyle(document.documentElement)
      .getPropertyValue(LOOK_VAR[key] || "") || "").trim();
    if (/^#[0-9a-fA-F]{3}$/.test(css)){
      return "#" + css[1] + css[1] + css[2] + css[2] + css[3] + css[3];
    }
    if (/^#[0-9a-fA-F]{6}$/.test(css)) return css;
    var rgb = rgbToHex(css);
    if (rgb && !/rgba\(/i.test(css)) return rgb;
    var fb = LOOK_COLOR_FALLBACK[key];
    if (fb) return document.body.classList.contains("dark") ? fb.dark : fb.light;
    if (rgb) return rgb;
    return "#8B7FE0";
  }

  var LOOK_COLOR_FALLBACK = {
    gap:{light:"#C7CAD3", dark:"#3A3D4C"},
    slot:{light:"#F1F2F5", dark:"#252732"},
    on:{light:"#4A45E3", dark:"#5B56EE"}
  };

  function lookHtml(){
    var l = lookRead();
    return '<div class="lookprev">' +
        '<div class="progress" id="lookBar"><div class="track" id="lookTrack"></div>' +
          '<div class="deadline" id="lookDl"></div></div>' +
        '<div class="lookrow"><button type="button" class="btn btn-ghost" id="btnLookPlay">播放一轮</button>' +
          '<span class="lookst" id="lookSt">9 个源 · 最快 0.4s · 最慢 4.0s</span></div>' +
      '</div>' +
      '<div class="field inline"><span class="lbl" id="lb_lookp">配色</span>' +
        '<div class="seg" id="s_lookpreset" role="group" aria-labelledby="lb_lookp">' +
        segHtml(LOOK_PRESETS, lookPreset, "lp") + '</div></div>' +
      '<div class="looksub">颜色</div>' +
      '<div class="lookgrid c3">' + LOOK_COLORS.map(function(c){
        return '<div class="lookc"><input type="color" class="csel" data-lookc="' + c.key +
          '" value="' + lookCurrentColor(c.key) + '" aria-label="' + esc(c.label) + '">' +
          '<span>' + esc(c.label) + '</span></div>';
      }).join("") + '</div>' +
      '<div class="looksub">形状</div>' +
      '<div class="lookgrid">' + LOOK_NUMS.slice(0, 4).map(function(n){
        return lookNumHtml(n, l);
      }).join("") + '</div>' +
      '<div class="looksub">动画</div>' +
      '<div class="lookgrid">' + LOOK_NUMS.slice(4).map(function(n){
        return lookNumHtml(n, l);
      }).join("") + '</div>' +
      '<div class="looksub">导入导出</div>' +
      '<textarea class="lookjson" id="lookJson" spellcheck="false"></textarea>' +
      '<div class="lookacts">' +
        '<button type="button" class="btn btn-ghost" id="btnLookExport">复制</button>' +
        '<button type="button" class="btn btn-ghost" id="btnLookImport">从文本框应用</button>' +
      '</div>';
  }

  function lookNumHtml(n, l){
    var r = lookRange(n.key) || [0, 100];
    var v = lookNum(l[n.key], n.key);
    return '<div class="lookn" data-lookn="' + n.key + '">' +
      '<div class="lrow"><span class="lb">' + esc(n.label) + '</span>' +
        '<b class="rv">' + v + esc(n.unit) + '</b></div>' +
      '<input type="range" min="' + r[0] + '" max="' + r[1] + '" step="' + n.step +
        '" value="' + v + '" aria-label="' + esc(n.label) + '">' +
      '<div class="rscale"><span>' + r[0] + '</span><span>' + r[1] + '</span></div>' +
    '</div>';
  }

  function lookWire(){
    var box = root.querySelector("#lookCtl");
    if (!box) return;
    box.querySelectorAll("[data-lookn]").forEach(function(wrap){
      var key = wrap.dataset.lookn;
      var input = wrap.querySelector("input[type=range]");
      var out = wrap.querySelector(".rv");
      var spec = null;
      LOOK_NUMS.forEach(function(n){ if (n.key === key) spec = n; });
      if (!spec || !input) return;
      input.addEventListener("input", function(){
        var v = lookNum(input.value, key);
        look[key] = v;
        input.value = v;
        out.textContent = v + spec.unit;
        lookApply();
        onEdit();
      });
    });
    box.querySelectorAll("[data-lookc]").forEach(function(el){
      el.addEventListener("input", function(){
        look[el.dataset.lookc] = el.value;
        lookPreset = "";
        syncSeg(root.querySelector("#s_lookpreset"), "lp", lookPreset);
        lookApply();
        onEdit();
      });
    });
    var presetBox = box.querySelector("#s_lookpreset");
    if (presetBox) presetBox.addEventListener("click", function(e){
      var b = e.target.closest("[data-lp]");
      if (!b) return;
      lookPreset = b.dataset.lp;
      syncSeg(this, "lp", lookPreset);
      var preset = LOOK_PRESET_COLORS[lookPreset] || null;
      LOOK_COLORS.forEach(function(c){
        look[c.key] = preset ? preset[c.key] : "";
        var el = root.querySelector('[data-lookc="' + c.key + '"]');
        if (el) el.value = lookCurrentColor(c.key);
      });
      lookApply();
      onEdit();
    });

    var play = box.querySelector("#btnLookPlay");
    if (play) play.onclick = lookPlay;

    var exp = box.querySelector("#btnLookExport");
    if (exp) exp.onclick = function(){
      var txt = root.querySelector("#lookJson").value;
      HC.motion.copy(txt).then(function(ok){
        HC.motion.toast(ok ? "已复制外观配置" : "复制失败", ok ? "ok" : "err");
      });
    };

    var imp = box.querySelector("#btnLookImport");
    if (imp) imp.onclick = function(){
      var txt = root.querySelector("#lookJson").value;
      var parsed = null;
      try { parsed = JSON.parse(txt); } catch (err) { parsed = null; }
      if (!parsed){
        HC.motion.toast("不是合法的 JSON", "err");
        return;
      }
      look = HC.readLook ? HC.readLook(parsed) : lookDefaults();
      buildLook(look);
      onEdit();
      HC.motion.toast("已应用", "ok");
    };
  }

  function lookApply(){
    if (HC.applyProgressLook) HC.applyProgressLook(look);
    var j = root.querySelector("#lookJson");
    if (j) j.value = JSON.stringify(look);
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
    bar.classList.toggle("flow", progStyleKey === "flow");
    track.innerHTML = "";
    if (progStyleKey === "flow"){
      var f = document.createElement("div");
      f.className = "fill";
      f.innerHTML = '<div class="tex"></div>';
      track.appendChild(f);
    } else {
      for (var i = 0; i < 9; i++){
        var s = document.createElement("div");
        s.className = "seg";
        track.appendChild(s);
      }
    }
    var dl = root.querySelector("#lookDl");
    if (dl) dl.classList.remove("show", "passed");
  }

  function lookPlay(){
    var track = root.querySelector("#lookTrack");
    var dl = root.querySelector("#lookDl");
    var st = root.querySelector("#lookSt");
    var bar = root.querySelector("#lookBar");
    if (!track || !bar) return;
    lookStop();
    lookResetPreview();
    var deadline = 3;
    var raw = (HC.settings || {}).soft_deadline_ms;
    if (raw !== undefined && raw !== null && raw !== "") deadline = parseInt(raw, 10) / 1000;
    if (!deadline || deadline <= 0 || isNaN(deadline)) deadline = 3;
    lookTimes = [];
    for (var j = 0; j < 9; j++) lookTimes.push(0.4 + Math.random() * 3.6);
    lookTimes.sort(function(a, b){ return a - b; });
    var t0 = performance.now();
    (function frame(now){
      var el = (now - t0) / 1000;
      var done = 0, warned = 0;
      var segs = track.querySelectorAll(".seg");
      for (var i = 0; i < segs.length; i++){
        var back = lookTimes[i] <= el;
        if (back) done++;
        else if (el > deadline) warned++;
        segs[i].className = "seg" + (back ? " on" : (el > deadline ? " warned" : ""));
      }
      if (dl){
        var ratio = Math.min(1, el / deadline);
        dl.style.left = (ratio * 100) + "%";
        dl.classList.add("show");
        dl.classList.toggle("passed", ratio >= 1);
      }
      if (st) st.textContent = done + "/9 源" + (warned ? " · 越过软截止 " + warned + " 个" : "");
      if (el >= lookTimes[8] + 0.3){ lookFinish(); return; }
      lookRaf = requestAnimationFrame(frame);
    })(t0);
  }

  function lookFinish(){
    var track = root.querySelector("#lookTrack");
    var dl = root.querySelector("#lookDl");
    var st = root.querySelector("#lookSt");
    var hold = lookNum(look.hold, "hold") || 0;
    var step = lookNum(look.step, "step") || 45;
    if (st) st.textContent = "完成 · 9/9";
    lookTimer.push(setTimeout(function(){
      var lit = [].slice.call(track.querySelectorAll(".seg.on")).reverse();
      lit.forEach(function(seg, i){
        lookTimer.push(setTimeout(function(){ seg.className = "seg"; }, i * step));
      });
      if (dl) dl.classList.remove("show", "passed");
      lookTimer.push(setTimeout(function(){
        if (st) st.textContent = "完成 · 已回退到空槽";
      }, lit.length * step + (HC.PROG_TAIL_MS || 560)));
    }, hold));
  }

  function buildLook(raw){
    look = HC.readLook ? HC.readLook(raw) : lookDefaults();
    var box = root.querySelector("#lookCtl");
    if (!box) return;
    box.innerHTML = lookHtml();
    lookPreset = "";
    syncSeg(root.querySelector("#s_lookpreset"), "lp", lookPreset);
    lookWire();
    lookApply();
    lookResetPreview();
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
    out.progress_style = progStyleKey;
    out.progress_line = progLineOn;
    out.keep_duplicates = keepDupOn;
    out.progress_look = look ? JSON.stringify(look) : "";
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
            '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none">' +
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
          '<div class="field inline"><label for="s_keepdup">保留重复项</label>' +
            '<button type="button" class="sw" id="s_keepdup" role="switch"></button></div>' +
          '<div class="field inline"><span class="lbl" id="lb_prog">进度条</span>' +
            '<div class="seg" id="s_progstyle" role="group" aria-labelledby="lb_prog"></div></div>' +
          '<div class="field inline"><label for="s_progline">警戒线</label>' +
            '<button type="button" class="sw" id="s_progline" role="switch"></button></div>' +
        '</div>' +
        '<div class="dfoot"><span class="status" id="st"></span>' +
          '<div class="spacer"></div>' +
          '<button class="btn btn-ghost" id="btnReset">恢复默认</button>' +
          '<button class="btn btn-brand" id="btnSave">保存</button></div>' +
      '</div>' +
      '<div class="card">' +
        '<div class="dhead"><span class="dtitle">进度条外观</span><div class="spacer"></div>' +
          '<span class="status" id="lookHint"></span></div>' +
        '<div class="div"></div>' +
        '<div class="mbody" id="lookCtl"></div>' +
      '</div>' +
      '<div class="card">' +
        '<div class="dhead"><span class="dtitle">关于</span></div>' +
        '<div class="div"></div>' +
        '<div class="mbody" id="about"></div>' +
        '<div class="dfoot"><div class="spacer"></div>' +
          '<button class="btn btn-ghost" id="btnReloadRoles">重新载入词表</button>' +
          '<button class="btn btn-ghost" id="btnLogs">打开日志目录</button></div>' +
      '</div>';

    mountEl.appendChild(root);

    netEl = root.querySelector("#netbar");
    netBusy = false;
    netGen += 1;
    root.querySelector("#btnNetRecheck").onclick = function(){ netCheck(true); };

    function fill(settings, list){
      root.querySelector("#fields").innerHTML = fieldsHtml(settings);
      netPlace();
      setTimeout(netCheck, 60);
      wireSteppers();
      fontKey = snapFont(settings.ui_font_size);
      syncSeg(root.querySelector("#s_ui_font_size"), "font", fontKey);
      applyFont(fontKey);

      dlKey = settings.default_downloader || "";
      paintDl(list, dlKey);
      selbarOn = settings.selbar === true;
      setSw("#s_selbar", selbarOn);
      themeOn = settings.theme === "dark";
      setSw("#s_theme", themeOn);
      autoFilesOn = settings.auto_files !== false;
      setSw("#s_autofiles", autoFilesOn);
      keepDupOn = settings.keep_duplicates === true;
      setSw("#s_keepdup", keepDupOn);
      progStyleKey = settings.progress_style === "flow" ? "flow" : "segment";
      paintProg(progStyleKey);
      progLineOn = settings.progress_line !== false;
      setSw("#s_progline", progLineOn);
      brandKey = settings.brand || "";
      paintBrand(brandKey);
      if (HC.applyTheme) HC.applyTheme(settings.theme || "light");
      if (HC.applyBrand) HC.applyBrand(brandKey);
      buildLook(settings.progress_look);
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

    function aboutHtml(info){
      var lines = [
        ["版本", info.version, false],
        ["数据目录", info.dataDir, true],
        ["运行模式", info.mode, false],
        ["日志", info.logFile, true]
      ];
      if (info.proxy) lines.push(["网络出口", info.proxy, true]);
      if (info.migratedFrom) lines.push(["配置来源", info.migratedFrom, true]);
      return lines.map(function(p){
        return '<div class="kv"><span class="k">' + esc(p[0]) + '</span>' +
          '<span class="v">' + esc(p[1] || "") + '</span>' +
          (p[2] ? '<button type="button" class="cp" data-cp="' + esc(p[1] || "") + '">复制</button>' : '') +
          '</div>';
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
      root.querySelector("#about").innerHTML = aboutHtml(info || {});
    }).catch(function(err){
      aboutFail("版本信息读取失败", err);
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

    root.querySelector("#s_keepdup").onclick = function(){
      keepDupOn = !keepDupOn;
      setSw("#s_keepdup", keepDupOn);
      onEdit();
    };

    root.querySelector("#s_progline").onclick = function(){
      progLineOn = !progLineOn;
      setSw("#s_progline", progLineOn);
      onEdit();
    };

    root.querySelector("#s_progstyle").onclick = function(e){
      var b = e.target.closest("button[data-ps]");
      if (!b) return;
      progStyleKey = b.dataset.ps;
      syncSeg(root.querySelector("#s_progstyle"), "ps", progStyleKey);
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
      var fields = readFields();
      btn.disabled = true;
      HC.api.saveSettings(fields).then(function(r){
        btn.disabled = false;
        if (r && r.ok){
          HC.settings = Object.assign({}, HC.settings, fields);
          if (HC.applyProgressLook) HC.applyProgressLook(fields.progress_look);
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
      lookStop();
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

    root.querySelector("#btnReloadRoles").onclick = function(){
      HC.api.reloadQueryRoles().then(function(){
        HC.motion.toast("词表已重新载入", "ok");
      }, function(){
        HC.motion.toast("词表载入失败", "err");
      });
    };
  }

  HC.views.settings = { mount: mount };
})();
