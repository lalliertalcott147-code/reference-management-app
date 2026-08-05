# 催化文献检索阅读 App

一个面向个人科研使用的 Windows 本地文献工作台。它使用独立的 Windows 桌面窗口，后端、数据库、PDF、译文、笔记和模型全部保存在当前电脑；关闭 App 窗口后，本地服务会安全退出。

当前版本：`0.1.0`。M0～M11 的工程实现和自动化验收已经完成，具体证据见[实施状态](IMPLEMENTATION_STATUS.md)。

## 主要能力

- Web of Science Starter API 主检索，OpenAlex/Crossref 免费补全，以及 WoS Plain Text、RIS、XLSX 官方导出导入。
- 多知识库、标签、收藏、阅读状态、笔记、本地检索和 BibTeX/RIS/CSV 导出。
- PDF 永久本地保存、SHA-256 去重、普通/扫描/混合页识别和 PP-OCRv6 本地 OCR。
- 基于 PDF.js 的阅读、搜索、续读、高亮、划线和批注；标注不写回原 PDF。
- 腾讯 Hy-MT2-1.8B GGUF 本地题名/摘要翻译，首次使用需明确确认下载。
- 可解释的主题推荐、期刊关注、保存检索和仅在 App 打开期间运行的更新提醒。

## 安装发布版

源码仓库不提交构建目录、安装 ZIP、OCR 模型或 llama.cpp 二进制。请从项目 Release 页面下载 `CatalystLiterature-0.1.0-windows-x64.zip`，解压后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

然后双击桌面的“催化文献”快捷方式。独立窗口使用 Microsoft Edge WebView2 Runtime；Windows 11 通常已预装。升级前关闭 App，再运行新版安装脚本。卸载默认保留知识库、PDF、模型和设置；只有明确提供双重删除参数时才会移除永久数据。

完整操作见[用户说明](docs/USER_GUIDE.md)。

## 从源码运行

要求 Windows 11 x64、Python 3.12、Node.js 24 和 pnpm 11。首次运行会安装固定版本依赖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-and-run.ps1
```

开发数据写入仓库内已忽略的 `.dev-data/`，不会覆盖正式数据。详细环境、命令和目录结构见[开发指南](docs/DEVELOPMENT.md)。

## 验证与打包

```powershell
# 全部静态检查、后端/前端测试、生产构建和浏览器 E2E
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1

# 获取固定且校验过的 llama.cpp 运行时，并生成 Windows 发布包
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-llama-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

提交前还可以单独运行不依赖第三方包的仓库卫生检查：

```powershell
py -3.12 .\scripts\repository_hygiene.py
```

测试规则和发布步骤分别见[开发指南](docs/DEVELOPMENT.md)与[发布指南](docs/RELEASE.md)。

## 数据、安全与范围边界

- 正式数据位于 `%LOCALAPPDATA%\CatalystLiterature`，不在 Git 工作区内。
- API Key 由 Windows DPAPI 加密；`.env`、数据库、PDF、模型、日志和本地缓存均被 Git 忽略。
- App 不接收学校账号密码，不模拟登录，不抓取 WoS 登录网页，也不绕过验证码、MFA、订阅或付费墙。
- 只使用免费服务或免费额度；达到额度后停止调用，不自动转为付费。
- 内置数据库备份不包含原始 PDF，重要 PDF 仍需用户自行备份。

安全问题的提交方式见[安全政策](SECURITY.md)，第三方许可见[第三方组件说明](THIRD_PARTY_NOTICES.md)。

## 文档导航

文档入口见 [docs/README.md](docs/README.md)。产品范围以 [PRD.md](PRD.md) 为准；已实现架构以 [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md) 为准；开发里程碑以 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 和 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 为准。

## 许可

本项目采用 [Apache License 2.0](LICENSE) 开源。使用、修改和分发时请遵守许可证中的署名、变更说明及其他条件。第三方组件继续分别受其原始许可证约束。
