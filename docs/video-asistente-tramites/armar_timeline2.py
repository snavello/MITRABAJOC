import json
F = 30
def fr(t): return int(round(t * F))
V = {"01": 13.30, "02": 13.78, "03": 6.89, "04": 8.88, "05": 9.50, "06": 11.54, "07": 6.22, "08": 10.85, "09": 8.86, "10": 6.98}
nom = {"01": "01_josefina", "02": "02_relato", "03": "03_entiende", "04": "04_preguntas", "05": "05_datos", "06": "06_circuito", "07": "07_minutos", "08": "08_celular", "09": "09_enviado", "10": "10_cierre"}
# tiempos de arranque de cada voz
t = {}; t["01"] = 2.4
t["02"] = t["01"] + V["01"] + 0.5
t["03"] = t["02"] + V["02"] + 0.6
t["04"] = t["03"] + V["03"] + 0.5
t["05"] = t["04"] + V["04"] + 0.5
t["06"] = t["05"] + V["05"] + 0.5
t["07"] = t["06"] + V["06"] + 0.5
t["08"] = t["07"] + V["07"] + 0.4
t["09"] = t["08"] + V["08"] + 0.3
t["10"] = t["09"] + V["09"] + 0.9
fin10 = t["10"] + V["10"]
DUR = round(fin10 + 2.2, 2)
voces = [{"archivo": nom[k] + ".mp3", "t": round(t[k], 3)} for k in V]
PANT = dict(clase="pantalla", w=1760, h=990)
TEL = dict(clase="telefono", w=430, h=930)
A = dict(dir="asistente2", prefijo="a"); M = dict(dir="movil2", prefijo="m"); P = dict(dir="portada", prefijo="p"); B = dict(dir="bandeja", prefijo="b")
shots = []; rot = []
# --- A: portada de Josefina (teléfono 3D)
a0, a1 = 2.0, t["02"] - 0.2
shots.append(dict(id="port", **TEL, t0=a0, t1=a1, fade_in=0.6, reflejo=0.25, z=2,
  fuente=dict(**P, tramos=[dict(u0=0, u1=0.32, i0=30, i1=120), dict(u0=0.32, u1=0.8, i0=120, i1=300), dict(u0=0.8, u1=1.0, i0=300, i1=380)]),
  cam=[dict(t=a0, tx=120, ty=40, tz=-520, rx=6, ry=34, rz=-3, s=1), dict(t=a0+3.2, tx=40, ty=10, tz=-60, rx=2, ry=12, rz=0, s=1, e="out"), dict(t=a1-2.5, tx=-20, ty=-10, tz=40, rx=-1, ry=-8, rz=0, s=1), dict(t=a1, tx=-30, ty=-10, tz=40, rx=-1, ry=-10, rz=0, s=1)]))
rot.append(dict(t0=t["01"]+0.6, t1=t["01"]+7.2, h="Josefina, afiliada a <b>La Bancaria</b>", s="Cada diciembre, el kit escolar: formulario en papel, fotocopias y una cola en la seccional."))
rot.append(dict(t0=t["01"]+8.2, t1=t["02"]-0.4, h="Su sindicato ya usa <b>Colm3na</b>", s="La app del afiliado: recibos, credencial, trámites, novedades y beneficios, con la marca del gremio."))
# --- B: el relato (pantalla, entra en ángulo y se endereza)
b0, b1 = a1, t["03"] - 0.3
shots.append(dict(id="asis", **PANT, t0=b0, t1=b1, fade_in=0.5, fuente=dict(**A, i0=0, i1=fr(12.6)),
  cam=[dict(t=b0, tx=140, ty=30, tz=-700, rx=6, ry=-26, rz=2, s=1), dict(t=b0+3.0, tx=0, ty=0, tz=-60, rx=0, ry=-4, rz=0, s=1, e="out"), dict(t=b1, tx=0, ty=0, tz=0, rx=0, ry=0, rz=0, s=1)]))
