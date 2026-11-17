// Kit.scene3d: Three.js ile 3D sahne; Kit.scene (2D) ile aynı arayüzü sunar, bu yüzden theme.json eylemleri,
// HUD, efektler (Kit.fx üstteki 2D katmanda çizer), isim etiketleri, sohbet balonları ortak kullanılır.
// scene.json "renderer": "3d" ile açılır; temanın index.html'inde "three" için importmap gerekir ve bu dosya yüklenir
// scene.js'den sonra yüklenir.
//
// scene.json (birim metre; x yana, y yukarı, z kameraya doğru, sahne negatif z'de):
//   "camera": { "position": [0, 7, 15], "target": [0, 1.2, -1], "fov": 38 }
//   "world": "assets/3d/stage.glb", "worldScale": 1     hazır sahne (isteğe bağlı); yoksa düz zemin çizilir
//   "background": "#14121c" veya "assets/bg.jpg", "fog": { "color": "#14121c", "near": 18, "far": 45 }
//   "lights": { "ambient": 0.8, "sun": { "intensity": 1.6, "position": [6, 12, 8], "shadows": false },
//               "points": [{ "at": [0, 3, -4], "color": "#ff8a5c", "intensity": 30, "distance": 12 }] }
//   "floor": { "x": [-6, 6], "z": [-1, 7], "color": "#2a2633" }   kalabalığın duracağı alan
//   "aisle": { "x": 0, "half": 0.7 }, "spacing": 1.1, "fill": { "rows": 1 }
//   "seats": [[-2, -2], [2, -2]], "points": { "stage": [0, -3], "entry": [0, 12], "focus": [0, 2.5, -4] }
//   "bloom": { "strength": 0.6, "radius": 0.4, "threshold": 0.85 }, "maxAnimated": 120, "fps": 30
//   "facing": "focus" (hareketsizken focus / stage noktasına bakar, varsayılan) veya "camera" (izleyiciye döner)
//   Noktalar [x, z] (zeminde) veya [x, y, z] yazılır.
// theme.json "characters" (3D): { "id": "guest", "model": "assets/3d/guest.glb", "height": 1.7,
//   "clips": { "idle": "Idle", "walk": "Walk", "cheer": "Cheer", "dance": "Dance", "wave": "Wave" } }
//   "pose" / "play" "clips" içindeki adları kullanır; yoksa adı eşleşen klip aranır (büyük/küçük harf fark etmez).
//   "animations": { "bow": { "clip": "Bow", "ms": 1600 } } bir oynatmanın süresini belirler.
// Model yoksa yer tutucu insan (gövde + baş) çizilir ve eğilme, zıplama, dans hareketlerini kendisi yapar.
// Hazır sahne (hareketli ışık, lazer, video ekranı) ve 3D efektler: scene.json "stage", "stage" / "fx3d" adımları (bkz. sdk/stage3d.js).
// OBS birleştirme için yeşil arka plan: kontrol panelindeki "Yeşil arka plan" ayarı veya ?chroma; zemin, hazır sahne, sis gizlenir.

