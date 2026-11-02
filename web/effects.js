/* Swarm World viewer: effects. Fire sparks and smoke, burning trees, flowing rivers, falling leaves, dust
 * where creatures walk, sparkles on discoveries, and the weather: rain and its splashes, drizzle, storms
 * with lightning, fog, wind and heat.
 *
 * Decoration only: everything shown here is something the creatures are already told in words (a fire, the
 * weather, a discovery, the river's flow), so no effect carries meaning of its own.
 *
 * Bounded, for a tab left open for hours: every particle kind has a fixed cap (CAPS), emission is per second
 * of frames drawn (nothing runs while the tab is hidden, since requestAnimationFrame stops, and events that
 * arrive then don't spawn), and when zoomed out the small stuff (leaves, dust, flow streaks) thins or stops.
 *
 * The viewer calls, each frame: under() after the terrain (flowing water, splashes, dust), over() after
 * objects and creatures (smoke, leaves, flames), then its night shading, then sky() (sparks, sparkles, rain,
 * fog, lightning, heat). In the ASCII skin particles are drawn as faint characters.
 */
(function () {
  'use strict';

  const T = window.SwarmTiles;
  const CAPS = { sparks: 90, smoke: 70, leaves: 48, dust: 48, splashes: 50, sparkles: 120, rain: 340, wind: 24 };
  const FLOW = [[1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]];  // flow codes 0..7
  const DRY = new Set(['dirt', 'sand', 'gravel', 'grass']);
  const TREES = new Set(['tree', 'pine']);

  const P = { sparks: [], smoke: [], leaves: [], dust: [], splashes: [], sparkles: [], wind: [] };
  const rain = [];
  for (let i = 0; i < CAPS.rain; i++) rain.push({ x: Math.random(), y: Math.random(), v: 0.55 + Math.random() * 0.45, l: 0.6 + Math.random() * 0.6 });
  for (let i = 0; i < CAPS.wind; i++) P.wind.push({ x: Math.random(), y: Math.random(), v: 0.6 + Math.random() * 0.6, l: 0.4 + Math.random() * 0.8 });
  const W = { rain: 0, drizzle: 0, storm: 0, fog: 0, wind: 0, heat: 0 };  // eased weather levels 0..1
  const flash = { at: -1e9, x: 0, y: 0, strike: false, seed: 0 };
  const burning = new Map();             // "x,y" -> { x, y, until }: trees struck by lightning
  const acc = new Map();                 // emission accumulators, per source (cleared now and then: fires come and go)
  const walkAt = new Map();              // creature id -> last dust puff (ms)
  let fogCv = null, fogCtx = null;

  const rnd = (a, b) => a + Math.random() * (b - a);
  function add(kind, p) { const list = P[kind]; if (list.length < CAPS[kind]) list.push(p); }
  function emit(key, rate, dt) {                    // how many to emit this frame for a steady `rate` per second
    if (acc.size > 256) acc.clear();
    const v = (acc.get(key) || 0) + rate * dt;
    const n = Math.floor(v);
    acc.set(key, v - n);
    return n;
  }
  function age(list, dt) {
    for (let i = list.length - 1; i >= 0; i--) {
      const p = list[i];
      p.t += dt;
      if (p.t >= p.life) { list[i] = list[list.length - 1]; list.pop(); }
    }
  }
  const ascii = (V) => V.skin && V.skin.name === 'ascii';
  /** A particle: a pixel square, or in the ASCII skin a small faint character. */
  function dot(ctx, V, x, y, size, color, alpha, ch, cell) {
    if (alpha <= 0.01) return;
    if (ascii(V) && ch) {             // cell: a fixed glyph cell for screen-wide weather, else the tile size
      const c = cell || V.ts;
      T.drawGlyph(ctx, { char: ch, color }, x - c / 2, y - c / 2, c, { scale: 0.55, outline: false, alpha, weight: 500 });
      return;
    }
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    const s = Math.max(1, Math.round(size));
    ctx.fillRect(Math.round(x - s / 2), Math.round(y - s / 2), s, s);
    ctx.globalAlpha = 1;
  }
  const onScreen = (V, x, y, m) => {
    const sx = V.ox + x * V.ts, sy = V.oy + y * V.ts;
    return sx > -m && sy > -m && sx < V.vw + m && sy < V.vh + m;
  };

  /* ---------------------------------------------------------------- events */
  function events(evs, S) {
    if (!Array.isArray(evs)) return;
    const now = performance.now();
    for (const ev of evs) {
      if (!ev || typeof ev !== 'object') continue;
      const x = +ev.x, y = +ev.y;
      if (ev.kind === 'lightning' && Number.isFinite(x)) {
        burning.set(x + ',' + y, { x, y, until: now + 90000 });   // until fire_out says so (or a safety timeout)
        if (!document.hidden) Object.assign(flash, { at: now, x, y, strike: true, seed: Math.random() * 1000 });
      } else if (ev.kind === 'fire_out') {
        burning.delete(x + ',' + y);
      } else if (ev.kind === 'sound' && ev.sound === 'thunder' && !document.hidden && now - flash.at > 600) {
        Object.assign(flash, { at: now, x, y, strike: false, seed: Math.random() * 1000 });
      } else if ((ev.kind === 'discover' || ev.kind === 'invent') && Number.isFinite(x) && !document.hidden) {
        for (let i = 0; i < 24; i++) {
          const a = Math.random() * Math.PI * 2, v = rnd(0.6, 2.2);
          add('sparkles', { x: x + 0.5, y: y + 0.1, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 1.2, t: 0, life: rnd(0.9, 1.7), c: Math.random() < 0.7 ? '#ffd75e' : '#fff6c8' });
        }
      }
    }
    if (S && burning.size) {
      for (const [k, b] of burning) {
        const here = (S.objAt.get(k) || []).some((o) => TREES.has(o.kind));
        if (!here || now > b.until) burning.delete(k);
      }
    }
  }

  /** Fires and burning trees light the night: [{ x, y, r }] in tiles, for the viewer's night shading. */
  function lights() {
    const out = [];
    for (const b of burning.values()) out.push({ x: b.x, y: b.y - 0.6, r: 4.2 });
    return out;
  }

  /** A creature walking on (x, y): a puff of dust on dry ground, now and then. */
  function walk(id, x, y, surface, now) {
    if (!DRY.has(surface) || W.rain + W.storm + W.drizzle > 0.3 || document.hidden) return;
    const last = walkAt.get(id) || 0;
    if (now - last < (surface === 'grass' ? 520 : 260)) return;
    walkAt.set(id, now);
    if (walkAt.size > 400) walkAt.clear();
    const c = surface === 'sand' ? '#e6d2a4' : surface === 'gravel' ? '#b8b0b4' : surface === 'grass' ? '#c8c8a0' : '#c8a47c';
    add('dust', { x: x + 0.5 + rnd(-0.15, 0.15), y: y + 0.92, vx: rnd(-0.25, 0.25), vy: rnd(-0.25, -0.1), t: 0, life: rnd(0.45, 0.8), c, g: surface === 'grass' ? 0.5 : 1 });
  }

  /* -------------------------------------------------------------- per frame */
  function weather(S, dt) {
    const w = (S.clock && S.clock.weather) || 'clear';
    const k = 1 - Math.exp(-dt * 0.8);
    const want = { rain: w === 'rain' ? 1 : 0, drizzle: w === 'drizzle' ? 1 : 0, storm: w === 'storm' ? 1 : 0, fog: w === 'fog' ? 1 : 0,
                   wind: w === 'wind' || w === 'storm' ? 1 : 0, heat: w === 'heat' ? 1 : 0 };
    for (const key of Object.keys(W)) W[key] += (want[key] - W[key]) * k;
  }

  /** After the terrain: flowing water, rain splashes, dust. */
  function under(ctx, V) {
    const { S, ox, oy, ts, now, dt } = V;
    weather(S, dt);
    const flow = S.land && S.land.flow;
    // rivers: short light streaks carried along the flow (the ASCII skin draws its own)
    if (flow && !ascii(V)) {
      const streaks = V.zoom >= 1.5 ? 2 : 1;
      const q = Math.max(1, Math.round(ts / 16));
      ctx.fillStyle = 'rgb(214,236,250)';
      for (let y = V.y0; y <= V.y1; y++) {
        const row = flow[y];
        if (!row) continue;
        for (let x = V.x0; x <= V.x1; x++) {
          const c = row.charCodeAt(x) - 48;
          if (!(c >= 0 && c < 8)) continue;
          const [fx, fy] = FLOW[c];
          const n = fx && fy ? Math.SQRT1_2 : 1;
          for (let i = 0; i < streaks; i++) {
            const ph = T.hash2(x, y, 60 + i);
            const life = (now / 1600 + ph) % 1;
            const along = life - 0.5;
            const side = (T.hash2(x, y, 70 + i) - 0.5) * 0.6;
            const cx = x + 0.5 + (fx * along - fy * side) * n, cy = y + 0.5 + (fy * along + fx * side) * n;
            ctx.globalAlpha = Math.sin(life * Math.PI) * 0.5;
            const sx = Math.round(ox + cx * ts), sy = Math.round(oy + cy * ts);
            for (let j = 0; j < 3; j++) ctx.fillRect(sx - fx * q * j, sy - fy * q * j, q, q);   // a 3-pixel dash, pointing downstream
          }
        }
      }
      ctx.globalAlpha = 1;
    }
    // splashes in the rain: small crowns on land, rings on water
    const wet = Math.min(1, W.rain + W.storm * 1.4 + W.drizzle * 0.35);
    if (wet > 0.02) {
      const tiles = (V.x1 - V.x0 + 1) * (V.y1 - V.y0 + 1);
      for (let n = emit('splash', Math.min(60, tiles * 0.03) * wet, dt); n > 0; n--) {
        const x = Math.floor(rnd(V.x0, V.x1 + 1)), y = Math.floor(rnd(V.y0, V.y1 + 1));
        const code = (S.tiles[y] || '')[x];
        add('splashes', { x: x + rnd(0.1, 0.9), y: y + rnd(0.1, 0.9), t: 0, life: code === 'w' || code === 'W' ? 0.55 : 0.3, water: code === 'w' || code === 'W' });
      }
    }
    age(P.splashes, dt);
    ctx.lineWidth = 1;
    for (const p of P.splashes) {
      const k = p.t / p.life, sx = ox + p.x * ts, sy = oy + p.y * ts;
      if (ascii(V)) { dot(ctx, V, sx, sy, 1, '#9fc4e8', (1 - k) * 0.6, p.water ? 'o' : '.'); continue; }
      if (p.water) {
        ctx.strokeStyle = `rgba(200,225,255,${(0.55 * (1 - k)).toFixed(3)})`;
        ctx.beginPath(); ctx.ellipse(sx, sy, 1 + k * ts * 0.2, 0.5 + k * ts * 0.09, 0, 0, Math.PI * 2); ctx.stroke();
      } else {
        const q = Math.max(1, Math.round(ts / 16)), h = k * 3 * q;
        ctx.fillStyle = `rgba(210,228,255,${(0.6 * (1 - k)).toFixed(3)})`;
        ctx.fillRect(Math.round(sx - 2 * q), Math.round(sy - h), q, q);
        ctx.fillRect(Math.round(sx + q), Math.round(sy - h), q, q);
        ctx.fillRect(Math.round(sx - q / 2), Math.round(sy - h - q), q, q);
      }
    }
    // dust at walkers' feet
    age(P.dust, dt);
    for (const p of P.dust) {
      p.x += p.vx * dt; p.y += p.vy * dt;
      const k = p.t / p.life;
      if (ascii(V)) { dot(ctx, V, ox + p.x * ts, oy + p.y * ts, 1, p.c, (1 - k) * 0.5 * p.g, '.'); continue; }
      ctx.globalAlpha = (1 - k) * 0.42 * p.g;
      ctx.fillStyle = p.c;
      ctx.beginPath(); ctx.arc(ox + p.x * ts, oy + p.y * ts, ts * (0.06 + k * 0.12), 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  /** After objects and creatures: smoke from fires and burning trees, flames, falling leaves. */
  function over(ctx, V) {
    const { S, ox, oy, ts, now, dt } = V;
    const wind = W.wind;
    const far = V.zoom < 1.5;
    // sources: lit fires on screen and struck trees
    const fires = [];
    for (const o of S.lit) if (onScreen(V, o.x, o.y, ts * 3)) fires.push({ x: o.x, y: o.y, kind: o.kind, id: o.id, big: false });
    for (const b of burning.values()) if (onScreen(V, b.x, b.y, ts * 4)) fires.push({ x: b.x, y: b.y, kind: 'tree', id: b.x + ',' + b.y, big: true });
    for (const f of fires) {
      const top = f.big ? 1.6 : 0.45;
      const anchor = V.skin && V.skin.smokeAt ? V.skin.smokeAt(f.kind) : null;
      const ax = f.x + (anchor ? anchor[0] : 0.5), ay = f.y + (anchor ? 1 - anchor[1] * 1.6 : 1 - top);
      for (let n = emit('smoke' + f.id, (f.big ? 7 : 1.6) * (far ? 0.5 : 1), dt); n > 0; n--) {
        add('smoke', { x: ax + rnd(-0.1, 0.1), y: ay, vx: rnd(-0.05, 0.05), vy: rnd(-0.5, -0.32), t: 0, life: rnd(2.2, 3.6), r: rnd(0.1, 0.16) * (f.big ? 1.6 : 1) });
      }
      for (let n = emit('spark' + f.id, (f.big ? 14 : 3.2) * (far ? 0.5 : 1), dt); n > 0; n--) {
        add('sparks', { x: f.x + 0.5 + rnd(-0.18, 0.18) * (f.big ? 2 : 1), y: f.y + 1 - top - 0.1, vx: rnd(-0.2, 0.2), vy: rnd(-1.4, -0.7), t: 0, life: rnd(0.5, 1.1) });
      }
      if (f.big) drawFlames(ctx, V, f, now);
    }
    // smoke: soft grey puffs, growing and fading, blown by the wind
    age(P.smoke, dt);
    for (const p of P.smoke) {
      p.x += (p.vx + wind * 0.9 + Math.sin(now / 900 + p.life * 10) * 0.04) * dt; p.y += p.vy * dt;
      const k = p.t / p.life;
      const a = Math.sin(Math.min(1, k * 3) * Math.PI / 2) * (1 - k) * 0.34;
      if (ascii(V)) { dot(ctx, V, ox + p.x * ts, oy + p.y * ts, 1, '#8a8a92', a * 1.5, k < 0.5 ? '°' : '∘'); continue; }
      ctx.globalAlpha = a;
      ctx.fillStyle = '#9a96a0';
      ctx.beginPath(); ctx.arc(ox + p.x * ts, oy + p.y * ts, ts * p.r * (1 + k * 2.2), 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
    // falling leaves over forest tiles (fewer over pines; none when zoomed out)
    if (!far) {
      const visible = (V.x1 - V.x0 + 1) * (V.y1 - V.y0 + 1);
      for (let n = emit('leaf', Math.min(10, visible * 0.006) * (1 + wind * 2), dt); n > 0; n--) {
        const x = Math.floor(rnd(V.x0, V.x1 + 1)), y = Math.floor(rnd(V.y0, V.y1 + 1));
        if ((S.tiles[y] || '')[x] !== 'f') continue;
        const biome = S.land && S.land.biomes && S.land.biomes[y] ? S.land.biomes[y][x] : 'o';
        if (biome === 'p' && Math.random() < 0.7) continue;
        const c = biome === 'p' ? '#8a6a3a' : ['#d8c050', '#c8862e', '#e0a848', '#a8d060'][Math.floor(Math.random() * 4)];
        add('leaves', { x: x + rnd(0, 1), y: y - rnd(0.6, 1.2), vx: rnd(-0.1, 0.1), vy: rnd(0.22, 0.38), t: 0, life: rnd(3, 5), c, ph: rnd(0, 6.28) });
      }
    }
    age(P.leaves, dt);
    for (const p of P.leaves) {
      p.x += (p.vx + wind * 0.8 + Math.sin(now / 520 + p.ph) * 0.18) * dt; p.y += p.vy * dt;
      const k = p.t / p.life;
      const a = Math.min(1, k * 4) * (1 - k * k) * 0.95;
      const sx = ox + p.x * ts, sy = oy + p.y * ts;
      if (ascii(V)) { dot(ctx, V, sx, sy, 1, p.c, a, '`'); continue; }
      const q = Math.max(1, Math.round(ts / 16));
      ctx.globalAlpha = a;
      ctx.fillStyle = p.c;
      const flip = Math.sin(now / 300 + p.ph) > 0;    // a leaf tumbling: wide, then edge-on
      ctx.fillRect(Math.round(sx), Math.round(sy), flip ? 3 * q : q, flip ? 2 * q : 2 * q);
      ctx.fillStyle = 'rgba(30,40,20,0.5)';
      ctx.fillRect(Math.round(sx), Math.round(sy + 2 * q), flip ? 3 * q : q, Math.max(1, q >> 1));
    }
    ctx.globalAlpha = 1;
  }

  /** Flames licking up a struck tree: flickering tongues of red, orange and yellow over its crown. */
  function drawFlames(ctx, V, f, now) {
    const { ox, oy, ts } = V;
    const q = Math.max(1, Math.round(ts / 16));
    const tall = V.skin && V.skin.spriteTopTiles > 1 ? 2.1 : 1;      // LimeZu trees stand about two tiles tall
    const bx = ox + (f.x + 0.5) * ts, by = oy + (f.y + 1) * ts;
    if (ascii(V)) {
      for (let i = 0; i < 3; i++) dot(ctx, V, bx + (i - 1) * ts * 0.3, by - ts * (1 + (i % 2) * 0.3), 1, i % 2 ? '#ffd27a' : '#ff7a2a', 0.9, '^');
      return;
    }
    for (let i = 0; i < 9; i++) {
      const fl = 0.5 + 0.5 * Math.sin(now / (80 + i * 11) + i * 1.7);
      const x = bx + (T.hash2(f.x, f.y, 80 + i) - 0.5) * ts * 1.1;
      const y = by - ts * tall * (0.35 + T.hash2(f.x, f.y, 90 + i) * 0.55);
      const h = Math.round((4 + fl * 6) * q * (tall > 1 ? 1.3 : 1)), w = 3 * q;
      ctx.fillStyle = '#c8301c';
      ctx.fillRect(Math.round(x - w / 2), Math.round(y - h), w, h);
      ctx.fillStyle = '#ff7a22';
      ctx.fillRect(Math.round(x - w / 2 + q / 2), Math.round(y - h * 0.8), Math.max(1, w - q), Math.round(h * 0.8));
      ctx.fillStyle = '#ffd86a';
      ctx.fillRect(Math.round(x - q / 2), Math.round(y - h * 0.45), q, Math.round(h * 0.45));
    }
  }

  /** After the night shading: sparks and sparkles (they glow), rain, fog, lightning and heat. */
  function sky(ctx, V) {
    const { S, ox, oy, ts, vw, vh, now, dt } = V;
    // sparks: tiny embers that rise, drift and wink out
    age(P.sparks, dt);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const q = Math.max(1, Math.round(ts / 16));
    for (const p of P.sparks) {
      p.x += (p.vx + W.wind * 0.8) * dt; p.y += p.vy * dt; p.vy *= 0.985;
      const k = p.t / p.life;
      dot(ctx, V, ox + p.x * ts, oy + p.y * ts, q, k < 0.4 ? '#ffd27a' : '#ff8a3a', (1 - k) * 0.95, '·');
    }
    // sparkles: a burst of gold where something was discovered
    age(P.sparkles, dt);
    for (const p of P.sparkles) {
      p.x += p.vx * dt; p.y += p.vy * dt; p.vy += 1.6 * dt; p.vx *= 0.97;
      const k = p.t / p.life;
      const a = (1 - k) * (0.6 + 0.4 * Math.sin(now / 60 + p.life * 40));
      const sx = ox + p.x * ts, sy = oy + p.y * ts;
      if (ascii(V)) { dot(ctx, V, sx, sy, q, p.c, a, '*'); continue; }
      dot(ctx, V, sx, sy, 2 * q, p.c, a);
      if (k < 0.6) {                    // a four-pointed twinkle
        for (const [ax, ay] of [[-2, 0], [2, 0], [0, -2], [0, 2]]) dot(ctx, V, sx + ax * q, sy + ay * q, q, p.c, a * 0.6);
      }
    }
    ctx.restore();

    // a darker, cooler sky in rain and storms; warm in heat
    const gloom = W.rain * 0.2 + W.drizzle * 0.1 + W.storm * 0.3;
    if (gloom > 0.01) { ctx.fillStyle = `rgba(28,44,72,${gloom.toFixed(3)})`; ctx.fillRect(0, 0, vw, vh); }
    if (W.heat > 0.01) drawHeat(ctx, V);
    drawRain(ctx, V);
    if (W.wind > 0.02) drawWind(ctx, V);
    if (W.fog > 0.01) drawFog(ctx, V);
    drawLightning(ctx, V);
  }

  function drawRain(ctx, V) {
    const { vw, vh, dt } = V;
    const level = Math.min(1, W.rain + W.storm + W.drizzle * 0.3);
    if (level < 0.01) return;
    const n = Math.round(rain.length * level);
    const slant = 0.18 + W.storm * 0.5 + W.wind * 0.25;
    const len = 9 + W.storm * 5;
    if (ascii(V)) {
      for (let i = 0; i < n; i += 2) {
        const d = rain[i];
        d.y += d.v * dt * 1.1; d.x -= d.v * dt * slant;
        if (d.y > 1) { d.y -= 1; d.x = Math.random(); }
        if (d.x < 0) d.x += 1;
        dot(ctx, V, d.x * vw, d.y * vh, 1, '#8fb4e0', 0.5 * level, '\'', 24);
      }
      return;
    }
    ctx.save();
    ctx.strokeStyle = `rgba(196,218,255,${((0.42 - W.drizzle * 0.18) * level).toFixed(3)})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const d = rain[i];
      d.y += d.v * dt * (1.1 + W.storm * 0.6);
      d.x -= d.v * dt * slant;
      if (d.y > 1) { d.y -= 1; d.x = Math.random(); }
      if (d.x < 0) d.x += 1;
      const px = Math.round(d.x * vw), py = Math.round(d.y * vh);
      const l = d.l * (1 - W.drizzle * 0.5);
      ctx.moveTo(px, py);
      ctx.lineTo(px - len * slant * l, py + len * l);
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawWind(ctx, V) {
    const { vw, vh, dt } = V;
    ctx.save();
    for (const p of P.wind) {
      p.x += p.v * dt * 0.9;
      if (p.x > 1.1) { p.x = -0.1; p.y = Math.random(); }
      const x = p.x * vw, y = p.y * vh + Math.sin(p.x * 9 + p.l * 5) * 6;
      if (ascii(V)) { dot(ctx, V, x, y, 1, '#c8d4e0', 0.25 * W.wind, '-', 24); continue; }
      ctx.strokeStyle = `rgba(232,240,250,${(0.26 * W.wind).toFixed(3)})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 40 * p.l, y - 2); ctx.stroke();
    }
    ctx.restore();
  }

  /** Fog: a pale veil, thickest at the screen's edges, with drifting banks and a clear patch around each
   *  awake creature about as far as it can see. In the ASCII skin the veil is a dimming instead. */
  function drawFog(ctx, V) {
    const { S, ox, oy, ts, vw, vh, now, dpr } = V;
    const w = Math.max(1, Math.round(vw * dpr)), h = Math.max(1, Math.round(vh * dpr));
    if (!fogCv) { fogCv = document.createElement('canvas'); fogCtx = fogCv.getContext('2d'); }
    if (fogCv.width !== w || fogCv.height !== h) { fogCv.width = w; fogCv.height = h; }
    const g = fogCtx;
    const L = W.fog;
    const base = ascii(V) ? [8, 9, 14] : [196, 202, 212];
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.globalCompositeOperation = 'source-over';
    g.clearRect(0, 0, vw, vh);
    g.fillStyle = `rgba(${base},${(0.4 * L).toFixed(3)})`;
    g.fillRect(0, 0, vw, vh);
    const edge = g.createRadialGradient(vw / 2, vh / 2, Math.min(vw, vh) * 0.25, vw / 2, vh / 2, Math.max(vw, vh) * 0.7);
    edge.addColorStop(0, `rgba(${base},0)`);
    edge.addColorStop(1, `rgba(${base},${(0.35 * L).toFixed(3)})`);
    g.fillStyle = edge;
    g.fillRect(0, 0, vw, vh);
    for (let i = 0; i < 5; i++) {       // slow banks of thicker fog
      const bx = ((now / 60000 * (0.6 + i * 0.13) + i * 0.27) % 1.4 - 0.2) * vw, by = (0.15 + i * 0.18) * vh;
      const r = Math.max(vw, vh) * 0.28;
      const b = g.createRadialGradient(bx, by, 0, bx, by, r);
      b.addColorStop(0, `rgba(${base},${(0.18 * L).toFixed(3)})`);
      b.addColorStop(1, `rgba(${base},0)`);
      g.fillStyle = b;
      g.fillRect(bx - r, by - r, r * 2, r * 2);
    }
    g.globalCompositeOperation = 'destination-out';
    for (const e of S.cres.values()) {
      if (e.d.asleep) continue;
      const cx = ox + (e.rx + 0.5) * ts, cy = oy + (e.ry + 0.5) * ts, r = 3.4 * ts;
      if (cx < -r || cy < -r || cx > vw + r || cy > vh + r) continue;
      const c = g.createRadialGradient(cx, cy, 0, cx, cy, r);
      c.addColorStop(0, 'rgba(0,0,0,0.85)');
      c.addColorStop(0.6, 'rgba(0,0,0,0.5)');
      c.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = c;
      g.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(fogCv, 0, 0);
    ctx.restore();
  }

  function drawLightning(ctx, V) {
    const { ox, oy, ts, vw, vh, now } = V;
    const age = now - flash.at;
    if (age > 700) return;
    // the sky lights up twice, quickly
    const a = Math.max(0, 1 - age / 260) * 0.55 + (age > 120 && age < 220 ? 0.25 : 0);
    if (flash.strike && age < 260) {
      const tx = ox + (flash.x + 0.5) * ts, ty = oy + (flash.y + 0.2) * ts;
      if (tx > -50 && tx < vw + 50 && ty > -50 && ty < vh + 50) {
        ctx.save();
        ctx.strokeStyle = `rgba(240,246,255,${(1 - age / 260).toFixed(3)})`;
        ctx.lineWidth = Math.max(2, ts / 10);
        ctx.beginPath();
        let x = tx + Math.sin(flash.seed) * vw * 0.12, y = 0;
        ctx.moveTo(x, y);
        for (let i = 1; i <= 8; i++) {
          y = ty * i / 8;
          x += (tx - x) / (9 - i) + Math.sin(flash.seed + i * 7.3) * ts * 0.7;
          ctx.lineTo(i === 8 ? tx : x, y);
        }
        ctx.stroke();
        ctx.restore();
      }
    }
    if (a > 0.01) { ctx.fillStyle = `rgba(226,234,255,${a.toFixed(3)})`; ctx.fillRect(0, 0, vw, vh); }
  }

  function drawHeat(ctx, V) {
    const { vw, vh, now } = V;
    const L = W.heat;
    ctx.fillStyle = `rgba(255,150,60,${(0.08 * L).toFixed(3)})`;
    ctx.fillRect(0, 0, vw, vh);
    if (ascii(V)) return;
    // shimmer: faint bright bands drifting up the screen
    ctx.save();
    for (let i = 0; i < 6; i++) {
      const y = vh - ((now / 9000 + i / 6) % 1) * vh;
      ctx.globalAlpha = 0.05 * L;
      ctx.fillStyle = '#fff2d8';
      for (let x = 0; x < vw; x += 32) ctx.fillRect(x, Math.round(y + Math.sin(x / 40 + now / 500 + i) * 3), 24, 1);
    }
    ctx.restore();
  }

  function reset() {
    for (const list of Object.values(P)) if (list !== P.wind) list.length = 0;
    burning.clear();
    walkAt.clear();
    acc.clear();
  }

  function stats() {
    const out = {};
    for (const [k, list] of Object.entries(P)) out[k] = list.length;
    out.burning = burning.size;
    out.caps = CAPS;
    return out;
  }

  window.SwarmFX = { CAPS, events, lights, walk, under, over, sky, reset, stats, get weather() { return { ...W }; } };
})();
