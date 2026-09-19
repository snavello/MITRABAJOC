"""Arma recursos/bitacora.html a partir de BITACORA.md para la landing
/entornos → Recursos. Solo stdlib. Correr desde la raíz del repo:

    python generar_bitacora.py

Lee las tablas del markdown (una por mes), las vuelca en HTML con la estética
de los otros recursos (Barlow Condensed, tinta, miel) y agrega un buscador y
filtros por herramienta que corren en el navegador. La fecha de edición y el
commit se toman solos. Code lo corre al cerrar cada bloque (ver CLAUDE.md,
"Bitácora y cierre de bloque")."""
import re
import subprocess
from html import escape as e
from pathlib import Path

import fechas

RAIZ = Path(__file__).resolve().parent
ORIGEN = RAIZ / "BITACORA.md"
DESTINO = RAIZ / "recursos" / "bitacora.html"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
COLORES = {"Code": "azul", "Chat": "violeta", "Cowork": "verde", "Manual": "agua"}


def _commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "local"


def _inline(txt: str) -> str:
    """Negrita y código del markdown; el resto escapado."""
    txt = e(txt)
    txt = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", txt)
    txt = re.sub(r"`([^`]+)`", r"<code>\1</code>", txt)
    return txt


def _chips(herr: str) -> str:
    partes = re.split(r"\s*(?:→|\+|,)\s*", herr)
    return "".join(f'<span class="chip {COLORES.get(p, "gris")}">{e(p)}</span>' for p in partes if p)


def leer(md: str):
    """Devuelve [(titulo_mes, [filas])] con filas = listas de 6 celdas."""
    bloques, actual = [], None
    for linea in md.splitlines():
        if linea.startswith("## "):
            actual = (linea[3:].strip(), [])
            bloques.append(actual)
        elif actual and linea.startswith("|") and not re.match(r"^\|\s*-", linea):
            celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
            if len(celdas) == 6 and celdas[0] != "Fecha":
                actual[1].append(celdas)
    return [b for b in bloques if b[1]]