rot.append(dict(t0=t["02"]+0.8, t1=t["02"]+7.6, h="El <b>Asistente de trámites</b> de Colm3na", s="Alguien de Acción Social cuenta el trámite como se lo contaron: en lenguaje natural, sin programar."))
rot.append(dict(t0=t["02"]+8.6, t1=b1-0.2, h="Un clic: <b>Analizar con IA</b>", s="La inteligencia artificial de Colm3na lee el relato y propone el trámite entero."))
# --- C: esto entendí
c0, c1 = b1, t["04"] - 0.3
shots.append(dict(id="asis", **PANT, t0=c0, t1=c1, fuente=dict(**A, i0=fr(12.6), i1=fr(19.0)), cam=[dict(t=c0, tx=0, ty=0, tz=0, s=1), dict(t=c1, tx=0, ty=-10, tz=30, s=1)]))
rot.append(dict(t0=t["03"]+0.5, t1=c1-0.2, h="La IA <b>lo entiende</b>", s="Para qué sirve, quién lo pide, quién lo revisa y cómo termina. Lo que infiere, marcado como «IA»."))
# --- D: seis preguntas (leve ángulo para variar)
d0, d1 = c1, t["05"] - 0.3
shots.append(dict(id="asis", **PANT, t0=d0, t1=d1, fuente=dict(**A, i0=fr(19.0), i1=fr(27.1)), cam=[dict(t=d0, tx=0, ty=0, tz=-120, rx=0, ry=10, s=1), dict(t=d0+2.5, tx=0, ty=0, tz=0, rx=0, ry=0, s=1, e="out"), dict(t=d1, tx=0, ty=0, tz=0, s=1)]))
rot.append(dict(t0=t["04"]+0.5, t1=d1-0.2, h="<b>Seis preguntas</b>, nada más", s="Cada una trae la respuesta recomendada ya puesta: se confirma con un clic, o se cambia."))
# --- E: los datos
e0, e1 = d1, t["06"] - 0.3
shots.append(dict(id="asis", **PANT, t0=e0, t1=e1, fuente=dict(**A, i0=fr(27.1), i1=fr(35.7)), cam=[dict(t=e0, tx=0, ty=0, tz=0, s=1), dict(t=e1, tx=0, ty=0, tz=40, s=1)]))
rot.append(dict(t0=t["05"]+0.5, t1=e1-0.2, h="Los datos y <b>sus controles</b>", s="DNI del chico, constancia de alumno regular, una fecha de nacimiento que no puede ser futura."))
# --- F: el circuito: plano fijo 1.6 s y después el vuelo 3D sobre la textura
f0, f1 = e1, t["07"] - 0.3
shots.append(dict(id="asis", **PANT, t0=f0, t1=f0+2.4, fade_out=0.8, fuente=dict(**A, i0=fr(35.7), i1=fr(38.5)), cam=[dict(t=f0, tx=0, ty=0, tz=0, s=1), dict(t=f0+2.4, tx=0, ty=0, tz=-300, rx=18, s=1)]))
shots.append(dict(id="piso", clase="piso", w=3000, h=476, t0=f0+1.6, t1=f1, fade_in=0.8, imagen="frames/diagrama.png", z=3,
  cam=[dict(t=f0+1.6, tx=1500, ty=160, tz=-900, rx=58, ry=0, rz=0, s=1.3), dict(t=f0+4.0, tx=1050, ty=110, tz=-250, rx=55, ry=6, rz=-2, s=1.42, e="out"),
       dict(t=f1-2.5, tx=-1100, ty=80, tz=-200, rx=51, ry=-6, rz=2, s=1.42), dict(t=f1, tx=-1550, ty=120, tz=-700, rx=56, ry=-10, rz=2, s=1.3)]))
