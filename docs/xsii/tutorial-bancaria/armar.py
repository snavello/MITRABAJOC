"""Arma el HTML del tutorial «XSII para implementar La Bancaria».

Lee `paginas.json` y escribe una sola página (un `.html` más las imágenes de
`img/` al lado). Cada hoja del tutorial termina con una caja para dejar una
opinión; las opiniones se guardan en la base del artefacto publicado.

    python docs/xsii/tutorial-bancaria/armar.py <carpeta_de_salida>
"""
from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).parent


def e(texto) -> str:
    return html.escape(str(texto or ""), quote=True)


ESTILO = """
/* Hojas apiladas, una por tema, con el índice fijo a la izquierda en pantallas anchas. */
:root{
  --fondo:#eef1f6; --hoja:#ffffff; --tinta:#141b2d; --tenue:#56607a; --linea:#d6dbe6;
  --azul:#2340c9; --azul-suave:#e6eafc; --miel:#f0a01e; --miel-suave:#fff3dc; --miel-tinta:#7a4a00;
  --verde:#0f7a5c; --verde-suave:#dcf3ea; --rojo:#b3261e;
  --display:"Barlow Condensed","Arial Narrow",Arial,sans-serif;
  --texto:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --fondo:#0e1320; --hoja:#171e30; --tinta:#eef1f8; --tenue:#a3adc4; --linea:#2b3550;
  --azul:#8fa3ff; --azul-suave:#1f2a55; --miel:#f4b23f; --miel-suave:#3a2c0c; --miel-tinta:#ffd88a;
  --verde:#5fd0aa; --verde-suave:#11362b; --rojo:#ff8a80; color-scheme:dark } }
:root[data-theme="dark"]{
  --fondo:#0e1320; --hoja:#171e30; --tinta:#eef1f8; --tenue:#a3adc4; --linea:#2b3550;
  --azul:#8fa3ff; --azul-suave:#1f2a55; --miel:#f4b23f; --miel-suave:#3a2c0c; --miel-tinta:#ffd88a;
  --verde:#5fd0aa; --verde-suave:#11362b; --rojo:#ff8a80; color-scheme:dark }
*{box-sizing:border-box}
body{background:var(--fondo);color:var(--tinta);font-family:var(--texto);font-size:16px;line-height:1.55}
.marco{max-width:1180px;margin:0 auto;padding-block:28px 64px;
  padding-left:max(16px, env(safe-area-inset-left, 0px));padding-right:max(16px, env(safe-area-inset-right, 0px));
  display:grid;grid-template-columns:230px minmax(0,1fr);gap:32px;align-items:start}
.indice{position:sticky;top:calc(env(safe-area-inset-top, 0px) + 20px);display:flex;flex-direction:column;gap:14px}
.sello{font-family:var(--display);font-weight:700;font-size:30px;letter-spacing:.02em;line-height:1}
.sello b{color:var(--azul)}
.sello small{display:block;font-family:var(--texto);font-weight:500;font-size:12.5px;color:var(--tenue);letter-spacing:0;margin-top:6px;line-height:1.35}
.indice ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px;counter-reset:hoja}
.indice li{counter-increment:hoja}
.indice a{display:flex;gap:8px;align-items:baseline;padding:6px 8px;border-radius:8px;color:var(--tinta);text-decoration:none;font-size:13.5px;line-height:1.3}
.indice a::before{content:counter(hoja);font-family:var(--mono);font-size:11.5px;color:var(--tenue);min-width:1.4em;text-align:right}
.indice a:hover{background:var(--azul-suave)}
.indice a:focus-visible,button:focus-visible,textarea:focus-visible{outline:3px solid var(--miel);outline-offset:2px}
.indice a.opinada::after{content:"";width:8px;height:8px;border-radius:50%;background:var(--verde);margin-left:auto;flex:none;align-self:center}
.cuenta{font-size:12.5px;color:var(--tenue)}
main{display:flex;flex-direction:column;gap:28px;min-width:0}
.tapa{display:flex;flex-direction:column;gap:10px}
.tapa h1{font-family:var(--display);font-weight:700;font-size:clamp(34px,5vw,52px);line-height:1;text-transform:uppercase;margin:0;text-wrap:balance}
.tapa p{margin:0;max-width:62ch;color:var(--tenue)}
.aviso{background:var(--miel-suave);color:var(--miel-tinta);border-radius:10px;padding:10px 14px;font-size:14px;max-width:62ch}
.hoja{background:var(--hoja);border:1px solid var(--linea);border-radius:14px;padding:28px clamp(18px,4vw,40px) 24px;display:flex;flex-direction:column;gap:18px;scroll-margin-top:16px}
.folio{font-family:var(--mono);font-size:12px;color:var(--tenue);letter-spacing:.06em;text-transform:uppercase}
.hoja h2{font-family:var(--display);font-weight:700;font-size:clamp(26px,3.6vw,36px);line-height:1.05;text-transform:uppercase;margin:0;text-wrap:balance}
.bajada{font-size:18px;color:var(--tenue);margin:0;max-width:60ch}
.hoja p{margin:0;max-width:66ch}
.pasos{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;counter-reset:paso;max-width:68ch}
.pasos li{counter-increment:paso;display:grid;grid-template-columns:30px minmax(0,1fr);gap:12px;align-items:start}
.pasos li::before{content:counter(paso);width:30px;height:30px;border-radius:50%;background:var(--azul);color:var(--hoja);font-weight:700;font-size:14px;display:grid;place-items:center}
.rotulo{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--tenue);margin:0}
figure{margin:0;display:flex;flex-direction:column;gap:8px}
figure img{display:block;width:100%;height:auto;border:1px solid var(--linea);border-radius:10px;background:var(--fondo)}
figcaption{font-size:13.5px;color:var(--tenue);max-width:70ch}
.tips{list-style:none;margin:0;padding:12px 16px;background:var(--miel-suave);color:var(--miel-tinta);border-radius:10px;display:flex;flex-direction:column;gap:6px;max-width:68ch;font-size:15px}
.palabras{margin:0;display:grid;grid-template-columns:minmax(90px,max-content) minmax(0,1fr);gap:6px 16px;font-size:14.5px;max-width:68ch}
.palabras dt{font-weight:700}
.palabras dd{margin:0;color:var(--tenue)}
.opinion{border-top:1px dashed var(--linea);padding-top:16px;display:flex;flex-direction:column;gap:10px}
.opinion label{font-weight:700;font-size:15px}
.opinion textarea{width:100%;min-height:92px;resize:vertical;font:inherit;color:var(--tinta);background:var(--fondo);border:1px solid var(--linea);border-radius:10px;padding:10px 12px}
.fila{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center}
.opinion button{font:inherit;font-weight:700;border:0;border-radius:10px;padding:10px 18px;background:var(--azul);color:var(--hoja);cursor:pointer}
.opinion button[disabled]{opacity:.5;cursor:default}
.estado{font-size:13.5px;color:var(--tenue)}
.estado.ok{color:var(--verde)}
.estado.mal{color:var(--rojo)}
@media (max-width:860px){
  .marco{grid-template-columns:minmax(0,1fr);gap:20px}
  .indice{position:static}
  .indice ol{flex-direction:row;flex-wrap:wrap;gap:6px}
  .indice a{border:1px solid var(--linea);background:var(--hoja)}
  .indice a span{display:none}
  .indice a::before{min-width:0}
  .palabras{grid-template-columns:minmax(0,1fr)}
  .palabras dd{margin-bottom:6px}
}
@media (prefers-reduced-motion:no-preference){ html{scroll-behavior:smooth} }
"""

