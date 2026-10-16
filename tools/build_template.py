#!/usr/bin/env python3
"""
build_template.py - maak een eigen L-Connect 3 template voor het Lian Li 8.8" Universal Screen
door een bestaande (standaard) template een nieuwe achtergrond te geven.

Wat het doet
  * neemt de layout en alle live velden (CPU, GPU, RAM, tijd, ...) over uit een bestaande .template
  * zet jouw afbeelding (optioneel met vallende sterren) of video eronder
  * past tekst-, label- en balkkleuren aan zodat het leesbaar blijft
  * kan het hele info-blok omhoog/omlaag schuiven
  * levert een ZIP die je in L-Connect 3 importeert via de "+"-tegel

Voorbeeld
  python build_template.py --base 88016_.template --background arc.jpg \
      --name ArcRaiders_Samurai --stars --shift-up 75

Vereisten: Python 3.9+, ffmpeg in PATH, pip install pillow numpy scipy
Getest met de staande "samurai"-template (88016_) van L-Connect 3 v2.1.29.
"""
import argparse, io, os, random, subprocess, sys, zipfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nrbf import Parser, resolve, lp_encode

W, H, FPS = 480, 1920, 24
LC = r'C:\ProgramData\Lian-Li\L-Connect 3\universal-screen-8.8-inch'


