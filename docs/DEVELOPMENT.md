# 开发指南

## 1. 支持环境

- Windows 11 x64；
- Python 3.12；
- Node.js 24；
- pnpm 11；
- Microsoft Edge，用于 Playwright 浏览器 E2E；
- 建议至少 8 GB 内存和 8 GB 可用磁盘，完整打包建议预留更多空间。

依赖版本固定在 `requirements*.txt`、`frontend/package.json` 和 `frontend/pnpm-lock.yaml`。不要把 `.venv/`、`node_modules/`、模型或下载的原生二进制提交到 Git。

## 2. 全新克隆后启动

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-and-run.ps1
```

脚本会创建 `.venv/`、安装固定 Python/Node 依赖，然后使用 `.dev-data/` 启动 App。二者均在 `.gitignore` 中。后续无需重装依赖时可以使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-and-run.ps1 -SkipInstall
```

开发模式也只监听 `127.0.0.1`，并遵守浏览器标签页空闲退出规则。

## 3. 常用命令

```powershell
# 后端静态检查和严格类型检查
.\.venv\Scripts\python.exe -m ruff check backend tests scripts
.\.venv\Scripts\python.exe -m mypy backend\catalyst_literature

# 全部 Python 测试
.\.venv\Scripts\python.exe -m pytest tests backend\tests -q

# 前端检查、测试和构建
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build

# 真实浏览器端到端测试
pnpm --dir frontend test:e2e

# 仓库与 Markdown 检查
.\.venv\Scripts\python.exe .\scripts\repository_hygiene.py

# 完整验证入口
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

`verify.ps1` 会在缺少 M0 PyInstaller 探针时先构建探针，然后依次运行仓库卫生、Ruff、Mypy、全部 Python 测试、前端检查/测试/构建和浏览器 E2E。传入 `-PackageRoot` 时还会验证安装包。

## 4. 目录结构

```text
backend/catalyst_literature/  FastAPI、启动器、SQLite、检索、翻译、PDF、更新任务
backend/tests/                后端单元、集成、压力和发布测试
frontend/src/                 React、TypeScript、PDF.js 页面与组件测试
tests/fixtures/               固定、脱敏或生成的测试样本
tests/e2e/                    真实浏览器主流程
tests/m0/                     原生运行时预检
packaging/                    安装、卸载和直接依赖许可证
scripts/                      开发、验证、下载运行时和发布脚本
docs/                         用户、开发、发布、追踪和 ADR
vendor/                       下载得到的 llama.cpp；目录内容不提交
build/、dist/                 生成物；不提交
```

## 5. 数据与环境变量

正式数据默认位于 `%LOCALAPPDATA%\CatalystLiterature`。`run-dev.ps1` 将 `CATALYST_DATA_DIR` 指向 `.dev-data/`，防止开发测试覆盖正式资料。

仅开发和自动测试使用以下环境变量；普通用户应在 App 设置页配置来源：

| 变量 | 用途 |
|---|---|
| `CATALYST_DATA_DIR` | 覆盖本地数据根目录 |
| `CATALYST_NO_BROWSER=1` | 测试时不自动打开浏览器 |
| `CATALYST_*_SECONDS` | 生命周期专项测试的超时覆盖 |
| `CATALYST_NODE_EXE` | `verify.ps1` 找不到 Node 时指定路径 |
| `WOS_API_KEY` | 只供手动真实来源冒烟测试 |
| `OPENALEX_API_KEY` | 只供手动真实来源冒烟测试 |
| `CROSSREF_EMAIL` | Crossref polite pool 联系邮箱 |

不要创建或提交包含真实值的 `.env`。App 内保存的 Key 由 DPAPI 加密，测试日志也不得输出真实值。

## 6. llama.cpp 与发布构建

源码仓库不提交 60 MB 以上的 llama.cpp 解压目录。执行以下脚本会从固定官方 GitHub Release 下载 `b10276` CPU x64 包，验证 SHA-256 后解压到已忽略的 `vendor/llama.cpp/`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-llama-runtime.ps1
```

`build-release.ps1` 在缺少运行时时也会调用该脚本。Hy-MT2 模型不参与开发构建和 Git 提交；它只能由用户在 App 内首次明确确认后下载。

## 7. 数据库与测试规则

- 只允许前向迁移；数据库结构变化必须保留上一版升级测试。
- 永久数据写入必须处于事务中，文件先写 `.part` 再原子替换。
- 外部 API 单元测试使用固定响应，不依赖真实网络或用户密钥。
- 功能测试不得删除、跳过或降低断言来通过。
- PDF、导出和 API 样本必须公开、授权、脱敏或由测试生成。
