(function(){
  var HC = window.HC || (window.HC = {});
  var toastTimer = null;

  var esc = HC.esc;

  function rippleHost(el){
    return el.closest(".btn, .op, .iconbtn, .mi, .cb, .gobtn, .chipbtn, .seg button, .stepper button, .tb-btn, .sbtn, .sclose, .fchev, .srcdot");
  }

  document.addEventListener("pointerdown", function(e){
    var b = rippleHost(e.target);
    if (!b || b.disabled) return;
    var r = b.getBoundingClientRect();
    var d = Math.max(r.width, r.height) * 2.2;
    var dot = document.createElement("span");
    dot.className = "ripple";
    dot.style.width = dot.style.height = d + "px";
    dot.style.left = (e.clientX - r.left - d / 2) + "px";
    dot.style.top = (e.clientY - r.top - d / 2) + "px";
    b.appendChild(dot);
    setTimeout(function(){ dot.remove(); }, 620);
  });

  function toast(msg, kind){
    var el = document.getElementById("toast");
    if (!el){
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.innerHTML = (kind === "ok" ? ICON_CHECK : "") + "<span>" + esc(msg) + "</span>";
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ el.classList.remove("show"); }, kind === "long" ? 2600 : 1900);
  }

  var ICON_CHECK = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function copy(text){
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard && navigator.clipboard.writeText){
      return navigator.clipboard.writeText(text)
        .then(function(){ return true; })
        .catch(function(){ return fallbackCopy(text); });
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function fallbackCopy(text){
    try{
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      ta.remove();
      return ok;
    }catch(e){
      return false;
    }
  }

  function morph(btn, doneText){
    if (!btn || btn.dataset.morphing === "1") return;
    btn.dataset.morphing = "1";
    var html = btn.innerHTML;
    btn.classList.add("done");
    btn.innerHTML = ICON_CHECK + "<span>" + esc(doneText) + "</span>";
    setTimeout(function(){
      btn.classList.remove("done");
      btn.innerHTML = html;
      delete btn.dataset.morphing;
    }, 1100);
  }

  function dragRows(container, opts){
    var ctx = null;

    container.addEventListener("pointerdown", function(e){
      var handle = e.target.closest("[data-drag]");
      if (!handle) return;
      if (opts && opts.blocked && opts.blocked()) return;
      var row = handle.closest(".row");
      if (!row) return;
      ctx = {
        row: row,
        key: row.dataset.key,
        startY: e.clientY,
        dy: 0,
        active: false,
        target: null
      };
      row.setPointerCapture(e.pointerId);
    });

    container.addEventListener("pointermove", function(e){
      if (!ctx) return;
      ctx.dy = e.clientY - ctx.startY;
      if (!ctx.active && Math.abs(ctx.dy) < 4) return;
      if (!ctx.active){
        ctx.active = true;
        ctx.row.classList.add("dragging");
      }
      ctx.row.style.transform = "translateY(" + ctx.dy + "px)";

      var rows = [].slice.call(container.querySelectorAll(".row")).filter(function(r){
        return r !== ctx.row;
      });
      var target = rows.length;
      for (var i = 0; i < rows.length; i++){
        var rc = rows[i].getBoundingClientRect();
        if (e.clientY < rc.top + rc.height / 2){ target = i; break; }
      }
      ctx.target = target;

      [].slice.call(container.querySelectorAll(".indicator")).forEach(function(x){ x.remove(); });
      var ind = document.createElement("div");
      ind.className = "indicator";
      if (target >= rows.length) container.appendChild(ind);
      else container.insertBefore(ind, rows[target]);
    });

    function finish(){
      if (!ctx) return;
      var done = ctx;
      ctx = null;
      done.row.style.transform = "";
      done.row.classList.remove("dragging");
      [].slice.call(container.querySelectorAll(".indicator")).forEach(function(x){ x.remove(); });
      if (done.active && done.target != null && opts && opts.onDrop){
        opts.onDrop(done.key, done.target);
      }
    }

    container.addEventListener("pointerup", finish);
    container.addEventListener("pointercancel", finish);
  }

  HC.motion = {
    esc: esc,
    toast: toast,
    copy: copy,
    morph: morph,
    dragRows: dragRows
  };
})();