GUION = r"""
(function () {
  var CLAVE = 'xsii-bancaria-borrador-';
  var cajas = Array.prototype.slice.call(document.querySelectorAll('.opinion'));
  var guardado = {};      // id de hoja -> texto guardado
  var db = null;
  var puedeEscribir = true;

  function borrador(id, valor) {
    try {
      if (valor === undefined) return localStorage.getItem(CLAVE + id) || '';
      if (valor) localStorage.setItem(CLAVE + id, valor); else localStorage.removeItem(CLAVE + id);
    } catch (err) { /* sin almacenamiento: no pasa nada */ }
    return '';
  }
  function decir(caja, texto, clase) {
    var s = caja.querySelector('.estado');
    s.textContent = texto;
    s.className = 'estado' + (clase ? ' ' + clase : '');
  }
  function fecha(iso) {
    try { return new Date(iso).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); }
    catch (err) { return ''; }
  }
  function marcar(id, hay) {
    var a = document.querySelector('.indice a[href="#' + id + '"]');
    if (a) a.classList.toggle('opinada', !!hay);
    var n = document.querySelectorAll('.indice a.opinada').length;
    var c = document.getElementById('cuenta');
    c.textContent = n ? (n === 1 ? '1 página con opinión guardada' : n + ' páginas con opinión guardada') : 'Todavía no hay opiniones guardadas';
  }
  function refrescarBoton(caja) {
    var id = caja.dataset.hoja;
    var area = caja.querySelector('textarea');
    var boton = caja.querySelector('button');
    boton.disabled = !db || !puedeEscribir || area.value.trim() === (guardado[id] || '').trim();
  }

  cajas.forEach(function (caja) {
    var id = caja.dataset.hoja;
    var area = caja.querySelector('textarea');
    var boton = caja.querySelector('button');
    var b = borrador(id);
    if (b) { area.value = b; decir(caja, 'Borrador sin guardar (solo en este navegador).'); }
    area.addEventListener('input', function () {
      borrador(id, area.value);
      refrescarBoton(caja);
      if (area.value.trim() !== (guardado[id] || '').trim()) decir(caja, 'Sin guardar.');
    });
    boton.addEventListener('click', function () {
      if (!db) return;
      var texto = area.value.trim().slice(0, 6000);
      boton.disabled = true;
      decir(caja, 'Guardando…');
      var ref = db.doc('opiniones/' + id);
      var hecho = texto ? ref.set({ hoja: id, titulo: caja.dataset.titulo, texto: texto, cuando: new Date().toISOString() }) : ref.delete();
      hecho.then(function () {
        guardado[id] = texto;
        borrador(id, '');
        marcar(id, !!texto);
        decir(caja, texto ? 'Guardado. Ya lo puedo leer.' : 'Opinión borrada.', 'ok');
        refrescarBoton(caja);
      }).catch(function (err) {
        if (err && err.code === 'invalid_argument') { puedeEscribir = false; }
        decir(caja, 'No se pudo guardar. Tu texto sigue acá; probá de nuevo en un momento.', 'mal');
        refrescarBoton(caja);
      });
    });
    refrescarBoton(caja);
  });

  function sinBase() {
    cajas.forEach(function (caja) {
      if (!caja.querySelector('.estado').textContent) decir(caja, 'Las opiniones se guardan abriendo esta página con tu sesión de Claude.');
    });
  }

  if (!(window.claude && window.claude.use)) { sinBase(); return; }
  window.claude.use('db').then(function (base) {
    if (!base) { sinBase(); return; }
    db = base;
    var reloj = setTimeout(function () {
      cajas.forEach(function (caja) { if (!caja.querySelector('.estado').textContent) decir(caja, 'Todavía no pude traer lo guardado. Podés escribir igual.'); });
    }, 10000);
    db.collection('opiniones').onSnapshot(function (foto) {
      if (!foto.metadata.fromCache) clearTimeout(reloj);
      var vistos = {};
      foto.docs.forEach(function (d) {
        var dato = d.data() || {};
        vistos[d.id] = true;
        var caja = document.querySelector('.opinion[data-hoja="' + d.id + '"]');
        if (!caja) return;
        var texto = typeof dato.texto === 'string' ? dato.texto : '';
        var area = caja.querySelector('textarea');
        var sinTocar = area.value.trim() === '' || area.value.trim() === (guardado[d.id] || '').trim();
        guardado[d.id] = texto;
        if (sinTocar) { area.value = texto; decir(caja, 'Guardado el ' + fecha(dato.cuando) + '.', 'ok'); }
        marcar(d.id, !!texto);
        refrescarBoton(caja);
      });
      cajas.forEach(function (caja) {
        var id = caja.dataset.hoja;
        if (!vistos[id] && guardado[id]) { guardado[id] = ''; marcar(id, false); }
        refrescarBoton(caja);
      });
    }, function () {
      clearTimeout(reloj);
      cajas.forEach(function (caja) { decir(caja, 'No pude conectar con lo guardado. Tu texto queda como borrador en este navegador.', 'mal'); });
    });
  });
})();
"""