def render(bloques) -> str:
    total = sum(len(f) for _, f in bloques)
    hoy = fechas.hoy()          # la hora de Buenos Aires, no la del servidor (test_fechas.py)
    cuerpo = []
    for titulo, filas in reversed(bloques):  # el mes más reciente arriba
        cuerpo.append(f'<section><h2>{_inline(titulo)}</h2><table><thead><tr>'
                      '<th>Fecha</th><th>Herr.</th><th>Módulo</th><th>Qué se hizo</th>'
                      '<th>Dónde</th><th>Quién</th></tr></thead><tbody>')
        for f in reversed(filas):
            herr = re.sub(r"[`*]", "", f[1])
            cuerpo.append(f'<tr data-h="{e(herr)}"><td class="f">{e(f[0])}</td><td>{_chips(herr)}</td>'
                          f'<td class="m">{_inline(f[2])}</td><td>{_inline(f[3])}</td>'
                          f'<td class="d">{_inline(f[4])}</td><td class="q">{_inline(f[5])}</td></tr>')
        cuerpo.append("</tbody></table></section>")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bitácora Colm3na</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600&family=Barlow+Condensed:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{{--tinta:#0a1421;--miel:#f0a01e;--agua:#a0030b;--verde:#0f8a6a;--azul:#2e5c8a;--violeta:#7a2e8f;--gris:#5b6b80;
--papel:#f4f6f9;--blanco:#fff;--linea:#dbe2ea;--texto:#16243a;--texto2:#4c5d75;--suave:#eef2f7;
--display:'Barlow Condensed','Arial Narrow',sans-serif;--body:'Barlow',system-ui,sans-serif;--mono:ui-monospace,Consolas,monospace;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--papel:#0e1622;--blanco:#152030;--linea:#2a3748;--texto:#e6ecf4;--texto2:#a3b1c4;--suave:#1c2838;--azul:#8db6e3;--verde:#3fbf98;--violeta:#c39ad6;--agua:#e2565f;--gris:#9fb0c4;color-scheme:dark}}}}
:root[data-theme="dark"]{{--papel:#0e1622;--blanco:#152030;--linea:#2a3748;--texto:#e6ecf4;--texto2:#a3b1c4;--suave:#1c2838;--azul:#8db6e3;--verde:#3fbf98;--violeta:#c39ad6;--agua:#e2565f;--gris:#9fb0c4;color-scheme:dark}}
*{{box-sizing:border-box;margin:0}}body{{background:var(--papel);color:var(--texto);font-family:var(--body);font-size:14px;line-height:1.45}}
code{{font-family:var(--mono);font-size:.88em;background:var(--suave);padding:1px 4px;border-radius:4px;white-space:nowrap}}
.top{{background:linear-gradient(160deg,#0d1626 20%,var(--tinta) 70%,#24354f);color:#fff;padding:24px clamp(16px,4vw,48px) 20px}}
.top code{{background:rgba(255,255,255,.14);color:#fff}}
.eyebrow{{font-family:var(--display);font-weight:600;letter-spacing:2.4px;text-transform:uppercase;color:var(--miel);font-size:13px}}
.top h1{{font-family:var(--display);font-weight:700;font-size:clamp(30px,4.5vw,48px);line-height:1;margin:6px 0 8px}}
.top p{{max-width:80ch;color:rgba(255,255,255,.8)}}.top .datos{{display:flex;flex-wrap:wrap;gap:8px 24px;margin-top:12px;font-size:13px;color:rgba(255,255,255,.7)}}
.barra{{position:sticky;top:0;z-index:2;background:var(--blanco);border-bottom:1px solid var(--linea);padding:10px clamp(16px,4vw,48px);display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.barra input{{flex:1;min-width:200px;padding:8px 12px;border:1px solid var(--linea);border-radius:8px;background:var(--papel);color:var(--texto);font:inherit}}
.barra button{{font:inherit;font-size:13px;padding:6px 10px;border-radius:999px;border:1px solid var(--linea);background:var(--blanco);color:var(--texto2);cursor:pointer}}
.barra button.on{{background:var(--tinta);color:#fff;border-color:var(--tinta)}}
main{{padding:16px clamp(16px,4vw,48px) 48px}}section{{margin-bottom:28px}}
h2{{font-family:var(--display);font-weight:700;font-size:24px;margin:8px 0 10px;color:var(--texto)}}
table{{width:100%;border-collapse:collapse;background:var(--blanco);border:1px solid var(--linea);border-radius:10px;overflow:hidden}}
th{{text-align:left;font-family:var(--display);font-weight:600;font-size:13px;letter-spacing:1px;text-transform:uppercase;color:var(--texto2);padding:8px 10px;border-bottom:1px solid var(--linea);background:var(--suave)}}
td{{padding:8px 10px;border-bottom:1px solid var(--linea);vertical-align:top}}tr:last-child td{{border-bottom:0}}tr.oculta{{display:none}}
td.f{{white-space:nowrap;font-family:var(--mono);font-size:12.5px;color:var(--texto2)}}td.m{{font-weight:600;min-width:110px}}td.d{{font-size:12.5px;color:var(--texto2);min-width:160px}}td.q{{white-space:nowrap}}
.chip{{display:inline-block;font-family:var(--display);font-weight:600;font-size:12px;letter-spacing:.6px;padding:1px 7px;border-radius:999px;color:#fff;margin:1px 2px 1px 0}}
.chip.azul{{background:var(--azul)}}.chip.violeta{{background:var(--violeta)}}.chip.verde{{background:var(--verde)}}.chip.agua{{background:var(--agua)}}.chip.gris{{background:var(--gris)}}
.vacio{{padding:24px;color:var(--texto2);text-align:center;display:none}}
@media (max-width:760px){{table,thead,tbody,tr,td{{display:block}}thead{{display:none}}tr{{border-bottom:1px solid var(--linea);padding:6px 0}}td{{border:0;padding:3px 10px}}td.d{{min-width:0}}}}
</style></head><body>
<header class="top"><div class="eyebrow">Colm3na · Bitácora del proyecto</div><h1>Qué se hizo, con qué y dónde está</h1>
<p>Una línea por bloque de trabajo, del más reciente al más antiguo. El detalle técnico está en <code>HISTORIAL.md</code>; el estado vigente, en <code>CLAUDE.md</code>. La fuente es <code>BITACORA.md</code> en el repo.</p>
<div class="datos"><span>{total} bloques</span><span>Edición: {hoy.day} de {MESES[hoy.month-1]} de {hoy.year}</span><span>Commit: <code>{_commit()}</code></span></div></header>
<div class="barra"><input id="q" type="search" placeholder="Buscar módulo, texto, commit, chat…" autocomplete="off">
<button data-f="" class="on">Todo</button><button data-f="Code">Code</button><button data-f="Chat">Chat</button><button data-f="Cowork">Cowork</button><button data-f="Manual">Manual</button></div>
<main>{''.join(cuerpo)}<p class="vacio" id="vacio">Nada coincide con la búsqueda.</p></main>
<script>
(function(){{var q=document.getElementById('q'),bs=document.querySelectorAll('.barra button'),f='';
function ap(){{var t=q.value.trim().toLowerCase(),n=0;document.querySelectorAll('tbody tr').forEach(function(r){{
var ok=(!f||r.dataset.h.indexOf(f)>=0)&&(!t||r.textContent.toLowerCase().indexOf(t)>=0);r.classList.toggle('oculta',!ok);if(ok)n++;}});
document.querySelectorAll('section').forEach(function(s){{s.style.display=s.querySelector('tbody tr:not(.oculta)')?'':'none';}});
document.getElementById('vacio').style.display=n?'none':'block';}}
q.addEventListener('input',ap);bs.forEach(function(b){{b.addEventListener('click',function(){{bs.forEach(function(x){{x.classList.remove('on');}});b.classList.add('on');f=b.dataset.f;ap();}});}});
}})();
</script></body></html>"""


if __name__ == "__main__":
    bloques = leer(ORIGEN.read_text(encoding="utf-8"))
    DESTINO.parent.mkdir(exist_ok=True)
    DESTINO.write_text(render(bloques), encoding="utf-8")
    print(f"{DESTINO.relative_to(RAIZ)}: {sum(len(f) for _, f in bloques)} bloques en {len(bloques)} meses")
