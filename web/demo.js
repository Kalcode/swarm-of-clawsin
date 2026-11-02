/* Swarm World viewer: demo mode (?demo=1).
 *
 * Fakes the world server in the browser so the viewer can be developed and
 * checked without Python: a random 64x64 world, 12 wandering creatures, a tick
 * stream on a fake WebSocket, and fake REST answers. Every message follows the
 * spectator-stream schema in docs/superpowers/plans/2026-11-01-swarm-world.md.
 *
 * Optional URL params: seed=<int> (world seed), start=<tick> (start time;
 * 800 starts at night), speed=<n> (tick rate multiplier).
 */
(function () {
  'use strict';

  const params = new URLSearchParams(location.search);
  const SEED = (parseInt(params.get('seed'), 10) || 7) >>> 0;
  // the demo world has been running for a few days, so the History tab has something to show
  const START_TICK = params.has('start') ? Math.max(0, parseInt(params.get('start'), 10) || 0) : 4030;
  const SPEED = Math.min(8, Math.max(0.25, parseFloat(params.get('speed')) || 1));
  const W = 64, H = 64, DAY = 1200, TICK_MS = 500 / SPEED;

  /* ---------------------------------------------------------------- random */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rnd = mulberry32(SEED);
  const randint = (a, b) => a + Math.floor(rnd() * (b - a + 1));
  const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
  const chance = (p) => rnd() < p;

  function makeNoise(seed, cell) {
    const r = mulberry32(seed);
    const gw = Math.ceil(W / cell) + 2, gh = Math.ceil(H / cell) + 2;
    const g = [];
    for (let i = 0; i < gw * gh; i++) g.push(r());
    const sm = (t) => t * t * (3 - 2 * t);
    return (x, y) => {
      const fx = x / cell, fy = y / cell;
      const ix = Math.floor(fx), iy = Math.floor(fy);
      const tx = sm(fx - ix), ty = sm(fy - iy);
      const v = (a, b) => g[(b) * gw + (a)];
      const top = v(ix, iy) * (1 - tx) + v(ix + 1, iy) * tx;
      const bot = v(ix, iy + 1) * (1 - tx) + v(ix + 1, iy + 1) * tx;
      return top * (1 - ty) + bot * ty;
    };
  }
  const n1 = makeNoise(SEED * 3 + 1, 14), n2 = makeNoise(SEED * 5 + 2, 7), n3 = makeNoise(SEED * 7 + 3, 3);
  const m1 = makeNoise(SEED * 11 + 4, 12), m2 = makeNoise(SEED * 13 + 5, 5);
  const height = (x, y) => n1(x, y) * 0.6 + n2(x, y) * 0.3 + n3(x, y) * 0.1;
  const moist = (x, y) => m1(x, y) * 0.7 + m2(x, y) * 0.3;

  /* --------------------------------------------------------------- terrain */
  const CX = 32, CY = 32;
  const grid = [];
  for (let y = 0; y < H; y++) grid.push(new Array(W).fill('g'));
  const inb = (x, y) => x >= 0 && y >= 0 && x < W && y < H;
  const cheb = (ax, ay, bx, by) => Math.max(Math.abs(ax - bx), Math.abs(ay - by));

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const h = height(x, y), m = moist(x, y);
      let t = 'g';
      if (h > 0.64) t = 'r';
      else if (m > 0.56) t = 'f';
      else if (h < 0.36 && m < 0.42) t = 'd';
      grid[y][x] = t;
    }
  }
  // a lake off to one side
  const LX = randint(12, 20), LY = randint(40, 50), LR = randint(7, 9);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const d = Math.hypot((x - LX) * 0.9, y - LY) + (n3(x, y) - 0.5) * 3;
      if (d < LR * 0.55) grid[y][x] = 'W';
      else if (d < LR) grid[y][x] = 'w';
    }
  }
  // a river from the lake to the east edge
  {
    let ry = LY - 2;
    for (let x = LX; x < W; x++) {
      ry += Math.round((n2(x * 3, 9) - 0.5) * 2.2);
      ry = Math.max(6, Math.min(H - 6, ry));
      if (cheb(x, ry, CX, CY) < 9) ry += ry < CY ? -1 : 1;
      for (let k = 0; k < 2; k++) if (inb(x, ry + k)) grid[ry + k][x] = 'w';
    }
  }
  // sand around water
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (grid[y][x] === 'w' || grid[y][x] === 'W') continue;
      let near = false;
      for (let dy = -1; dy <= 1 && !near; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (inb(x + dx, y + dy) && (grid[y + dy][x + dx] === 'w')) { near = true; break; }
      }
      if (near && grid[y][x] !== 'r') grid[y][x] = 's';
    }
  }
  // the meadow at the center, with a worn dirt patch around the fire
  for (let y = CY - 7; y <= CY + 7; y++) {
    for (let x = CX - 7; x <= CX + 7; x++) {
      const d = Math.hypot(x - CX, y - CY);
      if (d < 7) grid[y][x] = d < 2.2 ? 'd' : 'g';
    }
  }

  /* --------------------------------------------------------------- objects */
  const BLOCKING = new Set(['tree', 'pine', 'rock', 'copper_vein', 'iron_vein', 'wall', 'workbench', 'furnace', 'chest', 'terminal']);
  const objects = new Map();
  const objAt = new Map();
  let oid = 0;
  function addObj(kind, x, y, extra) {
    const o = Object.assign({ id: 'o' + (++oid), kind, x, y }, extra || {});
    objects.set(o.id, o);
    objAt.set(x + ',' + y, o);
    return o;
  }
  function removeObj(o) { objects.delete(o.id); objAt.delete(o.x + ',' + o.y); }
  const tileAt = (x, y) => (inb(x, y) ? grid[y][x] : 'W');
  const isWater = (t) => t === 'w' || t === 'W';
  function walkable(x, y) {
    if (!inb(x, y) || isWater(grid[y][x])) return false;
    const o = objAt.get(x + ',' + y);
    return !(o && BLOCKING.has(o.kind));
  }
  const free = (x, y) => inb(x, y) && !isWater(grid[y][x]) && !objAt.has(x + ',' + y);

  // the camp
  const camp = addObj('campfire', CX, CY + 1, { lit: true });
  addObj('workbench', CX + 3, CY - 1);
  addObj('sign', CX - 3, CY - 2, { label: 'camp', text: 'Fire here. Berries to the east. Flint in the grey hills.' });
  addObj('pile', CX - 2, CY + 3, { label: '3 sticks' });
  const chestObj = addObj('chest', CX + 4, CY + 2, { text: '3 planks, 1 rope' });
  const basket = addObj('basket', CX - 1, CY + 3, { label: 'basket', text: '4 berries, 2 stick' });
  const store = { berries: 4, stick: 2 };
  // a first wheat field, a sapling and some new furniture
  const field = [];
  for (let fy = 0; fy < 2; fy++) for (let fx = 0; fx < 4; fx++) {
    const x = CX - 5 + fx, y = CY + 5 + fy;
    if (!objAt.has(x + ',' + y) && grid[y][x] !== 'w' && grid[y][x] !== 'W') {
      grid[y][x] = 'd';
      const crop = fx < 2 ? 'wheat' : 'carrot';
      field.push(addObj('crop', x, y, { label: crop, crop, stage: (fx + fy) % 3 }));
    }
  }
  addObj('sapling', CX + 2, CY + 4);
  addObj('millstone', CX + 5, CY - 2);
  addObj('bed', CX - 4, CY + 1);
  addObj('door', CX + 1, CY - 4);
  addObj('creation', CX - 2, CY - 3, { label: 'sun totem', text: 'A carved post that catches the morning light.' });
  // a few farm animals wander around the meadow
  const animals = [];
  for (const [kind, dx, dy] of [['chicken', 3, 3], ['chicken', 4, 4], ['chicken', -2, 5], ['sheep', 6, -4], ['sheep', -6, -3], ['cow', 7, 1]]) {
    const x = CX + dx, y = CY + dy;
    if (!objAt.has(x + ',' + y)) animals.push(addObj(kind, x, y, { label: kind }));
  }
  if (animals[0]) animals[0].tamed_by = 'Tam';
  // named places
  const landmarks = [
    { name: "Tam's camp", x: CX, y: CY + 1, kind: 'camp', size: 5 },
    { name: 'Mirror Lake', x: LX, y: LY, kind: 'lake', size: 0 },
    { name: 'the Long Meadow', x: CX + 9, y: CY - 7, kind: 'meadow', size: 0 },
  ];

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (!free(x, y) || cheb(x, y, CX, CY) < 5) continue;
      const t = grid[y][x], h = height(x, y);
      if (t === 'f') {
        if (chance(0.42)) addObj(h > 0.5 || chance(0.3) ? 'pine' : 'tree', x, y);
        else if (chance(0.05)) addObj('bush', x, y);
      } else if (t === 'g') {
        if (chance(0.03)) addObj('tree', x, y);
        else if (chance(0.028)) addObj('bush', x, y);
      } else if (t === 'r') {
        if (chance(0.2)) addObj('rock', x, y);
        else if (chance(0.02)) addObj('copper_vein', x, y);
        else if (chance(0.014)) addObj('iron_vein', x, y);
      } else if (t === 's') {
        if (chance(0.06)) addObj('clay', x, y);
      } else if (t === 'd') {
        if (chance(0.03)) addObj('rock', x, y);
      }
    }
  }
  // guarantee a few of each resource so the world reads well
  function ensure(kind, count, where) {
    let have = [...objects.values()].filter((o) => o.kind === kind).length;
    for (let tries = 0; have < count && tries < 4000; tries++) {
      const x = randint(1, W - 2), y = randint(1, H - 2);
      if (free(x, y) && where(grid[y][x]) && cheb(x, y, CX, CY) > 6) { addObj(kind, x, y); have++; }
    }
  }
  ensure('copper_vein', 4, (t) => t === 'r');
  ensure('iron_vein', 3, (t) => t === 'r');
  ensure('clay', 6, (t) => t === 's');
  ensure('bush', 22, (t) => t === 'g' || t === 'f');
  // a few bushes near the meadow so there is visible activity at the start
  for (const [dx, dy] of [[6, -3], [7, 2], [-6, 4], [5, 6], [-7, -2]]) {
    const x = CX + dx, y = CY + dy;
    if (free(x, y)) addObj('bush', x, y);
  }
  for (const [dx, dy] of [[-8, -6], [9, -5], [-5, 8]]) {
    const x = CX + dx, y = CY + dy;
    if (free(x, y)) addObj(chance(0.5) ? 'tree' : 'pine', x, y);
  }
  for (const [dx, dy] of [[8, 5], [-9, 1]]) { const x = CX + dx, y = CY + dy; if (free(x, y)) addObj('rock', x, y); }
  { const x = CX - 6, y = CY - 5; if (free(x, y)) addObj('stump', x, y); }

  // two terminals with tablets, far from the center
  function placeTerminal() {
    for (let tries = 0; tries < 3000; tries++) {
      const x = randint(4, W - 5), y = randint(4, H - 5);
      if (cheb(x, y, CX, CY) < 15) continue;
      if (!free(x, y) || !free(x + 1, y) || !walkable(x, y + 1)) continue;
      const term = addObj('terminal', x, y, { text: '' });
      addObj('tablet', x + 1, y, { text: 'Terminals run Lua. Try: say("hello")' });
      return term;
    }
    return null;
  }
  // words carved into a couple of trees near the camp
  {
    const carved = [...objects.values()].filter((o) => (o.kind === 'tree' || o.kind === 'pine') && cheb(o.x, o.y, CX, CY) <= 10).slice(0, 2);
    if (carved[0]) carved[0].text = 'TAM WAS HERE';
    if (carved[1]) carved[1].text = 'berries east, flint in the hills';
  }
  const terminals = [placeTerminal(), placeTerminal()].filter(Boolean);
  terminals.forEach((t, i) => landmarks.push({ name: i ? 'the Quiet Machine' : 'the Humming Stone', x: t.x, y: t.y, kind: 'terminal', size: 0 }));

  /* ------------------------------------------------------------- catalog */
  const ITEMS = {
    stick: 'stick', log: 'log', stone: 'stone', flint: 'flint', plant_fiber: 'plant fiber', berries: 'berries',
    sand: 'sand', clay: 'clay', copper_ore: 'copper ore', iron_ore: 'iron ore', water: 'water', rope: 'rope',
    campfire: 'campfire', stone_knife: 'stone knife', stone_axe: 'stone axe', stone_pickaxe: 'stone pickaxe',
    planks: 'planks', workbench: 'workbench', sign: 'sign', wooden_wall: 'wooden wall', chest: 'chest',
    roasted_berries: 'roasted berries', charcoal: 'charcoal', brick: 'brick', furnace: 'furnace',
    copper_ingot: 'copper ingot', iron_ingot: 'iron ingot', copper_wire: 'copper wire', paper: 'paper',
    book: 'book', copper_pickaxe: 'copper pickaxe', terminal: 'terminal',
    wheat_seeds: 'wheat seeds', wheat: 'wheat', flour: 'flour', bread: 'bread', hoe: 'hoe', millstone: 'millstone',
    bed: 'bed', door: 'door', fishing_rod: 'fishing rod', fish: 'fish', cooked_fish: 'cooked fish',
    egg: 'egg', cooked_egg: 'cooked egg', milk: 'milk', wool: 'wool', cloth: 'cloth', carrot_seeds: 'carrot seeds', carrot: 'carrot', basket: 'basket',
    inv_berry_cake: 'berry cake', inv_sun_totem: 'sun totem',
  };
  const DISCOVERABLE = ['stone_axe', 'stone_pickaxe', 'planks', 'roasted_berries', 'charcoal', 'brick', 'sign', 'wooden_wall', 'paper', 'chest'];

  /* ------------------------------------------------------------- creatures */
  const MODELS = [
    // these hues pass the dataviz colour checks together once moved into the chart lightness band
    { tag: 'qwen3.5-9b', color: '#5bc0eb' },
    { tag: 'qwen3.5-4b', color: '#f2c14e' },
    { tag: 'gemma-4-e4b', color: '#e87ba4' },
  ];
  const NAMES = ['Tam', 'Mara', 'Ivo', 'Pell', 'Suri', 'Odo', 'Bex', 'Nim', 'Rook', 'Lia', 'Juno', 'Cato'];
  const TRAITS = ['curious', 'patient', 'chatty', 'cautious', 'bold', 'generous', 'stubborn', 'thoughtful', 'restless', 'tidy', 'playful', 'wary'];
  const DRIVES = ['curious', 'builder', 'social', 'explorer', 'gatherer', 'tinkerer'];
  const LINES = [
    'Has anyone found flint? I want to try a stick with a sharp stone.',
    'The berries by the river are back.',
    'Come sit by the fire, it is getting dark.',
    'I made rope from plant fiber. Three of them twist into one rope.',
    'Does anyone know what clay is for?',
    'There is grey rock in the hills to the north. Some of it shines orange.',
    'I think rope plus a stick plus a stone makes something useful. I am going to try that at the workbench before night, because after dark I can barely see two steps ahead and the fire is the only safe place to work.',
    'Hello! I am new here.',
    'Who built the workbench?',
    'I can share berries if you are hungry.',
    'The terminal by the water hums. The tablet says it runs Lua.',
    'Careful near the deep water.',
    'I will gather sticks for the fire.',
    'Mara, do you want to explore the forest with me?',
    'I wrote directions on the sign.',
    'My hands are full. I should drop some stones.',
  ];

  const cres = [];
  function spawnPoint() {
    for (let tries = 0; tries < 500; tries++) {
      const x = CX + randint(-6, 6), y = CY + randint(-6, 6);
      if (walkable(x, y) && !objAt.has(x + ',' + y) && !cres.some((o) => o.x === x && o.y === y)) return [x, y];
    }
    return [CX, CY];
  }
  NAMES.forEach((name, i) => {
    const model = MODELS[i < 6 ? 0 : i < 9 ? 1 : 2];
    const [x, y] = spawnPoint();
    const traits = [];
    while (traits.length < 2) { const t = pick(TRAITS); if (!traits.includes(t)) traits.push(t); }
    cres.push({
      id: 'c' + (i + 1), name, x, y, model: model.tag, color: model.color,
      activity: null, thinking: false, asleep: i === 10 || i === 11, say: null,
      satiety: randint(45, 95), energy: randint(50, 100), health: i === 7 ? 24 : randint(80, 100), holding: null,
      // private demo state
      persona: { name, traits, drive: pick(DRIVES) },
      inv: { stick: randint(0, 3), plant_fiber: randint(0, 2), berries: randint(0, 3), wheat_seeds: randint(0, 4), egg: i % 3 === 0 ? 2 : 0, wool: i % 4 === 1 ? 1 : 0 },
      path: null, job: null, sayUntil: 0, thinkUntil: 0, nextThink: START_TICK + randint(1, 20),
      known: ['rope', 'campfire'], people: {}, memory: [], heard: [],
      lastThought: '', lastIntention: null, lastResult: '', goal: '', summary: '',
      stats: { thinks: 0, acts_ok: 0, acts_failed: 0, words_spoken: 0, discoveries: 0, stored: 0, took_from_store: 0, tended_fire: 0 },
    });
  });
  const byId = new Map(cres.map((c) => [c.id, c]));

  /* ---------------------------------------------------------------- history */
  // A plausible past: smooth growth curves with a little deterministic texture,
  // one snapshot every 60 ticks from the beginning of the world.
  function historyList() {
    const out = [];
    let rkMax = 2, firstMax = 0, stMax = 0, tieMax = 0;
    for (let tk = 0; tk <= tick; tk += 60) {
      const t = tk / DAY;
      const wob = (k) => mulberry32(SEED * 97 + tk * 7 + k)();
      const models = {};
      MODELS.forEach((m, k) => {
        const n = cres.filter((c) => c.model === m.tag).length;
        const skill = [1, 0.82, 0.68][k];
        const grow = (a, p) => Math.floor(n * a * Math.pow(t, p) * skill);   // cumulative: never decreases
        models[m.tag] = {
          creatures: n, thinks: grow(70, 1), crafted: grow(4.2, 1.25), discoveries: Math.floor(Math.min(6, t * 1.3 * skill)),
          inventions: Math.floor(t * 0.45 * skill), speech: Math.floor(n * 16 * t * [0.9, 1.35, 1.1][k]), built: grow(0.8, 1.4),
          gathered: grow(38, 1), writing: grow(0.35, 1.2), collapses: Math.floor(n * 0.12 * t), learned: grow(1.4, 1.35),
          recipes_known: Math.floor(n * (2 + 6 * (1 - Math.exp(-t * skill / 2)))),
        };
      });
      rkMax = Math.max(rkMax, 2 + Math.floor(14 * (1 - Math.exp(-t / 1.6)) + 0.9 * wob(9)));
      firstMax = Math.max(firstMax, Math.floor((rkMax - 2) * 0.6 + 0.6 * wob(10)));
      stMax = Math.max(stMax, Math.floor(17 * (1 - Math.exp(-t / 2.1)) + 0.5 * wob(11)));
      tieMax = Math.max(tieMax, Math.floor(34 * (1 - Math.exp(-t / 1.25)) + wob(12)));
      out.push({
        tick: tk, day: Math.floor(tk / DAY) + 1, models,
        world: {
          recipes_known: rkMax, firsts: firstMax,
          structures: stMax, camps: Math.min(3, Math.floor(t / 1.1)),
          inventions: Math.floor(t * 0.9), ties: tieMax,
        },
      });
    }
    return out;
  }

  /* ---------------------------------------------------------------- society */
  const ties = new Map();               // 'a|b' (sorted ids) -> {a, b, talk, gift, teach}
  function tie(a, b) {
    const [x, y] = a.id < b.id ? [a, b] : [b, a];
    const k = x.id + '|' + y.id;
    let t = ties.get(k);
    if (!t) { t = { a: x.id, b: y.id, talk: 0, gift: 0, teach: 0 }; ties.set(k, t); }
    return t;
  }
  // a little history so the graph has shape from the start
  for (let i = 0; i < 26; i++) {
    const a = cres[randint(0, 9)], b = cres[randint(0, 9)];
    if (a === b) continue;
    const t = tie(a, b);
    t.talk += randint(1, 9);
    if (chance(0.3)) t.gift += randint(1, 3);
    if (chance(0.15)) t.teach += 1;
  }
  function societyMsg() {
    const edges = [...ties.values()].map((t) => ({ ...t, weight: t.talk + 2 * t.gift + 3 * t.teach }));
    const deg = new Map();
    for (const e of edges) { deg.set(e.a, (deg.get(e.a) || 0) + e.weight); deg.set(e.b, (deg.get(e.b) || 0) + e.weight); }
    const hubs = [...deg.entries()].sort((x, y) => y[1] - x[1]).slice(0, 3).map(([id, w]) => ({ id, name: byId.get(id).name, weight: w }));
    return {
      nodes: cres.map((c) => ({ id: c.id, name: c.name, model: c.model, color: c.color, asleep: c.asleep, drive: c.persona.drive })),
      edges, hubs, loners: cres.filter((c) => !deg.has(c.id)).map((c) => c.name),
    };
  }


  /* ----------------------------------------------------------------- clock */
  let tick = START_TICK;
  let weather = params.get('weather') === 'rain' ? 'rain' : 'clear';
  function clock() {
    const f = (tick % DAY) / DAY;
    let phase, light;
    if (f < 0.08) { phase = 'dawn'; light = 0.2 + 0.8 * (f / 0.08); }
    else if (f < 0.55) { phase = 'day'; light = 1; }
    else if (f < 0.65) { phase = 'dusk'; light = 1 - 0.8 * ((f - 0.55) / 0.1); }
    else { phase = 'night'; light = 0.2; }
    return { day: Math.floor(tick / DAY) + 1, phase, light: Math.round(light * 1000) / 1000, weather };
  }

  /* --------------------------------------------------------------- metrics */
  const metrics = {};
  for (const m of MODELS) {
    metrics[m.tag] = {
      thinks: 0, act_ok: 0, act_fail: 0, parse_failures: 0, avg_latency_ms: 0, tokens_in: 0, tokens_out: 0,
      speech: 0, discoveries: 0, inventions: 0, crafted: 0, unique_items: 4, loops: 0, _lat: [],
    };
  }
  const LAT = { 'qwen3.5-9b': [1800, 4200], 'qwen3.5-4b': [900, 2400], 'gemma-4-e4b': [1100, 2900] };
  const discoveries = [
    { item: 'stone_knife', by: 'c3', tick: Math.max(1, START_TICK - 190) },
    { item: 'inv_sun_totem', by: 'c5', tick: Math.max(1, START_TICK - 60), invented: true },
  ];
  metrics['qwen3.5-9b'].inventions = 1;
  metrics['qwen3.5-9b'].discoveries = 1;
  const thinkTicks = [];

  /* --------------------------------------------------------------- helpers */
  const DIRS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest'];
  function direction(dx, dy) {
    if (!dx && !dy) return 'here';
    const a = Math.atan2(dx, -dy);
    return DIRS[(Math.round(a / (Math.PI / 4)) + 8) % 8];
  }
  const plural = (n, w) => (n === 1 ? `a ${w}` : `${n} ${w.endsWith('s') ? w : w + 's'}`);
  const KIND_WORD = {
    tree: 'tree', pine: 'pine', stump: 'stump', bush: 'berry bush', bush_empty: 'bare bush', rock: 'rock',
    copper_vein: 'orange-streaked rock', iron_vein: 'dark-streaked rock', clay: 'clay bank', campfire: 'campfire',
    workbench: 'workbench', furnace: 'furnace', wall: 'wall', sign: 'sign', chest: 'chest', terminal: 'terminal',
    tablet: 'stone tablet', pile: 'pile of things', crop: 'wheat plant', sapling: 'sapling', millstone: 'millstone',
    bed: 'bed', door: 'door', chicken: 'chicken', sheep: 'sheep', cow: 'cow', creation: 'carved creation', basket: 'woven basket',
  };
  const TILE_WORD = { g: 'grass', d: 'bare dirt', s: 'sand', w: 'shallow water', W: 'deep water', r: 'rocky ground', f: 'the forest floor' };

  function bfs(c, goal) {
    // path to any walkable tile adjacent (Chebyshev 1) to goal
    const key = (x, y) => y * W + x;
    const prev = new Map([[key(c.x, c.y), -1]]);
    const q = [[c.x, c.y]];
    let found = null, n = 0;
    while (q.length && n < 900) {
      const [x, y] = q.shift(); n++;
      if (cheb(x, y, goal.x, goal.y) <= 1 && !(x === goal.x && y === goal.y)) { found = [x, y]; break; }
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]]) {
        const nx = x + dx, ny = y + dy, k = key(nx, ny);
        if (prev.has(k) || !walkable(nx, ny)) continue;
        prev.set(k, key(x, y));
        q.push([nx, ny]);
      }
    }
    if (!found) return null;
    const path = [];
    let k = key(found[0], found[1]);
    while (k !== -1 && k !== key(c.x, c.y)) { path.unshift([k % W, Math.floor(k / W)]); k = prev.get(k); }
    return path;
  }

  function nearest(c, kinds, maxD) {
    let best = null, bd = Infinity;
    for (const o of objects.values()) {
      if (!kinds.includes(o.kind)) continue;
      const d = cheb(c.x, c.y, o.x, o.y);
      if (d < bd && d <= maxD) { bd = d; best = o; }
    }
    return best;
  }

  function invText(inv) {
    const parts = Object.entries(inv).filter(([, n]) => n > 0).map(([k, n]) => plural(n, ITEMS[k] || k));
    if (!parts.length) return 'You carry nothing.';
    return 'You carry ' + (parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]) + '.';
  }

  function remember(c, text) {
    c.memory.push(`[t${tick}] ${text}`);
    if (c.memory.length > 12) c.memory.shift();
  }

  /* ---------------------------------------------------------------- events */
  let pendingEvents = [];
  const upserts = new Map();
  const removed = [];
  function emitEvent(kind, c, text, x, y) {
    pendingEvents.push({ tick, kind, actor: c ? c.id : null, x: x != null ? x : c ? c.x : 0, y: y != null ? y : c ? c.y : 0, text });
  }
  function say(c, line) {
    c.say = line;
    c.sayUntil = tick + 8;
    c.stats.words_spoken += line.split(/\s+/).length;
    metrics[c.model].speech++;
    emitEvent('say', c, line);
    for (const o of cres) {
      if (o === c || cheb(o.x, o.y, c.x, c.y) > 5) continue;
      tie(c, o).talk++;
      o.heard.push(`${c.name} said: “${line}”`);
      if (o.heard.length > 3) o.heard.shift();
      o.people[c.name] = o.people[c.name] || pick(['talks a lot', 'shared a tip about berries', 'seems friendly', 'knows the hills', 'works by the fire']);
      remember(o, `${c.name} said: “${line.slice(0, 80)}${line.length > 80 ? '…' : ''}”`);
    }
  }

  function intention(c, action, target, extra) {
    c.lastIntention = Object.assign({ thought: c.lastThought, action, target: target || '', items: [], text: '', count: 1, goal: c.goal }, extra || {});
  }

  function finishThink(c) {
    c.thinking = false;
    c.stats.thinks++;
    const m = metrics[c.model];
    m.thinks++;
    const [lo, hi] = LAT[c.model];
    m._lat.push(randint(lo, hi));
    if (m._lat.length > 40) m._lat.shift();
    m.avg_latency_ms = Math.round(m._lat.reduce((a, b) => a + b, 0) / m._lat.length);
    m.tokens_in += randint(1400, 2300);
    m.tokens_out += randint(40, 120);
    thinkTicks.push(tick);
    if (chance(0.02)) { m.parse_failures++; c.lastResult = 'You hesitate, unsure what to do.'; return; }

    const ph = clock().phase;
    const hungry = c.satiety < 40;
    const r = rnd();
    if (hungry && (c.inv.berries || 0) > 0) {
      c.lastThought = 'My stomach is growling. I have berries.';
      intention(c, 'eat', 'berries');
      c.inv.berries--;
      c.satiety = Math.min(100, c.satiety + 12);
      c.lastResult = 'You eat the berries. You feel less hungry.';
      emitEvent('eat', c, `${c.name} ate some berries.`);
      m.act_ok++; c.stats.acts_ok++;
      return;
    }
    if (c.energy < 25) {
      c.lastThought = 'I am exhausted. I need to lie down.';
      intention(c, 'rest', '', { count: 3 });
      c.asleep = true;
      c.activity = null;
      c.lastResult = 'You lie down and close your eyes.';
      emitEvent('sleep', c, `${c.name} lay down to sleep.`);
      return;
    }
    if (ph === 'night' && chance(0.5) && cheb(c.x, c.y, camp.x, camp.y) > 2) {
      c.goal = 'Stay near the fire tonight';
      c.lastThought = 'It is dark. I can barely see. The fire is warm and bright.';
      intention(c, 'walk_to', 'campfire');
      startWalk(c, camp, 'walk_to campfire', null);
      return;
    }
    if (r < 0.2) {
      c.lastThought = pick(['I should tell the others what I found.', 'Maybe someone knows a recipe.', 'I wonder who is nearby.']);
      const line = pick(LINES);
      intention(c, 'say', '', { text: line });
      say(c, line);
      c.lastResult = 'You speak. Those nearby can hear you.';
      m.act_ok++; c.stats.acts_ok++;
      return;
    }
    if (r < 0.62) {
      const want = pick([['bush'], ['tree', 'pine'], ['rock'], ['bush', 'tree']]);
      const tgt = nearest(c, want, 14);
      if (!tgt) {
        c.lastThought = 'Nothing useful in sight. I should look around.';
        intention(c, 'gather', want[0]);
        c.lastResult = `You don't see any ${KIND_WORD[want[0]]} nearby.`;
        emitEvent('fail', c, `${c.name} looked for a ${KIND_WORD[want[0]]} but saw none.`);
        m.act_fail++; c.stats.acts_failed++;
        return;
      }
      c.goal = c.goal || pick(['Gather enough to make an axe', 'Keep the camp stocked', 'Find out what clay is for', 'Learn a new recipe']);
      c.lastThought = pick([`There is a ${KIND_WORD[tgt.kind]} close by. I could use what it gives.`, 'Gathering now will help later.', `I'll get what I can from that ${KIND_WORD[tgt.kind]}.`]);
      intention(c, 'gather', KIND_WORD[tgt.kind], { count: randint(1, 3) });
      startWalk(c, tgt, `gather ${tgt.kind}`, 'gather');
      return;
    }
    if (r < 0.78) {
      const dir = pick(DIRS);
      c.lastThought = `I haven't been ${dir} yet.`;
      intention(c, 'explore', dir);
      const [dx, dy] = { north: [0, -1], northeast: [1, -1], east: [1, 0], southeast: [1, 1], south: [0, 1], southwest: [-1, 1], west: [-1, 0], northwest: [-1, -1] }[dir];
      const goal = { x: Math.max(1, Math.min(W - 2, c.x + dx * 8)), y: Math.max(1, Math.min(H - 2, c.y + dy * 8)) };
      startWalk(c, goal, 'explore ' + dir, null);
      return;
    }
    if (r < 0.9) {
      // try combining things
      const tryItems = pick([['stick', 'stone', 'rope'], ['berries'], ['clay'], ['stick', 'flint'], ['log'], ['stone', 'berries']]);
      c.lastThought = `What happens if I put ${tryItems.map((k) => ITEMS[k]).join(' and ')} together?`;
      intention(c, 'combine', '', { items: tryItems.map((k) => ITEMS[k]) });
      const undiscovered = DISCOVERABLE.filter((k) => !discoveries.some((d) => d.item === k));
      if (undiscovered.length && chance(0.3)) {
        const item = undiscovered[0];
        discoveries.push({ item, by: c.id, tick });
        c.known.push(item);
        c.inv[item] = (c.inv[item] || 0) + 1;
        m.discoveries++; m.crafted++; m.unique_items++; c.stats.discoveries++;
        c.lastResult = `You made ${ITEMS[item]}! You will remember how.`;
        emitEvent('discover', c, `${c.name} discovered how to make ${ITEMS[item]}!`);
        remember(c, `I discovered how to make ${ITEMS[item]}.`);
        if (item === 'wooden_wall' || item === 'chest' || item === 'sign') placeNear(c, item === 'wooden_wall' ? 'wall' : item);
      } else if (c.known.length > 2 && chance(0.5)) {
        const item = pick(c.known.filter((k) => k !== 'campfire'));
        c.inv[item] = (c.inv[item] || 0) + 1;
        m.crafted++;
        c.lastResult = `You craft ${ITEMS[item]}.`;
        emitEvent('craft', c, `${c.name} crafted ${ITEMS[item]}.`);
      } else {
        c.lastResult = pick(['Nothing happens. Those things don’t go together.', 'You need a lit campfire nearby for that.', 'You don’t have enough of those.']);
        emitEvent('fail', c, `${c.name} tried to combine ${tryItems.map((k) => ITEMS[k]).join(' + ')}: ${c.lastResult}`);
        m.act_fail++; c.stats.acts_failed++;
        if (chance(0.2)) m.loops++;
      }
      return;
    }
    if (r < 0.93 && chance(0.5)) {
      // plant wheat on a free tile next to the creature
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const x = c.x + dx, y = c.y + dy;
        if (!free(x, y) || isWater(grid[y][x])) continue;
        const crop = chance(0.5) ? 'wheat' : 'carrot';
        const o = addObj('crop', x, y, { label: crop, crop, stage: 0 });
        field.push(o);
        upserts.set(o.id, o);
        const n = randint(1, 3);
        c.lastThought = `Seeds grow into ${crop} if I give them time.`;
        intention(c, 'plant', `${crop} seeds`, { count: n });
        c.lastResult = `You plant ${n} ${crop} seed${n > 1 ? 's' : ''}.`;
        c.inv[crop + '_seeds'] = Math.max(0, (c.inv[crop + '_seeds'] || 0) - n);
        emitEvent('plant', c, `${c.name} planted ${n} ${crop} seed${n > 1 ? 's' : ''}.`, x, y);
        m.act_ok++; c.stats.acts_ok++;
        return;
      }
    }
    if (r < 0.95 && terminals.length) {
      const t = nearest(c, ['terminal', 'sign'], 10);
      if (t) {
        const verb = t.kind === 'terminal' ? 'program' : 'write';
        const text = verb === 'program' ? 'for _,t in ipairs(scan(5)) do print(t.kind) end' : pick(['Berries east of camp.', 'Flint in the grey hills.', 'Meet at the fire at dusk.']);
        c.lastThought = verb === 'program' ? 'The tablet said terminals run Lua. Let me try.' : 'I should leave a note for the others.';
        intention(c, verb, KIND_WORD[t.kind], { text });
        startWalk(c, t, verb + ' ' + t.kind, verb, text);
        return;
      }
    }
    c.lastThought = 'I will rest a moment and watch.';
    intention(c, 'wait', '');
    c.lastResult = 'You wait.';
    c.nextThink = tick + randint(6, 20);
  }

  function startWalk(c, goal, activity, then, text) {
    const path = bfs(c, goal);
    if (!path) {
      c.lastResult = 'You can’t find a way there.';
      emitEvent('fail', c, `${c.name} couldn't find a way to the ${KIND_WORD[goal.kind] || 'spot'}.`);
      metrics[c.model].act_fail++; c.stats.acts_failed++;
      c.nextThink = tick + randint(4, 10);
      return;
    }
    c.path = path;
    c.job = { goal, then, text };
    c.activity = activity;
    c.lastResult = path.length ? `You set off (${path.length} steps).` : 'You are already there.';
  }

  function placeNear(c, kind) {
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1]]) {
      const x = c.x + dx, y = c.y + dy;
      if (free(x, y)) {
        const o = addObj(kind, x, y, kind === 'sign' ? { label: c.name + '’s sign', text: '' } : {});
        upserts.set(o.id, o);
        emitEvent('place', c, `${c.name} placed a ${KIND_WORD[kind] || kind}.`, x, y);
        return;
      }
    }
  }

  function arrive(c) {
    const job = c.job;
    c.job = null;
    c.path = null;
    c.activity = null;
    const m = metrics[c.model];
    if (!job || !job.then) { c.lastResult = 'You arrive.'; c.nextThink = tick + randint(2, 8); return; }
    const o = job.goal;
    if (job.then === 'gather') {
      if (!objects.has(o.id)) { c.lastResult = 'It is gone.'; return; }
      let item, n = randint(1, 2), msg;
      if (o.kind === 'bush') {
        item = 'berries'; n = randint(2, 4);
        removeObj(o);
        const e = addObj('bush_empty', o.x, o.y);
        upserts.set(e.id, e);
        removed.push(o.id);
        regrow.push({ at: tick + randint(120, 300), id: e.id });
        msg = `${c.name} picked ${n} berries.`;
      } else if (o.kind === 'tree' || o.kind === 'pine') {
        item = 'stick'; msg = `${c.name} gathered ${plural(n, 'stick')} from a ${o.kind}.`;
      } else if (o.kind === 'rock') {
        item = 'stone'; msg = `${c.name} gathered ${plural(n, 'stone')}.`;
        if (chance(0.25)) { c.inv.flint = (c.inv.flint || 0) + 1; msg += ' And a piece of flint!'; }
      } else {
        c.lastResult = 'You need a pickaxe for that.';
        emitEvent('fail', c, `${c.name} tried to gather from the ${KIND_WORD[o.kind]} but has no pickaxe.`, o.x, o.y);
        m.act_fail++; c.stats.acts_failed++;
        return;
      }
      c.inv[item] = (c.inv[item] || 0) + n;
      c.holding = item;
      c.lastResult = msg.replace(c.name, 'You').replace('gathered', 'gather').replace('picked', 'pick');
      emitEvent('gather', c, msg, o.x, o.y);
      remember(c, msg.replace(c.name, 'I'));
      m.act_ok++; c.stats.acts_ok++;
    } else if (job.then === 'write') {
      o.text = job.text;
      upserts.set(o.id, o);
      c.lastResult = `You write on the sign: “${job.text}”`;
      emitEvent('write', c, `${c.name} wrote on the sign: “${job.text}”`, o.x, o.y);
      m.act_ok++; c.stats.acts_ok++;
    } else if (job.then === 'program') {
      o.text = job.text;
      upserts.set(o.id, o);
      c.lastResult = 'The terminal accepts your program. Its screen flickers.';
      emitEvent('program', c, `${c.name} programmed the terminal.`, o.x, o.y);
      m.act_ok++; c.stats.acts_ok++;
    }
    c.nextThink = tick + randint(2, 8);
  }

  const regrow = [];

  /* ------------------------------------------------------------- inventions */
  const inventionList = [
    { id: 'inv_sun_totem', name: 'sun totem', desc: 'A carved post that catches the morning light.', inputs: { log: 2, copper_ore: 1, rope: 1 },
      tool: false, food: 0, placeable: true, depth: 1, by: 'Suri', model: 'qwen3.5-9b', tick: Math.max(1, START_TICK - 60) },
    { id: 'inv_stone_hammer', name: 'stone hammer', desc: 'A heavy hammer for smashing roots.', inputs: { stone_knife: 2, flint: 2, stone: 2 },
      tool: true, food: 0, placeable: false, depth: 1, by: 'Ivo', model: 'qwen3.5-9b', tick: Math.max(1, START_TICK - 30) },
    { id: 'inv_berry_cake', name: 'berry cake', desc: 'A sweet cake to eat.', inputs: { berries: 2, wheat: 1 },
      tool: false, food: 30, placeable: false, depth: 1, by: 'Tam', model: 'qwen3.5-9b', tick: START_TICK + 6 },
    { id: 'inv_honey_bread', name: 'honey bread', desc: 'Bread baked around a slice of berry cake.', inputs: { inv_berry_cake: 1, flour: 1 },
      tool: false, food: 45, placeable: false, depth: 2, by: 'Tam', model: 'qwen3.5-9b', tick: START_TICK + 6 },
  ];

  /* -------------------------------------------------------------- chronicle */
  const chapters = [
    { tick: Math.max(1, START_TICK - 380), day: 1, phase: 'dawn',
      text: 'The first light found twelve strangers in a meadow, a cold fire pit between them and no memory of how they came to be there. ' +
        'Tam was the first to speak. He asked whether anyone knew what the grey stones were for, and nobody did.\n\n' +
        'By the time the dew burned off, Mara had worked out that the low bushes gave berries, and the news travelled fast.' },
    { tick: Math.max(2, START_TICK - 120), day: 1, phase: 'day',
      text: 'Ivo spent the morning turning a flint over in his hands until it occurred to him to bind it to a stick. ' +
        'The stone knife he made was crude, but it was the first thing anyone had made on purpose, and the others gathered to look.\n\n' +
        'Near noon, Pell scratched directions onto a wooden sign by the fire: berries east, flint in the hills.' },
  ];
  const LATER = [
    'Toward evening the meadow grew busy. Lia and Juno carried sticks to the fire while Bex pressed wheat seeds into a strip of bare dirt, ' +
    'not entirely sure what would come of it. Odo wandered off to the humming terminal by the water and came back quiet, ' +
    'saying only that the machine had answered him.',
    'Night settled over the camp. Most of them slept close to the fire; Rook kept watch and talked to himself about rope.',
  ];
  function carvedEvent() {
    const o = [...objects.values()].find((x) => x.text && (x.kind === 'tree' || x.kind === 'pine'));
    if (!o) return false;
    pendingEvents.push({ tick, kind: 'write', actor: 'c1', x: o.x, y: o.y, text: `Tam carved words into a ${o.kind === 'pine' ? 'pine' : 'oak tree'}: "${o.text}"` });
    return true;
  }

  function writeChapter() {
    const text = LATER[(chapters.length - 2) % LATER.length];
    const cl = clock();
    chapters.push({ tick, day: cl.day, phase: cl.phase, text });
    pendingEvents.push({ tick, kind: 'chronicle', actor: null, x: CX, y: CY, text: `Chronicle, day ${cl.day}: ${text}` });
  }

  /* ------------------------------------------------------------------ tick */
  function cre(c) {
    return {
      id: c.id, name: c.name, x: c.x, y: c.y, model: c.model, color: c.color,
      activity: c.activity, thinking: c.thinking, asleep: c.asleep, say: c.say,
      satiety: Math.round(c.satiety * 10) / 10, energy: Math.round(c.energy * 10) / 10,
      health: Math.round(c.health * 10) / 10, holding: c.holding,
    };
  }

  function step() {
    tick++;
    const ph = clock().phase;
    for (const c of cres) {
      if (tick % 16 === 0) c.satiety = Math.max(0, c.satiety - 1);
      if (tick % 40 === 0 && !c.asleep) c.energy = Math.max(0, c.energy - 1);
      if (c.say && tick >= c.sayUntil) c.say = null;

      if (c.asleep) {
        c.energy = Math.min(100, c.energy + 0.4);
        if ((c.energy > 90 && chance(0.02)) || chance(0.0008)) {
          c.asleep = false;
          c.nextThink = tick + 2;
          emitEvent('join', c, `${c.name} woke up; a ${c.model} brain is thinking for them.`);
        }
        continue;
      }
      // the sickly one slowly fades, collapses, then respawns
      if (c.health < 30 && tick % 6 === 0) c.health = Math.max(0, c.health - 1);
      if (c.health <= 0) {
        emitEvent('collapse', c, `${c.name} collapsed from weakness and dropped everything.`);
        const p = addObj('pile', c.x, c.y, { label: `${c.name}’s things` });
        upserts.set(p.id, p);
        const [x, y] = spawnPoint();
        c.x = x; c.y = y; c.health = 60; c.satiety = 50; c.inv = {}; c.path = null; c.job = null; c.activity = null; c.holding = null;
        remember(c, 'Everything went dark. I woke up in the meadow with nothing.');
        continue;
      }
      if (c.thinking) {
        if (tick >= c.thinkUntil) finishThink(c);
        continue;
      }
      if (c.path) {
        if (!c.path.length) { arrive(c); continue; }
        const [nx, ny] = c.path[0];
        const occupied = cres.some((o) => o !== c && o.x === nx && o.y === ny);
        if (occupied && (c.blocked = (c.blocked || 0) + 1) < 4) continue;
        c.blocked = 0;
        if (walkable(nx, ny)) { c.x = nx; c.y = ny; c.path.shift(); }
        else { c.path = null; c.job = null; c.activity = null; c.lastResult = 'Something is in your way.'; }
        if (c.path && !c.path.length) arrive(c);
        continue;
      }
      if (tick >= c.nextThink) {
        c.thinking = true;
        c.thinkUntil = tick + randint(3, 10);
        c.nextThink = tick + randint(10, 30);
      }
    }
    // night: tired creatures may doze off
    if (ph === 'night' && chance(0.004)) {
      const c = pick(cres.filter((x) => !x.asleep && !x.thinking));
      if (c) { c.asleep = true; c.path = null; c.activity = null; emitEvent('sleep', c, `${c.name} dozed off by the fire.`); }
    }
    // animals wander one tile at a time; now and then someone tames one
    for (const a of animals) {
      if (!chance(a.kind === 'cow' ? 0.12 : 0.25)) continue;
      const [dx, dy] = pick([[1, 0], [-1, 0], [0, 1], [0, -1]]);
      const x = a.x + dx, y = a.y + dy;
      if (!free(x, y) || cheb(x, y, CX, CY) > 10 || cres.some((c) => c.x === x && c.y === y)) continue;
      objAt.delete(a.x + ',' + a.y);
      a.x = x; a.y = y;
      objAt.set(x + ',' + y, a);
      upserts.set(a.id, a);
    }
    if (chance(0.01)) {
      const a = pick(animals.filter((o) => !o.tamed_by));
      const c = a && cres.find((o) => !o.asleep && cheb(o.x, o.y, a.x, a.y) <= 3);
      if (c) { a.tamed_by = c.name; upserts.set(a.id, a); emitEvent('tame', c, `${c.name} tamed a ${a.kind}!`, a.x, a.y); }
    }
    if (chance(0.03)) {
      const a = pick(cres.filter((x) => !x.asleep));
      const b = a && cres.find((x) => x !== a && !x.asleep && cheb(x.x, x.y, a.x, a.y) <= 4);
      if (a && b) {
        const t = tie(a, b);
        if (chance(0.5)) {
          t.teach++;
          const what = pick(['stone knife', 'rope', 'campfire', 'stone axe']);
          const how = pick(['watching', 'listening to', 'reading the sign by']);
          emitEvent('learn', b, `${b.name} learned to make ${what} by ${how} ${a.name}.`);
        } else {
          t.gift++;
          emitEvent('craft', a, `${a.name} gave ${b.name} some berries.`);
        }
      }
    }
    if (tick === START_TICK + 12) carvedEvent();
    // the shared basket and the fire need looking after
    if (chance(0.025)) {
      const c = pick(cres.filter((x) => !x.asleep));
      if (c) {
        const r = rnd();
        if (r < 0.4) {
          const n = randint(1, 4); store.berries = (store.berries || 0) + n; c.stats.stored += n;
          emitEvent('store', c, `${c.name} stored ${n} berries in the basket.`, basket.x, basket.y);
        } else if (r < 0.7 && (store.berries || 0) > 0) {
          const n = Math.min(store.berries, randint(1, 3)); store.berries -= n; c.stats.took_from_store += n;
          emitEvent('take', c, `${c.name} took ${n} berr${n === 1 ? 'y' : 'ies'} from the basket.`, basket.x, basket.y);
        } else {
          c.stats.tended_fire++;
          emitEvent('tend', c, `${c.name} fed the campfire with ${plural(randint(1, 2), 'stick')}.`, camp.x, camp.y);
        }
        const parts = Object.entries(store).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}`);
        basket.text = parts.length ? parts.join(', ') : 'empty';
        upserts.set(basket.id, basket);
      }
    }
    if ((tick - START_TICK) % 130 === 0) {
      weather = weather === 'rain' ? 'clear' : 'rain';
      pendingEvents.push({ tick, kind: 'weather', actor: null, x: CX, y: CY,
        text: weather === 'rain' ? 'Clouds gather, and rain begins to fall.' : 'The rain stops and the clouds drift apart.' });
    }
    if (tick === START_TICK + 18) {
      const [teacher, pupil] = [cres[2], cres[1]];
      tie(teacher, pupil).teach++;
      emitEvent('learn', pupil, `${pupil.name} learned to make stone knife by watching ${teacher.name}.`);
    }
    if (tick % 40 === 0) {
      const o = field.length ? pick(field) : null;
      if (o && objects.has(o.id) && o.stage < 2) { o.stage++; upserts.set(o.id, o); }
    }
    if (tick === START_TICK + 50 || (tick - START_TICK) % 600 === 0) writeChapter();
    if (tick === START_TICK + 6) {
      const c = cres[0];
      c.inv.inv_berry_cake = 1;
      c.inv.inv_honey_bread = 2;
      c.inv.inv_stone_hammer = 1;
      c.invented = ['berries + wheat -> berry cake'];
      discoveries.push({ item: 'inv_berry_cake', by: c.id, tick, invented: true });
      metrics[c.model].inventions++;
      pendingEvents.push({ tick, kind: 'invent', actor: c.id, x: c.x, y: c.y,
        text: `${c.name} invented the berry cake! “A sweet cake to eat.” (berries + wheat -> berry cake (near a campfire))` });
    }
    for (let i = regrow.length - 1; i >= 0; i--) {
      if (tick < regrow[i].at) continue;
      const e = objects.get(regrow[i].id);
      regrow.splice(i, 1);
      if (!e) continue;
      removeObj(e);
      removed.push(e.id);
      const b = addObj('bush', e.x, e.y);
      upserts.set(b.id, b);
    }

    const msg = {
      type: 'tick', tick, clock: clock(), creatures: cres.map(cre),
      objects_upsert: [...upserts.values()].filter((o) => objects.has(o.id)), objects_removed: removed.splice(0),
      events: pendingEvents,
      landmarks: tick % 30 === 0 ? landmarks : null,
    };
    upserts.clear();
    pendingEvents = [];
    return msg;
  }

  function initMsg() {
    return {
      type: 'init', width: W, height: H, tiles: grid.map((r) => r.join('')), objects: [...objects.values()], creatures: cres.map(cre),
      tick, clock: clock(), items: ITEMS, landmarks,
    };
  }

  function metricsMsg() {
    const models = {};
    for (const [tag, m] of Object.entries(metrics)) {
      const { _lat, ...pub } = m;
      models[tag] = Object.assign({ creatures: cres.filter((c) => c.model === tag).length }, pub);
    }
    while (thinkTicks.length && thinkTicks[0] < tick - 120) thinkTicks.shift();
    const span = Math.min(120, Math.max(1, tick - START_TICK));
    return { type: 'metrics', models, discoveries: discoveries.slice(), thinks_per_min: Math.round((thinkTicks.length / span) * 120 * 10) / 10 };
  }

  /* ------------------------------------------------------------ perception */
  function perceive(c) {
    const cl = clock();
    const lines = [];
    const timeWords = { dawn: 'It is dawn; the sky is turning pale.', day: 'It is day; the light is clear.', dusk: 'It is dusk; long shadows stretch across the ground.', night: 'It is night; you can see only a few steps.' };
    lines.push(`Day ${cl.day}. ${timeWords[cl.phase]}`);
    const under = objAt.get(c.x + ',' + c.y);
    lines.push(`You stand on ${TILE_WORD[tileAt(c.x, c.y)]}${under ? `, next to a ${KIND_WORD[under.kind]}` : ''}.`);
    const sight = cl.phase === 'night' ? (cheb(c.x, c.y, camp.x, camp.y) <= 3 ? 5 : 2) : 6;
    const groups = new Map();
    for (const o of objects.values()) {
      const d = cheb(c.x, c.y, o.x, o.y);
      if (d > sight || d === 0) continue;
      const k = KIND_WORD[o.kind] || o.kind;
      const g = groups.get(k);
      if (!g) groups.set(k, { n: 1, d, o });
      else { g.n++; if (d < g.d) { g.d = d; g.o = o; } }
    }
    const near = [...groups.entries()].sort((a, b) => a[1].d - b[1].d).slice(0, 8).map(([k, g]) =>
      `${plural(g.n, k)}${g.n > 1 ? ', nearest' : ''} ${g.d} step${g.d === 1 ? '' : 's'} ${direction(g.o.x - c.x, g.o.y - c.y)}${g.o.lit ? ' (burning)' : ''}`);
    lines.push(near.length ? `Nearby: ${near.join('; ')}.` : 'You see nothing useful nearby.');
    const others = cres.filter((o) => o !== c && cheb(c.x, c.y, o.x, o.y) <= sight);
    if (others.length) {
      lines.push(others.slice(0, 4).map((o) => {
        const d = cheb(c.x, c.y, o.x, o.y);
        const where = d === 0 ? 'right beside you' : `${d} step${d === 1 ? '' : 's'} ${direction(o.x - c.x, o.y - c.y)}`;
        return `${o.name} is ${where}${o.asleep ? ', asleep' : ''}, holding ${o.holding ? ITEMS[o.holding] : 'nothing'}.`;
      }).join(' '));
    }
    let far = [];
    if (cl.phase !== 'night') {
      let water = null, hills = null;
      for (let dy = -10; dy <= 10; dy++) for (let dx = -10; dx <= 10; dx++) {
        const t = tileAt(c.x + dx, c.y + dy);
        if (!water && isWater(t) && Math.max(Math.abs(dx), Math.abs(dy)) > 2) water = direction(dx, dy);
        if (!hills && t === 'r' && Math.max(Math.abs(dx), Math.abs(dy)) > 3) hills = direction(dx, dy);
      }
      if (water) far.push(`water to the ${water}`);
      if (hills) far.push(`grey hills to the ${hills}`);
    }
    if (far.length) lines.push(`Further off: ${far.join(', ')}.`);
    if (c.heard.length) lines.push('You hear: ' + c.heard.join(' '));
    lines.push(invText(c.inv));
    const sat = c.satiety > 70 ? 'well fed' : c.satiety > 40 ? 'a little hungry' : c.satiety > 20 ? 'hungry' : 'starving';
    const en = c.energy > 70 ? 'rested' : c.energy > 35 ? 'a bit tired' : 'exhausted';
    const he = c.health > 70 ? 'healthy' : c.health > 35 ? 'sore' : 'weak and unsteady';
    lines.push(`You feel ${sat}, ${en} and ${he}.`);
    if (c.activity) lines.push(`You are busy: ${c.activity.replace(/_/g, ' ')}.`);
    return lines.join('\n');
  }

  function detail(c) {
    const inventory = {};
    for (const [k, n] of Object.entries(c.inv)) if (n > 0) inventory[ITEMS[k] || k] = n;
    return {
      id: c.id, name: c.name, model: c.model, persona: c.persona,
      perception: perceive(c),
      last_thought: c.lastThought || null,
      last_intention: c.lastIntention,
      last_result: c.lastResult || null,
      inventory,
      satiety: Math.round(c.satiety), energy: Math.round(c.energy), health: Math.round(c.health),
      goal: c.goal || '',
      summary: c.summary || (c.stats.thinks > 3
        ? `I am ${c.name}. I live in the meadow around the fire. I have learned that bushes give berries and trees give sticks. ${Object.keys(c.people)[0] ? Object.keys(c.people)[0] + ' talks to me often.' : 'I have not made friends yet.'}`
        : ''),
      known_recipes: c.known.concat(c.invented || []),
      people: Object.entries(c.people).map(([n, note]) => `${n}: ${note}`),
      recent: c.memory.slice(-10),
      stats: Object.assign({}, c.stats),
    };
  }

  /* ---------------------------------------------------------- transports */
  let running = null;
  const sockets = new Set();
  function broadcast(obj) {
    const data = JSON.stringify(obj);
    for (const s of sockets) if (s.readyState === 1 && typeof s.onmessage === 'function') s.onmessage({ data });
  }
  function ensureRunning() {
    if (running) return;
    running = setInterval(() => {
      broadcast(step());
      if (tick % 10 === 0) broadcast(metricsMsg());
    }, TICK_MS);
  }

  function createSocket() {
    const sock = {
      readyState: 0, onopen: null, onmessage: null, onclose: null, onerror: null,
      send() {},
      close() {
        if (sock.readyState === 3) return;
        sock.readyState = 3;
        sockets.delete(sock);
        if (typeof sock.onclose === 'function') sock.onclose({ code: 1000 });
      },
    };
    setTimeout(() => {
      if (sock.readyState !== 0) return;
      sock.readyState = 1;
      sockets.add(sock);
      if (typeof sock.onopen === 'function') sock.onopen({});
      if (typeof sock.onmessage === 'function') {
        sock.onmessage({ data: JSON.stringify(initMsg()) });
        sock.onmessage({ data: JSON.stringify(metricsMsg()) });
      }
      ensureRunning();
    }, 300);
    return sock;
  }

  function api(path) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        const p = String(path).split('?')[0];
        let m;
        if ((m = p.match(/^\/api\/creature\/(.+)$/))) {
          const c = byId.get(decodeURIComponent(m[1]));
          if (!c) return reject(new Error('HTTP 404'));
          return resolve(JSON.parse(JSON.stringify(detail(c))));
        }
        if (p === '/api/metrics') { const x = metricsMsg(); delete x.type; return resolve(x); }
        if (p === '/api/state') { const x = initMsg(); delete x.type; return resolve(x); }
        if (p === '/api/chronicle') return resolve(JSON.parse(JSON.stringify(chapters)));
        if (p === '/api/society') return resolve(JSON.parse(JSON.stringify(societyMsg())));
        if (p === '/api/history') return resolve(historyList());
        if (p === '/api/inventions') return resolve(JSON.parse(JSON.stringify(inventionList.filter((x) => x.tick <= tick))));
        reject(new Error('HTTP 404'));
      }, 40 + Math.random() * 80);
    });
  }

  /** POST /api/voice: a voice from the sky, heard by every awake creature or those near a spot. */
  function post(path, body) {
    return new Promise((resolve, reject) => {
      setTimeout(() => {
        if (String(path).split('?')[0] !== '/api/voice') return reject(Object.assign(new Error('HTTP 404'), { status: 404 }));
        const text = String((body && body.text) || '').trim().slice(0, 300);
        if (!text) return reject(Object.assign(new Error('HTTP 400'), { status: 400 }));
        const near = body && Number.isFinite(body.x) && Number.isFinite(body.y);
        const r = near && Number.isFinite(body.radius) ? body.radius : 6;
        const heard = cres.filter((c) => !c.asleep && (!near || cheb(c.x, c.y, body.x, body.y) <= r));
        for (const c of heard) {
          c.heard.push(`A voice from the sky: “${text}”`);
          if (c.heard.length > 3) c.heard.shift();
          remember(c, `A voice from the sky said: “${text}”`);
        }
        pendingEvents.push({ tick, kind: 'voice', actor: null, x: near ? body.x : CX, y: near ? body.y : CY, text: `A voice from the sky: "${text}"` });
        resolve({ ok: true, heard_by: heard.map((c) => c.name) });
      }, 120);
    });
  }

  window.SwarmDemo = { createSocket, api, post };
})();
