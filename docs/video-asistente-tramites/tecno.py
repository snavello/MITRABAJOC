"""Clásico + tecno: la grabación CC de Vivaldi ("La primavera") estirada a 124 BPM
con bombo, hats, clap y bombeo de cadena lateral sintetizados en numpy.
Salida: tecno.wav (estéreo 48 kHz, DUR segundos)."""
import numpy as np, subprocess, sys, wave, struct
import json
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 64.0
SECC = json.loads(sys.argv[2]) if len(sys.argv) > 2 else [[0,8,'intro'],[8,38,'drop'],[38,44,'break'],[44,DUR-3.5,'drop']]
SR = 48000; BPM = 124.0; BEAT = 60.0 / BPM
# 1) Vivaldi estirado: 97 BPM -> 124 BPM (x1.278), sin cambiar el tono, pasa-altos para dejar lugar al bombo
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', 'spring.mp3', '-af', f'atempo=1.278,highpass=f=120,aresample={SR}', '-ac', '2', '-t', str(DUR + 2), 'spring_124.wav'], check=True)
w = wave.open('spring_124.wav'); n = w.getnframes(); st = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32).reshape(-1, 2) / 32768
N = int(DUR * SR); st = st[:N] if len(st) >= N else np.vstack([st, np.zeros((N - len(st), 2), np.float32)])
t = np.arange(N) / SR
# 2) patrón: intro 0-8 s (solo hats suaves + cuerdas), drop 8-38, corte 38-44 (vuelo del circuito: sin bombo, barrido), vuelta 44-fin
def env_exp(nn, tau): return np.exp(-np.arange(nn) / (SR * tau))
def kick(): nn = int(0.32 * SR); tt = np.arange(nn) / SR; f = 48 + 160 * np.exp(-tt * 22); ph = 2 * np.pi * np.cumsum(f) / SR; return (np.sin(ph) * env_exp(nn, 0.11) * 1.0 + np.tanh(np.sin(ph) * 3) * env_exp(nn, 0.04) * 0.5)
def hat(op=False): nn = int((0.22 if op else 0.06) * SR); x = np.random.randn(nn); x = np.diff(np.concatenate([[0], x])); return x / np.abs(x).max() * env_exp(nn, 0.09 if op else 0.018) * 0.35
def clap(): nn = int(0.25 * SR); x = np.random.randn(nn); e = np.zeros(nn); 
def clap():
    nn = int(0.25 * SR); x = np.random.randn(nn); e = np.zeros(nn)
    for k, g in [(0, .6), (0.012, .8), (0.025, 1.0)]:
        i = int(k * SR); e[i:] += env_exp(nn - i, 0.07) * g
    b, a = 1, 1  # sin filtro: queda crudo, estilo
    y = x * e; y = np.convolve(y, np.ones(6) / 6, 'same'); return y / np.abs(y).max() * 0.32
def riser(dur): nn = int(dur * SR); x = np.random.randn(nn); tt = np.linspace(0, 1, nn); return x * (tt ** 2) * 0.25
drums = np.zeros(N); pump = np.ones(N)
def add(buf, i, s):
    j = min(N, i + len(s)); buf[i:j] += s[:j - i]
K = kick(); C = clap()
def seccion(t0, t1, bombo=True, hats=True, cl=True, ganancia=1.0):
    b = int(np.ceil(t0 / BEAT))
    while b * BEAT < t1:
        i = int(b * BEAT * SR)
        if bombo:
            add(drums, i, K * ganancia)
            # bombeo de cadena lateral sobre las cuerdas
            nn = int(0.5 * SR); j = min(N, i + nn); pump[i:j] = np.minimum(pump[i:j], 0.28 + 0.72 * (1 - np.exp(-np.arange(j - i) / (SR * 0.14))))
        if hats:
            add(drums, i + int(BEAT * SR / 2), hat(False) * ganancia)
            if b % 2 == 1: add(drums, i, hat(True) * 0.6 * ganancia)
        if cl and b % 2 == 1: add(drums, i, C * ganancia)
        b += 1
# el beat nunca se va: en la intro y el corte el bombo sigue, más suave y sin clap
for t0, t1, modo in SECC:
    if modo == 'intro': seccion(t0, t1, bombo=True, hats=True, cl=False, ganancia=0.62)
    elif modo == 'break': seccion(t0, t1, bombo=True, hats=True, cl=False, ganancia=0.7)
    else: seccion(t0, t1, True, True, True, 1.0)
    if modo != 'drop' and t1 < DUR - 2: add(drums, int((t1 - 1.8) * SR), riser(1.8))
add(drums, int((DUR - 3.5) * SR), K * 1.2)  # golpe final
# 3) sub en mi (41 Hz) solo donde hay bombo, con el bombeo, muy abajo
sub = np.sin(2 * np.pi * 41.2 * t) * 0.18
gate = np.zeros(N)
for t0, t1, modo in SECC:
    gate[int(t0 * SR):int(min(t1, DUR - 3.5) * SR)] = 1 if modo == 'drop' else 0.6
sub *= gate * pump
# 4) mezcla
mix = st * pump[:, None] * 0.62 + drums[:, None] * 0.95 + sub[:, None] * 1.2
mix = np.tanh(mix * 1.1) / 1.05
# fundido final
fo = int(2.5 * SR); mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
out = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
with wave.open('tecno.wav', 'wb') as o:
    o.setnchannels(2); o.setsampwidth(2); o.setframerate(SR); o.writeframes(out.tobytes())
print('tecno.wav', DUR, 's')
