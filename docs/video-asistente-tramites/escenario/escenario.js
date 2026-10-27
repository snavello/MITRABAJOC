/* Driver del escenario 3D: lee timeline2.json y renderiza cada cuadro final. */
const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
const R = path.resolve(__dirname, '..');
const TL = JSON.parse(fs.readFileSync(path.join(R, 'timeline2.json'), 'utf8'));
const OUT = path.join(R, 'out2'); fs.mkdirSync(OUT, { recursive: true });
const FPS = 30;
const ease = { inout: (u) => (u < .5 ? 4*u*u*u : 1 - Math.pow(-2*u+2, 3)/2), out: (u) => 1 - Math.pow(1-u, 3), in: (u) => u*u*u, lin: (u) => u };
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const frames = {};
function listar(dir, pref) { const k = dir + '/' + pref; if (!frames[k]) frames[k] = fs.readdirSync(path.join(R, 'frames', dir)).filter((f) => f.startsWith(pref + '_') && f.endsWith('.png')).sort().map((f) => 'file://' + path.join(R, 'frames', dir, f)); return frames[k]; }
function interp(keys, t, campos) {
  // keys: [{t, ...valores}] ordenados; devuelve valores interpolados con ease inout entre claves
  if (!keys.length) return {};
  if (t <= keys[0].t) return { ...keys[0] };
  if (t >= keys[keys.length - 1].t) return { ...keys[keys.length - 2] || {}, ...keys[keys.length - 1] };
  let i = 0; while (keys[i + 1].t < t) i++;
  const a = keys[i], b = keys[i + 1]; const u = (t - a.t) / (b.t - a.t); const k = ease[b.e || 'inout'](u);
  const o = {}; for (const c of campos) { if (a[c] == null && b[c] == null) continue; const va = a[c] ?? b[c], vb = b[c] ?? a[c]; o[c] = va + (vb - va) * k; } return o;
}
const CAMPOS = ['tx', 'ty', 'tz', 'rx', 'ry', 'rz', 's', 'op', 'zx', 'zy', 'zs'];
function transformDe(v) {
  // zoom interno: zs escala alrededor del punto (zx, zy) en 0..1 del plano -> se aplica como transform-origin cambiando translate
  return `translate3d(${v.tx || 0}px, ${v.ty || 0}px, ${v.tz || 0}px) rotateX(${v.rx || 0}deg) rotateY(${v.ry || 0}deg) rotateZ(${v.rz || 0}deg) scale(${v.s == null ? 1 : v.s})`;
}
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.goto('file://' + path.join(__dirname, 'stage.html'), { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  const total = Math.round(TL.duracion * FPS);
  const desde = parseInt(process.env.DESDE || '0'), hasta = parseInt(process.env.HASTA || String(total));
  for (let g = desde; g < hasta; g++) {
    const t = g / FPS; const f = { planos: [] };
    for (const sh of TL.shots) {
      if (t < sh.t0 || t >= sh.t1) continue;
      const u = (t - sh.t0) / (sh.t1 - sh.t0);
      let src = null;
      if (sh.fuente) {
        const lista = listar(sh.fuente.dir, sh.fuente.prefijo);
        const i0 = sh.fuente.i0 ?? 0, i1 = sh.fuente.i1 ?? (lista.length - 1);
        let idx;
        if (sh.fuente.tramos) { // mapeo por tramos: [{u0,u1,i0,i1}]
          const tr = sh.fuente.tramos.find((x) => u >= x.u0 && u < x.u1) || sh.fuente.tramos[sh.fuente.tramos.length - 1];
          idx = tr.i0 + (clamp((u - tr.u0) / (tr.u1 - tr.u0), 0, 1)) * (tr.i1 - tr.i0);
        } else idx = i0 + u * (i1 - i0);
        src = lista[clamp(Math.round(idx), 0, lista.length - 1)];
      } else if (sh.imagen) src = 'file://' + path.join(R, sh.imagen);
      const v = interp(sh.cam || [{ t: 0 }], t, CAMPOS);
      let w = sh.w, h = sh.h;
      // zoom interno del plano (recorte): se simula con scale + translate del plano completo alrededor de un punto
      let tr = transformDe(v);
      if (v.zs && v.zs > 1.0001) {
        const ox = (0.5 - (v.zx ?? 0.5)) * w * (v.zs - 1), oy = (0.5 - (v.zy ?? 0.5)) * h * (v.zs - 1);
        tr = `translate3d(${ox}px, ${oy}px, 0) ` + tr + ` scale(${v.zs})`;
      }
      let op = v.op == null ? 1 : v.op;
      if (sh.fade_in && t - sh.t0 < sh.fade_in) op *= (t - sh.t0) / sh.fade_in;
      if (sh.fade_out && sh.t1 - t < sh.fade_out) op *= (sh.t1 - t) / sh.fade_out;
      // destello especular: recorre el plano durante el primer 1,6 s de la toma
      const espec = clamp((t - sh.t0) / 1.6, 0, 1);
      f.planos.push({ id: sh.id, clase: sh.clase, src, w, h, t: tr, op, z: sh.z || 1, reflejo: sh.reflejo, espec: espec < 1 ? espec : null });
      if (sh.suelo) f.suelo = { x: (v.tx || 0) * 0.6, y: (sh.h / 2) * 0.72 + (v.ty || 0), s: sh.suelo };
    }
    // luz: halos en deriva lenta, rayos que giran, pulso al compás de la música (124 BPM), flare en cada corte
    const bpm = (TL.musica && TL.musica.bpm) || 124; const beat = (t * bpm / 60) % 1;
    const pulso = 1 + 0.035 * Math.exp(-beat * 6);
    let flare = 0, fx = 50, fy = 50;
    for (const sh of TL.shots) { const d = t - sh.t0; if (d >= 0 && d < 0.55 && sh.flare !== false) { flare = Math.max(flare, 0.9 * (1 - d / 0.55)); fx = sh.fx || 50; fy = sh.fy || 45; } }
    f.luz = { ax: 960 + 520 * Math.sin(t * 0.21), ay: 420 + 260 * Math.cos(t * 0.17), bx: 960 + 640 * Math.cos(t * 0.13 + 1), by: 760 + 220 * Math.sin(t * 0.19 + 2), rot: t * 1.7, pulso, flare, fx, fy,
      suelo: f.suelo ? f.suelo.s : 0, sx: f.suelo ? f.suelo.x : 0, sy: f.suelo ? f.suelo.y : 0, ss: f.suelo ? 1 : 0.5 };
    for (const r of TL.rotulos || []) {
      if (t >= r.t0 - 0.05 && t <= r.t1) {
        const kin = clamp((t - r.t0) / 0.5, 0, 1), kout = clamp((r.t1 - t) / 0.4, 0, 1);
        if (r.pos === 'izq' || r.pos === 'der') f.lateral = { h: r.h, s: r.s, k: ease.out(kin) * kout, lado: r.pos };
        else f.rotulo = { h: r.h, s: r.s, k: ease.out(kin) * kout };
      }
    }
    for (const p of TL.placas || []) {
      if (t >= p.t0 && t <= p.t1) { const kin = clamp((t - p.t0) / 0.7, 0, 1), kout = clamp((p.t1 - t) / 0.6, 0, 1); f.placa = { h: p.h, s: p.s, k: ease.out(kin) * kout }; }
    }
    for (const n of TL.negros || []) { if (t >= n.t0 && t <= n.t1) f.negro = n.a0 + (n.a1 - n.a0) * clamp((t - n.t0) / (n.t1 - n.t0), 0, 1); }
    for (const b of TL.brillos || []) { if (t >= b.t0 && t <= b.t1) f.brillo = (t - b.t0) / (b.t1 - b.t0); }
    await page.evaluate((ff) => window.render(ff), f);
    if (process.env.DEBUG) console.log(JSON.stringify(f.planos.map((p) => [p.id, p.src && p.src.slice(-40), p.t])), await page.evaluate(() => Array.from(document.querySelectorAll('.plano')).map((p) => [p.id, p.querySelector('img').naturalWidth, p.querySelector('img').currentSrc.slice(-30), JSON.stringify(p.getBoundingClientRect()), getComputedStyle(p).opacity, getComputedStyle(p).display])));
    await page.screenshot({ path: path.join(OUT, String(g).padStart(5, '0') + '.png'), type: 'png' });
    if (g % 150 === 0) console.log('cuadro', g, '/', total);
  }
  console.log('listo');
  await browser.close();
})().catch((e) => { console.error('ERROR', e); process.exit(1); });
