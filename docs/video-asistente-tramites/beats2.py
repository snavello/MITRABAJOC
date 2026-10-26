import numpy as np, wave
w = wave.open("presto_mono.wav"); sr = w.getframerate(); n = w.getnframes()
x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768
# flujo espectral (onsets) con hop 5 ms
hop = int(sr*0.005); win = 1024
nfr = (len(x)-win)//hop
prev = None; flux = np.zeros(nfr)
hann = np.hanning(win)
for i in range(nfr):
    s = np.abs(np.fft.rfft(x[i*hop:i*hop+win]*hann))
    if prev is not None: flux[i] = np.sum(np.maximum(s-prev, 0))
    prev = s
t = np.arange(nfr)*hop/sr
# tempo por autocorrelación del flujo en el tramo 125-158 s
a, b = int(125/0.005), int(158/0.005)
f = flux[a:b] - np.convolve(flux[a:b], np.ones(40)/40, 'same'); f = np.maximum(f, 0)
ac = np.correlate(f, f, 'full')[len(f)-1:]
lags = np.arange(len(ac))*0.005
cand = [(lags[i], ac[i]) for i in range(int(0.25/0.005), int(1.2/0.005)) if ac[i] > ac[i-1] and ac[i] >= ac[i+1]]
cand.sort(key=lambda c: -c[1]); print("lags candidatos (s):", [round(c[0],3) for c in cand[:8]])
# picos de onset fuertes en 120-159 s
seg = flux[int(120/0.005):]; ts = t[int(120/0.005):]
thr = np.percentile(seg, 97)
picos = [(round(ts[i],3), round(seg[i],1)) for i in range(1, len(seg)-1) if seg[i] > thr and seg[i] >= seg[i-1] and seg[i] > seg[i+1]]
# agrupar picos a menos de 80 ms
out = []
for p in picos:
    if out and p[0]-out[-1][0] < 0.08:
        if p[1] > out[-1][1]: out[-1] = p
    else: out.append(p)
print("picos fuertes:", [p[0] for p in out])
np.save("flux.npy", flux)
