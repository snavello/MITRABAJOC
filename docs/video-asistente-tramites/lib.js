/* Filmador cuadro por cuadro con reloj virtual (Playwright clock) + seek de
   animaciones CSS + cámara (zoom/pan/3D) + cursor dibujado. */
const fs = require('fs');
const path = require('path');

const FPS = 30;
const ease = {
  linear: (u) => u,
  inout: (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2),
  out: (u) => 1 - Math.pow(1 - u, 3),
  in: (u) => u * u * u,
};

const PAGE_SCRIPT = `
(function(){
  if (window.__film) return;
  const F = window.__film = { anims: new Map(), cam: null, cursor: null, extra: {} };
  const st = document.createElement('style');
  st.id = '__film_style';
  st.textContent = '#distintivo-entorno{display:none!important} html,body{overflow:hidden!important} body{transform-origin:0 0; will-change:transform} ' +
    '#__cursor{position:absolute; left:0; top:0; width:26px; height:34px; z-index:99999; pointer-events:none; filter:drop-shadow(0 2px 3px rgba(0,0,0,.5)); transition:none}' +
    '#__cursor .pulso{position:absolute; left:-14px; top:-14px; width:28px; height:28px; border-radius:50%; background:rgba(255,176,32,.55); transform:scale(0); }';
  document.documentElement.appendChild(st);
  F.step = function(dt, cam, cursor, extra){
    // animaciones: pausar y ubicar
    const vivas = new Set();
    for (const a of document.getAnimations()) {
      vivas.add(a);
      if (!F.anims.has(a)) { try { a.pause(); a.currentTime = 0; } catch(e){} F.anims.set(a, 0); }
      else { const t = F.anims.get(a) + dt; F.anims.set(a, t); try { a.currentTime = t; } catch(e){} }
    }
    for (const a of F.anims.keys()) if (!vivas.has(a)) F.anims.delete(a);
    if (cam) {
      F.cam = cam;
      const W = window.innerWidth, H = window.innerHeight;
      document.body.style.transform = 'translate(' + (W/2) + 'px,' + (H/2) + 'px) scale(' + cam.z + ') translate(' + (-cam.x) + 'px,' + (-cam.y) + 'px)';
    }
    if (cursor !== undefined) {
      let c = document.getElementById('__cursor');
      if (!c) { c = document.createElement('div'); c.id = '__cursor';
        c.innerHTML = '<div class="pulso"></div><svg width="26" height="34" viewBox="0 0 26 34"><path d="M2 2 L2 26 L8 20 L13 31 L17 29 L12 18 L21 18 Z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
        document.body.appendChild(c); }
      if (cursor === null) c.style.display = 'none';
      else { c.style.display = 'block'; c.style.transform = 'translate(' + cursor.x + 'px,' + cursor.y + 'px)';
        const p = c.querySelector('.pulso'); const s = cursor.pulso || 0; p.style.transform = 'scale(' + (s*2.2) + ')'; p.style.opacity = String(Math.max(0, 1 - s)); }
    }
    if (extra && F.onExtra) F.onExtra(extra);
  };
  F.rect = function(sel, nth){
    const els = typeof sel === 'string' ? document.querySelectorAll(sel) : [sel];
    const el = els[nth || 0]; if (!el) return null;
    const r = el.getBoundingClientRect();
    const cam = F.cam || { x: window.innerWidth/2, y: window.innerHeight/2, z: 1 };
    const W = window.innerWidth, H = window.innerHeight;
    const inv = (cx, cy) => [cam.x + (cx - W/2) / cam.z, cam.y + (cy - H/2) / cam.z];
    const [x1, y1] = inv(r.left, r.top), [x2, y2] = inv(r.right, r.bottom);
    return { x: x1, y: y1, w: x2 - x1, h: y2 - y1, cx: (x1 + x2) / 2, cy: (y1 + y2) / 2 };
  };
})();`;

