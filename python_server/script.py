
import io
import json

import numpy as np
from PIL import Image
from skimage import filters, measure, morphology, restoration

PEN_DOWN = "M3"
PEN_UP = "M5"
FEED = 1500


def load_image(data, max_dim=500):
    if hasattr(data, "to_py"):
        data = data.to_py()

    im = Image.open(io.BytesIO(bytes(data))).convert("RGBA")

    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    im = bg.convert("RGB")

    k = max_dim / max(im.size)

    if k < 1:
        im = im.resize(
            (round(im.width * k), round(im.height * k)),
            Image.LANCZOS
        )

    rgb = np.asarray(im, np.uint8)
    gray = np.asarray(im.convert("L"), float) / 255

    return rgb, gray


def subject_mask(rgb, rect):
    import cv2

    H, W = rgb.shape[:2]
    x0, y0, x1, y1 = rect

    r = (
        int(x0 * W),
        int(y0 * H),
        max(10, int((x1 - x0) * W)),
        max(10, int((y1 - y0) * H))
    )

    mask = np.zeros((H, W), np.uint8)

    cv2.grabCut(
        np.ascontiguousarray(rgb[..., ::-1]),
        mask,
        r,
        np.zeros((1, 65)),
        np.zeros((1, 65)),
        5,
        cv2.GC_INIT_WITH_RECT
    )

    m = ((mask == 1) | (mask == 3)).astype(np.uint8)

    m = cv2.morphologyEx(
        m,
        cv2.MORPH_OPEN,
        np.ones((5, 5), np.uint8)
    )

    return m.astype(bool)


