# PRD 需求追踪表

> 更新日期：2026-08-06。路径均对应当前仓库；最终汇总命令为 `scripts/verify.ps1`。

| PRD 范围 | 开发任务 | 当前主要自动化证据 |
|---|---|---|
| 本地启动、快捷方式、单实例和空闲退出 | M1、M11 | `backend/tests/test_launcher.py`、`test_lifecycle.py`、`test_processes.py`、`test_diagnostics_and_shortcut.py`、安装冒烟 |
| 会话、同源、防跨站和安全响应头 | M1、M11 | `backend/tests/test_security_and_app.py`、`test_server_integration.py` |
| SQLite、迁移、备份、缓存和永久数据保护 | M2、M11 | `backend/tests/storage/`、`backend/tests/release/test_hardening.py` |
| WoS Starter、OpenAlex、Crossref | M3 | `backend/tests/search/test_sources.py`、`test_merge_service.py`、固定 `tests/fixtures/api/` |
| WoS 官方文件导入 | M4 | `backend/tests/importers/test_importers.py`、`frontend/src/pages/ImportPage.test.tsx`、`tests/fixtures/wos/` |
| 页面结构、导航、搜索和详情 | M5 | `frontend/src/App.test.tsx`、`SearchPage.test.tsx`、`components/PaperDetail.test.tsx`、浏览器 E2E |
| 知识库、标签、状态、笔记、导出和回收站 | M6 | `backend/tests/library/`、`frontend/src/pages/LibraryPage.test.tsx`、浏览器持久化 E2E |
| Hy-MT2 本地题名和摘要翻译 | M7 | `backend/tests/translation/`、`backend/tests/release/test_runtime_probe.py` |
| PDF 永久保存、去重、校验、提取和 OCR | M8 | `backend/tests/pdfs/test_ingest.py`、`test_analysis.py`、`test_processing.py`、`test_api.py`、`tests/m0/test_ocr_probe.py` |
| PDF 阅读、续读、搜索和批注笔记联动 | M9 | `backend/tests/pdfs/test_reader.py`、`test_reader_api.py`、`frontend/src/pages/PdfReaderPage.test.tsx` |
| 推荐、期刊、保存检索和 App 内提醒 | M10 | `backend/tests/updates/`、`HomePage.test.tsx`、`JournalsPage.test.tsx`、`SearchPage.test.tsx` |
| 安全、性能、异常恢复和发布 | M11 | `backend/tests/release/`、`tests/e2e/run.mjs`、`scripts/smoke-package.ps1`、`scripts/verify.ps1` |
| Git 提交范围、Markdown 链接和敏感文件防护 | 仓库维护 | `scripts/repository_hygiene.py`、`backend/tests/release/test_repository_hygiene.py` |

真实 WoS/OpenAlex 凭证联调、用户明确确认后的 Hy-MT2 大模型下载，以及另一台物理纯净 Windows 电脑复验需要外部条件参与，不能用固定样本冒充；状态记录在 `IMPLEMENTATION_STATUS.md`。