def hexcolor(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def args_parse():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--base', required=True, help='bestaande .template (bv. uit C:\\ProgramData\\Lian-Li\\L-Connect 3\\universal-screen-8.8-inch\\template)')
    p.add_argument('--background', required=True, help='achtergrond: afbeelding (jpg/png) of video (mp4), 480x1920 staand')
    p.add_argument('--name', required=True, help='naam van de nieuwe template (letters, cijfers, _)')
    p.add_argument('--out', default='out', help='uitvoermap (standaard: out)')
    p.add_argument('--stars', action='store_true', help='voeg vallende sterren toe (alleen bij een afbeelding)')
    p.add_argument('--star-zone', default='330,40,470,420,40,700,150,960',
                   help='sterren: start-x1,y1,x2,y2 en doel-x1,y1,x2,y2 (standaard: rechtsboven -> linksonder)')
    p.add_argument('--duration', type=int, default=12, help='lengte van de loop in seconden (afbeelding)')
    p.add_argument('--shift-up', type=int, default=0, help='schuif het hele info-blok zoveel pixels omhoog')
    p.add_argument('--text-color', default='F2E8D5', help='kleur van tekst en waarden (hex)')
    p.add_argument('--label-color', default='0E1330', help='tekstkleur in de labelpillen (hex)')
    p.add_argument('--overlay-color', default='F2E8D5', help='kleur van pillen en lijnen (hex)')
    p.add_argument('--scrim', type=float, default=0.70, help='verdonkering achter het info-blok (1.0 = geen)')
    p.add_argument('--scrim-end', type=int, default=780, help='y waar de verdonkering uitloopt (voor verschuiving)')
    return p.parse_args()


class Tpl:
    """Leest een .template en verzamelt patches (offset-gebaseerd, structuur blijft gelijk)."""

    def __init__(self, path):
        self.data = bytearray(open(path, 'rb').read())
        self.P = Parser(bytes(self.data)); self.P.parse()
        self.root = [r for r in self.P.records if r.kind == 'class'][0]
        self.patches = []

    def R(self, v):
        v = resolve(self.P, v)
        return None if (v is not None and not isinstance(v, tuple) and v.kind in ('null', 'nullmulti')) else v

    def F(self, n, k):
        for kk, v in n.fields.items():
            if kk.split('+')[-1].replace('>k__BackingField', '').lstrip('<') == k:
                return self.R(v)

    def items(self):
        gl = self.F(self.root, 'GraphList')
        lst = self.R(gl.fields['Collection`1+items'])
        arr = self.R(lst.fields['_items']); size = self.F(lst, '_size')[2]
        return [self.R(i) for i in arr.items[:size]]

    def bitmap(self, bm):
        node = self.R(bm.fields['Data'])
        return node, Image.open(io.BytesIO(self.data[node.dstart:node.dstart + node.length]))

    def set_string(self, node, s):
        self.patches.append((node.lenoff, node.end, lp_encode(s)))

    def set_bytes(self, node, data):
        hdr = bytes([15]) + node.oid.to_bytes(4, 'little', signed=True) + len(data).to_bytes(4, 'little') + bytes([2])
        self.patches.append((node.start, node.end, hdr + data))

    def set_int(self, prim, value):
        self.patches.append((prim[3], prim[3] + 4, int(value).to_bytes(4, 'little', signed=True)))

    def set_color(self, cnode, rgb):
        v, kc, st = self.F(cnode, 'value'), self.F(cnode, 'knownColor'), self.F(cnode, 'state')
        argb = (0xFF << 24) | (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
        self.patches += [(v[3], v[3] + 8, argb.to_bytes(8, 'little', signed=True)),
                         (kc[3], kc[3] + 2, (0).to_bytes(2, 'little')),
                         (st[3], st[3] + 2, (2).to_bytes(2, 'little'))]

    def write(self, path):
        ps = sorted(self.patches, key=lambda p: p[0])
        for a, b in zip(ps, ps[1:]):
            assert a[1] <= b[0], 'overlappende patches'
        d = bytearray(self.data)
        for s, e, b in reversed(ps):
            d[s:e] = b
        open(path, 'wb').write(d)
        Parser(bytes(d)).parse()          # controle: moet opnieuw te lezen zijn
        return len(d)


def shift_up(a, dy):
    if dy <= 0: return a
    return np.concatenate([a[dy:], np.zeros((dy,) + a.shape[1:], a.dtype)])


def png_bytes(im):
    b = io.BytesIO(); im.save(b, 'PNG'); return b.getvalue()


def make_stars(zone, dur, seed=7, n=11):
    sx1, sy1, sx2, sy2, tx1, ty1, tx2, ty2 = zone
    rnd = random.Random(seed); stars = []
    for i in range(n):
        stars.append(dict(sx=rnd.uniform(sx1, sx2), sy=rnd.uniform(sy1, sy2),
                          tx=rnd.uniform(tx1, tx2), ty=rnd.uniform(ty1, ty2),
                          life=rnd.uniform(1.0, 1.6), t0=(i / n) * dur + rnd.uniform(-0.4, 0.4),
                          tail=rnd.uniform(0.28, 0.40), width=rnd.uniform(2.2, 3.2),
                          tint=rnd.choice([(1, 1, 1), (0.85, 0.92, 1), (1, 0.95, 0.85)])))
    return stars


def star_layer(stars, t, dur, max_y):
    layer = Image.new('RGB', (W, H)); d = ImageDraw.Draw(layer)
    for s in stars:
        age = (t - s['t0']) % dur
        if age > s['life']: continue
        p = age / s['life']
        bright = min(1.0, p / 0.12) * (1 - max(0.0, (p - 0.55) / 0.45)) ** 1.5
        head = p * p * (3 - 2 * p) * 0.4 + p * 0.6
        tail = max(0.0, head - s['tail'])
        for k in range(24):
            a = tail + (head - tail) * k / 24; b = tail + (head - tail) * (k + 1) / 24
            f = ((k + 1) / 24) ** 2 * bright
            d.line([(s['sx'] + (s['tx'] - s['sx']) * a, s['sy'] + (s['ty'] - s['sy']) * a),
                    (s['sx'] + (s['tx'] - s['sx']) * b, s['sy'] + (s['ty'] - s['sy']) * b)],
                   fill=tuple(int(255 * f * c) for c in s['tint']),
                   width=max(1, int(s['width'] * (0.4 + 0.6 * (k + 1) / 24))))
        hx = s['sx'] + (s['tx'] - s['sx']) * head; hy = s['sy'] + (s['ty'] - s['sy']) * head
        r = s['width'] * 1.3; c = int(255 * bright)
        d.ellipse([hx - r, hy - r, hx + r, hy + r], fill=(c, c, c))
    arr = np.asarray(layer, np.float32) / 255
    g1 = np.asarray(layer.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255
    g2 = np.asarray(layer.filter(ImageFilter.GaussianBlur(14)), np.float32) / 255
    add = np.clip(arr + g1 * 1.4 + g2 * 0.9 * np.array([0.7, 0.85, 1.0]), 0, 1)
    add[max_y:] = 0
    return add


def main():
    a = args_parse()
    out = os.path.join(a.out, a.name); os.makedirs(out, exist_ok=True)
    text_c, label_c, ov_c = hexcolor(a.text_color), hexcolor(a.label_color), hexcolor(a.overlay_color)
    dy = a.shift_up
    T = Tpl(a.base)
    items = T.items()

    # --- overlay (pillen/lijnen) en originele stills uit de basistemplate ---
    overlay_src = anim_still = None
    for it in items:
        cls = it.cls.split('.')[-1]
        if cls == 'GraphImage' and overlay_src is None:
            overlay_src = np.asarray(T.bitmap(T.F(it, 'bitmap'))[1].convert('RGBA')).copy()
        if cls == 'GraphAnimation' and anim_still is None:
            anim_still = T.bitmap(T.F(it, 'bitmap'))[1].convert('RGB')
    theme_pic = T.bitmap(T.F(T.root, 'themePic'))[1].convert('RGB')

    pill = np.zeros((H, W), bool)
    if overlay_src is not None:
        ov = shift_up(overlay_src, dy); al = ov[..., 3]; m = al > 20
        pill = ndimage.binary_dilation(ndimage.binary_opening(m, structure=np.ones((9, 1))), iterations=1) & m
        new = np.zeros_like(ov); new[..., :3] = ov_c
        alpha = np.zeros(al.shape, np.float32)
        mx = max(int(al.max()), 1)
        alpha[m] = al[m] / mx * 165; alpha[pill] = al[pill] / mx * 250
        new[..., 3] = alpha.clip(0, 255).astype(np.uint8)
        overlay = Image.fromarray(new, 'RGBA')
    else:
        overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ov_f = np.asarray(overlay, np.float32) / 255
    pill_mask = ndimage.binary_dilation(pill, iterations=2)

    # --- achtergrond + verdonkering ---
    y = np.arange(H, dtype=np.float32); s0 = a.scrim_end - dy
    scrim = np.where(y < s0, a.scrim, np.where(y > s0 + 80, 1.0, a.scrim + (1 - a.scrim) * (y - s0) / 80))
    is_video = a.background.lower().endswith(('.mp4', '.mov', '.webm', '.gif'))

    mp4 = os.path.join(out, a.name + '.mp4'); h264 = os.path.join(out, a.name + '.h264')
    enc_args = ['-an', '-c:v', 'libx264', '-profile:v', 'baseline', '-x264opts', 'bframes=0',
                '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'slow']
    first = None
    if is_video:
        # video: schalen naar 480x1920, verdonkering + overlay erover via een masker-PNG
        mask_png = os.path.join(out, '_layer.png')
        layer = np.zeros((H, W, 4), np.float32)
        dark = (1 - scrim)[:, None]
        # combineer verdonkering (zwart) en overlay in één RGBA-laag
        oa = ov_f[..., 3]
        comb_a = oa + dark * (1 - oa)
        layer[..., :3] = np.where(comb_a[..., None] > 0, ov_f[..., :3] * oa[..., None] / np.maximum(comb_a, 1e-6)[..., None], 0)
        layer[..., 3] = comb_a
        Image.fromarray((layer * 255).astype(np.uint8), 'RGBA').save(mask_png)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', a.background, '-i', mask_png, '-filter_complex',
                        f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}[b];[b][1:v]overlay',
                        *enc_args, mp4], check=True)
        first = np.asarray(Image.open(io.BytesIO(subprocess.run(
            ['ffmpeg', '-loglevel', 'error', '-i', mp4, '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'],
            capture_output=True, check=True).stdout)).convert('RGB'))
        os.remove(mask_png)
    else:
        img = Image.open(a.background).convert('RGB')
        if img.size != (W, H):
            sc = max(W / img.width, H / img.height)
            img = img.resize((round(img.width * sc), round(img.height * sc)), Image.LANCZOS)
            l, t = (img.width - W) // 2, (img.height - H) // 2
            img = img.crop((l, t, l + W, t + H))
        base = np.asarray(img, np.float32) / 255 * scrim[:, None, None]
        stars = make_stars([float(v) for v in a.star_zone.split(',')], a.duration) if a.stars else []
        max_y = int(float(a.star_zone.split(',')[-1])) + 40
        frames = FPS * a.duration if stars else FPS * 2
        enc = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', *enc_args, '-movflags', '+faststart', mp4],
                               stdin=subprocess.PIPE)
        for f in range(frames):
            im = base
            if stars:
                im = 1 - (1 - base) * (1 - star_layer(stars, f / FPS, a.duration, max_y))
            im = im * (1 - ov_f[..., 3:]) + ov_f[..., :3] * ov_f[..., 3:]
            fr = (np.clip(im, 0, 1) * 255).astype(np.uint8)
            if first is None: first = fr
            enc.stdin.write(fr.tobytes())
        enc.stdin.close(); enc.wait()
    # raw h264 zoals L-Connect zelf maakt (24 fps, geen B-frames)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', mp4, '-f', 'h264', *enc_args, '-r', str(FPS), h264], check=True)

    # --- voorbeeld: tekst uit het origineel halen en herkleuren ---
    still = Image.fromarray(first).convert('RGBA')
    pic = np.asarray(theme_pic, np.float32); sbg = np.asarray(anim_still if anim_still is not None else theme_pic, np.float32)
    lp, lb = pic.mean(-1), sbg.mean(-1)
    dark_a = np.clip((lb - lp) / np.maximum(lb - 20, 1), 0, 1); light_a = np.clip((lp - lb) / np.maximum(255 - lb, 1), 0, 1)
    dark_a[dark_a < 0.08] = 0; light_a[light_a < 0.08] = 0
    dark_a, light_a = shift_up(dark_a, dy), shift_up(light_a, dy)
    prev = np.asarray(still.convert('RGB'), np.float32)
    ta = (dark_a * ~pill_mask)[..., None]; prev = prev * (1 - ta) + np.array(text_c) * ta
    la = (light_a * pill_mask)[..., None]; prev = prev * (1 - la) + np.array(label_c) * la
    preview = Image.fromarray(prev.clip(0, 255).astype(np.uint8)).convert('RGBA')
    preview.save(os.path.join(out, 'preview.png'))

    # --- template patchen ---
    vid_path = LC + '\\video\\' + a.name + '.h264'
    T.set_string(T.F(T.root, 'name'), a.name)
    T.set_string(T.F(T.root, 'themePath'), LC + '\\template\\' + a.name + '.template')
    done = set()
    for k in ('videoPath', 'o_videoPath'):
        s = T.F(T.root, k)
        if s and s.oid not in done: T.set_string(s, vid_path); done.add(s.oid)
    T.set_string(T.F(T.root, 'videoName'), a.name + '.h264')
    T.set_bytes(T.R(T.F(T.root, 'themePic').fields['Data']), png_bytes(preview))
    still_png = png_bytes(still); stats = dict(text=0, label=0, bar=0, moved=0)
    for it in items:
        cls = it.cls.split('.')[-1]
        if cls == 'GraphAnimation':
            for k in ('bitmap', 'O_bitmap', 'S_bitmap'):
                bm = T.F(it, k)
                if bm: T.set_bytes(T.R(bm.fields['Data']), still_png)
            for k, v in (('videoName', a.name + '.mp4'), ('FilePath', vid_path)):
                s = T.F(it, k)
                if s and s.oid not in done: T.set_string(s, v); done.add(s.oid)
            continue
        if cls == 'GraphImage':
            T.set_bytes(T.R(T.F(it, 'bitmap').fields['Data']), png_bytes(overlay)); continue
        if cls == 'GraphStatuBar':
            T.set_color(T.F(it, 'FrontColor'), text_c); stats['bar'] += 1
        py = T.F(it, 'posY')
        if py and dy:
            T.set_int(py, py[2] - dy); stats['moved'] += 1
        fc = T.F(it, 'fontConfig')
        if fc:
            c = T.F(fc, 'color')
            if T.F(c, 'knownColor')[2] == 164:      # wit label in een pil
                T.set_color(c, label_c); stats['label'] += 1
            else:
                T.set_color(c, text_c); stats['text'] += 1
    tpl_out = os.path.join(out, a.name + '.template')
    size = T.write(tpl_out)

    zpath = os.path.join(out, a.name + '.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(tpl_out, a.name + '.template'); z.write(h264, a.name + '.h264')
    print(f'Klaar: {zpath}\n  template {size} bytes, aangepast: {stats}\n  importeer de ZIP in L-Connect 3 via de "+"-tegel')


if __name__ == '__main__':
    main()