rot.append(dict(t0=t["06"]+0.5, t1=f1-0.3, h="El circuito, <b>actor por actor</b>", s="El afiliado pide desde la app; Acción Social revisa la documentación, aprueba y avisa dónde retirar el kit."))
# --- G: en minutos: vista previa + el formulario en la lista del celular
g0, g1 = f1, t["08"] - 0.3
gm = g0 + 2.6
shots.append(dict(id="asis", **PANT, t0=g0, t1=gm, fade_in=0.5, fuente=dict(**A, i0=fr(39.7), i1=fr(42.5)), cam=[dict(t=g0, tx=0, ty=0, tz=-200, ry=8, s=1), dict(t=gm, tx=0, ty=0, tz=0, ry=0, s=1)]))
shots.append(dict(id="cel", **TEL, t0=gm, t1=g1, fade_in=0.4, reflejo=0.2, z=2, fuente=dict(**M, i0=0, i1=fr(1.3)), cam=[dict(t=gm, tx=0, ty=20, tz=-260, rx=4, ry=22, s=1), dict(t=g1, tx=0, ty=10, tz=-60, rx=2, ry=10, s=1)]))
rot.append(dict(t0=t["07"]+0.4, t1=g1-0.2, h="En minutos, <b>sin intervención técnica</b>", s="El trámite ya está publicado en la app del sindicato, con la marca de La Bancaria."))
# --- H: Josefina completa (teléfono 3D que se endereza para tocar Enviar)
h0, h1 = g1, t["09"] - 0.5
shots.append(dict(id="cel", **TEL, t0=h0, t1=h1, reflejo=0.2, z=2, fuente=dict(**M, i0=fr(1.3), i1=fr(6.0)),
  cam=[dict(t=h0, tx=0, ty=10, tz=-60, rx=2, ry=10, s=1), dict(t=h0+3.0, tx=380, ty=0, tz=40, rx=0, ry=-16, rz=-2, s=1), dict(t=h1-3.0, tx=420, ty=0, tz=70, rx=-2, ry=12, rz=1, s=1), dict(t=h1, tx=420, ty=0, tz=90, rx=0, ry=0, rz=0, s=1)]))
rot.append(dict(t0=t["08"]+0.5, t1=h1-0.2, h="Desde el celular, <b>en cinco minutos</b>", s="Los datos de Mateo, el DNI y la constancia adjuntos: Josefina envía desde el colectivo."))
# --- I: sello ENVIADO + expediente; J: la bandeja del panel
i0, i1 = h1, h1 + 5.6
shots.append(dict(id="cel", **TEL, t0=i0, t1=i1, z=2, fuente=dict(**M, tramos=[dict(u0=0, u1=0.55, i0=fr(6.0), i1=fr(8.3)), dict(u0=0.55, u1=1.0, i0=fr(9.0), i1=fr(12.7))]),
  cam=[dict(t=i0, tx=420, ty=0, tz=90, s=1, zs=1, zx=.5, zy=.5), dict(t=i0+1.2, tx=420, ty=0, tz=120, s=1, zs=1.3, zx=.5, zy=.6, e="out"), dict(t=i0+3.0, tx=420, ty=0, tz=120, s=1, zs=1.3, zx=.5, zy=.6), dict(t=i1, tx=420, ty=0, tz=60, s=1, zs=1.0, zx=.5, zy=.5)]))
j0, j1 = i1, t["10"] - 0.4
shots.append(dict(id="band", **PANT, t0=j0, t1=j1, fade_in=0.5, fuente=dict(**B, i0=0, i1=180), cam=[dict(t=j0, tx=60, ty=20, tz=-400, rx=4, ry=-18, s=1), dict(t=j1, tx=0, ty=0, tz=-80, rx=0, ry=-6, s=1)]))
rot.append(dict(t0=t["09"]+0.4, t1=j1-0.3, h="Expediente numerado, <b>estado a la vista</b>", s="Y en la seccional, el pedido ya está en la bandeja de Acción Social: sin papel, sin cola."))
placas = [dict(t0=0.0, t1=2.3, h="Asistente <b>de trámites</b>", s="De una necesidad contada en palabras a un trámite digital"),
          dict(t0=j1, t1=DUR, h="De una necesidad en palabras<br>a un trámite digital <b>para miles de trabajadores</b>", s="Colm3na · Asistente de trámites · sin programar, sin intervención técnica")]
negros = [dict(t0=DUR-1.0, t1=DUR, a0=0, a1=1), dict(t0=0, t1=0.6, a0=1, a1=0)]
tl = dict(duracion=DUR, shots=shots, rotulos=rot, placas=placas, negros=negros, voces=voces, musica=dict(archivo="spring.mp3", desde=0.0, volumen=0.8))
json.dump(tl, open("timeline2.json", "w"), indent=1, ensure_ascii=False)
print("DUR", DUR, {k: round(v, 1) for k, v in t.items()})
