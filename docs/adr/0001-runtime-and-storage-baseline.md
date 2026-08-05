# ADR-0001：Windows 本地运行时与数据库基线

- 状态：已接受
- 日期：2026-08-05

## 背景

V1 只在一台 Windows 电脑上运行，同时要求 SQLite 版本不低于 3.51.3、支持 FTS5/WAL，并需要 PDF、OCR、翻译和单文件启动器。

## 决定

1. 使用 Python 3.12、FastAPI 后端和 React/TypeScript 前端。
2. 核心数据库直接使用 APSW 3.53.3.1；不使用当前 Python 标准库内置的 SQLite 3.50.4。
3. PDF 后端使用 pypdfium2，前端使用 PDF.js。
4. OCR 使用 PaddleOCR PP-OCRv6；翻译使用官方 llama.cpp 和 Hy-MT2-1.8B Q4_K_M。
5. 第一版 Windows 打包以 PyInstaller 为基线，M11 再完成安装器、快捷方式和升级策略。

## 后果

- 数据访问层需直接封装 APSW，不能假定 SQLAlchemy 的 sqlite3 驱动。
- 打包时必须显式收集 APSW、PDFium、Paddle 原生库及许可证。
- SQLite 最低版本、FTS5 和 WAL 都由启动预检及自动测试保护。
