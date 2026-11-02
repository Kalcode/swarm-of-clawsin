/* Swarm World audio: Web Audio playback for sound events near the camera, plus quiet ambient music.
 * Everything is synthesized (no files), so it is CC0 by construction. Muted until the person clicks the speaker
 * button (browser autoplay rules); on/off and volume are remembered in localStorage.
 * viewer.js calls SwarmSound.tick(events, cam, clock) once per world message. */
(function () {
  'use strict';
  const KEY = 'swarmworld.sound';
  const HEARD_TILES = 26;      // beyond this distance from the view center a sound is silent
  const MAX_VOICES = 8;
  const MIN_GAP_MS = 140;      // per sound kind

  let ctx = null, master = null, sfx = null, musicBus = null, noiseBuf = null;
  let state = { on: false, vol: 0.6 };
  try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* private mode */ }
  state.on = !!state.on;
  state.vol = Math.min(1, Math.max(0, +state.vol || 0));
  let voices = 0;
  const lastAt = {};
  let phase = 'day';
  let pendingStart = state.on;  // remembered "on" still needs one gesture before audio may start

  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* ignore */ } }

  function ensure() {
    if (ctx) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain();
    master.connect(ctx.destination);
    sfx = ctx.createGain(); sfx.gain.value = 0.9; sfx.connect(master);
    musicBus = ctx.createGain(); musicBus.gain.value = 0.16; musicBus.connect(master);
    const n = ctx.sampleRate * 2;
    noiseBuf = ctx.createBuffer(1, n, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    applyVolume();
    return true;
  }

  function applyVolume() {
    if (master) master.gain.value = state.on ? state.vol * state.vol : 0;
  }

  // ---------------------------------------------------------------- voice helpers
  function env(g, t, a, peak, d) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(Math.max(peak, 0.0002), t + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t + a + d);
  }
  function osc(type, f0, f1, t, dur, peak, a, dest) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + dur);
    env(g, t, a || 0.01, peak, dur);
    o.connect(g); g.connect(dest);
    o.start(t); o.stop(t + dur + a + 0.05);
    return o;
  }
  function noise(t, dur, peak, a, filterType, f0, f1, q, dest) {
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noiseBuf; s.loop = true;
    f.type = filterType; f.Q.value = q || 0.7;
    f.frequency.setValueAtTime(f0, t);
    if (f1 && f1 !== f0) f.frequency.exponentialRampToValueAtTime(f1, t + dur);
    env(g, t, a || 0.005, peak, dur);
    s.connect(f); f.connect(g); g.connect(dest);
    s.start(t, Math.random()); s.stop(t + dur + a + 0.05);
  }
  const hash = (s) => { let h = 7; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h; };
  const PENT = [0, 2, 4, 7, 9];
  const hz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);

  // ---------------------------------------------------------------- one synth per SOUND_KINDS entry
  const SYNTH = {
    chop(t, o) {
      for (let i = 0; i < 2; i++) {
        const k = t + i * 0.22;
        noise(k, 0.09, 0.5, 0.002, 'lowpass', 1400, 500, 0.8, o);
        osc('sine', 170, 70, k, 0.14, 0.7, 0.002, o);
      }
    },
    knock(t, o) {
      for (let i = 0; i < 3; i++) {
        const k = t + i * 0.13;
        osc('triangle', 900 - i * 80, 420, k, 0.07, 0.5, 0.001, o);
        noise(k, 0.04, 0.25, 0.001, 'bandpass', 2500, 1800, 2, o);
      }
    },
    splash(t, o) {
      noise(t, 0.45, 0.5, 0.02, 'bandpass', 700, 2600, 1.2, o);
      osc('sine', 500, 180, t + 0.03, 0.12, 0.25, 0.005, o);
    },
    fire(t, o) {
      noise(t, 1.0, 0.07, 0.15, 'lowpass', 500, 380, 0.5, o);
      for (let i = 0; i < 7; i++) noise(t + Math.random() * 0.9, 0.025, 0.35, 0.001, 'highpass', 2500 + Math.random() * 3000, 0, 0.7, o);
    },
    thunder(t, o) {
      noise(t, 2.6, 0.9, 0.08, 'lowpass', 380, 90, 0.6, o);
      osc('sine', 60, 30, t, 2.0, 0.6, 0.05, o);
    },
    rain(t, o) { noise(t, 1.6, 0.18, 0.4, 'highpass', 1500, 0, 0.5, o); },
    river(t, o) {
      noise(t, 1.8, 0.2, 0.6, 'bandpass', 500, 900, 0.8, o);
      noise(t + 0.2, 1.5, 0.1, 0.5, 'highpass', 2200, 0, 0.5, o);
    },
    crickets(t, o) {
      for (let c = 0; c < 3; c++) {
        for (let i = 0; i < 4; i++) osc('sine', 4300 + c * 90, 0, t + c * 0.34 + i * 0.045, 0.03, 0.09, 0.004, o);
      }
    },
    bird(t, o) {
      osc('sine', 2400, 3400, t, 0.12, 0.2, 0.01, o);
      osc('sine', 3300, 2500, t + 0.15, 0.16, 0.2, 0.01, o);
    },
    animal(t, o, kind) {
      const h = hash(kind), base = 150 + (h % 7) * 55;
      if (/wolf|dog|fox/.test(kind)) { osc('sawtooth', base * 1.5, base * 3, t, 0.9, 0.12, 0.2, lp(o, 700)); osc('sawtooth', base * 3, base * 2, t + 0.9, 0.7, 0.1, 0.05, lp(o, 700)); return; }
      if (/cow|ox|bull|boar|pig/.test(kind)) { osc('sawtooth', base * 0.7, base * 0.55, t, 0.9, 0.14, 0.12, lp(o, 500)); return; }
      if (/chick|hen|duck|goose|bird/.test(kind)) { for (let i = 0; i < 3; i++) osc('square', 700 + i * 90, 500, t + i * 0.11, 0.07, 0.07, 0.005, lp(o, 1800)); return; }
      osc('triangle', base * 1.6, base * 1.1, t, 0.45, 0.2, 0.04, o);
      osc('triangle', base * 1.2, base * 1.5, t + 0.5, 0.35, 0.16, 0.04, o);
    },
    crowd(t, o) {
      for (let i = 0; i < 4; i++) noise(t + i * 0.28, 0.3, 0.16, 0.08, 'bandpass', 380 + (i % 3) * 170, 300 + (i % 2) * 260, 3, o);
    },
    footsteps(t, o) {
      for (let i = 0; i < 3; i++) noise(t + i * 0.2, 0.08, 0.3, 0.003, 'lowpass', 700, 300, 0.7, o);
    },
    build(t, o) {
      for (let i = 0; i < 2; i++) {
        osc('sine', 230, 120, t + i * 0.3, 0.12, 0.6, 0.002, o);
        noise(t + i * 0.3, 0.06, 0.3, 0.001, 'bandpass', 1500, 900, 1.5, o);
      }
    },
    music(t, o) {
      [0, 2, 4, 7].forEach((s, i) => osc('triangle', hz(72 + PENT[(s + i) % 5]), 0, t + i * 0.16, 0.5, 0.2, 0.01, o));
    },
    dance(t, o) {
      [0, 4, 2, 4, 3, 4].forEach((s, i) => osc('square', hz(67 + PENT[s % 5] + (i % 2 ? 12 : 0)), 0, t + i * 0.12, 0.12, 0.07, 0.005, lp(o, 2200)));
    },
    hunt(t, o) {
      osc('sine', 110, 55, t, 0.25, 0.7, 0.005, o);
      osc('sine', 110, 55, t + 0.3, 0.25, 0.6, 0.005, o);
      noise(t + 0.6, 0.2, 0.2, 0.02, 'bandpass', 900, 400, 1, o);
    },
    blip(t, o) { osc('sine', 660, 440, t, 0.12, 0.2, 0.01, o); },
  };
  function lp(dest, f) {
    const b = ctx.createBiquadFilter();
    b.type = 'lowpass'; b.frequency.value = f; b.connect(dest);
    return b;
  }

  function play(kind, gain) {
    if (!ctx || !state.on || ctx.state !== 'running') return;
    const sub = kind.startsWith('animal:') ? kind.slice(7) : '';
    const name = sub ? 'animal' : (SYNTH[kind] ? kind : 'blip');
    const now = performance.now();
    if (now - (lastAt[kind] || 0) < MIN_GAP_MS || voices >= MAX_VOICES) return;
    lastAt[kind] = now;
    const g = ctx.createGain();
    g.gain.value = gain;
    g.connect(sfx);
    voices++;
    try { SYNTH[name](ctx.currentTime + 0.02, g, sub); } catch (e) { /* a bad voice must not break the viewer */ }
    setTimeout(() => { voices--; try { g.disconnect(); } catch (e) { /* gone */ } }, 3200);
  }

  // ---------------------------------------------------------------- ambient music (generative: no loop seam)
  const MUSIC = {
    day: { root: 60, scale: [0, 2, 4, 7, 9], gap: [2.2, 5.0], oct: [0, 12], type: 'triangle', vol: 0.5 },
    night: { root: 57, scale: [0, 3, 5, 7, 10], gap: [3.5, 7.5], oct: [-12, 0], type: 'sine', vol: 0.45 },
  };
  let musicTimer = null, nextNote = 0, padNodes = null, padFor = '';
  const variant = () => (phase === 'night' || phase === 'dusk' ? 'night' : 'day');

  function setPad() {
    const v = variant();
    if (padFor === v || !ctx) return;
    padFor = v;
    const m = MUSIC[v], t = ctx.currentTime;
    const old = padNodes;
    if (old) { old.g.gain.cancelScheduledValues(t); old.g.gain.setValueAtTime(old.g.gain.value, t); old.g.gain.linearRampToValueAtTime(0, t + 4); setTimeout(() => old.stop(), 4500); }
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.5, t + 4);
    const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = v === 'day' ? 900 : 500;
    g.connect(f); f.connect(musicBus);
    const os = [0, 7].map((s, i) => {
      const o = ctx.createOscillator();
      o.type = 'sine'; o.frequency.value = hz(m.root - 12 + s); o.detune.value = i ? 6 : -6;
      const og = ctx.createGain(); og.gain.value = 0.35;
      o.connect(og); og.connect(g); o.start();
      return o;
    });
    padNodes = { g, stop() { os.forEach((o) => { try { o.stop(); } catch (e) { /* stopped */ } }); } };
  }
  function musicLoop() {
    if (!ctx || !state.on || ctx.state !== 'running') return;
    setPad();
    const m = MUSIC[variant()];
    while (nextNote < ctx.currentTime + 0.6) {
      if (nextNote < ctx.currentTime) nextNote = ctx.currentTime + 0.1;
      const note = m.root + m.oct[(Math.random() * m.oct.length) | 0] + m.scale[(Math.random() * m.scale.length) | 0];
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = m.type; o.frequency.value = hz(note);
      const dur = 2.4;
      g.gain.setValueAtTime(0.0001, nextNote);
      g.gain.exponentialRampToValueAtTime(m.vol * 0.5, nextNote + 0.06);
      g.gain.exponentialRampToValueAtTime(0.0001, nextNote + dur);
      o.connect(g); g.connect(musicBus);
      o.start(nextNote); o.stop(nextNote + dur + 0.1);
      nextNote += m.gap[0] + Math.random() * (m.gap[1] - m.gap[0]);
    }
  }
  function startMusic() {
    if (musicTimer) return;
    nextNote = 0;
    musicTimer = setInterval(musicLoop, 300);
    musicLoop();
  }
  function stopMusic() { if (musicTimer) { clearInterval(musicTimer); musicTimer = null; } }

  // ---------------------------------------------------------------- on/off, volume, UI
  const ICON_ON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19 6a8.5 8.5 0 0 1 0 12"/></svg>';
  const ICON_OFF = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 9l5 6"/><path d="M22 9l-5 6"/></svg>';

  function renderUI() {
    const b = document.getElementById('sound-btn'), v = document.getElementById('sound-vol');
    if (b) {
      b.innerHTML = (state.on ? ICON_ON : ICON_OFF) + '<span class="sr-only">Sound</span>';
      b.setAttribute('aria-pressed', state.on ? 'true' : 'false');
      b.title = state.on ? 'Mute sound (M)' : 'Turn sound on (M)';
    }
    if (v) { v.value = Math.round(state.vol * 100); v.disabled = false; }
  }

  function setOn(on) {
    state.on = !!on;
    save();
    pendingStart = false;
    if (state.on && ensure()) {
      applyVolume();
      const go = () => { startMusic(); };
      if (ctx.state === 'running') go(); else ctx.resume().then(go, () => {});
    } else {
      applyVolume();
      stopMusic();
      if (ctx && ctx.state === 'running') setTimeout(() => { if (!state.on && ctx) ctx.suspend(); }, 300);
    }
    renderUI();
  }

  function init() {
    const b = document.getElementById('sound-btn'), v = document.getElementById('sound-vol');
    renderUI();
    if (b) b.addEventListener('click', (e) => { e.stopPropagation(); setOn(!state.on); });
    if (v) v.addEventListener('input', () => { state.vol = v.value / 100; save(); applyVolume(); });
    window.addEventListener('keydown', (e) => {
      const tag = (e.target && e.target.tagName) || '';
      if ((e.key === 'm' || e.key === 'M') && !e.metaKey && !e.ctrlKey && !e.altKey && !/INPUT|TEXTAREA|SELECT/.test(tag)) setOn(!state.on);
    });
    // a remembered "on" resumes with the first gesture, as browsers require
    const first = () => { if (pendingStart && state.on) setOn(true); window.removeEventListener('pointerdown', first, true); };
    window.addEventListener('pointerdown', first, true);
    window.addEventListener('keydown', first, true);
  }

  // ---------------------------------------------------------------- the hook viewer.js calls
  function tick(events, cam, clock) {
    if (clock && clock.phase) phase = clock.phase;
    if (!state.on || !ctx || ctx.state !== 'running' || !Array.isArray(events)) return;
    const cx = cam && +cam.x, cy = cam && +cam.y;
    for (const ev of events) {
      if (!ev || ev.kind !== 'sound') continue;
      const kind = String(ev.sound || 'blip');
      const d = isFinite(cx) && isFinite(ev.x) ? Math.hypot(ev.x - cx, ev.y - cy) : 0;
      if (d > HEARD_TILES) continue;
      let gain = 1 / (1 + d / 7);
      if (ev.loud) gain = Math.min(1, gain * 1.6);
      play(kind, gain);
    }
  }

  window.SwarmSound = { tick, setOn, get on() { return state.on; }, kinds: Object.keys(SYNTH), play };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
