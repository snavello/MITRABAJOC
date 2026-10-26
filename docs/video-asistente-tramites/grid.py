import numpy as np
flux = np.load("flux.npy"); H = 0.005
# Ajustar compás (período P en [1.10,1.20]) y fase en el tramo 125–152 s
a, b = int(125/H), int(152/H)
f = flux[a:b].copy(); f = f / f.max()
best = None
for P in np.arange(1.10, 1.20, 0.001):
    for ph in np.arange(0, P, 0.01):
        ts = np.arange(125 + ph, 152, P)
        idx = ((ts - 125) / H).astype(int)
        idx = idx[idx < len(f)]
        # tomar el máximo en ±25 ms alrededor de cada punto de grilla
        sc = sum(f[max(0,i-5):i+6].max() for i in idx) / len(idx)
        if best is None or sc > best[0]: best = (sc, P, ph)
print("mejor: score %.3f  P=%.3f  fase=%.3f" % best)
P, ph = best[1], best[2]
# compases hacia atrás y adelante: lista de tiempos de compás en el tema
t = 125 + ph
while t - P > 100: t -= P
bars = []
while t < 158.6: bars.append(round(t, 3)); t += P
print("fin del sonido 158.57; últimos compases:", bars[-6:])
import json; json.dump({"P": P, "fase": ph, "bars": bars}, open("grid.json", "w"))
