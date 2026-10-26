import json
F = 30
def fr(t): return int(round(t * F))
V = {"01": 8.064, "02": 6.936, "03": 7.296, "04": 5.184, "05": 4.776, "06": 7.392, "07": 8.28, "08": 4.08}
nom = {"01": "01_cerca", "02": "02_media_hora", "03": "03_entiende", "04": "04_preguntas", "05": "05_circuito", "06": "06_publicada", "07": "07_celular", "08": "08_cierre"}
t = {"01": 0.8}
for a, b, gap in [("01", "02", 0.4), ("02", "03", 0.4), ("03", "04", 0.4), ("04", "05", 0.4), ("05", "06", 2.1), ("06", "07", 0.4), ("07", "08", 1.7)]:
    t[b] = round(t[a] + V[a] + gap, 2)
DUR = round(t["08"] + V["08"] + 2.0, 2)
voces = [{"archivo": "v3/" + nom[k] + ".mp3", "t": t[k]} for k in V]
PANT = dict(clase="pantalla", w=1760, h=990); TEL = dict(clase="telefono", w=430, h=930)
A = dict(dir="asistente2", prefijo="a"); M = dict(dir="movil2", prefijo="m"); P = dict(dir="portada", prefijo="p"); B = dict(dir="bandeja", prefijo="b")
S = []; R = []
# A: portada en el celular
a0, a1 = 2.0, t["02"] - 0.3
S.append(dict(id="port", **TEL, t0=a0, t1=a1, fade_in=0.5, reflejo=0.25, z=2, suelo=0.9, fx=62, fy=40,
  fuente=dict(**P, tramos=[dict(u0=0, u1=0.35, i0=40, i1=125), dict(u0=0.35, u1=1.0, i0=125, i1=300)]),
  cam=[dict(t=a0, tx=160, ty=60, tz=-560, rx=8, ry=36, rz=-4, s=1), dict(t=a0+2.6, tx=60, ty=10, tz=-40, rx=2, ry=12, rz=0, s=1, e="out"), dict(t=a1, tx=-10, ty=-10, tz=50, rx=-1, ry=-9, rz=0, s=1)]))
R.append(dict(t0=a0+0.6, t1=a1-0.3, h="Más cerca de <b>los trabajadores</b>", s="La app del afiliado, con la marca del sindicato: recibos, credencial, novedades y gestiones electrónicas."))
# B: el relato (acelerado)
b0, b1 = a1, t["03"] - 0.2
S.append(dict(id="asis", **PANT, t0=b0, t1=b1, fade_in=0.4, fuente=dict(**A, i0=0, i1=fr(12.6)),
  cam=[dict(t=b0, tx=140, ty=30, tz=-700, rx=6, ry=-26, rz=2, s=1), dict(t=b0+2.4, tx=0, ty=0, tz=-60, rx=0, ry=-4, rz=0, s=1, e="out"), dict(t=b1, tx=0, ty=0, tz=0, ry=0, s=1)]))
R.append(dict(t0=b0+0.6, t1=b1-0.2, h="Cualquier gestión, <b>en media hora</b>", s="Contada en lenguaje natural por alguien del sindicato: sin programar, sin intervención técnica."))
# C: lo entendió
c0, c1 = b1, t["04"] - 0.2
S.append(dict(id="asis", **PANT, t0=c0, t1=c1, fuente=dict(**A, i0=fr(12.6), i1=fr(19.0)), cam=[dict(t=c0, tx=0, ty=0, tz=0, ry=0, s=1), dict(t=c1, tx=0, ty=-10, tz=40, ry=0, s=1)]))
R.append(dict(t0=c0+0.5, t1=c1-0.2, h="La IA <b>la entiende</b>", s="Quién la pide, quién la revisa, qué datos lleva y cómo termina. Lo que propone, marcado como «IA»."))
# D: seis preguntas
d0, d1 = c1, t["05"] - 0.2
S.append(dict(id="asis", **PANT, t0=d0, t1=d1, fuente=dict(**A, i0=fr(19.0), i1=fr(27.1)), cam=[dict(t=d0, tx=0, ty=0, tz=-140, rx=0, ry=12, s=1), dict(t=d0+2.0, tx=0, ty=0, tz=0, ry=0, s=1, e="out"), dict(t=d1, tx=0, ty=0, tz=0, s=1)]))
R.append(dict(t0=d0+0.5, t1=d1-0.2, h="<b>Seis preguntas</b>", s="Con la respuesta recomendada ya puesta: un clic por cada una, o se cambia."))
# E: los datos (barrido rápido) y F: el vuelo
e0, e1 = d1, d1 + 2.6
S.append(dict(id="asis", **PANT, t0=e0, t1=e1 + 0.6, fade_out=0.6, fuente=dict(**A, i0=fr(27.1), i1=fr(36.5)), cam=[dict(t=e0, tx=0, ty=0, tz=0, rx=0, s=1), dict(t=e1 + 0.6, tx=0, ty=0, tz=-320, rx=20, s=1)]))
f0, f1 = e1, t["06"] - 0.4
S.append(dict(id="piso", clase="piso", w=3000, h=476, t0=f0, t1=f1, fade_in=0.7, imagen="frames/diagrama.png", z=3, suelo=0.6,
  cam=[dict(t=f0, tx=1500, ty=160, tz=-900, rx=58, ry=0, rz=0, s=1.3), dict(t=f0+1.6, tx=1050, ty=110, tz=-250, rx=55, ry=6, rz=-2, s=1.42, e="out"),
       dict(t=f1-1.2, tx=-1100, ty=80, tz=-200, rx=51, ry=-6, rz=2, s=1.42), dict(t=f1, tx=-1550, ty=120, tz=-700, rx=56, ry=-10, rz=2, s=1.3)]))