def hoja(p: dict, n: int, total: int) -> str:
    partes = [f'<section class="hoja" id="{e(p["id"])}">',
              f'<div class="folio">Página {n} de {total}</div>',
              f'<h2>{e(p["titulo"])}</h2>']
    if p.get("bajada"):
        partes.append(f'<p class="bajada">{e(p["bajada"])}</p>')
    for parrafo in p.get("parrafos") or []:
        partes.append(f"<p>{e(parrafo)}</p>")
    if p.get("pasos"):
        partes.append('<p class="rotulo">Paso a paso</p><ol class="pasos">'
                      + "".join(f"<li><span>{e(x)}</span></li>" for x in p["pasos"]) + "</ol>")
    for f in p.get("figuras") or []:
        partes.append(f'<figure><img src="{e(f["archivo"])}" alt="{e(f.get("pie"))}" loading="lazy">'
                      f'<figcaption>{e(f.get("pie"))}</figcaption></figure>')
    if p.get("tips"):
        partes.append('<ul class="tips">' + "".join(f"<li>{e(x)}</li>" for x in p["tips"]) + "</ul>")
    if p.get("palabras"):
        partes.append('<p class="rotulo">Palabras de esta página</p><dl class="palabras">'
                      + "".join(f'<dt>{e(w["termino"])}</dt><dd>{e(w["significa"])}</dd>' for w in p["palabras"])
                      + "</dl>")
    partes.append(caja(p["id"], p["titulo"], "¿Qué te parece esta página?",
                       "¿Se entiende? ¿Sobra o falta algo? ¿Alguna palabra rara? ¿La captura ayuda?"))
    partes.append("</section>")
    return "\n".join(partes)


