(function(){
  var HC = window.HC || (window.HC = {});

  var MOCK = [
    {key:"nyaa", label:"Nyaa", enabled:true,
     addr:"https://nyaa.si", health:{ms:148, err:"", outcomes:["ok","ok","ok","ok","ok"]}},
    {key:"apibay", label:"海盗湾", enabled:true,
     addr:"https://apibay.org", health:{ms:62, err:"", outcomes:["ok","ok","ok","ok","ok"]}},
    {key:"mikan", label:"蜜柑计划", enabled:true,
     addr:"https://mikanani.me", health:{ms:5230, err:"", outcomes:["ok","ok","slow","slow","slow"]}},
    {key:"dmhy", label:"动漫花园", enabled:true,
     addr:"https://share.dmhy.org", health:{ms:0, err:"超时", outcomes:["ok","ok","timeout","timeout","timeout"]}},
    {key:"sukebei", label:"Sukebei", enabled:true,
     addr:"https://sukebei.nyaa.si", health:{ms:183, err:"", outcomes:["ok","ok","ok","ok","ok"]}},
    {key:"eztv", label:"EZTV", enabled:true,
     addr:"https://eztvx.to", health:{ms:94, err:"无结果", outcomes:["ok","empty","empty","empty","empty"]}},
    {key:"bitsearch", label:"BitSearch", enabled:true,
     addr:"https://bitsearch.to", health:{ms:41, err:"", outcomes:["ok","ok","ok","ok","ok"]}},
    {key:"tpb", label:"TPB镜像", enabled:true,
     addr:"https://thepiratebay10.org", health:{ms:112, err:"", outcomes:["ok","ok","ok","ok","ok"]}},
    {key:"xccl263", label:"小草磁力", enabled:false,
     addr:"https://www.xccl263.xyz", health:{ms:240, err:"", outcomes:["ok","ok","ok","ok","ok"]}},
    {key:"knaben", label:"Knaben", enabled:true,
     addr:"https://api.knaben.org/v1", health:{ms:356, err:"", outcomes:["ok","ok","http429","ok","http429"]}}
  ];

  var db = null;

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
        enabled: s.enabled !== false,
        addr: s.addr || "",
        health: {
          ms: (s.health && s.health.ms) || 0,
          err: (s.health && s.health.err) || "",
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
  var sHooks = {};
  var mockToken = 0;
  var MAX_QUERY_LEN = 100;
  var MAGNET_CAP = 200;
  var mockSettings = {
    min_query_len: 2, max_workers: 8, timeout: 15, retries: 1,
    default_downloader: "", proxy: "", user_agent: "",
    ui_font_size: 18, selbar: false, theme: "light", brand: "", auto_files: true,
    soft_deadline_ms: 3000, keep_duplicates: false, progress_style: "segment",
    progress_line: true, progress_look: ""
  };
  var mockDefaults = Object.assign({}, mockSettings);

  var probeDoneSubs = [];

  window.__onProbeDone = function(){
    probeDoneSubs.slice().forEach(function(fn){
      try{ fn(); }catch(e){ console.error(e); }
    });
  };

  window.__onSearchBatch = function(d){ if (sHooks.batch && d) sHooks.batch(d); };
  window.__onSearchSource = function(d){ if (sHooks.source && d) sHooks.source(d); };
  window.__onSearchStart = function(d){ if (sHooks.start && d) sHooks.start(d); };
  window.__onSearchDone = function(d){ if (sHooks.done && d) sHooks.done(d); };
  window.__onSearchSettled = function(d){ if (sHooks.settled && d) sHooks.settled(d); };

  var api = {
    mode: function(){ return live() ? "live" : "mock"; },

    onProbeDone: function(fn){
      probeDoneSubs = fn ? [fn] : [];
    },

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
        window.__onProbeDone();
        return Promise.resolve(0);
      }
      targets.forEach(function(s, i){
        setTimeout(function(){
          var st = HC.mergeState((s.health.outcomes || []).slice(-5));
          var outcome = st === "err"
            ? "timeout"
            : st === "empty"
            ? "empty"
            : st === "warn" ? "slow" : "ok";
          var res = st === "err"
            ? {state:"err", ms:0, err:s.health.err || "超时", outcome:outcome}
            : st === "empty"
            ? {state:"empty", ms:s.health.ms || 90, err:"无结果", outcome:outcome}
            : {state: st === "warn" ? "warn" : "ok",
               ms: st === "warn" ? 4800 + Math.round(Math.random()*900)
                                  : 30 + Math.round(Math.random()*260),
               err:"", outcome:outcome};
          var outcomes = (s.health.outcomes || []).slice();
          outcomes.push(outcome);
          s.health = {ms:res.ms, err:res.err, outcomes: outcomes.slice(-5)};
          if (probeOne) probeOne(s.key, res);
          left--;
          if (!left) window.__onProbeDone();
        }, 380 + i * 260 + Math.random() * 220);
      });
      return Promise.resolve(targets.length);
    },

    setAutoOrder: function(on){
      if (live()) return window.pywebview.api.set_auto_order(on);
      return Promise.resolve(true);
    },

    diagnostics: function(keys){
      if (live()) return window.pywebview.api.diagnostics(keys);
      var list = seed().filter(function(s){
        var st = HC.mergeState((s.health.outcomes || []).slice(-5));
        return (st === "err" || st === "empty") &&
               (!keys || !keys.length || keys.indexOf(s.key) >= 0);
      });
      if (!list.length) return Promise.resolve("");
      var report = {
        at: stamp(),
        version: "1.2.3",
        lax: [],
        sources: list.map(function(s){
          var outs = (s.health.outcomes || []).slice(-5);
          var st = HC.mergeState(outs);
          return {
            key: s.key,
            label: s.label,
            addr: s.addr,
            kind: st === "empty" ? "empty" : "fail",
            state: st,
            err: s.health.err || "",
            lastOk: 0,
            outcomes: outs,
            peers: 0,
            peerHits: 0,
            events: outs.map(function(t){
              return {at: 0, outcome: t, code: 0, count: 0, ms: s.health.ms || 0, round: "", err: ""};
            }),
            adapter: adapterLocation(s)
          };
        })
      };
      return Promise.resolve(JSON.stringify(report, null, 2));
    },

    sourceIssues: function(){
      if (live()) return window.pywebview.api.source_issues();
      var list = seed().filter(function(s){
        var st = HC.mergeState((s.health.outcomes || []).slice(-5));
        return st === "err" || st === "empty";
      });
      return Promise.resolve(list.map(function(s){
        var outs = (s.health.outcomes || []).slice(-5);
        var st = HC.mergeState(outs);
        return {
          key: s.key, label: s.label, addr: s.addr,
          kind: st === "err" ? "fail" : "empty",
          detail: st === "err" ? (s.health.err || "请求失败") : "最近 5 次请求均为 0 条"
        };
      }));
    },

    selftest: function(){
      if (live()) return window.pywebview.api.selftest();
      return Promise.resolve({ok:true, missing:[]});
    },

    proxyStatus: function(force){
      if (live()) return window.pywebview.api.proxy_status(!!force);
      return Promise.resolve({mode:"system", addr:"http://127.0.0.1:7890",
                              portOk:true, works:true, systemOn:true,
                              checkedAt:Date.now()/1000});
    },

    defaultSettings: function(){
      if (live()) return window.pywebview.api.default_settings();
      return Promise.resolve(mockDefaults);
    },

    appInfo: function(){
      if (live()) return window.pywebview.api.app_info();
      return Promise.resolve({version:"1.2.3", dataDir:"(mock 模式)", mode:"mock",
                              logFile:"(mock 模式)",
                              proxy:"跟随系统 127.0.0.1:7890"});
    },

    onSearch: function(hooks){ sHooks = hooks || {}; },

    torrentFiles: function(p){
      if (live()) return window.pywebview.api.torrent_files(p);
      return new Promise(function(res){
        setTimeout(function(){
          var u = String((p || {}).url || "");
          if (u.indexOf("mock.local") >= 0){
            res({ok: true, files: [
              {n: "ubuntu 第 6 话 [简繁字幕].mp4", s: "1.1 GB"},
              {n: "ubuntu 花絮.mp4", s: "88.2 MB"},
              {n: "credits.nfo", s: "4.1 KB"}
            ], error: ""});
          } else {
            res({ok: false, files: [], error: "mock 没有懒加载文件清单"});
          }
        }, 500);
      });
    },

    startSearch: function(query){
      if (live()) return window.pywebview.api.start_search(query);
      var text = (query || "").replace(/^\s+|\s+$/g, "");
      var minLen = Number(mockSettings.min_query_len) || 2;
      if (text.length < minLen){
        return Promise.resolve({ok:false, token:0, total:0,
                                error:"关键字至少 " + minLen + " 个字符"});
      }
      if (text.length > MAX_QUERY_LEN){
        return Promise.resolve({ok:false, token:0, total:0,
                                error:"关键字最长 " + MAX_QUERY_LEN + " 个字符"});
      }
      var list = mockItems(query);
      var errs = mockErrors(query);
      var keys = seed().filter(function(s){ return s.enabled; }).map(function(s){ return s.key; });
      if (!keys.length){
        return Promise.resolve({ok:false, token:0, total:0, error:"没有启用的数据源"});
      }
      var token = Date.now();
      mockToken = token;
      var fatal = mockFatal(query);
      keys.forEach(function(key, i){
        var part = list.filter(function(it){ return it.sources.indexOf(key) >= 0; });
        var typical = mockTypical(key);
        setTimeout(function(){
          if (token !== mockToken) return;
          if (sHooks.start){
            sHooks.start({token:token, key:key, typical_ms:typical});
          }
        }, 60 + i * 30);
        setTimeout(function(){
          if (token !== mockToken) return;
          var err = errs[key] || "";
          var outcome = err ? "err" : (part.length ? "ok" : "empty");
          if (sHooks.source){
            sHooks.source({token:token, key:key, count: err ? 0 : part.length,
                           err: err || (outcome === "empty" ? "无结果" : ""),
                           outcome: outcome,
                           state: err ? "err" : (part.length ? "ok" : "empty")});
          }
          if (!err && part.length && sHooks.batch){
            sHooks.batch({token:token, key:key, items:part});
          }
          if (i === keys.length - 1 && sHooks.done){
            var done = Object.assign({}, errs);
            if (fatal) done[""] = fatal;
            sHooks.done({token:token, total:list.length, errors:done});
          }
        }, 420 + i * 380);
      });
      var toks = text.toLowerCase().split(/\s+/).filter(Boolean);
      var parsed = {
        raw: text, text: text.toLowerCase(), tokens: toks,
        subject: toks.slice(), bigrams: [],
        mods: [], soft: [], season: null, year: null,
        browse: toks.length === 0
      };
      return Promise.resolve({ok:true, token:token, total:keys.length,
                              error:"", query:parsed});
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

    onLive: onLive,
    isLive: live,

    saveSettings: function(fields){
      if (live()) return window.pywebview.api.save_settings(fields || {});
      var f = fields || {};
      var proxy = String(f.proxy || "").trim();
      var err = mockProxyError(proxy);
      if (err) return Promise.resolve({ok: false, errors: [err]});
      mockSettings = Object.assign(mockSettings, f);
      return Promise.resolve({ok: true, errors: []});
    },

    openLogs: function(){
      if (live()) return window.pywebview.api.open_logs();
      return Promise.resolve(true);
    },

    reloadQueryRoles: function(){
      if (live()) return window.pywebview.api.reload_query_roles();
      return Promise.resolve(true);
    },

    setWindowTone: function(color){
      if (live()) return window.pywebview.api.set_window_tone(color);
      return Promise.resolve(true);
    }
  };

  function mockItems(query){
    var q = query || "关键词";
    if (q.indexOf("空") >= 0) return [];
    if (q.indexOf("断网") >= 0) return [];
    var tags = ["1080p", "720p", "2160p", "WEB-DL", "BluRay", "BDRip"];
    var qFirst = q.split(/\s+/)[0] || q;
    var out = [];
    for (var i = 0; i < 24; i++){
      var gb = (0.4 + i * 0.37).toFixed(1);
      var hash = mockHash(i);
      var it = {
        hash: hash,
        title: "[" + tags[i % tags.length] + "] " + qFirst + " 第 " + (i + 1) + " 话 [简繁字幕]",
        size: Math.round(parseFloat(gb) * 1073741824),
        sizeText: gb + " GB",
        seeders: 240 - i * 7,
        leechers: 8 + (i % 20),
        added: Math.round(Date.now() / 1000) - i * 90000,
        addedText: i === 0 ? "今天" : (i < 6 ? i + " 天前" : "2026-08-" + (10 + (i % 18))),
        magnet: "magnet:?xt=urn:btih:" + hash,
        sources: [["nyaa", "apibay", "dmhy"][i % 3]]
      };
      if (i === 5){
        it.fetch = {url: "https://mock.local/demo-5.torrent"};
      } else if (i % 3 === 0){
        it.files = [
          {n: q + " 第 " + (i + 1) + " 话 [简繁字幕].mp4", s: (890 - i % 90) + "." + (i % 10) + " MB"},
          {n: q + " 第 " + (i + 1) + " 话 花絮.mp4", s: "88.2 MB"},
          {n: "credits.nfo", s: "4.1 KB"}
        ];
      } else {
        it.files = [
          {n: "vol_" + (i + 1) + "_main.mkv", s: (890 - i % 90) + "." + (i % 10) + " MB"},
          {n: "credits.nfo", s: "4.1 KB"}
        ];
      }
      out.push(it);
    }
    return out;
  }

  function mockErrors(query){
    if ((query || "").indexOf("坏") >= 0) return {"dmhy": "超时", "mikan": "返回 0 条"};
    return {};
  }

  var MOCK_TYPICAL = {nyaa:1500, apibay:112, mikan:5230, dmhy:1180,
                      sukebei:2600, eztv:940, bitsearch:410, tpb:2900,
                      xccl263:2400, knaben:356};

  function mockTypical(key){
    return MOCK_TYPICAL[key] || 0;
  }

  function mockFatal(query){
    if ((query || "").indexOf("断网") >= 0){
      return "未检测到代理，这些源需要代理才能访问。";
    }
    return "";
  }

  function mockProxyError(raw){
    var text = String(raw || "").replace(/^\s+|\s+$/g, "");
    if (!text) return "";
    var parts = text.split(";").map(function(s){ return s.replace(/^\s+|\s+$/g, ""); })
      .filter(function(s){ return s; });
    if (!parts.length) return "代理地址为空";
    var seen = {};
    var bad = "";
    parts.forEach(function(p){
      var full = p.indexOf("://") >= 0 ? p : "http://" + p;
      var scheme = (full.split("://")[0] || "").toLowerCase();
      if (scheme.indexOf("socks") === 0 && !bad){
        bad = "不支持 " + scheme + " 代理，只支持 HTTP 代理端口";
        return;
      }
      if (scheme !== "http" && scheme !== "https" && !bad){
        bad = "代理地址格式无法识别：" + p;
        return;
      }
      var key = scheme === "https" ? "https" : "http";
      if (seen[key] && !bad){
        bad = "代理重复指定同一类型：" + p;
        return;
      }
      seen[key] = 1;
    });
    return bad;
  }

  function adapterName(key){
    var MAP = {
      apibay:"_search_apibay", nyaa:"_search_nyaa", mikan:"_search_mikan",
      dmhy:"_search_dmhy", sukebei:"_search_sukebei", eztv:"_search_eztv",
      bitsearch:"_search_bitsearch", tpb:"_search_tpb_mirror",
      xccl263:"_search_xccl263", knaben:"_search_knaben"
    };
    return MAP[key] || null;
  }

  function adapterLocation(s){
    var n = adapterName(s.key);
    return n ? "app/sources.py :: " + n
             : "app/sources.py :: (未知内置源 " + s.key + ")";
  }

  function stamp(){
    var d = new Date(), p = function(n){ return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + p(d.getMonth()+1) + "-" + p(d.getDate()) +
           " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  function esc(v){
    return String(v === undefined || v === null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function mockHash(i){
    var head = (0x100000 + i * 0x9e3779).toString(16).slice(-6);
    var body = "";
    var seed = i * 2654435761 % 4294967296;
    while (body.length < 34){
      seed = (seed * 1103515245 + 12345) % 2147483648;
      body += ("0000000" + seed.toString(16)).slice(-7);
    }
    return (head + body).slice(0, 40);
  }

  HC.api = api;
  HC.esc = esc;
  HC.MAGNET_CAP = MAGNET_CAP;
})();
