"""Terrain for the wall maps: Terrarium elevation tiles (AWS Terrain Tiles, open data) mosaicked,
resampled into the map projection, and turned into a shaded-relief image with a light elevation tint."""
import glob, math, os
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter


def mosaic(tiledir, z):
    files = glob.glob(os.path.join(tiledir, f"{z}_*_*.png"))
    xs = sorted({int(f.split("_")[-2]) for f in files}); ys = sorted({int(f.split("_")[-1][:-4]) for f in files})
    x0, y0 = xs[0], ys[0]
    arr = np.full(((ys[-1] - y0 + 1) * 256, (xs[-1] - x0 + 1) * 256), np.nan, dtype=np.float32)
    for f in files:
        x, y = int(f.split("_")[-2]), int(f.split("_")[-1][:-4])
        a = np.asarray(Image.open(f).convert("RGB"), dtype=np.float32)
        arr[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    return arr, x0 * 256, y0 * 256, z


def sample(m, lon, lat):
    arr, px0, py0, z = m
    n = 256 * 2 ** z
    px = (lon + 180) / 360 * n - px0
    py = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n - py0
    return map_coordinates(arr, [py, px], order=1, mode="nearest")


def relief(tiledir, zooms, inv, W, H, px_m):
    """inv(X, Y) -> lon, lat for projected metres. Grid: W x H pixels, px_m metres per pixel, origin top-left given by inv."""
    jj, ii = np.meshgrid(np.arange(W), np.arange(H))
    lon, lat = inv(jj, ii)
    elev = None
    for z in zooms:  # coarse first, finer zoom overrides where it has data
        m = mosaic(tiledir, z)
        e = sample(m, lon, lat)
        arr, px0, py0, _ = m
        n = 256 * 2 ** z
        px = (lon + 180) / 360 * n - px0; py = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n - py0
        ok = (px >= 1) & (py >= 1) & (px < arr.shape[1] - 2) & (py < arr.shape[0] - 2)
        elev = e if elev is None else np.where(ok, e, elev)
    elev = gaussian_filter(elev, 0.8)
    return elev


def shade(elev, px_m, exag=2.2):
    dy, dx = np.gradient(elev, px_m)
    dx *= exag; dy *= exag
    slope = np.arctan(np.hypot(dx, dy)); aspect = np.arctan2(-dy, dx)  # image rows go down (south)
    out = np.zeros_like(elev)
    for az, alt, w in [(315, 45, 0.55), (270, 50, 0.2), (360, 50, 0.15), (225, 60, 0.1)]:
        a, h = math.radians(360 - az + 90), math.radians(alt)
        out += w * (np.sin(h) * np.cos(slope) + np.cos(h) * np.sin(slope) * np.cos(a - aspect))
    return np.clip(out, 0, 1)


TINT = [(500, (214, 226, 196)), (1100, (226, 232, 204)), (1500, (236, 232, 208)), (1900, (232, 222, 200)),
        (2400, (230, 224, 216)), (2900, (242, 240, 238)), (3600, (252, 252, 252))]


def tint(elev):
    zs = np.array([t[0] for t in TINT], dtype=np.float32)
    cols = np.array([t[1] for t in TINT], dtype=np.float32)
    rgb = np.stack([np.interp(elev, zs, cols[:, k]) for k in range(3)], -1)
    return rgb


def image(elev, px_m, exag=2.2):
    hs = shade(elev, px_m, exag)
    flat = 0.70  # shade of flat ground; lighten everything so linework reads
    f = 0.62 + 0.38 * (hs / flat)
    f = np.clip(f, 0.45, 1.12)
    rgb = tint(elev) * f[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