def caja(ident: str, titulo: str, pregunta: str, ayuda: str) -> str:
    return (f'<div class="opinion" data-hoja="{e(ident)}" data-titulo="{e(titulo)}">'
            f'<label for="op-{e(ident)}">{e(pregunta)}</label>'
            f'<textarea id="op-{e(ident)}" maxlength="6000" placeholder="{e(ayuda)}"></textarea>'
            f'<div class="fila"><button type="button" id="bt-{e(ident)}" disabled>Guardar opinión</button>'
            f'<span class="estado" role="status"></span></div></div>')


def armar(paginas: list) -> str:
    total = len(paginas)
    indice = "".join(f'<li><a href="#{e(p["id"])}"><span>{e(p["titulo"])}</span></a></li>' for p in paginas)
    hojas = "\n".join(hoja(p, i + 1, total) for i, p in enumerate(paginas))
    return f"""<title>XSII para La Bancaria</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;700&display=swap">
<style>{ESTILO}</style>
<div class="marco">
<nav class="indice" aria-label="Páginas del tutorial">
<div class="sello">XS<b>II</b><small>Tutorial para implementar La Bancaria · primera versión</small></div>
<ol>{indice}<li><a href="#general"><span>Opinión general</span></a></li></ol>
<div class="cuenta" id="cuenta">Todavía no hay opiniones guardadas</div>
</nav>
<main>
<header class="tapa">
<h1>XSII, paso a paso, para implementar La Bancaria</h1>
<p>Una guía corta para quien se suma al equipo y todavía no conoce las palabras del proyecto. Son {total} páginas; cada una se lee en dos minutos.</p>
<div class="aviso">Borrador para revisar. Al pie de cada página hay una caja: escribí qué cambiarías y tocá «Guardar opinión». Las capturas usan datos inventados.</div>
</header>
{hojas}
<section class="hoja" id="general">
<div class="folio">Para cerrar</div>
<h2>Opinión general</h2>
<p>Lo que no entra en una página puntual: el orden, el largo, el tono, qué tema falta o cuál sobra.</p>
{caja("general", "Opinión general", "¿Qué cambiarías del tutorial entero?", "Orden de las páginas, temas que faltan, nivel de detalle…")}
</section>
</main>
</div>
<script>{GUION}</script>
"""


def main() -> None:
    salida = Path(sys.argv[1]) if len(sys.argv) > 1 else AQUI / "salida"
    paginas = json.loads((AQUI / "paginas.json").read_text(encoding="utf-8"))
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "xsii-bancaria.html").write_text(armar(paginas), encoding="utf-8")
    destino = salida / "img"
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(AQUI / "img", destino)
    figuras = sum(len(p.get("figuras") or []) for p in paginas)
    print(f"{len(paginas)} hojas, {figuras} figuras -> {salida / 'xsii-bancaria.html'}")


if __name__ == "__main__":
    main()
