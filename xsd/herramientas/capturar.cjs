// XSD: captura cada pantalla del inventario en cada vista, para una variante.
//
//   node xsd/herramientas/capturar.cjs <ficha.json> <variante> <sesiones.json> <carpeta> [ids,separados,por,coma]
//
// - <variante>: una de `variantes.con_variantes` (captura las pantallas con
//   `temas: true`) o `variantes.sin_variantes` (las que no tienen variantes).
// - <sesiones.json>: lo que imprime `sesiones.comando` de la ficha
//   ({rol: {cookie: valor}}), recién generado: las sesiones vencen.
// - [ids]: opcional, solo esas pantallas (la segunda vuelta captura lo tocado).
//
// Reglas que salieron de la primera corrida (Colm3na, 2026-10-24):
// - about:blank entre pantalla y pantalla: si solo cambia el # el navegador no
//   recarga y todas las pestañas salen iguales;
// - movimiento reducido, para no capturar animaciones a medio camino;
// - el locale de la ficha: con el navegador en inglés las fechas dicen
//   mm/dd/yyyy y aparecen como falsos hallazgos;
// - página entera con tope (vistas.<v>.tope).
// Deja <carpeta>/capturas/<variante>-<vista>-<id>.png y
// <carpeta>/errores-<variante>.json (vacío si salió todo).
const fs = require('fs');
const path = require('path');

function playwright() {
  try { return require('playwright'); } catch (e) { /* sigue */ }
  const global = require('child_process').execSync('npm root -g').toString().trim();
  return require(path.join(global, 'playwright'));
}

(async () => {
  const [fichaRuta, variante, sesionesRuta, carpeta, soloIds] = process.argv.slice(2);
  if (!carpeta) {
    console.error('Uso: node capturar.cjs <ficha.json> <variante> <sesiones.json> <carpeta> [ids]');
    process.exit(2);
  }
  const ficha = JSON.parse(fs.readFileSync(fichaRuta, 'utf8'));
  const sesiones = JSON.parse(fs.readFileSync(sesionesRuta, 'utf8'));
  const sinVariantes = (ficha.variantes || {}).sin_variantes || 'base';
  const conVariantes = variante !== sinVariantes;
  const solo = soloIds ? new Set(soloIds.split(',').map(s => s.trim()).filter(Boolean)) : null;
  const pantallas = JSON.parse(fs.readFileSync(ficha.pantallas, 'utf8'))
    .filter(p => Boolean(p.temas) === conVariantes)
    .filter(p => !solo || solo.has(p.id));
  const base = (ficha.base_url || `http://localhost:${ficha.servidor.puerto}`).replace(/\/$/, '');
  const dominio = (ficha.sesiones || {}).dominio || new URL(base).hostname;
  const roles = ficha.roles || [...new Set(pantallas.map(p => p.rol))];
  fs.mkdirSync(path.join(carpeta, 'capturas'), { recursive: true });

  const { chromium } = playwright();
  const br = await chromium.launch(process.env.XSD_CHROMIUM ? { executablePath: process.env.XSD_CHROMIUM } : {});
  const errores = [];
  let hechas = 0;
  for (const [vista, v] of Object.entries(ficha.vistas)) {
    const opts = { viewport: { width: v.ancho, height: v.alto } };
    if (v.movil) Object.assign(opts, { isMobile: true, hasTouch: true });
    if (v.escala) opts.deviceScaleFactor = v.escala;
    for (const rol of roles) {
      const lista = pantallas.filter(p => p.rol === rol);
      if (!lista.length) continue;
      const ctx = await br.newContext({ ...opts, reducedMotion: 'reduce', locale: ficha.locale || 'es-AR' });
      const cookies = Object.entries(sesiones[rol] || {}).map(([name, value]) => ({ name, value, domain: dominio, path: '/' }));
      if (cookies.length) await ctx.addCookies(cookies);
      const pg = await ctx.newPage();
      pg.on('pageerror', e => errores.push({ id: pg._xsd, vista, error: 'JS: ' + String(e).slice(0, 200) }));
      for (const p of lista) {
        pg._xsd = p.id;
        try {
          await pg.goto('about:blank');
          await pg.goto(base + p.url, { waitUntil: 'networkidle', timeout: 30000 });
          if (p.js) await pg.evaluate(p.js);
          await pg.waitForTimeout(p.espera || 1300);
          const alto = Math.min(await pg.evaluate(() => document.documentElement.scrollHeight), v.tope || 5000);
          await pg.screenshot({ path: path.join(carpeta, 'capturas', `${variante}-${vista}-${p.id}.png`), fullPage: true,
                                clip: { x: 0, y: 0, width: v.ancho, height: alto } });
          hechas += 1;
        } catch (e) {
          errores.push({ id: p.id, vista, error: String(e).slice(0, 200) });
        }
      }
      await ctx.close();
    }
  }
  await br.close();
  fs.writeFileSync(path.join(carpeta, `errores-${variante}.json`), JSON.stringify(errores, null, 1));
  console.log(`xsd: ${hechas} capturas de ${variante}, ${errores.length} errores`);
})();
