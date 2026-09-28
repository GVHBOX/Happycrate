(function(){
  var HC = window.HC || (window.HC = {});

  var FATAL = ["timeout", "net", "http403", "http5xx", "blocked"];

  var WARNED = ["http429", "http4xx", "parse", "shape", "login", "unknown"];

  function mergeState(outcomes){
    var recent = (outcomes || []).filter(function(o){
      return o && o !== "cancel";
    }).slice(-5);
    if (!recent.length) return "na";
    var miss = 0, hit = 0, i, o;
    for (i = 0; i < recent.length; i++){
      o = recent[i];
      if (FATAL.indexOf(o) >= 0) miss++;
      if (o === "empty") hit++;
    }
    if (miss >= 3) return "err";
    var last = recent[recent.length - 1];
    if (FATAL.indexOf(last) >= 0) return "err";
    if (last === "empty") return "empty";
    if (WARNED.indexOf(last) >= 0) return "warn";
    if (last === "ok" || last === "slow"){
      if (!hit || hit < miss) return "ok";
      return hit > recent.length - hit ? "warn" : "ok";
    }
    if (last === "http451") return "err";
    return "na";
  }

  function stateOf(source){
    var h = (source && source.health) || {};
    if (h.state) return h.state;
    return mergeState(h.outcomes || []);
  }

  var state = {
    sources: [],
    filter: "",
    probing: false,
    firstPaint: true,
    probeDone: 0,
    probeTotal: 0
  };

  var subs = [];

  function stateCount(want){
    return state.sources.filter(function(s){
      return s.enabled && stateOf(s) === want;
    }).length;
  }

  var store = {
    get: function(){ return state; },

    set: function(patch){
      for (var k in patch) state[k] = patch[k];
      emit();
    },

    subscribe: function(fn){ if (subs.indexOf(fn) < 0) subs.push(fn); },

    byKey: function(key){
      return state.sources.filter(function(s){ return s.key === key; })[0] || null;
    },

    visible: function(){
      var f = state.filter.trim().toLowerCase();
      return state.sources.filter(function(s){
        if (!f) return true;
        return (s.label + " " + s.addr).toLowerCase().indexOf(f) >= 0;
      });
    },

    badCount: function(){
      return stateCount("err");
    },

    emptyCount: function(){
      return stateCount("empty");
    },

    enabledCount: function(){
      return state.sources.filter(function(s){ return s.enabled; }).length;
    }
  };

  function emit(){
    subs.forEach(function(fn){
      try { fn(state); } catch(e) { console.error(e); }
    });
  }

  HC.store = store;
  HC.mergeState = mergeState;
  HC.stateOf = stateOf;
})();
