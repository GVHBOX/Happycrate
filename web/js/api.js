(function(){
  var HC = window.HC || (window.HC = {});

  var MOCK = [
    {key:"nyaa", label:"Nyaa", type:"builtin", enabled:true, timeout:15,
     addr:"https://nyaa.si", health:{state:"ok", ms:148, err:"", times:["ok","ok","ok","ok","ok"]}},
    {key:"apibay", label:"海盗湾", type:"builtin", enabled:true, timeout:15,
     addr:"https://apibay.org", health:{state:"ok", ms:62, err:"", times:["ok","ok","ok","ok","ok"]}},
    {key:"mikan", label:"蜜柑计划", type:"builtin", enabled:true, timeout:15,
     addr:"https://mikanani.me", health:{state:"warn", ms:5230, err:"", times:["ok","ok","slow","slow","slow"]}},
    {key:"dmhy", label:"动漫花园", type:"builtin", enabled:true, timeout:15,
     addr:"https://share.dmhy.org", health:{state:"err", ms:0, err:"超时", times:["ok","ok","err","err","err"]}},
    {key:"sukebei", label:"Sukebei", type:"builtin", enabled:true, timeout:15,
     addr:"https://sukebei.nyaa.si", health:{state:"ok", ms:183, err:"", times:["ok","ok","ok","ok","ok"]}},
    {key:"eztv", label:"EZTV", type:"builtin", enabled:true, timeout:15,
     addr:"https://eztvx.to", health:{state:"err", ms:94, err:"返回 0 条", times:["ok","empty","empty","empty","empty"]}},
    {key:"bitsearch", label:"BitSearch", type:"builtin", enabled:true, timeout:15,
     addr:"https://bitsearch.to", health:{state:"ok", ms:41, err:"", times:["ok","ok","ok","ok","ok"]}},
    {key:"tpb", label:"TPB镜像", type:"builtin", enabled:true, timeout:15,
     addr:"https://thepiratebay10.org", health:{state:"ok", ms:112, err:"", times:["ok","ok","ok","ok","ok"]}},
    {key:"custom1", label:"我的私藏源", type:"json", enabled:true, timeout:15,
     addr:"https://e.com/api/search?q={query}&p={page}",
     listPath:"data.list",
     map:{title:"title", hash:"info_hash", size:"size", seeders:"seeders", added:"added"},
     health:{state:"na", ms:0, err:"", times:[]}},
    {key:"custom2", label:"备用索引", type:"rss", enabled:true, timeout:20,
     addr:"https://index.example.org/search?q={query}",
     listPath:"", map:{title:"title"},
     health:{state:"ok", ms:87, err:"", times:["ok","ok","ok","ok","ok"]}},
    {key:"custom3", label:"旧镜像站", type:"html", enabled:false, timeout:15,
     addr:"https://old.example.net/s?k={query}&p={page}",
     listPath:"", map:{title:"title", hash:"hash"},
     health:{state:"na", ms:0, err:"", times:[]}}
  ];

  var db = null;
  var customSeq = 1;

  function clone(list){
    return list.map(function(s){
      var o = {};
      for (var k in s) o[k] = (s[k] && typeof s[k] === "object") ? JSON.parse(JSON.stringify(s[k])) : s[k];
      return o;
    });
  }

  function seed(){
    if (!db){
      db = clone(MOCK);
      customSeq = 1;
    }
    return db;
  }

  function live(){
    return !!(window.pywebview && window.pywebview.api &&
              typeof window.pywebview.api.start_search === "function");
  }

  function coerce(list){
    return (list || []).map(function(s){
      return {
        key: s.key || "",
        label: s.label || s.key || "",
        type: s.type || "builtin",
        enabled: s.enabled !== false,
        timeout: Number(s.timeout) || 15,
        addr: s.addr || "",
        listPath: s.listPath || "",
        map: s.map || null,
        health: {
          state: (s.health && s.health.state) || "na",
          ms: (s.health && s.health.ms) || 0,
          err: (s.health && s.health.err) || "",
          times: (s.health && s.health.times) || []
        }
      };
    });
  }

  var probeOne = null;
  var probeDone = null;
  var sHooks = {};
  var mockToken = 0;
  var mockSettings = {
    min_query_len: 2, max_workers: 8, timeout: 15, retries: 1,
    default_downloader: "", proxy: "", user_agent: "",
    ui_font_size: 18, selbar: false, theme: "light"
  };

  window.__onProbeDone = function(){
    if (probeDone) probeDone();
  };

  window.__onSearchBatch = function(d){ if (sHooks.batch && d) sHooks.batch(d); };
  window.__onSearchSource = function(d){ if (sHooks.source && d) sHooks.source(d); };
  window.__onSearchDone = function(d){ if (sHooks.done && d) sHooks.done(d); };

  var api = {
    mode: function(){ return live() ? "live" : "mock"; },

    onProbeDone: function(fn){ probeDone = fn; },

    listSources: function(){
      if (live()) return window.pywebview.api.list_sources().then(coerce);
      return Promise.resolve(coerce(seed()));
    },

    toggleSource: function(key, on){
      if (live()) return window.pywebview.api.toggle_source(key, on);
      var hit = seed().filter(function(s){ return s.key === key; })[0];
      if (hit) hit.enabled = !!on;
      return Promise.resolve(!!hit);
    },

    reorderSources: function(keys){
      if (live()) return window.pywebview.api.reorder_sources(keys);
      var list = seed(), next = [];
      keys.forEach(function(k){
        var hit = list.filter(function(s){ return s.key === k; })[0];
        if (hit) next.push(hit);
      });
      list.forEach(function(s){ if (next.indexOf(s) < 0) next.push(s); });
      db = next;
      return Promise.resolve(true);
    },

    saveSource: function(entry){
      if (live()) return window.pywebview.api.save_source(entry);
      var list = seed();
      var errors = validate(entry, list);
      if (errors.length) return Promise.resolve({ok:false, errors:errors});
      var hit = list.filter(function(s){ return s.key === entry.key; })[0];
      if (hit){
        for (var k in entry) if (k !== "key") hit[k] = entry[k];
      } else {
        var item = {};
        for (var j in entry) item[j] = entry[j];
        item.health = {state:"na", ms:0, err:"", times:[]};
        list.push(item);
      }
      return Promise.resolve({ok:true, errors:[]});
    },

    removeSource: function(key){
      if (live()) return window.pywebview.api.remove_source(key);
      var list = seed();
      var hit = list.filter(function(s){ return s.key === key; })[0];
      if (!hit) return Promise.resolve(false);
      db = list.filter(function(s){ return s.key !== key; });
      return Promise.resolve(true);
    },

    probeSources: function(keys, onOne){
      probeOne = onOne || null;
      if (live()){
        window.__onProbe = function(p){
          if (probeOne && p) probeOne(p.key, p);
        };
        return window.pywebview.api.probe_sources(keys || null);
      }
      var targets = seed().filter(function(s){
        return s.enabled && (!keys || !keys.length || keys.indexOf(s.key) >= 0);
      });
      var left = targets.length;
      if (!left){
        if (probeDone) probeDone();
        return Promise.resolve(0);
      }
      targets.forEach(function(s, i){
        setTimeout(function(){
          var roll = s.health.state;
          var res = roll === "err"
            ? {state:"err", ms:0, err:s.health.err || "超时"}
            : {state: roll === "warn" ? "warn" : "ok",
               ms: roll === "warn" ? 4800 + Math.round(Math.random()*900)
                                   : 30 + Math.round(Math.random()*260),
               err:""};
          s.health = {state:res.state, ms:res.ms, err:res.err, times:s.health.times};
          if (probeOne) probeOne(s.key, res);
          left--;
          if (!left && probeDone) probeDone();
        }, 380 + i * 260 + Math.random() * 220);
      });
      return Promise.resolve(targets.length);
    },

    testSource: function(entry){
      if (live()) return window.pywebview.api.test_source(entry);
      var errors = validate(entry, []);
      if (errors.length) return Promise.resolve({ok:false, count:0, errors:errors});
      return new Promise(function(res){
        setTimeout(function(){
          var bad = /example\.com|e\.com/.test(entry.addr || "");
          res(bad ? {ok:true, count:0, warn:"返回 0 条"}
                  : {ok:true, count: 3 + Math.floor(Math.random()*20), warn:""});
        }, 700);
      });
    },

    resetSources: function(){
      if (live()) return window.pywebview.api.reset_sources();
      db = clone(MOCK);
      customSeq = 1;
      return Promise.resolve(true);
    },

    exportSources: function(){
      if (live()) return window.pywebview.api.export_sources();
      return Promise.resolve({ok:true, path:"happycrate-sources.json"});
    },

    importSources: function(){
      if (live()) return window.pywebview.api.import_sources();
      return Promise.resolve({ok:true, added:1, updated:8, message:"新增 1 个，更新 8 个"});
    },

    nextCustomKey: function(){
      var list = seed(), n = 1;
      while (list.filter(function(s){ return s.key === "custom" + n; })[0]) n++;
      return "custom" + n;
    },

    diagnostics: function(keys){
      if (live()) return window.pywebview.api.diagnostics(keys);
      var list = seed().filter(function(s){
        return s.health.state === "err" && (!keys || !keys.length || keys.indexOf(s.key) >= 0);
      });
      if (!list.length) return Promise.resolve("");
      var out = ["[happycrate 诊断] " + stamp(), ""];
      list.forEach(function(s){
        var empty = s.health.err && s.health.err.indexOf("0 条") >= 0;
        out.push("> " + s.label + " (" + s.key + ")");
        out.push("  地址  " + s.addr);
        out.push("  现象  " + (empty
          ? "返回 200，但解析出 0 条结果"
          : (s.health.err || "请求失败")));
        out.push("  最近  " + (s.health.times.join(" ") || "无记录"));
        out.push("  建议  " + (empty ? "疑似站点改版，需要改解析代码" : "换镜像地址"));
        out.push("  位置  " + (s.type === "builtin"
          ? "app/sources.py :: _search_" + s.key
          : "app/templates.py :: _make_" + s.type));
        out.push("");
      });
      return Promise.resolve(out.join("\n"));
    },

    selftest: function(){
      if (live()) return window.pywebview.api.selftest();
      return Promise.resolve({ok:true, missing:[]});
    },

    appInfo: function(){
      if (live()) return window.pywebview.api.app_info();
      return Promise.resolve({version:"1.0.11", dataDir:"(mock 模式)", mode:"mock"});
    },

    onSearch: function(hooks){ sHooks = hooks || {}; },

    startSearch: function(query){
      if (live()) return window.pywebview.api.start_search(query);
      var list = mockItems(query);
      var errs = mockErrors(query);
      var keys = seed().filter(function(s){ return s.enabled; }).map(function(s){ return s.key; });
      var token = Date.now();
      mockToken = token;
      keys.forEach(function(key, i){
        var part = list.filter(function(it){ return it.sources.indexOf(key) >= 0; });
        setTimeout(function(){
          if (token !== mockToken) return;
          var err = errs[key] || "";
          if (sHooks.source){
            sHooks.source({token:token, key:key, count: err ? 0 : part.length, err:err});
          }
          if (!err && part.length && sHooks.batch){
            sHooks.batch({token:token, key:key, items:part});
          }
          if (i === keys.length - 1 && sHooks.done){
            sHooks.done({token:token, total:list.length, errors:errs});
          }
        }, 420 + i * 380);
      });
      return Promise.resolve({ok:true, token:token, total:keys.length, error:""});
    },

    cancelSearch: function(token){
      if (live()) return window.pywebview.api.cancel_search(token || 0);
      mockToken = 0;
      return Promise.resolve(true);
    },

    deliver: function(magnets, key){
      if (live()) return window.pywebview.api.deliver(magnets || [], key || "");
      return Promise.resolve({
        ok: true, message: "已提交 " + (magnets || []).length + " 个任务（mock）", method: "mock"
      });
    },

    downloaders: function(){
      if (live()) return window.pywebview.api.downloaders();
      return Promise.resolve([{key:"thunder", label:"迅雷", available:true}]);
    },

    getSettings: function(){
      if (live()) return window.pywebview.api.get_settings();
      return Promise.resolve(Object.assign({}, mockSettings));
    },

    saveSettings: function(fields){
      if (live()) return window.pywebview.api.save_settings(fields || {});
      var f = fields || {};
      var proxy = String(f.proxy || "").trim();
      if (proxy && !/^https?:\/\//i.test(proxy)){
        return Promise.resolve({ok: false, errors: ["代理仅支持 http:// 或 https:// 开头"]});
      }
      mockSettings = Object.assign(mockSettings, f);
      return Promise.resolve({ok: true, errors: []});
    },

    openLogs: function(){
      if (live()) return window.pywebview.api.open_logs();
      return Promise.resolve(true);
    }
  };

  function mockItems(query){
    var q = query || "关键词";
    if (q.indexOf("空") >= 0) return [];
    var tags = ["1080p", "720p", "2160p", "WEB-DL", "BluRay", "BDRip"];
    var out = [];
    for (var i = 0; i < 24; i++){
      var gb = (0.4 + i * 0.37).toFixed(1);
      var hash = ("hc" + i + "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").slice(0, 40);
      out.push({
        hash: hash,
        title: "[" + tags[i % tags.length] + "] " + q + " 第 " + (i + 1) + " 话 [简繁字幕]",
        size: Math.round(parseFloat(gb) * 1073741824),
        sizeText: gb + " GB",
        seeders: 240 - i * 7,
        leechers: 8 + (i % 20),
        added: Math.round(Date.now() / 1000) - i * 90000,
        addedText: i === 0 ? "今天" : (i < 6 ? i + " 天前" : "2026-08-" + (10 + (i % 18))),
        magnet: "magnet:?xt=urn:btih:" + hash,
        sources: [["nyaa", "apibay", "dmhy"][i % 3]]
      });
    }
    return out;
  }

  function mockErrors(query){
    if ((query || "").indexOf("坏") >= 0) return {"dmhy": "超时", "mikan": "返回 0 条"};
    return {};
  }

  function validate(e, list){
    var errs = [];
    if (!e.label) errs.push("名称不能为空");
    var url = String(e.addr || "");
    if (e.type !== "builtin"){
      if (!url) errs.push("地址不能为空");
      else if (!/^https?:\/\//i.test(url)) errs.push("地址必须以 http:// 或 https:// 开头");
      if (url && url.indexOf("{query}") < 0) errs.push("URL 模板必须包含 {query}");
    }
    if (e.type === "json" && !String(e.listPath || "").trim()) errs.push("json 类型必须填列表路径");
    var t = Number(e.timeout);
    if (!t || t < 1 || t > 120) errs.push("超时需在 1-120 秒之间");
    return errs;
  }

  function stamp(){
    var d = new Date(), p = function(n){ return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + p(d.getMonth()+1) + "-" + p(d.getDate()) +
           " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  HC.api = api;
  HC.validateSource = validate;
})();
