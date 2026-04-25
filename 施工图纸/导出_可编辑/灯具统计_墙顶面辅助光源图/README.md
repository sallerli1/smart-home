# 灯具数量与分布（自动识别）

输出文件：
- `summary.csv`：每种灯具（按图例顺序 fixture_01..）的数量
- `points.csv`：每个灯具匹配到的点位（像素坐标）
- `overlay.png`：在原图上标注匹配结果（用于人工核对）
- `overlay.drawio`：可在 draw.io 打开编辑的标注图（底图锁定，圆点可编辑/可删）
- `legend_crop.png`：自动识别到的图例区域（用于确认是否找对）
- `templates/fixture_*.png`：用于匹配的图例符号模板

如果识别偏少/偏多：
- 偏少：把 `--threshold` 调低一点（例如 0.58）
- 偏多：把 `--threshold` 调高一点（例如 0.68）
- 图例找错：用 `--legend-rect x,y,w,h` 手动指定图例框（像素）