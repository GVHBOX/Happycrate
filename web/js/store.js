(function(){
  var HC = window.HC || (window.HC = {});

  var FATAL = ["timeout", "net", "http403", "http5xx", "blocked", "http451", "err"];

  function mergeState(outcomes){
    var recent = (outcomes || []).filter(function(o){
      return o && o !== "cancel";
    }).slice(-5);
    if (!recent.length) return "na";
    var fatal = recent.filter(function(o){ return FATAL.indexOf(o) >= 0; }).length;
    if (fatal >= 3 || FATAL.indexOf(recent[recent.length - 1]) >= 0) return "err";
    var last = recent[recent.length - 1];
    if (last === "empty") return "empty";
    if (["http429", "http4xx", "parse", "shape", "unknown"].indexOf(last) >= 0) return "warn";
    if (last === "ok" || last === "slow"){
      var empties = recent.filter(function(o){ return o === "empty"; }).length;
      if (empties && empties * 2 > recent.length) return "empty";
      return "ok";
    }
    return "na";
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
      return state.sources.filter(function(s){
        return s.enabled && mergeState((s.health && s.health.outcomes) || []) === "err";
      }).length;
    },

    emptyCount: function(){
      return state.sources.filter(function(s){
        return s.enabled && mergeState((s.health && s.health.outcomes) || []) === "empty";
      }).length;
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
})();
