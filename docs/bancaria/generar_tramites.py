# Genera docs/bancaria/tramites-bancaria.html (el informe de trámites de La
# Bancaria) a partir de tramites-bancaria.json y tramites-bancaria.plantilla.html.
# Todos los números de la página salen del JSON: no hay totales a mano.
# Para corregir una gestión se edita el JSON y se corre:
#   python docs/bancaria/generar_tramites.py
# El JSON es el resultado de la verificación fila por fila del 2026-10-13
# (labancaria.org, Seccional Buenos Aires y los sistemas propios del sindicato).
import collections
import html
import json
from pathlib import Path

AQUI = Path(__file__).parent
DATOS = AQUI / "tramites-bancaria.json"
SALIDA = AQUI / "tramites-bancaria.html"
PLANTILLA = AQUI / "tramites-bancaria.plantilla.html"

EJES = [
    ("afil",    "Afiliación, datos e identidad"),
    ("recibo",  "Recibo, salario y convenio"),
    ("trabajo", "Licencias, condiciones de trabajo y reclamos"),
    ("social",  "Acción social, turismo y beneficios"),
    ("form",    "Formación y cultura"),
    ("prev",    "Previsión y jubilados"),
    ("inst",    "Vida institucional y comunicación"),
    ("emp",     "Bancos empleadores, endeudamiento y vivienda"),
]
MODALIDAD = {
    "online":      ("Online", "Todo el circuito se resuelve por internet y la respuesta llega por el mismo medio."),
    "semi-online": ("Semi-online", "Empieza por web, WhatsApp o mail, pero hay papeles, pago en banco, paso por la sede o la respuesta llega por fuera."),
    "presencial":  ("Presencial", "Hay que ir a la sede, la seccional o entregar un papel."),
    "no_dice":     ("Existe, sin canal publicado", "El servicio existe pero la web no dice cómo se pide."),
    "no_existe":   ("Sin canal", "No hay canal: el afiliado no tiene a quién pedírselo, o solo hay acción colectiva del sindicato."),
}
ESTRATEGIA = {
    "crear_de_cero":       ("Nuevo en Colm3na", "Hoy no hay canal: Colm3na lo crea."),
    "reemplazar":          ("Reemplaza el canal actual", "El papel, el Google Form o el WhatsApp pasan a un trámite."),
    "puerta_y_encadenado": ("Puerta del afiliado", "El afiliado pide y sigue en Colm3na; el sindicato sigue usando su sistema interno. Respuestas y comprobantes van por trámites encadenados."),
    "informar":            ("Informar", "Aviso, noticia, enlace o el bot del convenio: no hace falta formulario."),
}
NIVEL = {
    "listo":      ("Listo hoy", "Se configura con lo que Colm3na ya tiene."),
    "ajuste":     ("Ajuste menor", "Cambio chico sobre un módulo existente."),
    "desarrollo": ("Desarrollo", "Pieza nueva."),
    "fuera":      ("Fuera de alcance", "No corresponde a Colm3na."),
}
# Lo que el afiliado usa desde el primer día sin un formulario nuevo (sale del JSON por id).
SIN_FORMULARIO = ["T07", "T21", "T08", "T16", "T23", "T68", "T73", "T34", "T76", "T54"]

e = html.escape
D = json.loads(DATOS.read_text(encoding="utf-8"))
AF = [x for x in D if x["dirigido_al_afiliado"]]
NO_AF = [x for x in D if not x["dirigido_al_afiliado"]]
por_id = {x["id"]: x for x in D}
cm = collections.Counter(x["hoy"]["modalidad"] for x in AF)
ce = collections.Counter(x["colm3na"]["estrategia"] for x in AF)
cn = collections.Counter(x["colm3na"]["nivel"] for x in AF)


def chip(clase, texto, titulo=""):
    t = f' title="{e(titulo)}"' if titulo else ""
    return f'<span class="chip-e {clase}"{t}>{e(texto)}</span>'


def corto(u):
    s = u.replace("https://", "").replace("http://", "").rstrip("/")
    return s if len(s) <= 52 else s[:50] + "…"


def tarjeta(x):
    h, c = x["hoy"], x["colm3na"]
    mod, est, niv = h["modalidad"], c["estrategia"], c["nivel"]
    kit = {"kit": chip("k-kit", "Kit de inicio"), "segunda": chip("k-seg", "Segunda tanda")}.get(x.get("kit", ""), "")
    conf = "" if h.get("confianza") == "verificado" else chip("k-ded", "deducido", "Se deduce de la web; no está escrito como trámite")
    fuentes = "".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(corto(u))}</a>' if u.startswith("http") else f"<span>{e(u)}</span>"
                      for u in h.get("fuentes", [])) or "<span>Sin fuente: no hay canal publicado en ninguna de las páginas relevadas.</span>"
    detalle = []
    for rot, val in (("Formulario", c.get("formulario")), ("Formularios encadenados", c.get("encadenados")),
                     ("Área que lo atiende", c.get("area")), ("Qué falta", c.get("falta"))):
        if val:
            detalle.append(f"<dt>{rot}</dt><dd>{e(val)}</dd>")
    det = f'<details><summary>Diseño en Colm3na</summary><dl>{"".join(detalle)}</dl></details>' if detalle else ""
    req = f'<p class="req"><b>Requisitos:</b> {e(h["requisitos"])}</p>' if h.get("requisitos") else ""
    sis = f'<p class="req"><b>Sistema interno:</b> {e(h["sistema_interno"])}</p>' if h.get("sistema_interno") else ""
    inc = f'<p class="inc">Incluye: {e(" · ".join(x["incluye"]))}</p>' if x.get("incluye") else ""
    val = f'<p class="validar"><b>Para validar con el sindicato:</b> {e(x["validar_con_sindicato"])}</p>' if x.get("validar_con_sindicato") else ""
    return (f'<article class="tr" data-mod="{mod}" data-est="{est}" data-niv="{niv}" data-kit="{x.get("kit", "")}" id="{e(x["id"])}">'
            f'<header class="tr-cab"><h4>{e(x["nombre"])}</h4><div class="tr-chips">{kit}{conf}</div>'
            f'<p class="quien">{e(x["quien"])}</p>{inc}</header>'
            f'<div class="tr-cols"><section class="tr-hoy"><p class="rot">Hoy {chip("m-" + mod, MODALIDAD[mod][0], MODALIDAD[mod][1])}</p>'
            f'<p>{e(h["circuito"])}</p>{req}{sis}<p class="fuentes">{fuentes}</p></section>'
            f'<section class="tr-col"><p class="rot">En Colm3na {chip("e-" + est, ESTRATEGIA[est][0], ESTRATEGIA[est][1])}{chip("n-" + niv, NIVEL[niv][0], NIVEL[niv][1])}</p>'
            f'<p>{e(c["propuesta"])}</p>{det}</section></div>{val}</article>')


