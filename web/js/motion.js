(function(){
  var HC = window.HC || (window.HC = {});

  var esc = HC.esc;

  function rippleHost(el){
    return el.closest(".btn, .iconbtn, .mi, .cb, .gobtn, .chipbtn, .seg button, .stepper button, .tb-btn, .sbtn, .sclose, .fchev, .srcdot");
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
    setTimeout(function(){ dot.remove(); }, 480);
  });

  function dismissToast(el){
    if (el.dataset.gone) return;
    el.dataset.gone = "1";
    clearTimeout(el._t);
    el.classList.remove("show");
    setTimeout(function(){ if (el.parentNode) el.parentNode.removeChild(el); }, 300);
  }

  function toast(msg, kind){
    var box = document.getElementById("toasts");
    if (!box){
      box = document.createElement("div");
      box.id = "toasts";
      box.className = "toasts";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    var el = document.createElement("div");
    el.className = "toast" + (kind === "err" ? " err" : kind === "ok" ? " ok" : "");
    el.innerHTML = (kind === "ok" ? ICON_CHECK : kind === "err" ? ICON_CROSS : "") + "<span>" + esc(msg) + "</span>";
    box.appendChild(el);
    requestAnimationFrame(function(){ el.classList.add("show"); });
    el._t = setTimeout(function(){ dismissToast(el); }, kind === "long" ? 2600 : 1900);
    var live = [].slice.call(box.children).filter(function(x){ return !x.dataset.gone; });
    if (live.length > 3) dismissToast(live[0]);
  }

  var ICON_CHECK = '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M2.8 7.4L5.6 10.2L11.2 4.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var ICON_CROSS = '<svg width="14" height="14" viewBox="-1 -1 16 16" fill="none"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  function focusables(scope){
    return [].slice.call(scope.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
      .filter(function(x){ return x.offsetParent !== null; });
  }

  function confirm(question, okLabel, onOk){
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

  function openModal(html, wide){
    closeModal();
    var bd = document.createElement("div");
    bd.className = "backdrop";
    bd.innerHTML = '<div class="modal' + (wide ? " w640" : "") + '" role="dialog" aria-modal="true" tabindex="-1">' + html + '</div>';
    bd._opener = document.activeElement;
    document.body.appendChild(bd);
    bd.addEventListener("click", function(e){
      if (e.target === bd) closeModal();
      if (e.target.closest("[data-close]")) closeModal();
    });
    bd.addEventListener("keydown", function(e){
      if (e.key !== "Tab") return;
      var list = focusables(bd.querySelector(".modal"));
      if (!list.length) return;
      var first = list[0], last = list[list.length - 1];
      if (e.shiftKey && (document.activeElement === first || !bd.contains(document.activeElement))){
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !bd.contains(document.activeElement))){
        e.preventDefault();
        first.focus();
      }
    });
    var modal = bd.querySelector(".modal");
    var target = focusables(modal)[0];
    (target || modal).focus();
    return modal;
  }

  function closeModal(){
    var bds = document.querySelectorAll(".backdrop");
    var bd = bds[bds.length - 1];
    if (!bd || bd.classList.contains("closing")) return;
    bd.classList.add("closing");
    var opener = bd._opener;
    if (opener && opener.isConnected) opener.focus();
    setTimeout(function(){ bd.remove(); }, 180);
  }

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
      ta.focus();
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

  var dragEscCancel = null;
  document.addEventListener("keydown", function(e){
    if (e.key !== "Escape" || !dragEscCancel) return;
    var fn = dragEscCancel;
    dragEscCancel = null;
    fn();
  });

  function dragRows(container, opts){
    var ctx = null;
    var dragRow = null;
    var cancelled = false;

    container.addEventListener("pointerdown", function(e){
      var handle = e.target.closest("[data-drag]");
      if (!handle) return;
      if (opts && opts.blocked && opts.blocked()) return;
      var row = handle.closest(".row");
      if (!row) return;
      var rect = row.getBoundingClientRect();
      ctx = {
        row: row,
        key: row.dataset.key,
        startY: e.clientY,
        grabDy: e.clientY - rect.top,
        dy: 0,
        active: false,
        target: null,
        ph: null,
        top0: rect.top,
        rowH: rect.height
      };
      dragRow = row;
      cancelled = false;
      dragEscCancel = cancelDrag;
      row.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    function cancelDrag(){
      cancelled = true;
      var d = ctx;
      ctx = null;
      dragRow = null;
      if (!d) return;
      d.row.style.top = "";
      d.row.style.width = "";
      d.row.classList.remove("dragging");
      if (d.ph) d.ph.remove();
    }

    container.addEventListener("pointermove", function(e){
      if (!ctx || cancelled) return;
      ctx.dy = e.clientY - ctx.startY;
      if (!ctx.active && Math.abs(ctx.dy) < 6) return;
      if (!ctx.active){
        ctx.active = true;
        var rect = ctx.row.getBoundingClientRect();
        ctx.row.style.width = rect.width + "px";
        ctx.row.style.top = rect.top + "px";
        ctx.row.classList.add("dragging");
        ctx.rowH = rect.height;
        var ph = document.createElement("div");
        ph.style.height = rect.height + "px";
        ph.className = "placeholder";
        container.insertBefore(ph, ctx.row);
        ctx.ph = ph;
      }
      ctx.row.style.top = (ctx.top0 + ctx.dy) + "px";
      var pointerMid = e.clientY - ctx.grabDy + ctx.rowH / 2;
      var movers = rowList(ctx.row);
      var phNow = phIndexInDOM(ctx.ph, ctx.row);
      var phIdx = movers.length;
      for (var i = 0; i < movers.length; i++){
        var mid = movers[i].getBoundingClientRect().top + movers[i].offsetHeight / 2;
        if (pointerMid < mid){ phIdx = i; break; }
      }
      if (phIdx !== phNow) slidePlaceholder(container, ctx.ph, phIdx, movers);
    });

    function phIndexInDOM(ph, dragRowEl){
      var n = 0, el = ph.previousElementSibling;
      while (el){
        if (el.classList.contains("row") && el !== dragRowEl) n++;
        el = el.previousElementSibling;
      }
      return n;
    }

    function flipMove(movers, place){
      var before = new Map();
      movers.forEach(function(r){ before.set(r, r.getBoundingClientRect().top); });
      place();
      movers.forEach(function(r){
        var dy = before.get(r) - r.getBoundingClientRect().top;
        if (Math.abs(dy) > 1){
          r.style.transition = "none";
          r.style.transform = "translateY(" + dy + "px)";
          void r.offsetHeight;
          r.style.transition = "";
          r.style.transform = "";
        } else {
          r.style.transition = "";
        }
      });
    }

    function slidePlaceholder(containerEl, ph, to, movers){
      var phBefore = ph.getBoundingClientRect().top;
      flipMove(movers, function(){
        if (to <= 0) containerEl.insertBefore(ph, movers[0] || null);
        else if (to >= movers.length) containerEl.appendChild(ph);
        else containerEl.insertBefore(ph, movers[to]);
      });
      var phDy = phBefore - ph.getBoundingClientRect().top;
      if (Math.abs(phDy) > 1){
        ph.style.transition = "none";
        ph.style.transform = "translateY(" + phDy + "px)";
        void ph.offsetHeight;
        ph.style.transition = "";
        ph.style.transform = "";
      }
    }

    function rowList(exclude){
      return [].slice.call(container.querySelectorAll(".row")).filter(function(r){
        return r !== exclude;
      });
    }

    function finish(commit){
      if (dragEscCancel === cancelDrag) dragEscCancel = null;
      if (!ctx || cancelled) { ctx = null; dragRow = null; return; }
      var d = ctx;
      ctx = null;
      if (!d.active){
        dragRow = null;
        return;
      }
      d.row.style.width = "";
      var dropTo = -1;
      if (d.ph && d.ph.isConnected){
        dropTo = phIndexInDOM(d.ph, d.row);
        var phRect = d.ph.getBoundingClientRect();
        var rowRect = d.row.getBoundingClientRect();
        d.row.style.top = (rowRect.top + phRect.top - rowRect.top) + "px";
        d.row.style.transition = "top .26s var(--spring), box-shadow .2s var(--e)";
        d.ph.style.height = "0px";
        d.ph.style.marginTop = "0px";
        d.ph.style.marginBottom = "0px";
        var movers = rowList(d.row);
        flipMove(movers, function(){
          container.insertBefore(d.row, d.ph);
        });
        setTimeout(function(){
          d.row.style.top = "";
          d.row.style.transition = "";
          d.row.style.width = "";
          d.row.classList.remove("dragging");
          if (d.ph) d.ph.remove();
          if (commit && dropTo >= 0 && opts && opts.onDrop){
            opts.onDrop(d.key, dropTo);
          }
        }, 270);
        return;
      }
      d.row.style.top = "";
      d.row.classList.remove("dragging");
      if (d.ph) d.ph.remove();
      if (commit && dropTo >= 0 && opts && opts.onDrop){
        opts.onDrop(d.key, dropTo);
      }
    }

    container.addEventListener("pointerup", function(){ finish(true); });
    container.addEventListener("pointercancel", function(){ finish(false); });
  }

  HC.motion = {
    esc: esc,
    toast: toast,
    copy: copy,
    morph: morph,
    dragRows: dragRows,
    openModal: openModal,
    closeModal: closeModal,
    confirm: confirm
  };
})();
