import argparse
import base64
import csv
import datetime as _dt
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    def clip(self, width: int, height: int) -> "Rect":
        x = max(0, min(self.x, width - 1))
        y = max(0, min(self.y, height - 1))
        w = max(1, min(self.w, width - x))
        h = max(1, min(self.h, height - y))
        return Rect(x, y, w, h)


def imread_unicode(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Failed to read image: {path}")
    return img


def imwrite_unicode(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise RuntimeError(f"Failed to encode image: {path}")
    buf.tofile(str(path))


def to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def auto_find_legend_rect(img: np.ndarray) -> Rect:
    """Heuristically find the legend table rectangle (bottom-left)"""
    h, w = img.shape[:2]

    # Focus on bottom-left area to avoid title blocks.
    roi = Rect(0, int(h * 0.62), int(w * 0.36), int(h * 0.38)).clip(w, h)
    crop = img[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    gray = to_gray(crop)

    # Binarize and find rectangular contours.
    _, bw = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY_INV)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=1)

    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_score = -1.0

    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < 8_000:
            continue
        aspect = cw / max(ch, 1)
        if aspect < 0.8 or aspect > 2.5:
            continue

        # Prefer larger rectangles near the very bottom-left.
        cx = x + cw / 2
        cy = y + ch / 2
        score = area * (1.0 + (1.0 - cx / roi.w)) * (1.0 + (cy / roi.h))

        if score > best_score:
            best_score = score
            best = Rect(roi.x + x, roi.y + y, cw, ch)

    if best is None:
        # Fallback: a fixed guess.
        return Rect(int(w * 0.03), int(h * 0.74), int(w * 0.28), int(h * 0.22)).clip(w, h)

    return best.clip(w, h)


def detect_legend_icons(img: np.ndarray, legend: Rect) -> list[Rect]:
    """Return bounding boxes for the icon column items inside legend."""
    h, w = img.shape[:2]
    legend = legend.clip(w, h)
    crop = img[legend.y : legend.y + legend.h, legend.x : legend.x + legend.w]
    gray = to_gray(crop)

    # Make lines/text white.
    _, bw = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY_INV)

    # Remove table grid lines (horizontal/vertical) so they don't merge into icons.
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 35))
    h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel, iterations=1)
    v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel, iterations=1)
    lines = cv2.bitwise_or(h_lines, v_lines)
    bw = cv2.bitwise_and(bw, cv2.bitwise_not(lines))

    # Lightly merge icon strokes.
    bw = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    # Icon column is on left of legend.
    icon_col_w = int(legend.w * 0.22)
    icon_crop = bw[:, :icon_col_w]

    # Find connected components.
    num, labels, stats, _ = cv2.connectedComponentsWithStats(icon_crop, connectivity=8)

    rects: list[Rect] = []
    for i in range(1, num):
        x, y, cw, ch, area = stats[i]
        if area < 80:
            continue
        if cw < 6 or ch < 6:
            continue
        if cw > 80 or ch > 80:
            continue
        if cw > icon_col_w * 0.9:
            continue
        # Map back to full image coordinates.
        rects.append(Rect(legend.x + x, legend.y + y, cw, ch))

    # Merge components that belong to same icon row via y clustering.
    rects.sort(key=lambda r: (r.y, r.x))

    merged: list[Rect] = []
    for r in rects:
        if not merged:
            merged.append(r)
            continue
        prev = merged[-1]
        # If vertically overlapping significantly, union.
        if (r.y <= prev.y + prev.h and prev.y <= r.y + r.h) and abs((r.y + r.h / 2) - (prev.y + prev.h / 2)) < 12:
            x0 = min(prev.x, r.x)
            y0 = min(prev.y, r.y)
            x1 = max(prev.x + prev.w, r.x + r.w)
            y1 = max(prev.y + prev.h, r.y + r.h)
            merged[-1] = Rect(x0, y0, x1 - x0, y1 - y0)
        else:
            merged.append(r)

    # Filter to one icon per row by picking the largest per y-band.
    merged.sort(key=lambda r: r.y)
    rows: list[list[Rect]] = []
    for r in merged:
        placed = False
        for row in rows:
            ry = row[0].y + row[0].h / 2
            if abs((r.y + r.h / 2) - ry) < 16:
                row.append(r)
                placed = True
                break
        if not placed:
            rows.append([r])

    icons: list[Rect] = []
    for row in rows:
        icons.append(max(row, key=lambda rr: rr.w * rr.h))

    # Sort by vertical position (top-to-bottom)
    icons.sort(key=lambda r: r.y)
    return icons