catalogo = []
for k, titulo in EJES:
    items = [x for x in AF if x["eje"] == k]
    if not items:
        continue
    cnt = collections.Counter(x["colm3na"]["nivel"] for x in items)
    res = " · ".join(f"{cnt[n]} {NIVEL[n][0].lower()}" for n in NIVEL if cnt[n])
    catalogo.append(f'<section class="eje" id="eje-{k}"><header class="eje-cab"><h3>{e(titulo)}</h3>'
                    f'<p class="eje-res">{len(items)} gestiones · {res}</p></header>{"".join(tarjeta(x) for x in items)}</section>')


def lista_kit(ids, con_area=True):
    out = []
    for i in ids:
        x = por_id[i]
        area = f'<span class="kit-area">{e(x["colm3na"]["area"])}</span>' if con_area else ""
        out.append(f'<li><a href="#{e(i)}"><b>{e(x["nombre"])}</b></a>{area}<span>{e(x["kit_inicio"]["por_que"])}</span></li>')
    return "".join(out)


# El kit se lista por tema, empezando por lo que más gente pide.
ORDEN_KIT = ["social", "recibo", "trabajo", "prev", "afil", "inst", "form", "emp"]
KIT = [x["id"] for x in sorted(D, key=lambda x: ORDEN_KIT.index(x["eje"])) if x.get("kit") == "kit"]
SEG = [x["id"] for x in sorted(D, key=lambda x: ORDEN_KIT.index(x["eje"])) if x.get("kit") == "segunda"]


def barra(contador, catalogo_nombres, prefijo):
    total = sum(contador.values())
    segs = "".join(f'<span class="seg {prefijo}{k}" style="flex:{contador[k]}" title="{e(v[0])}: {contador[k]}"></span>' for k, v in catalogo_nombres.items() if contador[k])
    ley = "".join(f'<li><span class="pt {prefijo}{k}"></span>{e(v[0])} <b>{contador[k]}</b></li>' for k, v in catalogo_nombres.items() if contador[k])
    return f'<div class="barra-g">{segs}</div><ul class="ley-g">{ley}</ul><p class="tot">{total} gestiones del afiliado</p>'


def filtros():
    out = ['<div class="filtros" role="group" aria-label="Filtrar el catálogo">',
           '<button type="button" class="f activo" data-f="todos">Todas</button>',
           f'<button type="button" class="f" data-f="kit:kit">Kit de inicio ({len(KIT)})</button>']
    for k, v in NIVEL.items():
        if cn[k]:
            out.append(f'<button type="button" class="f" data-f="niv:{k}">{e(v[0])} ({cn[k]})</button>')
    for k, v in ESTRATEGIA.items():
        if ce[k]:
            out.append(f'<button type="button" class="f" data-f="est:{k}">{e(v[0])} ({ce[k]})</button>')
    for k, v in MODALIDAD.items():
        if cm[k]:
            out.append(f'<button type="button" class="f" data-f="mod:{k}">Hoy: {e(v[0].lower())} ({cm[k]})</button>')
    out.append("</div>")
    return "".join(out)


fuera = "".join(f'<li><b>{e(x["nombre"])}</b>: {e(x["colm3na"]["propuesta"])}</li>' for x in NO_AF)
sin_canal = cm["no_existe"] + cm["no_dice"]
valores = {
    "AF": len(AF), "ONLINE": cm["online"], "SEMI": cm["semi-online"], "PRESENCIAL": cm["presencial"],
    "SINCANAL": sin_canal, "LISTO": cn["listo"], "AJUSTE": cn["ajuste"], "DESARROLLO": cn["desarrollo"],
    "NKIT": len(KIT), "NSEG": len(SEG),
    "BARRA_HOY": barra(cm, MODALIDAD, "m-"), "BARRA_EST": barra(ce, ESTRATEGIA, "e-"),
    "KIT": lista_kit(KIT), "SEGUNDA": lista_kit(SEG), "SINFORM": lista_kit(SIN_FORMULARIO, con_area=False),
    "FILTROS": filtros(), "CATALOGO": "\n".join(catalogo), "FUERA": fuera,
}
salida = PLANTILLA.read_text(encoding="utf-8")
for k, v in valores.items():
    salida = salida.replace("{{" + k + "}}", str(v))
assert "{{" not in salida, "quedó un marcador sin reemplazar"
SALIDA.write_text(salida, encoding="utf-8")
print(f"{len(D)} filas, {len(AF)} del afiliado; hoy {dict(cm)}; nivel {dict(cn)}; kit {len(KIT)} + {len(SEG)}")
