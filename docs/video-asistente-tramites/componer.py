"""Compone el video: cuadros de cada escena en su tiempo absoluto, el
teléfono enmarcado, los rótulos al compás, y el audio."""
import json, os, sys, glob, math, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter
R = os.path.dirname(os.path.abspath(__file__))
FPS = 30; W, H = 1920, 1080
F_BARLOW = '/home/user/MITRABAJOC/static/fonts/barlow-condensed-bold.woff2'
F_MANROPE = '/home/user/MITRABAJOC/static/fonts/manrope.woff2'
cfg = json.load(open(os.path.join(R, 'timeline.json')))
OUT = os.path.join(R, 'out'); os.makedirs(OUT, exist_ok=True)
for f in glob.glob(OUT + '/*.png'): os.remove(f)

def ease_out(u): return 1 - (1 - u) ** 3
def ease_inout(u): return 4*u*u*u if u < .5 else 1 - (-2*u + 2) ** 3 / 2

# ---- fondo del teléfono (una vez)
def fondo():
    im = Image.new('RGB', (W, H), (13, 22, 38)); d = ImageDraw.Draw(im)
    for y in range(H):
        k = y / H
        c = (int(13 + (42 - 13) * k), int(22 + (60 - 22) * k), int(38 + (106 - 38) * k))
        d.line([(0, y), (W, y)], fill=c)
    halo = Image.new('RGB', (W, H), (0, 0, 0)); hd = ImageDraw.Draw(halo)
    hd.ellipse((W * .55, -300, W * 1.15, 420), fill=(40, 90, 110)); hd.ellipse((-200, H * .55, 500, H * 1.3), fill=(90, 70, 20))
    halo = halo.filter(ImageFilter.GaussianBlur(160))
    im = Image.blend(im, Image.eval(halo, lambda v: v), 0.0)
    im = Image.fromarray(__import__('numpy').clip(__import__('numpy').asarray(im).astype(int) + __import__('numpy').asarray(halo).astype(int) // 2, 0, 255).astype('uint8'))
    # colmena
    hexa = Image.new('L', (W, H), 0); hd = ImageDraw.Draw(hexa)
    s = 34
    for row in range(-1, H // int(s * 1.5) + 2):
        for col in range(-1, W // int(s * 1.732) + 2):
            cx = col * s * 1.732 + (s * 0.866 if row % 2 else 0); cy = row * s * 1.5
            pts = [(cx + s * math.cos(math.pi / 6 + i * math.pi / 3), cy + s * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
            hd.polygon(pts, outline=22)
    im.paste((255, 255, 255), (0, 0), hexa)
    return im
FONDO = fondo()

def telefono(frame_path, zoom, foco_y):
    """Pantalla del celular dentro de un marco, centrada, con zoom alrededor de foco_y (0..1 de la pantalla)."""
    scr = Image.open(frame_path).convert('RGB')
    ph = 980; pw = int(scr.width * ph / scr.height)
    scr = scr.resize((pw, ph), Image.LANCZOS)
    bez = 14; rad = 54
    marco = Image.new('RGBA', (pw + 2 * bez, ph + 2 * bez), (0, 0, 0, 0)); md = ImageDraw.Draw(marco)
    md.rounded_rectangle((0, 0, marco.width - 1, marco.height - 1), rad + bez, fill=(18, 20, 26, 255), outline=(70, 76, 90, 255), width=2)
    mask = Image.new('L', scr.size, 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), rad, fill=255)
    marco.paste(scr, (bez, bez), mask)
    # sombra
    base = FONDO.copy()
    sombra = Image.new('RGBA', (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sombra)
    x0 = (W - marco.width) // 2; y0 = (H - marco.height) // 2
    sd.rounded_rectangle((x0 + 10, y0 + 30, x0 + marco.width + 10, y0 + marco.height + 30), rad + bez, fill=(0, 0, 0, 150))
    sombra = sombra.filter(ImageFilter.GaussianBlur(28))
    base.paste(sombra, (0, 0), sombra)
    base.paste(marco, (x0, y0), marco)
    if zoom > 1.001:
        cx = W / 2; cy = y0 + bez + foco_y * ph
        cw, ch = W / zoom, H / zoom
        l = min(max(0, cx - cw / 2), W - cw); t = min(max(0, cy - ch / 2), H - ch)
        base = base.crop((int(l), int(t), int(l + cw), int(t + ch))).resize((W, H), Image.LANCZOS)
    return base

FB = ImageFont.truetype(F_BARLOW, 58); FM = ImageFont.truetype(F_MANROPE, 22)
def rotulo(im, texto, u_in, u_out):
    """Píldora abajo a la izquierda. u_in 0..1 entrada, u_out 0..1 salida."""
    d = ImageDraw.Draw(im, 'RGBA')
    k = ease_out(min(1, u_in)) * (1 - ease_inout(max(0, u_out)))
    if k <= 0: return
    tw = d.textlength(texto, font=FB); x = 72; y = H - 118 + int((1 - ease_out(min(1, u_in))) * 40)
    a = int(255 * k)
    d.rounded_rectangle((x - 26, y - 14, x + tw + 26, y + 70), 14, fill=(13, 22, 38, int(190 * k)))
    d.rectangle((x - 26, y - 14, x - 18, y + 70), fill=(255, 176, 32, a))
    d.text((x, y), texto, font=FB, fill=(255, 255, 255, a))

def frames_de(d, prefijo):
    return sorted(glob.glob(os.path.join(R, 'frames', d, prefijo + '_*.png')))

# ---- plano de cuadros: índice global -> (ruta, tipo)
total = int(round(cfg['duracion'] * FPS))
plano = [None] * total
for esc in cfg['escenas']:
    fr = frames_de(esc['dir'], esc['prefijo']); i0 = int(round(esc['t0'] * FPS))
    i1 = int(round(esc.get('t1', 1e9) * FPS))
    for i, f in enumerate(fr):
        g = i0 + i
        if 0 <= g < total and g < i1: plano[g] = (f, esc)
faltan = [i for i, p in enumerate(plano) if p is None]
if faltan: print('cuadros sin escena:', len(faltan), faltan[:10], '...')

rotulos = cfg.get('rotulos', [])
for g in range(total):
    t = g / FPS
    p = plano[g]
    if p is None:
        im = Image.new('RGB', (W, H), (13, 22, 38))
    else:
        f, esc = p
        if esc.get('telefono'):
            u = (t - esc['t0']) / max(.01, esc.get('t1', cfg['duracion']) - esc['t0'])
            zoom, foco = 1.0, .5
            for z in esc.get('zooms', []):
                if z['t0'] <= t <= z['t1']:
                    k = ease_inout((t - z['t0']) / max(.01, z['t1'] - z['t0'])); zoom = z['z0'] + (z['z1'] - z['z0']) * k; foco = z['foco']
                elif t > z['t1']: zoom, foco = z['z1'], z['foco']
            im = telefono(f, zoom, foco)
        else:
            im = Image.open(f).convert('RGB')
    for r in rotulos:
        if r['t'] - 0.1 <= t <= r['t'] + r.get('dur', 2.2):
            rotulo(im, r['texto'], (t - r['t']) / 0.3, (t - (r['t'] + r.get('dur', 2.2) - 0.35)) / 0.35)
    # fundido a negro al final
    if t > cfg['duracion'] - 0.5:
        k = (t - (cfg['duracion'] - 0.5)) / 0.5
        im = Image.blend(im, Image.new('RGB', (W, H), (0, 0, 0)), min(1, k))
    im.save(os.path.join(OUT, '%05d.png' % g), compress_level=1)
    if g % 150 == 0: print('cuadro', g, '/', total)
print('listo', total, 'cuadros')
