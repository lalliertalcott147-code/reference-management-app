# M0 技术与硬件基线

> 采集日期：2026-08-05。仅记录开发和运行兼容性所需的非敏感信息。

## 目标电脑

- 系统：Windows 11，build 26100，64 位。
- CPU：Intel Core i5-12600KF，16 个逻辑处理器。
- GPU：NVIDIA GeForce RTX 4060，8188 MiB 显存，驱动 580.97。
- 内存：由 scripts/preflight.py 在测试时通过 Windows API 读取。
- 工作磁盘：200 GiB，总剩余空间在预检时动态检查；M0 初检约 29.56 GiB。

## 运行时结论

- Python：3.12.13，64 位。
- Node.js：24.14.0。
- pnpm：11.9.0。
- Python 自带 SQLite 是 3.50.4，低于技术设计要求，不能作为核心数据库运行时。
- 核心数据库改用 APSW 3.53.3.1 所附 SQLite，并由自动测试强制最低版本 3.51.3。
- PDF 后端固定 pypdfium2 5.12.1 的默认非 V8/XFA 预编译 PDFium。
- PDF 前端固定 pdfjs-dist 6.1.200，并使用无符号链接的 hoisted 依赖布局兼容中文工作路径。
- OCR 固定 PaddleOCR 3.7.0、PaddlePaddle 3.3.1，PP-OCRv6 本地模型。
- Windows 打包预检使用 PyInstaller 6.21.0。
- llama.cpp 使用官方 Windows x64 CPU 便携构建作为兼容性基线；后续可增加 Vulkan/GPU 构建，但 CPU 回退必须保留。
- llama.cpp 预检构建：b10276（commit 6ea215d17），官方压缩包本地 SHA-256 为 b1db7fc5b3d2728dcead5b792b0565da045dec688df81c9272ce5aef5f55a3e8。
- Paddle 默认会写用户主目录，且其 Windows 原生推理器不能可靠读取中文模型路径；正式实现通过 `PADDLE_PDX_CACHE_HOME` 和 `PADDLE_HOME` 把 OCR 模型定向到 App 管理的 `models/ocr/`，不改写 Windows 用户主目录。M0 测试使用系统临时目录下的纯 ASCII 运行目录。
- PaddlePaddle 3.3.1 的 CPU oneDNN/PIR 路径存在已知回归，PP-OCRv6 必须显式使用 enable_mkldnn=False；固定 OCR 图片测试会防止后续升级重新引入该崩溃。

## 翻译模型决定

- 模型：tencent/Hy-MT2-1.8B-GGUF。
- 文件：Hy-MT2-1.8B-Q4_K_M.gguf，官方页面标称约 1.13 GB。
- 许可证：Apache-2.0。
- 获取方式：首次使用翻译时由用户明确确认后，从官方 Hugging Face 仓库下载；安装包不内置 1.13 GB 模型。
- 完整性：下载到 .part 临时文件，完成后计算 SHA-256；M7 从官方仓库元数据取得并固定校验值，校验通过后原子改名。
- 无模型时：检索、导入、知识库和 PDF 阅读照常工作，翻译入口显示模型未安装。

## M0 判定

M0 自动预检只有在 SQLite/FTS5/WAL、PDFium、PDF.js、PaddleOCR/PaddlePaddle 导入、llama.cpp 可执行文件和最小 Windows 打包探针全部通过时才通过。
