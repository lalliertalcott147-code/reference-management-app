# Windows 发布指南

## 1. 发布前检查

1. 确认工作区没有 `.env`、API Key、私人 PDF、数据库、模型、日志或用户数据。
2. 同步版本号：
   - `backend/catalyst_literature/__init__.py`；
   - `frontend/package.json`；
   - `packaging/install.ps1`；
   - `scripts/build-release.ps1` 默认值；
   - `CHANGELOG.md`。
3. 更新 `THIRD_PARTY_NOTICES.md`，确认新增运行时依赖的许可证会进入发布包。
4. 确认根目录 `LICENSE` 和发布目录中的许可证均为 Apache License 2.0 完整文本。
5. 运行仓库检查和完整验证。

```powershell
py -3.12 .\scripts\repository_hygiene.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

## 2. 构建

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-llama-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1 -Version 0.1.0
```

构建脚本会生成前端生产资源、运行 PyInstaller、收集依赖许可证，并输出：

```text
build/release/CatalystLiterature-<version>/
build/release/CatalystLiterature-<version>-windows-x64.zip
```

这些目录和 ZIP 是发布产物，不应 `git add`。把 ZIP 上传为仓库 Release 附件，并在 Release Notes 中附上 SHA-256。

## 3. 安装包验收

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-package.ps1 `
  -PackageRoot .\build\release\CatalystLiterature-0.1.0

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1 `
  -PackageRoot .\build\release\CatalystLiterature-0.1.0
```

冒烟测试必须通过原生依赖自检、临时目录安装、快捷方式、两次启动、健康检查、独立窗口、关闭窗口后的安全退出、卸载和默认保留数据。发布前还应在一台没有开发环境的 Windows 电脑上人工复验安装、打开独立窗口、导入、PDF 阅读和再次启动。

## 4. Release 内容

- 版本号和发布日期；
- 用户可见的新功能、修复和已知限制；
- ZIP 文件名、字节数和 SHA-256；
- 数据迁移或升级注意事项；
- 外部服务 Key、Hy-MT2 首次下载和“数据库备份不含 PDF”的提示。

不要把真实 Key、日志、用户数据库或测试时使用的私人资料放进 Release。
