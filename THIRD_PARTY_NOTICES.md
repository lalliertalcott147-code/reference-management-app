# 第三方组件与外部服务说明

催化文献检索阅读 App 自有源码采用 Apache License 2.0，完整文本见根目录 `LICENSE`。第三方组件不因此改为 Apache-2.0，仍分别适用下列原始许可证。

发行包的 `licenses/` 目录包含构建环境中各运行时依赖的许可证原文。本文件列出主要直接依赖；若摘要与许可证原文冲突，以原文为准。

| 组件 | 版本 | 用途 | 许可证/来源 |
|---|---:|---|---|
| FastAPI | 0.139.2 | 本地 HTTP API | MIT，https://github.com/fastapi/fastapi |
| Starlette | 1.4.0 | Web 运行时 | BSD-3-Clause，https://github.com/Kludex/starlette |
| Uvicorn | 0.51.0 | 回环服务器 | BSD-3-Clause，https://www.uvicorn.org/ |
| APSW / SQLite | 3.53.3.1 | 本地数据库 | any-OSI / SQLite public domain，https://github.com/rogerbinns/apsw |
| pypdfium2 / PDFium | 5.12.1 | PDF 验证、提取与渲染 | BSD-3-Clause、Apache-2.0 及依赖许可证，https://github.com/pypdfium2-team/pypdfium2 |
| pywebview | 6.2.1 | Windows 独立桌面窗口 | BSD-3-Clause，https://github.com/r0x0r/pywebview |
| PaddlePaddle | 3.3.1 | 本地 OCR 推理 | Apache-2.0，https://github.com/PaddlePaddle/Paddle |
| PaddleOCR / PaddleX | 3.7.x | PP-OCRv6 | Apache-2.0，https://github.com/PaddlePaddle/PaddleOCR |
| llama.cpp | b10276 | 本地 GGUF 推理服务 | MIT，https://github.com/ggml-org/llama.cpp |
| Hy-MT2-1.8B-GGUF | b27182d | 本地中英翻译模型，按需下载 | Apache-2.0，https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF |
| React / React DOM | 19.2.8 | 本地界面 | MIT，https://react.dev/ |
| PDF.js | 6.1.200 | WebView2 窗口内 PDF 阅读 | Apache-2.0，https://github.com/mozilla/pdf.js |
| openpyxl | 3.1.5 | WoS Excel 导入 | MIT，https://openpyxl.readthedocs.io/ |
| PyInstaller | 6.21.0 | Windows 打包 | GPL-2.0-or-later + Bootloader Exception，https://pyinstaller.org/ |

外部服务只在用户主动检索或 App 打开期间的已启用更新任务中调用：

- Clarivate Web of Science Starter API：需要用户自己的可用 Key，受 Clarivate 当前条款和额度约束。
- OpenAlex API：使用用户配置的免费 Key/免费访问，受 OpenAlex 当前条款与速率限制约束。
- Crossref REST API：免费公共元数据服务；配置联系邮箱用于 polite pool。
- Hugging Face：仅在用户明确确认后，从固定 Tencent 仓库下载已知文件并校验 SHA-256。

App 不会自动升级到付费方案，不会模拟学校登录，也不会绕过验证码、MFA、付费墙或访问控制。
