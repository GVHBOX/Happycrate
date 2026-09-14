(function(){
  var HC = window.HC || (window.HC = {});

  var calls = [];
  var errors = [];
  var MAX = 20;

  window.addEventListener("error", function(e){
    errors.push({
      at: Date.now(),
      text: (e.message || "未知错误") + " @ " + (e.filename || "?").split("/").pop() +
            ":" + (e.lineno || 0)
    });
    if (errors.length > MAX) errors.shift();
  });

  window.addEventListener("unhandledrejection", function(e){
    errors.push({at: Date.now(), text: "Promise: " + ((e.reason && e.reason.message) || e.reason || "?")});
    if (errors.length > MAX) errors.shift();
  });

  function stamp(ts){
    var d = new Date(ts), p = function(n){ return String(n).padStart(2, "0"); };
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  function record(name, ms, state){
    calls.push({at: Date.now(), name: name, ms: Math.round(ms), state: state});
    if (calls.length > MAX) calls.shift();
  }

  function wrap(){
    Object.keys(HC.api || {}).forEach(function(name){
      var fn = HC.api[name];
      if (typeof fn !== "function") return;
      if (name === "onSearch" || name === "onProbeDone") return;
      HC.api[name] = function(){
        var t0 = performance.now();
        var args = [].slice.call(arguments);
        var out;
        try {
          out = fn.apply(null, args);
        } catch (e){
          record(name, performance.now() - t0, "throw");
          throw e;
        }
        if (out && typeof out.then === "function"){
          return out.then(function(v){
            record(name, performance.now() - t0, "ok");
            return v;
          }, function(e){
            record(name, performance.now() - t0, "fail");
            throw e;
          });
        }
        record(name, performance.now() - t0, "ok");
        return out;
      };
    });
  }

  var esc = HC.esc;

  function text(){
    var lines = ["[happycrate 诊断] " + stamp(Date.now()), ""];
    lines.push("> 环境");
    var info = HC._diagInfo || {};
    lines.push("  版本  " + (info.version || "?"));
    lines.push("  接口  " + (HC.api.mode ? HC.api.mode() : "?"));
    lines.push("  模式  " + (info.mode || "?"));
    lines.push("  数据  " + (info.dataDir || "?"));
    lines.push("  日志  " + (info.logFile || "?"));
    if (info.migratedFrom) lines.push("  迁移  " + info.migratedFrom);
    lines.push("  内核  " + navigator.userAgent);

    lines.push("");
    lines.push("> 最近调用");
    if (!calls.length){
      lines.push("  （无）");
    } else {
      calls.slice().reverse().forEach(function(c){
        lines.push("  " + stamp(c.at) + "  " + pad(c.name, 20) + pad(c.state, 6) + c.ms + "ms");
      });
    }

    lines.push("");
    lines.push("> 前端错误");
    if (!errors.length){
      lines.push("  （无）");
    } else {
      errors.slice().reverse().forEach(function(e){
        lines.push("  " + stamp(e.at) + "  " + e.text);
      });
    }
    return lines.join("\n");
  }

  function pad(s, n){
    s = String(s);
    while (s.length < n) s += " ";
    return s;
  }

  function refresh(){
    if (!HC.api || !HC.api.appInfo) return Promise.resolve();
    return HC.api.appInfo().then(function(info){
      HC._diagInfo = info || {};
    }, function(){});
  }

  function render(){
    close();
    var bd = document.createElement("div");
    bd.className = "backdrop";
    bd.innerHTML =
      '<div class="modal w640">' +
        '<div class="dhead"><span class="dtitle">诊断</span></div>' +
        '<div class="div"></div>' +
        '<div class="mbody"><div class="term selectable" style="max-height:380px;overflow:auto">' +
          esc(text()) + '</div></div>' +
        '<div class="dfoot"><div class="spacer"></div>' +
          '<button class="btn btn-ghost" data-close>关闭</button>' +
          '<button class="btn btn-brand" data-copy>复制</button></div>' +
      '</div>';
    document.body.appendChild(bd);
    bd.addEventListener("click", function(e){
      if (e.target === bd || e.target.closest("[data-close]")) close();
      var cp = e.target.closest("[data-copy]");
      if (cp){
        HC.motion.copy(text()).then(function(ok){
          if (ok) HC.motion.morph(cp, "已复制");
          else HC.motion.toast("复制失败", "err");
        });
      }
    });
  }

  function open(){
    refresh().then(render, render);
  }

  function close(){
    var bds = document.querySelectorAll(".backdrop");
    var bd = bds[bds.length - 1];
    if (!bd || bd.classList.contains("closing")) return;
    bd.classList.add("closing");
    setTimeout(function(){ bd.remove(); }, 180);
  }

  document.addEventListener("keydown", function(e){
    if (e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d")){
      e.preventDefault();
      open();
    }
    if (e.key === "Escape"){
      var bd = document.querySelector(".backdrop");
      if (bd && bd.querySelector("[data-close]")) close();
    }
  });

  if (HC.api) wrap();

  HC.diagnostics = { open: open, text: text };
})();
