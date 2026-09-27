(function(){
  var HC = window.HC || (window.HC = {});

  var ctx = null;
  var master = null;

  var VOLUME_DEFAULT = 80;
  HC.SOUND_VOLUME_DEFAULT = VOLUME_DEFAULT;

  function volumeGain(){
    var v = parseInt((HC.settings || {}).sound_volume, 10);
    if (isNaN(v)) v = VOLUME_DEFAULT;
    v = Math.max(0, Math.min(100, v));
    return 0.25 * v / 100;
  }

  function ensure(){
    if (!ctx){
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      try { ctx = new AC(); } catch (e){ return false; }
      master = ctx.createGain();
      master.gain.value = volumeGain();
      master.connect(ctx.destination);
    }
    if (ctx.state === "suspended") ctx.resume();
    return true;
  }

  function tone(o){
    var t = (o.t0 != null ? o.t0 : ctx.currentTime);
    var osc = ctx.createOscillator();
    osc.type = o.type || "triangle";
    osc.frequency.setValueAtTime(o.freq, t);
    if (o.to) osc.frequency.exponentialRampToValueAtTime(o.to, t + o.dur);
    var g = ctx.createGain();
    var peak = o.gain != null ? o.gain : 0.7;
    var atk = o.attack != null ? o.attack : 0.004;
    var rel = o.rel != null ? o.rel : 0.09;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + atk);
    g.gain.exponentialRampToValueAtTime(0.0001, t + o.dur + rel);
    var node = osc;
    if (o.filter){
      var f = ctx.createBiquadFilter();
      f.type = "lowpass";
      f.frequency.value = o.filter;
      f.Q.value = 0.7;
      node.connect(f);
      node = f;
    }
    node.connect(g);
    g.connect(master);
    osc.start(t);
    osc.stop(t + o.dur + rel + 0.03);
  }

  function seq(notes, o){
    var base = o.t0 != null ? o.t0 : ctx.currentTime;
    notes.forEach(function(pair){
      tone({freq: pair[0], t0: base + pair[1], type: o.type, dur: o.dur,
            gain: o.gain, rel: o.rel, filter: o.filter});
    });
  }

  var BANK = {
    start: function(){
      tone({freq: 880, type: "triangle", dur: 0.03, gain: 0.28, rel: 0.04});
      tone({freq: 880, type: "triangle", dur: 0.03, gain: 0.28, rel: 0.04, t0: ctx.currentTime + 0.09});
    },
    done: function(){
      seq([[523.25, 0], [659.25, 0.08], [783.99, 0.16]],
          {type: "triangle", dur: 0.09, gain: 0.55, rel: 0.14});
    },
    select: function(){
      tone({freq: 800, to: 480, type: "sine", dur: 0.02, gain: 0.25, rel: 0.04});
    },
    copy: function(){
      seq([[659.25, 0], [880, 0.07]],
          {type: "sine", dur: 0.06, gain: 0.42, rel: 0.08});
    },
    deliver: function(){
      seq([[392, 0], [523.25, 0.09]],
          {type: "triangle", dur: 0.1, gain: 0.5, rel: 0.1, filter: 2400});
    },
    fail: function(){
      tone({freq: 300, to: 247, type: "square", dur: 0.1, gain: 0.2, rel: 0.12, filter: 1100});
      tone({freq: 300, to: 247, type: "triangle", dur: 0.1, gain: 0.17, rel: 0.12, t0: ctx.currentTime + 0.13});
    }
  };

  function allowed(name){
    var s = HC.settings || {};
    if (s.sound === false) return false;
    return s["sound_" + name] !== false;
  }

  function run(name){
    if (!ensure()) return;
    master.gain.value = volumeGain();
    try { BANK[name](); } catch (e){}
  }

  function play(name){
    if (!BANK[name] || !allowed(name)) return;
    run(name);
  }

  function preview(name){
    if (!BANK[name]) return;
    run(name);
  }

  HC.sfx = { play: play, preview: preview };
})();
