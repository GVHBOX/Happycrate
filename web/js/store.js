(function(){
  var HC = window.HC || (window.HC = {});

  var state = {
    sources: [],
    filter: "",
    batch: false,
    checked: [],
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

    subscribe: function(fn){ subs.push(fn); },

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
      return state.sources.filter(function(s){ return s.health.state === "err"; }).length;
    },

    enabledCount: function(){
      return state.sources.filter(function(s){ return s.enabled; }).length;
    },

    isChecked: function(key){ return state.checked.indexOf(key) >= 0; },

    toggleChecked: function(key){
      var i = state.checked.indexOf(key);
      if (i >= 0) state.checked.splice(i, 1);
      else state.checked.push(key);
    },

    clearChecked: function(){ state.checked = []; emit(); }
  };

  function emit(){
    subs.forEach(function(fn){
      try { fn(state); } catch(e) { console.error(e); }
    });
  }

  HC.store = store;
})();
