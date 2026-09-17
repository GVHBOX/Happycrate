(function(){
  var HC = window.HC || (window.HC = {});

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
    dragRows: dragRows,
    openModal: openModal,
    closeModal: closeModal,
    confirm: confirm
  };
})();
