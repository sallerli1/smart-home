# 施工图纸导出（可编辑版本）

这里是把装修公司给的 PDF 施工图转换成「每页 PNG 图片 + 可编辑的 PPT」的导出目录，方便你在不使用 CAD 的情况下进行标注、加点位、写说明。

## 你能怎么编辑

### 方式 A（推荐给点位标注）：diagrams.net / draw.io
- 打开 diagrams.net（网页版或桌面版均可）
- 新建空白图 → 把对应的 `page-xxx.png` 拖进去作为底图
- 右键底图 → `锁定`，避免误移动
- 用图层（Layer）管理：网络/照明回路/开关/插座/窗帘/传感器/电器

### 方式 B（更通用）：PowerPoint（PPT）
- 直接打开 `PPT/*.pptx`
- 在图片上叠加文本框、线条、编号即可

## 文件说明
- `INDEX.md`：导出清单（每份 PDF 对应多少页、PNG 路径、PPT 路径）
- `<图纸名>/page-001.png`：逐页导出的高清图片
- `PPT/<图纸名>.pptx`：把每页图纸做成一页 PPT，方便直接标注

## 重新导出（如需要更清晰）
在工作区根目录运行（我已经准备好脚本）：

- PNG + PPT：
  - `C:\Users\SALLER\AppData\Local\Programs\Python\Python312\python.exe tools\export_construction_pdfs.py --zoom 3.0`
- 只导 PNG：
  - `C:\Users\SALLER\AppData\Local\Programs\Python\Python312\python.exe tools\export_construction_pdfs.py --no-pptx --zoom 3.0`

`zoom` 越大越清晰（文件也越大），一般 2.5~3.0 比较合适。
