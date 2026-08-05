# 变更日志

本项目按 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 组织版本记录，并使用语义化版本号。

## [Unreleased]

### Changed

- 整理 Git 仓库文档、忽略规则、文本属性和可复现开发/发布说明。
- 项目自有源码采用 Apache License 2.0 开源。

## [0.1.0] - 2026-08-06

### Added

- pywebview 与 Microsoft Edge WebView2 驱动的 Windows 独立桌面窗口；主界面不再占用浏览器标签页。
- 关闭窗口时安全停止本地服务，以及重复启动时恢复并聚焦已有窗口。
- Windows 本地 App、单实例启动、一次性会话和页面心跳异常兜底退出。
- APSW SQLite 永久存储、前向迁移、数据库备份、DPAPI 密钥和 500 MB 缓存控制。
- WoS Starter、OpenAlex、Crossref 检索适配器与 WoS Plain Text/RIS/XLSX 导入。
- 文献详情、多知识库、标签、状态、笔记、本地检索和 BibTeX/RIS/CSV 导出。
- Hy-MT2-1.8B GGUF 按需本地翻译与术语保护。
- PDF 永久入库、三级去重、PDFium 提取、PP-OCRv6 和题名摘要候选。
- PDF.js 阅读器、续读、搜索、高亮、划线、批注及笔记联动。
- 可解释推荐、期刊关注、保存检索和仅在 App 打开时运行的提醒。
- Windows 安装、升级、卸载、原生依赖自检、浏览器 E2E 和发布冒烟测试。