R.append(dict(t0=e0+0.4, t1=f1-0.3, h="Datos, controles <b>y circuito</b>", s="El circuito completo, actor por actor, lo arma el asistente."))
# G: publicada en la app
g0, g1 = f1, t["07"] - 0.2
gm = g0 + 2.4
S.append(dict(id="asis", **PANT, t0=g0, t1=gm, fade_in=0.4, fuente=dict(**A, i0=fr(39.7), i1=fr(42.5)), cam=[dict(t=g0, tx=0, ty=0, tz=-200, ry=8, s=1), dict(t=gm, tx=0, ty=0, tz=0, ry=0, s=1)]))
S.append(dict(id="cel", **TEL, t0=gm, t1=g1, fade_in=0.4, reflejo=0.2, z=2, suelo=0.8, fuente=dict(**M, tramos=[dict(u0=0, u1=0.25, i0=0, i1=0), dict(u0=0.25, u1=0.6, i0=0, i1=fr(1.3)), dict(u0=0.6, u1=1.0, i0=fr(1.3), i1=fr(1.3))]),
  cam=[dict(t=gm, tx=0, ty=20, tz=-260, rx=4, ry=24, s=1), dict(t=g1, tx=0, ty=10, tz=-40, rx=2, ry=10, s=1)]))
R.append(dict(t0=g0+0.5, t1=g1-0.2, h="Publicada en la app, <b>minutos después</b>", s="Con la marca del sindicato. Un ejemplo: el kit escolar."))
# H: el afiliado completa; I: sello y expediente; J: bandeja del panel
h0, h1 = g1, g1 + 4.4
S.append(dict(id="cel", **TEL, t0=h0, t1=h1, reflejo=0.2, z=2, suelo=0.8, fuente=dict(**M, i0=fr(1.3), i1=fr(6.0)),
  cam=[dict(t=h0, tx=0, ty=10, tz=-40, rx=2, ry=10, s=1), dict(t=h0+1.6, tx=400, ty=0, tz=50, rx=0, ry=-14, rz=-2, s=1), dict(t=h1, tx=420, ty=0, tz=90, rx=0, ry=0, rz=0, s=1)]))
i0, i1 = h1, h1 + 2.6
S.append(dict(id="cel", **TEL, t0=i0, t1=i1, z=2, suelo=0.8, flare=False, fuente=dict(**M, tramos=[dict(u0=0, u1=0.5, i0=fr(6.0), i1=fr(8.3)), dict(u0=0.5, u1=1.0, i0=fr(9.0), i1=fr(12.0))]),
  cam=[dict(t=i0, tx=420, ty=0, tz=90, s=1, zs=1, zx=.5, zy=.5), dict(t=i0+0.8, tx=420, ty=0, tz=120, s=1, zs=1.3, zx=.5, zy=.6, e="out"), dict(t=i1, tx=420, ty=0, tz=60, s=1, zs=1.05, zx=.5, zy=.55)]))
j0, j1 = i1, t["08"] - 0.3
S.append(dict(id="band", **PANT, t0=j0, t1=j1, fade_in=0.4, fuente=dict(**B, i0=0, i1=180), cam=[dict(t=j0, tx=60, ty=20, tz=-420, rx=4, ry=-18, s=1), dict(t=j1, tx=0, ty=0, tz=-80, rx=0, ry=-6, s=1)]))
R.append(dict(t0=h0+0.5, t1=j1-0.3, h="Desde el celular <b>del afiliado</b>", s="Expediente numerado, estado a la vista, y el pedido en la bandeja del área que lo atiende."))
placas = [dict(t0=0.0, t1=2.2, h="Gestiones electrónicas <b>fáciles</b>", s="Una herramienta de última tecnología para estar más cerca de los trabajadores"),
          dict(t0=j1, t1=DUR, h="Gestiones electrónicas <b>fáciles</b>", s="Colm3na · de una necesidad en palabras a una gestión digital, en media hora")]
negros = [dict(t0=0, t1=0.5, a0=1, a1=0), dict(t0=DUR-0.9, t1=DUR, a0=0, a1=1)]
secc = [[0, b0, "intro"], [b0, e1, "drop"], [e1, f1, "break"], [f1, DUR - 3.5, "drop"]]
tl = dict(duracion=DUR, shots=S, rotulos=R, placas=placas, negros=negros, voces=voces, musica=dict(archivo="tecno.wav", desde=0.0, volumen=0.85, bpm=124, secciones=secc))
json.dump(tl, open("timeline2.json", "w"), indent=1, ensure_ascii=False)
json.dump(tl, open("timeline3.json", "w"), indent=1, ensure_ascii=False)
print("DUR", DUR, t, "secciones", secc)