class Filmador {
  constructor(page, outDir, { prefix = 'f', fps = FPS, mobile = false } = {}) {
    this.page = page; this.outDir = outDir; this.prefix = prefix; this.fps = fps; this.mobile = mobile;
    this.t = 0; this.n = 0; this.cam = null; this.cursor = null;
    this.tweens = []; this.marks = [];
    fs.mkdirSync(outDir, { recursive: true });
  }
  async preparar() {
    await this.page.addInitScript(PAGE_SCRIPT);
    await this.page.evaluate(PAGE_SCRIPT);
  }
  marca(nombre) { this.marks.push({ t: this.t, nombre }); console.log(`  [${this.t.toFixed(2)}s] ${nombre}`);
    fs.writeFileSync(path.join(this.outDir, 'marcas.json'), JSON.stringify(this.marks)); }
  // --- tweens
  _tween(obj, a, b, T, e) { this.tweens.push({ obj, a: { ...a }, b: { ...b }, t0: this.t, t1: T, e: ease[e] || ease.inout }); }
  camTo(cam, T, e = 'inout') { const a = this.cam || cam; this._tween('cam', a, { ...a, ...cam }, T, e); }
  camSet(cam) { this.cam = { ...(this.cam || {}), ...cam }; }
  cursorTo(pt, T, e = 'inout') { const a = this.cursor || pt; this._tween('cursor', { ...a, pulso: 0 }, { ...pt, pulso: 0 }, T, e); }
  cursorSet(pt) { this.cursor = pt; }
  pulso(T) { const a = this.cursor; this._tween('cursor', { ...a, pulso: 0 }, { ...a, pulso: 1 }, T, 'out'); }
  _aplicarTweens() {
    for (const tw of this.tweens) {
      const u = tw.t1 <= tw.t0 ? 1 : Math.min(1, Math.max(0, (this.t - tw.t0) / (tw.t1 - tw.t0)));
      const k = tw.e(u); const v = {};
      for (const key of Object.keys(tw.b)) v[key] = (tw.a[key] ?? tw.b[key]) + ((tw.b[key] - (tw.a[key] ?? tw.b[key])) * k);
      if (tw.obj === 'cam') this.cam = v; else this.cursor = v;
    }
    this.tweens = this.tweens.filter((tw) => this.t < tw.t1);
    if (this.cam && this.limites) {
      const half = 960 / this.cam.z;
      const l = this.limites.l, r = this.limites.r;
      if (r - l < 2 * half) this.cam.x = (l + r) / 2;
      else this.cam.x = Math.min(Math.max(this.cam.x, l + half), r - half);
    }
  }
  async rect(sel, nth = 0) {
    const r = await this.page.evaluate(([s, n]) => window.__film.rect(s, n), [sel, nth]);
    if (!r) throw new Error('no existe ' + sel);
    return r;
  }
  // --- un cuadro
  async cuadro(speed = 1, extra) {
    const dt = (1000 / this.fps) * speed;
    await this.page.clock.runFor(Math.max(1, Math.round(dt)));
    this._aplicarTweens();
    await this.page.evaluate(([d, cam, cur, ex]) => window.__film.step(d, cam, cur, ex), [dt, this.cam, this.cursor === undefined ? undefined : this.cursor, extra || null]);
    const file = path.join(this.outDir, `${this.prefix}_${String(this.n).padStart(5, '0')}.png`);
    await this.page.screenshot({ path: file, type: 'png', animations: 'allow', caret: 'hide' });
    this.n += 1; this.t += 1 / this.fps;
  }
  async hasta(T, speed = 1, extraFn) {
    while (this.t < T - 1e-6) await this.cuadro(speed, extraFn ? extraFn(this.t) : undefined);
  }
  // esperar una condición de la página avanzando el reloj virtual (waitForFunction no sirve: su rAF está congelado)
  async esperar(fn, { timeout = 30000, paso = 40 } = {}) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      await this.page.clock.runFor(paso);
      if (await this.page.evaluate(fn)) return true;
      await new Promise((r) => setTimeout(r, 30));
    }
    throw new Error('esperar: se agotó el tiempo');
  }
  // --- acciones
  async click(sel, nth = 0) {
    await this.page.evaluate(([s, n]) => { const el = document.querySelectorAll(s)[n]; if (!el) throw new Error('no existe ' + s); el.click(); }, [sel, nth]);
  }
  async escribir(sel, texto, T, { speed = 1, nth = 0 } = {}) {
    const total = texto.length; const t0 = this.t; const dur = Math.max(0.05, T - t0);
    let escritos = 0;
    while (this.t < T - 1e-6) {
      const objetivo = Math.min(total, Math.round(((this.t - t0 + 1 / this.fps) / dur) * total));
      if (objetivo > escritos) {
        escritos = objetivo;
        await this.page.evaluate(([s, n, v]) => { const el = document.querySelectorAll(s)[n]; const setter = Object.getOwnPropertyDescriptor(el.__proto__, 'value')?.set; if (setter) setter.call(el, v); else el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }, [sel, nth, texto.slice(0, escritos)]);
      }
      await this.cuadro(speed);
    }
    if (escritos < total) await this.page.evaluate(([s, n, v]) => { const el = document.querySelectorAll(s)[n]; const setter = Object.getOwnPropertyDescriptor(el.__proto__, 'value')?.set; if (setter) setter.call(el, v); else el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }, [sel, nth, texto]);
  }
  async elegir(sel, valor, nth = 0) {
    await this.page.evaluate(([s, n, v]) => { const el = document.querySelectorAll(s)[n]; el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }, [sel, nth, valor]);
  }
  // cursor viaja hasta un elemento y hace clic con pulso
  async irYClic(sel, T, { nth = 0, dx = 0, dy = 0, clic = true } = {}) {
    const r = await this.rect(sel, nth);
    const destino = { x: r.cx + dx, y: r.cy + dy };
    this.cursorTo(destino, T);
    await this.hasta(T);
    this.cursor = { ...destino, pulso: 0 };
    if (clic) { await this.click(sel, nth); this.pulso(this.t + 0.4); }
  }
}

module.exports = { Filmador, ease, FPS };
