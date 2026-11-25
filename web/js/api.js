(function(){
  var HC = window.HC || (window.HC = {});

  function live(){
    return !!(window.__TAURI__ && window.__TAURI__.core &&
              typeof window.__TAURI__.core.invoke === "function");
  }

  function invoke(name, args){
    if (!live()) return Promise.resolve(null);
    return window.__TAURI__.core.invoke(name, args);
  }

  function coerce(list){
    return (list || []).map(function(s){
      return {
        key: s.key || "",
        label: s.label || s.key || "",
        enabled: s.enabled !== false,
        signedIn: s.signed_in === true,
        addr: s.addr || "",
        health: {
          ms: (s.health && s.health.ms) || 0,
          err: (s.health && s.health.err) || "",
          state: (s.health && s.health.state) || "",
          outcomes: (s.health && s.health.outcomes) || []
        }
      };
    });
  }

  function onLive(fn){
    if (typeof fn !== "function") return;
    if (live()){ fn(); return; }
    var tries = 0;
    var timer = setInterval(function(){
      tries++;
      if (live()){
        clearInterval(timer);
        fn();
      } else if (tries > 80){
        clearInterval(timer);
      }
    }, 250);
  }

  var probeOne = null;
  var probeDoneSubs = [];
  var probeToken = -1;
  var sHooks = {};
  var MAGNET_CAP = 200;

  window.__onProbe = function(p){
    if (!p || p.token !== probeToken) return;
    if (probeOne) probeOne(p.key, p);
  };

  window.__onCaptcha = function(d){
    if (window.HC && HC.sfx) HC.sfx.play("captcha");
    if (sHooks.captcha && d) sHooks.captcha(d);
  };

  window.__onCaptchaDone = function(){
    if (window.HC && HC.sfx) HC.sfx.play("captcha_done");
  };

  window.__onProbeDone = function(p){
    if (p && p.token !== undefined && p.token !== probeToken) return;
    probeDoneSubs.slice().forEach(function(fn){
      try{ fn(); }catch(e){}
    });
  };

  window.__onSearchBatch = function(d){ if (sHooks.batch && d) sHooks.batch(d); };
  window.__onSearchSource = function(d){ if (sHooks.source && d) sHooks.source(d); };
  window.__onSearchStart = function(d){ if (sHooks.start && d) sHooks.start(d); };
  window.__onSearchDone = function(d){ if (sHooks.done && d) sHooks.done(d); };
  window.__onSearchSettled = function(d){ if (sHooks.settled && d) sHooks.settled(d); };

  var api = {
    mode: function(){ return live() ? "live" : "mock"; },
    isLive: live,
    onLive: onLive,

    onProbeDone: function(fn){
      probeDoneSubs = fn ? [fn] : [];
    },

    listSources: function(){
      return invoke("list_sources").then(function(res){
        return coerce(res || []);
      });
    },

    javdbLogin: function(){
      return invoke("javdb_login");
    },

    toggleSource: function(key, on){
      return invoke("toggle_source", {key: key, on: !!on});
    },

    reorderSources: function(keys){
      return invoke("reorder_sources", {keys: keys || []});
    },

    probeSources: function(keys, onOne){
      probeOne = onOne || null;
      return invoke("probe_sources", {keys: keys || null}).then(function(token){
        probeToken = token;
        return token;
      });
    },

    probeCancel: function(){
      probeToken = -1;
      return invoke("probe_cancel");
    },

    setAutoOrder: function(on){
      return invoke("set_auto_order", {on: !!on});
    },

    sourceIssues: function(){
      return invoke("source_issues").then(function(res){
        return res || [];
      });
    },

    selftest: function(){
      return invoke("selftest");
    },

    proxyStatus: function(force){
      return invoke("proxy_status", {force: !!force});
    },

    netThroughput: function(){
      return invoke("net_throughput", {});
    },

    defaultSettings: function(){
      return invoke("default_settings");
    },

    appInfo: function(){
      return invoke("app_info");
    },

    onSearch: function(hooks){
      sHooks = hooks || {};
    },

    torrentFiles: function(payload){
      return invoke("torrent_files", {payload: payload || {}});
    },

    startSearch: function(query, page){
      return invoke("start_search", {query: query || "", page: page || 1});
    },

    cancelSearch: function(token){
      return invoke("cancel_search", {token: token || 0});
    },

    deliver: function(magnets, key){
      return invoke("deliver", {magnets: magnets || [], key: key || ""});
    },

    downloaders: function(){
      return invoke("downloaders").then(function(res){
        return res || [];
      });
    },

    getSettings: function(){
      return invoke("get_settings");
    },

    saveSettings: function(fields){
      return invoke("save_settings", {fields: fields || {}});
    },

    openLogs: function(){
      return invoke("open_logs");
    },

    openDataDir: function(){
      return invoke("open_data_dir");
    },

    openRepo: function(){
      return invoke("open_repo");
    },

    reloadQueryRoles: function(){
      return invoke("reload_query_roles");
    },

    setWindowTone: function(color){
      return invoke("set_window_tone", {color: color});
    }
  };

  function esc(v){
    return String(v === undefined || v === null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  HC.api = api;
  HC.esc = esc;
  HC.MAGNET_CAP = MAGNET_CAP;
})();