def dedupe(paths, dist=3.0, cell=4):
    kept, grid = [], {}

    for p in sorted(paths, key=len, reverse=True):
        hit = 0

        for x, y in p:
            cx, cy = int(x // cell), int(y // cell)
            near = False

            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for qx, qy in grid.get((cx + dx, cy + dy), ()):
                        if (qx - x) ** 2 + (qy - y) ** 2 < dist ** 2:
                            near = True
                            break

                    if near:
                        break

                if near:
                    break

            hit += near

        if hit / len(p) > 0.6:
            continue

        kept.append(p)

        for x, y in p:
            grid.setdefault(
                (int(x // cell), int(y // cell)), []
            ).append((x, y))

    return kept


def hatch(b, thr, gap, min_run=6):
    H, W = b.shape

    mask = morphology.opening(
        b < thr,
        np.ones((3, 3), bool)
    )

    out = []

    for d in range(0, H + W, gap):
        xs = np.arange(
            max(0, d - H + 1),
            min(W, d + 1)
        )

        ys = d - xs

        m = mask[ys, xs].astype(np.int8)

        if not m.any():
            continue

        e = np.diff(np.concatenate([[0], m, [0]]))

        for s, t in zip(
            np.nonzero(e == 1)[0],
            np.nonzero(e == -1)[0]
        ):
            if t - s >= min_run:
                out.append(
                    np.array([
                        [xs[s], ys[s]],
                        [xs[t - 1], ys[t - 1]]
                    ], float)
                )

    return out


def paths_photo(
    gray, levels, weight, min_len,
    tol, hatch_gap, hatch_dark, mask=None
):
    b = restoration.denoise_tv_chambolle(
        gray,
        weight=weight
    )

    vals = b[mask] if mask is not None else b.ravel()

    iso = []

    for q in np.linspace(8, 70, levels):
        for c in measure.find_contours(
            b,
            np.percentile(vals, q)
        ):
            closed = np.allclose(c[0], c[-1])

            if len(c) >= min_len or (
                closed and len(c) >= 8 and q < 20
            ):
                iso.append(
                    measure.approximate_polygon(
                        c[:, ::-1],
                        tol
                    )
                )

    if mask is not None:
        for c in measure.find_contours(
            np.pad(mask, 1).astype(float),
            0.5
        ):
            if len(c) >= 60:
                iso.append(
                    measure.approximate_polygon(
                        (c - 1)[:, ::-1],
                        tol
                    )
                )

    out = dedupe(iso)

    if hatch_gap > 0:
        hb = np.where(mask, b, 1.0) if mask is not None else b

        out += hatch(
            hb,
            np.percentile(vals, hatch_dark),
            hatch_gap
        )

    return out


def mask_dark_lines(gray, offset):
    g = filters.gaussian(gray, 1.0)

    return g < filters.threshold_local(
        g,
        51,
        offset=offset
    )


def mask_object_contours(
    gray,
    min_area=0.0003,
    max_area=0.2
):
    H, W = gray.shape

    lum = filters.gaussian(gray, 1)
    sigma = 0.2 * min(H, W)

    w = np.ones((H, W))

    for _ in range(3):
        bg = filters.gaussian(lum * w, sigma) / (
            filters.gaussian(w, sigma) + 1e-6
        )

        d = np.clip(lum - bg, 0, None)

        hi = filters.threshold_otsu(d)

        raw = filters.apply_hysteresis_threshold(
            d,
            0.9 * hi,
            hi
        )

        w = (
            filters.gaussian(raw.astype(float), 4) < 0.02
        ).astype(float)

    grown = filters.gaussian(raw.astype(float), 1) > 0.2

    labels = measure.label(grown)

    mask = np.zeros((H, W), bool)

    for r in measure.regionprops(labels):
        minr, minc, maxr, maxc = r.bbox

        if r.area < min_area * H * W:
            continue

        if r.area > max_area * H * W:
            continue

        if minr == 0 or minc == 0 or maxr == H or maxc == W:
            continue

        mask[minr:maxr, minc:maxc] |= r.image_filled

    return mask


def trace_skeleton(skel):
    pix = set(zip(*np.nonzero(skel)))

    offs = [
        (-1, 0), (0, 1), (1, 0), (0, -1),
        (-1, -1), (-1, 1), (1, 1), (1, -1)
    ]

    def nb(p):
        return [
            (p[0] + dy, p[1] + dx)
            for dy, dx in offs
            if (p[0] + dy, p[1] + dx) in pix
        ]

    seen = set()
    paths = []

    def walk(p):
        path = [p]
        seen.add(p)

        while True:
            c = [
                q for q in nb(path[-1])
                if q not in seen
            ]

            if not c:
                return path

            path.append(c[0])
            seen.add(c[0])

    ends = [p for p in pix if len(nb(p)) == 1]

    for p in ends + sorted(pix):
        if p not in seen:
            paths.append(walk(p))

    return [
        np.array([(x, y) for y, x in p], float)
        for p in paths
    ]


def simplify(raw, min_len, tol):
    out = []

    for p in raw:
        if len(p) < min_len:
            continue

        s = measure.approximate_polygon(p, tol)

        if len(s) >= 2:
            out.append(s)

    return out


def order_paths(paths):
    left = list(paths)
    cur = np.zeros(2)
    out = []

    while left:
        best, bi, brev = 1e18, 0, False

        for i, p in enumerate(left):
            d0 = np.sum((p[0] - cur) ** 2)
            d1 = np.sum((p[-1] - cur) ** 2)

            if d0 < best:
                best, bi, brev = d0, i, False

            if d1 < best:
                best, bi, brev = d1, i, True

        p = left.pop(bi)

        if brev:
            p = p[::-1]

        out.append(p)
        cur = p[-1]

    return out


def to_gcode(paths, shape, aw, ah, mg):
    H, W = shape

    s = min(
        (aw - 2 * mg) / W,
        (ah - 2 * mg) / H
    )

    ox = (aw - W * s) / 2
    oy = (ah - H * s) / 2

    lines = [
        "G21",
        "G90",
        f"G1 F{FEED}",
        PEN_UP
    ]

    for p in paths:
        xy = [
            (ox + x * s, oy + (H - y) * s)
            for x, y in p
        ]

        lines.append(
            f"G0 X{xy[0][0]:.1f} Y{xy[0][1]:.1f}"
        )

        lines.append(PEN_DOWN)

        for x, y in xy[1:]:
            lines.append(f"G1 X{x:.1f} Y{y:.1f}")

        lines.append(PEN_UP)

    lines += ["G0 X0 Y0", "M30"]

    return lines


def finalize(paths_json, w, h, aw, ah, mg):
    ps = []

    for p in json.loads(paths_json):
        if len(p) < 2:
            continue

        s = measure.approximate_polygon(
            np.array(p, float),
            0.4
        )

        if len(s) >= 2:
            ps.append(s)

    ps = order_paths(ps)

    return json.dumps({
        "paths": [
            np.round(p, 1).tolist()
            for p in ps
        ],
        "gcode": to_gcode(
            ps,
            (h, w),
            aw,
            ah,
            mg
        )
    })


def process(
    data, mode, levels, smooth, min_len,
    tol, thr, hgap, hdark, bg,
    bx0, by0, bx1, by1, aw, ah, mg
):
    rgb, gray = load_image(data)

    m = None

    if bg:
        m = subject_mask(
            rgb,
            (bx0 / 100, by0 / 100, bx1 / 100, by1 / 100)
        )

        gray = np.where(m, gray, 1.0)

    if mode == "photo":
        paths = paths_photo(
            gray,
            int(levels),
            float(smooth),
            int(min_len),
            float(tol),
            int(hgap),
            float(hdark),
            m
        )

    elif mode == "lines":
        mask = mask_dark_lines(
            gray,
            thr / 100
        )

        paths = simplify(
            trace_skeleton(
                morphology.skeletonize(mask)
            ),
            8,
            float(tol)
        )

    else:
        mask = mask_object_contours(gray)

        raw = [
            c[:, ::-1]
            for c in measure.find_contours(
                mask.astype(float),
                0.5
            )
        ]

        paths = simplify(
            raw,
            8,
            float(tol)
        )

    paths = order_paths(paths)

    gcode = to_gcode(
        paths,
        gray.shape,
        aw,
        ah,
        mg
    )

    return json.dumps({
        "w": gray.shape[1],
        "h": gray.shape[0],
        "paths": [
            np.round(p, 1).tolist()
            for p in paths
        ],
        "gcode": gcode
    })