def extract_template(img: np.ndarray, rect: Rect, pad: int = 6) -> np.ndarray:
    h, w = img.shape[:2]
    r = Rect(rect.x - pad, rect.y - pad, rect.w + 2 * pad, rect.h + 2 * pad).clip(w, h)
    crop = img[r.y : r.y + r.h, r.x : r.x + r.w]
    gray = to_gray(crop)
    edges = cv2.Canny(gray, 50, 150)
    return edges


def nms_points(points: list[tuple[int, int, float]], min_dist: float) -> list[tuple[int, int, float]]:
    """Non-maximum suppression on points (x,y,score)"""
    points = sorted(points, key=lambda p: p[2], reverse=True)
    kept: list[tuple[int, int, float]] = []
    for x, y, s in points:
        ok = True
        for kx, ky, _ in kept:
            if (x - kx) ** 2 + (y - ky) ** 2 < min_dist**2:
                ok = False
                break
        if ok:
            kept.append((x, y, s))
    return kept


def match_template_all(plan_edges: np.ndarray, templ_edges: np.ndarray, threshold: float) -> list[tuple[int, int, float]]:
    res = cv2.matchTemplate(plan_edges, templ_edges, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)

    h, w = templ_edges.shape[:2]
    points = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        score = float(res[y, x])
        cx = int(x + w / 2)
        cy = int(y + h / 2)
        points.append((cx, cy, score))

    # suppress duplicates
    min_dist = max(12.0, min(w, h) * 0.6)
    return nms_points(points, min_dist=min_dist)