(function () {
  const K = window.Kit;
  const W = K.W || 1080, H = K.H || 1920;

  let T = null, loaderGLTF = null, cloneSkinned = null;
  let renderer = null, scene3 = null, camera = null, composer = null, raycaster = null, floorPlane = null;
  let stage = null, backdrop = null, worldObj = null, floorObj = null, fogObj = null, chromaOn = false; // hazır sahne; arka plan, dünya, zemin, sis (yeşil arka planda gizlenir)
  let ready = false, theme = { characters: [], animations: {}, npcs: [], colors: {} }, settings = {}, cfg = {};
  let canvas = null, ctx = null;
  const persons = new Map(), npcs = new Map(), fillers = new Map();
  let slots = [], seats = [], chars = [], anims = {};
  const cam = { queue: [], until: 0, cur: null, pos: null, look: null, basePos: null, baseLook: null };
  const emitters = [];
  let labels = null;
  const pending = { users: [], top: null }; // 3D sahne kurulmadan önce gelen izleyiciler / sıralama

  const now = () => performance.now();
  const hash = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const col = (k, d) => theme.colors?.[k] || d;
  const v3 = (a, y0 = 0) => (Array.isArray(a) ? (a.length >= 3 ? { x: a[0], y: a[1], z: a[2] } : { x: a[0], y: y0, z: a[1] }) : { x: a.x ?? 0, y: a.y ?? y0, z: a.z ?? 0 });

  // ---------- Başlatma ----------
  function init(opts) {
    canvas = opts.canvas; ctx = canvas.getContext('2d');
    theme = opts.theme || theme;
    settings = opts.settings || {};
    cfg = theme.scene || {};
    anims = theme.animations || {};
    labels = K.makeLabels({ head: (p) => P.head(p), color: col, maxTags: () => cfg.maxTags ?? 8 });
    const gl = document.createElement('canvas');
    gl.width = W; gl.height = H;
    gl.style.cssText = canvas.style.cssText;
    canvas.parentNode.insertBefore(gl, canvas);
    setup(gl).catch((e) => console.error('[Kit.scene3d] 3D sahne kurulamadı', e));
  }

  async function setup(gl) {
    T = await import('three');
    const [{ GLTFLoader }, SU] = await Promise.all([import('three/addons/loaders/GLTFLoader.js'), import('three/addons/utils/SkeletonUtils.js')]);
    loaderGLTF = new GLTFLoader(); cloneSkinned = SU.clone;
    renderer = new T.WebGLRenderer({ canvas: gl, antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(1);
    renderer.setSize(W, H, false);
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.ACESFilmicToneMapping;
    const sun = cfg.lights?.sun || {};
    renderer.shadowMap.enabled = Boolean(sun.shadows);
    scene3 = new T.Scene();
    raycaster = new T.Raycaster();
    floorPlane = new T.Plane(new T.Vector3(0, 1, 0), 0);

    const c = cfg.camera || {};
    camera = new T.PerspectiveCamera(c.fov ?? 38, W / H, 0.1, 500);
    cam.basePos = new T.Vector3(...(c.position || [0, 7, 15]));
    cam.baseLook = new T.Vector3(...(c.target || [0, 1.2, -1]));
    cam.pos = cam.basePos.clone(); cam.look = cam.baseLook.clone();
    camera.position.copy(cam.pos); camera.lookAt(cam.look);

    // arka plan, sis, ışık
    const bg = cfg.background || '#14121c';
    backdrop = new T.Color(/^#/.test(bg) ? bg : '#000000');
    if (/\.(png|jpe?g|webp)$/i.test(bg)) new T.TextureLoader().load(bg, (tex) => { tex.colorSpace = T.SRGBColorSpace; backdrop = tex; applyChroma(); });
    if (cfg.fog) fogObj = new T.Fog(cfg.fog.color || bg, cfg.fog.near ?? 18, cfg.fog.far ?? 45);
    const L = cfg.lights || {};
    scene3.add(new T.HemisphereLight(0xffffff, 0x404050, L.ambient ?? 0.8));
    const dl = new T.DirectionalLight(sun.color || 0xffffff, sun.intensity ?? 1.6);
    dl.position.set(...(sun.position || [6, 12, 8]));
    if (sun.shadows) { dl.castShadow = true; dl.shadow.mapSize.set(1024, 1024); Object.assign(dl.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, far: 60 }); }
    scene3.add(dl);
    for (const pl of L.points || []) {
      const l = new T.PointLight(pl.color || 0xffffff, pl.intensity ?? 20, pl.distance ?? 12);
      const at = v3(pl.at || [0, 3, 0], 3); l.position.set(at.x, at.y, at.z); scene3.add(l);
    }

    // hazır sahne veya düz zemin
    const fl = cfg.floor || { x: [-6, 6], z: [-1, 7] };
    if (cfg.world) {
      loaderGLTF.load(cfg.world, (g) => {
        g.scene.scale.setScalar(cfg.worldScale ?? 1);
        g.scene.traverse((o) => { if (o.isMesh) { o.receiveShadow = Boolean(sun.shadows); o.castShadow = Boolean(sun.shadows); } });
        worldObj = g.scene; scene3.add(g.scene); applyChroma();
      }, undefined, () => console.warn(`[Kit.scene3d] ${cfg.world} bulunamadı`));
    } else {
      const w = fl.x[1] - fl.x[0] + 16, d = fl.z[1] - fl.z[0] + 24;
      const m = new T.Mesh(new T.PlaneGeometry(w, d), new T.MeshStandardMaterial({ color: fl.color || '#2a2633', roughness: 0.9 }));
      m.rotation.x = -Math.PI / 2; m.position.set((fl.x[0] + fl.x[1]) / 2, 0, (fl.z[0] + fl.z[1]) / 2 - 4);
      m.receiveShadow = Boolean(sun.shadows);
      floorObj = m; scene3.add(m);
    }

    // son işlem: parlama (bloom)
    if (cfg.bloom) {
      const [{ EffectComposer }, { RenderPass }, { UnrealBloomPass }, { OutputPass }] = await Promise.all([
        import('three/addons/postprocessing/EffectComposer.js'), import('three/addons/postprocessing/RenderPass.js'),
        import('three/addons/postprocessing/UnrealBloomPass.js'), import('three/addons/postprocessing/OutputPass.js')]);
      composer = new EffectComposer(renderer);
      composer.setPixelRatio(1); composer.setSize(W, H);
      composer.addPass(new RenderPass(scene3, camera));
      composer.addPass(new UnrealBloomPass(new T.Vector2(W, H), cfg.bloom.strength ?? 0.6, cfg.bloom.radius ?? 0.4, cfg.bloom.threshold ?? 0.85));
      composer.addPass(new OutputPass());
    }

    // hazır sahne: hareketli ışık, lazer, ekran (scene.json "stage") ve 3D efektler
    const { createStage } = await import('/sdk/stage3d.js');
    stage = createStage({ T, scene: scene3, cfg, worldPoint, beat: K.fx.beat });
    applyChroma();

    // karakter: model bir kez yüklenir, her kişi bir kopyadır
    chars = (theme.characters || []).map((ch) => ({ ...ch, ready: false }));
    if (!chars.length) chars = [{ id: 'default', label: 'Kişi', placeholder: true }];
    for (const ch of chars) if (ch.model) loaderGLTF.load(ch.model, (g) => {
      const box = new T.Box3().setFromObject(g.scene);
      ch.unit = (ch.height ?? 1.7) / Math.max(0.01, box.max.y - box.min.y);
      ch.gltf = g; ch.ready = true;
    }, undefined, () => console.warn(`[Kit.scene3d] ${ch.model} bulunamadı, yer tutucu kişi kullanılıyor`));

    seats = (cfg.seats || []).map((s) => ({ ...v3(s), taken: null, vip: true }));
    buildSlots();
    for (const n of theme.npcs || []) addNpc(n);
    setAmbient(settings.ambientFx !== false);
    ready = true;
    for (const [u, o] of pending.users.splice(0)) ensure(u, o);
    if (pending.top) seatTop(pending.top);
  }

  function configure(s) { settings = s || {}; setAmbient(settings.ambientFx !== false); applyChroma(); }

  // OBS'de birleştirmek için yeşil arka plan (chroma key): yalnızca kişiler, ışıklar, efektler düz yeşil üstünde kalır
  function applyChroma() {
    if (!scene3) return;
    const on = chromaOn = settings.chroma === true || new URLSearchParams(location.search).has('chroma');
    stage?.setVisible(!on); // ışık huzmeleri, lazer, ekranlar yeşile eklenip OBS'in arka planı yanlış ayırmasına yol açar
    scene3.background = on ? new T.Color(cfg.chroma || '#00ff00') : backdrop;
    scene3.fog = on ? null : fogObj;
    if (worldObj) worldObj.visible = !on;
    if (floorObj) floorObj.visible = !on;
  }

  // scene.json "emitters" ile sürekli efektler: Kit.fx ile 2D katmanda çizilir, konum her karede yeniden yansıtılır
  function setAmbient(on) {
    if (!ready && !T) return;
    emitters.length = 0;
    (cfg.emitters || []).forEach((e, i) => {
      const id = 'scene3d-emitter-' + i;
      if (!on && !e.always) { K.fx.stop(id); return; }
      const o = { ...e, x: 0, y: 0 };
      K.fx.emitter(id, e.preset || 'smoke', o);
      emitters.push({ o, at: e.at });
    });
  }

  // ---------- Noktalar, koordinat yansıtma ----------
  function worldPoint(name) {
    if (!name) return null;
    if (typeof name === 'object') return name.z !== undefined ? name : Array.isArray(name) ? v3(name) : null;
    const p = cfg.points?.[name];
    return p ? v3(p) : null;
  }
  const _v = () => new T.Vector3();
  function project(x, y, z) {
    const v = _v().set(x, y, z).project(camera);
    return { x: (v.x + 1) / 2 * W, y: (1 - v.y) / 2 * H, behind: v.z > 1 };
  }
  /** scene.json "points" noktasını 1080 x 1920 çerçeveye yansıtır (2D efektler için), dünya koordinatıyla birlikte. */
  function point(name) {
    const w = worldPoint(name);
    if (!w || !camera) return null;
    return { ...project(w.x, w.y, w.z), world: w };
  }
  /** Çerçeve koordinatından zemindeki noktaya (kamera 2D koordinatla gösterilen yere yakınlaşsın diye). */
  function toFloor(x, y) {
    raycaster.setFromCamera(new T.Vector2(x / W * 2 - 1, 1 - y / H * 2), camera);
    const hit = _v();
    return raycaster.ray.intersectPlane(floorPlane, hit) ? { x: hit.x, y: 0, z: hit.z } : null;
  }

  // ---------- Duruş yerleri ----------
  function buildSlots() {
    const fl = cfg.floor || { x: [-6, 6], z: [-1, 7] };
    const sp = cfg.spacing ?? 1.1, aisle = cfg.aisle;
    slots = [];
    let row = 0;
    for (let z = fl.z[0]; z <= fl.z[1] + 1e-6; z += sp * 0.9, row++) {
      const off = row % 2 ? sp / 2 : 0;
      for (let x = fl.x[0] + off; x <= fl.x[1] + 1e-6; x += sp) {
        if (aisle && Math.abs(x - aisle.x) < (aisle.half ?? 0.7)) continue;
        const j = hash(`${x}:${z}`);
        slots.push({ x: x + ((j % 100) / 100 - 0.5) * sp * 0.25, y: 0, z: z + (((j >> 8) % 100) / 100 - 0.5) * sp * 0.2, row, taken: null });
      }
    }
  }
  const frontSlots = () => { const rows = cfg.fill?.rows || 0; return rows ? slots.filter((s) => s.row < rows) : []; };

  let fillAt = 0, fillSeq = 0;
  function maintainFill(t) {
    if (t - fillAt < 800) return;
    fillAt = t;
    const front = new Set(frontSlots());
    for (const [id, f] of fillers) if (!(front.has(f.slot) && f.slot.taken === id)) { if (f.slot.taken === id) f.slot.taken = null; drop(f); fillers.delete(id); }
    for (const s of front) {
      if (s.taken) continue;
      const id = 'fill:' + fillSeq++;
      const f = makePerson({ id, name: '' }, { npc: true, filler: true, showName: false, wx: s.x, wz: s.z });
      f.slot = s; s.taken = id;
      fillers.set(id, f);
    }
  }

  function freeSlot() {
    const front = new Set(frontSlots());
    let s = slots.find((x) => !x.taken && !front.has(x));
    if (s) return s;
    let oldest = null;
    for (const p of persons.values()) if (!p.leaving && !p.slot?.vip && !p.tasks.length && !p.task && (!oldest || p.lastActive < oldest.lastActive)) oldest = p;
    if (!oldest) return null;
    s = oldest.slot;
    leave(oldest);
    return s;
  }

  // ---------- Kişi ----------
  function pickChar(id, preferred) {
    if (preferred) { const c = chars.find((x) => x.id === preferred); if (c) return c; }
    const total = chars.reduce((a, c) => a + (c.weight ?? 1), 0);
    let r = (hash(id) % 1000) / 1000 * total;
    for (const c of chars) { r -= c.weight ?? 1; if (r <= 0) return c; }
    return chars[0];
  }

  function makePerson(user, extra = {}) {
    const p = {
      id: user.id, name: user.name || 'Misafir', avatar: user.avatar ? Live.img(user.avatar) : null,
      char: pickChar(user.id, user.character), tint: (hash(user.id + 't') % 17) - 8,
      wx: 0, wz: 30, x: W / 2, y: H + 80, heading: Math.PI, pose: 'idle', anim: null, tasks: [], task: null, bubble: null, aura: 0, boost: 1, boostUntil: 0,
      lastActive: now() - 15000, joinedAt: now(), rank: user.rank || 0, title: user.title || '', coins: user.coins || 0, ...extra,
    };
    build(p);
    return p;
  }

  // Bir kişinin 3D kısmını kurar (karakter / model yeni yüklendiyse yeniden kurar)
  function build(p) {
    if (p.obj) drop(p);
    const c = p.char, g = new T.Group();
    if (c.ready) {
      const m = cloneSkinned(c.gltf.scene);
      m.scale.setScalar(c.unit);
      m.traverse((o) => { if (o.isMesh) { o.castShadow = renderer.shadowMap.enabled; if (o.isSkinnedMesh) o.frustumCulled = false; } });
      g.add(m);
      p.mixer = new T.AnimationMixer(m); p.actions = {}; p.clip = null;
    } else {
      const robe = new T.MeshStandardMaterial({ color: cfg.personColor ? new T.Color(cfg.personColor).offsetHSL(0, 0, p.tint / 400) : new T.Color().setHSL((220 + p.tint) / 360, 0.18, 0.55 + p.tint / 200), roughness: 0.8 }); // scene.json "personColor": yer tutucu kişilerin elbise rengi
      const body = new T.Mesh(new T.CylinderGeometry(0.2, 0.28, 1.15, 12), robe); body.position.y = 0.58;
      const head = new T.Mesh(new T.SphereGeometry(0.17, 16, 12), new T.MeshStandardMaterial({ color: '#2a201c', roughness: 0.7 })); head.position.y = 1.36;
      const torso = new T.Group(); torso.add(body, head);
      body.castShadow = head.castShadow = renderer.shadowMap.enabled;
      g.add(torso); p.torso = torso; p.mixer = null;
    }
    p.obj = g; p.built = c.ready ? c : null;
    scene3.add(g);
  }
  function drop(p) { if (p.obj) { scene3.remove(p.obj); p.mixer?.stopAllAction(); p.obj = null; } }

  function ensure(user, { instant = false } = {}) {
    if (!user?.id) return null;
    if (!ready) { if (pending.users.length < 500) pending.users.push([user, { instant: true }]); return null; }
    let p = persons.get(user.id);
    if (p) {
      p.name = user.name || p.name;
      if (user.rank !== undefined) p.rank = user.rank;
      if (user.title) p.title = user.title;
      if (user.avatar && !p.avatar) p.avatar = Live.img(user.avatar);
      return p;
    }
    const slot = freeSlot();
    if (!slot) return null;
    p = makePerson(user);
    p.slot = slot; slot.taken = p.id;
    persons.set(p.id, p);
    if (instant) { p.wx = slot.x; p.wz = slot.z; p.lastActive = now() - 30000; }
    else {
      const entry = worldPoint('entry') || { x: cfg.aisle?.x ?? 0, z: (cfg.floor?.z?.[1] ?? 7) + 6 };
      p.wx = entry.x; p.wz = entry.z;
      p.tasks.push({ type: 'walk', pts: (q) => route(q, slot) }, { type: 'pose', pose: 'idle' });
    }
    return p;
  }

  function leave(p) { if (p.slot) p.slot.taken = null; p.leaving = true; p.fadeStart = now(); }

  function addNpc(n) {
    const at = worldPoint(n.at) || { x: 0, z: 0 };
    const p = makePerson({ id: 'npc:' + n.id, name: n.name || '', character: n.character }, { npc: true, wx: at.x, wz: at.z, showName: n.showName !== false, scale: n.scale || 1, pose: n.pose || 'idle', cfg: n });
    p.slot = { x: at.x, z: at.z };
    npcs.set(n.id, p);
  }

  // Yol: orta koridor boyunca gidip yerine döner (koridor yoksa doğrudan gider)
  function route(p, target) {
    const a = cfg.aisle;
    if (!a) return [{ x: target.x, z: target.z }];
    const side = target.x < a.x ? -1 : 1;
    const lx = a.x + side * (a.half ?? 0.7) * 0.4;
    return [{ x: lx, z: p.wz }, { x: lx, z: target.z }, { x: target.x, z: target.z }];
  }
  const resolveTarget = (p, to) => (to === 'home' || to === 'seat' ? p.slot : worldPoint(to) || p.slot);

  // Kişi başına iş kuyruğu (2D sahneyle aynı): walk / pose / play / wait / do
  const P = {
    walkTo(p, to) { p.tasks.push({ type: 'walk', pts: (q) => { const t = resolveTarget(q, to); return t ? route(q, t) : []; } }); },
    pose(p, pose) { p.tasks.push({ type: 'pose', pose }); },
    play(p, anim, times = 1, onEach) { p.tasks.push({ type: 'play', anim, times, onEach }); },
    wait(p, ms) { p.tasks.push({ type: 'wait', ms }); },
    do(p, fn) { p.tasks.push({ type: 'do', fn }); },
    say(p, text, ms = 6500) { p.bubble = { text: String(text).slice(0, 80), until: now() + ms }; p.lastActive = now(); },
    aura(p, level = 1) { p.aura = Math.max(p.aura, level); },
    boost(p, scale = 1.25, ms = 4000) { p.boost = scale; p.boostUntil = now() + ms; },
    /** Başın tepesi çerçeveye yansır; h kişinin piksel boyudur. */
    head(p) {
      if (!camera) return { x: p.x, y: p.y, h: 60 };
      const hm = (p.char.height ?? 1.7) * (p.scale || 1) * (p.boost || 1);
      const top = project(p.wx, hm * 1.05, p.wz), foot = project(p.wx, 0, p.wz);
      return { x: top.x, y: top.y, h: Math.max(8, foot.y - top.y) };
    },
  };
  const height = (p) => P.head(p).h;

  // ---------- Animasyonlar ----------
  function findClip(c, name) {
    const list = c.gltf?.animations || [];
    const want = String(c.clips?.[name] || name).toLowerCase();
    return list.find((a) => a.name.toLowerCase() === want) || list.find((a) => a.name.toLowerCase().endsWith('|' + want)) || list.find((a) => a.name.toLowerCase().includes(want)) || null;
  }
  function action(p, name) {
    if (!p.mixer) return null;
    if (p.actions[name] !== undefined) return p.actions[name];
    const clip = findClip(p.char, name);
    return (p.actions[name] = clip ? p.mixer.clipAction(clip) : null);
  }
  function setClip(p, name, once = false) {
    if (!p.mixer || p.clip === name + (once ? '!' : '')) return Boolean(p.mixer && action(p, name));
    const next = action(p, name) || (name !== 'idle' && action(p, 'idle'));
    if (!next) return false;
    const prev = p.cur;
    next.reset();
    next.setLoop(once ? T.LoopOnce : T.LoopRepeat, Infinity);
    next.clampWhenFinished = once;
    next.enabled = true; next.setEffectiveWeight(1).play();
    if (prev && prev !== next) prev.crossFadeTo(next, 0.25, false);
    p.cur = next; p.clip = name + (once ? '!' : '');
    return true;
  }
  const clipMs = (p, name) => { const a = action(p, name); return a ? a.getClip().duration * 1000 : 0; };

  // ---------- Güncelleme ----------
  function update(p, t, dt) {
    if (p.char.ready && p.built !== p.char) build(p); // model yeni yüklendi: yer tutucu kişi değiştirilir
    if (p.boostUntil && t > p.boostUntil) { p.boost += (1 - p.boost) * Math.min(1, dt / 300); if (Math.abs(p.boost - 1) < 0.01) { p.boost = 1; p.boostUntil = 0; } }
    if (!p.task && p.tasks.length) { p.task = p.tasks.shift(); p.task.start = t; }
    const task = p.task;
    p.walking = false;
    if (task) {
      if (task.type === 'walk') {
        if (typeof task.pts === 'function') task.pts = task.pts(p);
        const target = task.pts[0];
        if (!target) p.task = null;
        else {
          const dx = target.x - p.wx, dz = target.z - p.wz, dist = Math.hypot(dx, dz), step = (cfg.walkSpeed ?? 1.5) * dt / 1000;
          if (dist <= step) { p.wx = target.x; p.wz = target.z; task.pts.shift(); }
          else { p.wx += dx / dist * step; p.wz += dz / dist * step; p.heading = Math.atan2(dx, dz); }
          p.walking = true;
        }
      } else if (task.type === 'pose') { p.pose = task.pose; p.anim = null; p.task = null; }
      else if (task.type === 'play') {
        const a = anims[task.anim] || {};
        if (!task.ms) task.ms = a.ms || clipMs(p, a.clip || task.anim) || 1200;
        const k = (t - task.start) / task.ms;
        p.anim = { name: a.clip || task.anim, k, ms: task.ms };
        const n = Math.floor(k);
        if (task.onEach && n !== task.last) { task.last = n; if (n < task.times) task.onEach(p, n); }
        if (k >= task.times) { p.anim = null; p.task = null; }
      } else if (task.type === 'wait') { if (t - task.start >= task.ms) p.task = null; }
      else if (task.type === 'do') { p.task = null; try { task.fn(p); } catch (e) { console.error('[Kit.scene3d] "do" adımında hata', e); } }
    } else if (p.slot && !p.leaving && Math.hypot(p.wx - p.slot.x, p.wz - p.slot.z) > 0.05) {
      p.tasks.push({ type: 'walk', pts: (q) => route(q, q.slot) }, { type: 'pose', pose: 'idle' });
    }
    if (p.aura > 0) p.aura = Math.max(0, p.aura - dt / 3500);
    if (p.bubble && t > p.bubble.until) p.bubble = null;
  }

  // 3D kısmın konumunu, yönünü, hareketini kişinin durumuna göre ayarlar
  const focusXZ = () => worldPoint('focus') || worldPoint('stage') || { x: 0, z: -10 };
  function sync(p, t, dt, animate) {
    const g = p.obj;
    if (!g) return;
    let s = (p.scale || 1) * (p.boost || 1);
    if (p.leaving) { const k = 1 - (t - p.fadeStart) / 700; if (k <= 0) { drop(p); persons.delete(p.id); return; } s *= k; }
    g.position.set(p.wx, 0, p.wz);
    g.scale.setScalar(s);
    if (!p.walking && !p.task) { const f = cfg.facing === 'camera' ? camera.position : focusXZ(); p.heading = Math.atan2(f.x - p.wx, f.z - p.wz); }
    let d = p.heading - g.rotation.y; d = Math.atan2(Math.sin(d), Math.cos(d));
    g.rotation.y += d * Math.min(1, dt / 120);
    const name = p.walking ? 'walk' : p.anim ? p.anim.name : p.pose || 'idle';
    if (p.mixer) {
      setClip(p, name);
      if (animate) { p.mixer.update((dt + (p.skipped || 0)) / 1000); p.skipped = 0; } else p.skipped = (p.skipped || 0) + dt;
    } else if (p.torso) {
      // yer tutucu kişi: ada göre basit hareketleri kendisi yapar
      const tt = t / 1000 + (hash(p.id) % 100) / 30, tor = p.torso;
      tor.position.y = 0; tor.rotation.x = 0; tor.rotation.z = 0;
      if (p.walking) tor.position.y = Math.abs(Math.sin(tt * 9)) * 0.06;
      else if (/bow|lay|nod|offer|pray/i.test(name)) tor.rotation.x = Math.sin(((p.anim?.k ?? 0) % 1) * Math.PI) * (name === 'nod' ? 0.25 : 0.6);
      else if (/dance|cheer|jump|wave/i.test(name)) { tor.position.y = Math.abs(Math.sin(tt * 7)) * 0.18; tor.rotation.z = Math.sin(tt * 7) * 0.12; }
      else tor.rotation.z = Math.sin(tt * 1.3) * 0.02;
    }
    const foot = project(p.wx, 0, p.wz);
    p.x = foot.x; p.y = foot.y;
  }

  // ---------- Onur koltukları, görünüm değiştirme ----------
  // Sıra → koltuk: `top` dizisindeki i. kişi HER ZAMAN seats[i]'ye oturur (2D scene.js ile aynı mantık).
  function seatTop(top = []) {
    if (!ready) { pending.top = top; return; }
    if (!seats.length) return;
    const want = top.slice(0, seats.length);
    const rankIdx = new Map(want.map((u, i) => [u.id, i]));
    seats.forEach((seat, i) => { // 1) sırasına uymayanı koltuktan kaldır
      if (!seat.taken || rankIdx.get(seat.taken) === i) return;
      const p = persons.get(seat.taken);
      seat.taken = null;
      if (!p || p.leaving) return;
      const s = freeSlot();
      if (!s) { leave(p); return; }
      p.slot = s; s.taken = p.id;
      P.walkTo(p, 'home'); P.pose(p, 'idle');
    });
    want.forEach((u, i) => { // 2) seats[0], seats[1], ... sırayla oturt
      const p = persons.get(u.id) || ensure({ ...u, isPlayer: true });
      if (!p || p.leaving) return;
      p.rank = u.rank || i + 1; p.coins = u.coins;
      const seat = seats[i];
      if (p.slot === seat || seat.taken) return;
      if (p.task || p.tasks.length) return; // meşgul: sonraki state güncellemesinde oturur
      if (p.slot) p.slot.taken = null;
      p.slot = seat; seat.taken = p.id;
      P.walkTo(p, 'seat'); P.pose(p, 'idle');
      P.do(p, (q) => { q.aura = 1; const hd = P.head(q); K.fx.pillar(q.x, q.y, { height: hd.h * 6 }); K.events?.emit('seated', q); });
    });
  }

  function skinFromChat(user, text) {
    const w = String(text || '').toLowerCase().normalize('NFC').replace(/[^\p{L}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
    if (!w || w.split(' ').length > 3) return false;
    const c = chars.find((x) => (x.keywords || []).some((k) => w === k.toLowerCase()));
    const p = persons.get(user.id);
    if (!c || !p || p.char === c) return false;
    p.char = c; p.aura = 0.8; build(p);
    const hd = P.head(p);
    K.fx.emit('spark', { x: hd.x, y: hd.y + hd.h * 0.4, count: 10, spread: 20 });
    return true;
  }

  // ---------- Camera ----------
  function focus(target, o = {}) {
    if (settings.cameraFx === false) return;
    cam.queue.push({ target, zoom: o.zoom ?? 1.55, ms: o.duration ?? 3200 });
    if (cam.queue.length > 4) cam.queue.splice(1, cam.queue.length - 4);
  }
  function focusWorld(tg) {
    if (!tg) return null;
    if (tg.id && (persons.get(tg.id) || tg.wx !== undefined)) { const p = persons.get(tg.id) || tg; return { x: p.wx, y: (p.char.height ?? 1.7) * 0.8, z: p.wz }; }
    if (tg.world) return tg.world;
    if (tg.z !== undefined) return tg;
    if (tg.x !== undefined && tg.y !== undefined) { const f = toFloor(tg.x, tg.y); return f && { ...f, y: 1 }; }
    return null;
  }
  function updateCamera(t, dt) {
    if (t > cam.until && cam.queue.length) { cam.cur = cam.queue.shift(); cam.until = t + cam.cur.ms; }
    let pos = cam.basePos, look = cam.baseLook;
    if (cam.cur && t <= cam.until) {
      const tg = typeof cam.cur.target === 'function' ? cam.cur.target() : cam.cur.target;
      const f = focusWorld(tg);
      if (f) {
        look = new T.Vector3(f.x, f.y, f.z);
        pos = look.clone().add(cam.basePos.clone().sub(cam.baseLook).multiplyScalar(1 / Math.max(1, cam.cur.zoom)));
      }
    } else cam.cur = null;
    const k = Math.min(1, dt / 450);
    cam.pos.lerp(pos, k); cam.look.lerp(look, k);
    const sh = K.fx.shakeOffset(t);
    camera.position.set(cam.pos.x + sh.x * 0.004, cam.pos.y + sh.y * 0.004, cam.pos.z);
    camera.lookAt(cam.look);
  }

  // ---------- Çizim döngüsü ----------
  let debugOverlay = new URLSearchParams(location.search).has('scene');
  let rankAt = 0, animatedIds = new Set();
  function frame(t, dt) {
    if (!ctx) return;
    if (!ready) { ctx.clearRect(0, 0, W, H); return; }
    maintainFill(t);
    updateCamera(t, dt);
    K.fx.update(dt, t);
    const all = [...persons.values(), ...npcs.values(), ...fillers.values()];
    for (const p of all) update(p, t, dt);
    // her karede yalnızca kameraya en yakın kişilerin hareketi güncellenir (scene.json "maxAnimated"), uzaktakiler seyrek güncellenir
    const maxA = cfg.maxAnimated ?? 120;
    if (t - rankAt > 500) {
      rankAt = t;
      const c = camera.position;
      animatedIds = new Set(all.slice().sort((a, b) => Math.hypot(a.wx - c.x, a.wz - c.z) - Math.hypot(b.wx - c.x, b.wz - c.z)).slice(0, maxA).map((p) => p.id));
    }
    const tick = Math.floor(t / 16) % 4 === 0;
    for (const p of all) sync(p, t, dt, animatedIds.has(p.id) || p.task || tick);
    for (const e of emitters) { const at = point(e.at) || { x: W / 2, y: H / 2 }; e.o.x = at.x; e.o.y = at.y; }
    stage?.update(t, dt);
    if (composer && !chromaOn) composer.render(); else renderer.render(scene3, camera); // yeşil arka plan: parlama atılır ki arka plan rengi doğru kalsın

    // 2D katman: efektler, ışık halesi, isim etiketleri, balonlar
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const sh = K.fx.shakeOffset(t);
    ctx.setTransform(1, 0, 0, 1, sh.x, sh.y);
    K.fx.draw(ctx, 'back', t);
    for (const p of all) if (p.aura > 0 && p.obj) drawAura(p);
    K.fx.draw(ctx, 'front', t);
    K.fx.draw(ctx, 'top', t);
    const visible = all.filter((p) => p.obj);
    labels.pick(ctx, visible, t);
    for (const p of visible) if (!p.leaving) labels.draw(ctx, p);
    if (debugOverlay) drawDebug();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    K.fx.draw(ctx, 'screen', t);
  }

  function drawAura(p) {
    const hd = P.head(p), cy = hd.y + hd.h * 0.5, r = hd.h * 0.9;
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    const g = ctx.createRadialGradient(hd.x, cy, 2, hd.x, cy, r);
    g.addColorStop(0, `rgba(255,220,120,${0.55 * p.aura})`); g.addColorStop(1, 'rgba(255,200,80,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(hd.x, cy, r, 0, 6.283); ctx.fill(); ctx.restore();
  }

  // ?scene: scene.json'u ayarlamak için zemin, koridor, duruş yerleri, koltuklar, noktalar (dünya koordinatından yansıtılır)
  function drawDebug() {
    const fl = cfg.floor || { x: [-6, 6], z: [-1, 7] };
    ctx.save();
    ctx.strokeStyle = 'rgba(0,255,200,.9)'; ctx.lineWidth = 3; ctx.setLineDash([12, 8]);
    const c = [[fl.x[0], fl.z[0]], [fl.x[1], fl.z[0]], [fl.x[1], fl.z[1]], [fl.x[0], fl.z[1]]].map(([x, z]) => project(x, 0, z));
    ctx.beginPath(); c.forEach((q, i) => (i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y))); ctx.closePath(); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(0,255,200,.7)';
    for (const s of slots) { const q = project(s.x, 0, s.z); ctx.beginPath(); ctx.arc(q.x, q.y, 4, 0, 6.283); ctx.fill(); }
    ctx.fillStyle = 'rgba(255,215,0,.9)';
    for (const s of seats) { const q = project(s.x, 0, s.z); ctx.beginPath(); ctx.arc(q.x, q.y, 8, 0, 6.283); ctx.fill(); }
    ctx.fillStyle = 'rgba(255,0,180,.9)'; ctx.font = '700 22px system-ui';
    for (const name of Object.keys(cfg.points || {})) { const q = point(name); if (!q) continue; ctx.beginPath(); ctx.arc(q.x, q.y, 9, 0, 6.283); ctx.fill(); ctx.fillText(name, q.x + 12, q.y - 10); }
    ctx.restore();
  }

  function reset() { for (const p of persons.values()) leave(p); for (const s of seats) s.taken = null; fillAt = 0; }

  K.scene3d = {
    init, configure, frame, ensure, leave: (id) => { const p = persons.get(id); if (p) leave(p); }, reset, point, seatTop, skinFromChat, focus,
    person: (id) => persons.get(id), npc: (id) => npcs.get(id), people: () => [...persons.values()].filter((p) => !p.leaving),
    extras: () => [...fillers.values()],
    height, P, get layout() { return { slots }; }, get seats() { return seats; }, get scene() { return cfg; }, get chars() { return chars; },
    /** { "stage": "party" | "calm" | "strobe" } adımı. */
    stage: (step) => stage?.command(step),
    /** { "fx3d": "fireworks" | "confetti" | "beam" | "ring", "at": "person" | nokta adı } adımı. */
    fx3d(step, person) {
      if (!stage) return;
      const at = step.at && step.at !== 'person' ? worldPoint(step.at) : person ? { x: person.wx, y: 0, z: person.wz } : worldPoint('stage');
      stage.fx(step, at || { x: 0, y: 0, z: 0 });
    },
    get three() { return { THREE: T, scene: scene3, camera, renderer }; }, // theme.js kendi 3D nesnesini ekleyebilsin diye
    set debug(v) { debugOverlay = v; },
  };
})();