def build_drawio_markers(base_image_path: Path, width: int, height: int, markers: list[dict], out_path: Path) -> None:
    """Create an editable draw.io file: base image locked + marker circles editable."""
    png_bytes = base_image_path.read_bytes()
    b64 = base64.b64encode(png_bytes).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"

    now = _dt.datetime.now().isoformat(timespec="seconds")
    diagram_id = str(uuid.uuid4())

    cells_xml = [
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
        f'<mxCell id="bg" value="" style="shape=image;image={data_uri};aspect=fixed;movable=0;resizable=0;rotatable=0;locked=1;" vertex="1" parent="1">'
        f'<mxGeometry x="0" y="0" width="{width}" height="{height}" as="geometry"/>'
        "</mxCell>",
    ]

    for idx, m in enumerate(markers, start=1):
        mid = f"m{idx}"
        x = m["x"]
        y = m["y"]
        r = m.get("r", 10)
        stroke = m.get("stroke", "#D32F2F")
        fill = m.get("fill", "none")
        label = m.get("label", "")
        style = f"ellipse;whiteSpace=wrap;html=1;aspect=fixed;strokeColor={stroke};fillColor={fill};"
        cells_xml.append(
            f'<mxCell id="{mid}" value="{label}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x - r}" y="{y - r}" width="{2 * r}" height="{2 * r}" as="geometry"/>'
            "</mxCell>"
        )

    xml = (
        f'<mxfile host="app.diagrams.net" modified="{now}" agent="Copilot" version="22.1.0" type="device">'
        f'<diagram id="{diagram_id}" name="灯具统计标注" compressed="false">'
        f'<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
        f'page="1" pageScale="1" pageWidth="{max(width, 800)}" pageHeight="{max(height, 600)}" math="0" shadow="0">'
        "<root>"
        + "".join(cells_xml)
        + "</root>"
        "</mxGraphModel>"
        "</diagram>"
        "</mxfile>"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Count lighting fixtures from a plan image using legend-icon template matching.")
    parser.add_argument("--plan", required=True, help="Plan PNG (exported from PDF)")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument(
        "--legend-rect",
        default="",
        help="Optional legend rect override as x,y,w,h (in pixels). If omitted, auto-detect.",
    )
    parser.add_argument("--threshold", type=float, default=0.62, help="Template match threshold (0.5~0.8)")

    args = parser.parse_args()
    plan_path = Path(args.plan)
    out_dir = Path(args.out_dir)

    img = imread_unicode(plan_path)
    h, w = img.shape[:2]

    if args.legend_rect:
        x, y, lw, lh = [int(v) for v in args.legend_rect.split(",")]
        legend = Rect(x, y, lw, lh).clip(w, h)
    else:
        legend = auto_find_legend_rect(img)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Save legend crop for review
    legend_crop = img[legend.y : legend.y + legend.h, legend.x : legend.x + legend.w]
    imwrite_unicode(out_dir / "legend_crop.png", legend_crop)

    (out_dir / "legend_rect.txt").write_text(
        f"legend_rect={legend.x},{legend.y},{legend.w},{legend.h}\n",
        encoding="utf-8",
    )

    icon_rects = detect_legend_icons(img, legend)

    # Save a debug image showing detected icon boxes.
    legend_dbg = legend_crop.copy()
    for idx, r in enumerate(icon_rects, start=1):
        rr = Rect(r.x - legend.x, r.y - legend.y, r.w, r.h)
        cv2.rectangle(legend_dbg, (rr.x, rr.y), (rr.x + rr.w, rr.y + rr.h), (0, 0, 255), 2)
        cv2.putText(legend_dbg, str(idx), (rr.x + rr.w + 6, rr.y + rr.h), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    imwrite_unicode(out_dir / "legend_debug.png", legend_dbg)

    # If legend icons not detected well, bail with useful hint.
    if len(icon_rects) < 2:
        raise SystemExit(
            "Legend icon detection failed (found <2 icons). "
            "You can pass --legend-rect x,y,w,h to manually specify the legend box."
        )

    # Prepare edges for plan (ignore margins a bit to reduce false matches in title blocks)
    plan_gray = to_gray(img)
    plan_edges = cv2.Canny(plan_gray, 40, 120)

    # Mask out legend itself to avoid self-matching
    plan_edges[legend.y : legend.y + legend.h, legend.x : legend.x + legend.w] = 0

    palette = [
        (211, 47, 47),
        (25, 118, 210),
        (56, 142, 60),
        (123, 31, 162),
        (245, 124, 0),
        (0, 121, 107),
        (194, 24, 91),
    ]

    summary_rows = []
    points_rows = []
    overlay = img.copy()

    drawio_markers: list[dict] = []

    for i, icon_rect in enumerate(icon_rects, start=1):
        templ = extract_template(img, icon_rect, pad=8)
        templ_path = out_dir / "templates" / f"fixture_{i:02d}.png"
        imwrite_unicode(templ_path, templ)

        matches = match_template_all(plan_edges, templ, threshold=args.threshold)

        color = palette[(i - 1) % len(palette)]
        bgr = (color[0], color[1], color[2])

        for (x, y, score) in matches:
            points_rows.append(
                {
                    "fixture_id": f"fixture_{i:02d}",
                    "x": x,
                    "y": y,
                    "score": f"{score:.3f}",
                }
            )
            cv2.circle(overlay, (x, y), 12, bgr, 2)
            cv2.putText(overlay, f"{i}", (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, bgr, 2)
            drawio_markers.append(
                {
                    "x": x,
                    "y": y,
                    "r": 10,
                    "stroke": "#%02X%02X%02X" % (bgr[2], bgr[1], bgr[0]),
                    "fill": "none",
                    "label": str(i),
                }
            )

        summary_rows.append(
            {
                "fixture_id": f"fixture_{i:02d}",
                "legend_icon_rect": f"{icon_rect.x},{icon_rect.y},{icon_rect.w},{icon_rect.h}",
                "count": len(matches),
            }
        )

    # Write CSVs
    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["fixture_id", "legend_icon_rect", "count"])
        writer.writeheader()
        writer.writerows(summary_rows)

    with (out_dir / "points.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["fixture_id", "x", "y", "score"])
        writer.writeheader()
        writer.writerows(points_rows)

    imwrite_unicode(out_dir / "overlay.png", overlay)

    # Build draw.io file with markers over the original plan
    build_drawio_markers(plan_path, w, h, drawio_markers, out_dir / "overlay.drawio")

    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# 灯具数量与分布（自动识别）",
                "",
                "输出文件：",
                "- `summary.csv`：每种灯具（按图例顺序 fixture_01..）的数量",
                "- `points.csv`：每个灯具匹配到的点位（像素坐标）",
                "- `overlay.png`：在原图上标注匹配结果（用于人工核对）",
                "- `overlay.drawio`：可在 draw.io 打开编辑的标注图（底图锁定，圆点可编辑/可删）",
                "- `legend_crop.png`：自动识别到的图例区域（用于确认是否找对）",
                "- `templates/fixture_*.png`：用于匹配的图例符号模板",
                "",
                "如果识别偏少/偏多：",
                "- 偏少：把 `--threshold` 调低一点（例如 0.58）",
                "- 偏多：把 `--threshold` 调高一点（例如 0.68）",
                "- 图例找错：用 `--legend-rect x,y,w,h` 手动指定图例框（像素）",
            ]
        ),
        encoding="utf-8",
    )

    print(f"OK: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
