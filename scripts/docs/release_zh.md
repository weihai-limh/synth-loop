# synth-loop 分发脚本说明（release/）

> 本文档只覆盖 `scripts/release/` 部分。ingest 等其它脚本不在此文档范围。
> 脚本源码为唯一权威；本文档是辅助说明。

---

## 1. 分发全景图

```
src/sl-py/  (运行包：app 包在此，入口 python -m app.main，端口 13155)
    │
    ├─ scripts/release/win/build.py       →  deploy/win/synth-loop-v{V}/   (+ .zip + .sha256)
    ├─ scripts/release/linux/build.py     →  deploy/linux/synth-loop-v{V}/ (+ .tar.gz + .sha256)
    ├─ scripts/release/container/build.py →  docker compose build → 镜像 synth-loop:latest / synth-loop:{V}
    └─ scripts/release/build_all.py       →  一键触发上述三平台
```

与 `text-cli` / `strata-match` 的对标关系：

| 维度 | text-cli | strata-match | synth-loop |
|------|----------|--------------|------------|
| 运行包 | `src/` 多阶段骨架 | `src/` | `src/sl-py/` |
| 入口 | `python -m app.main` | `python -m app.main` | `python -m app.main`（PYTHONPATH=src/sl-py） |
| 端口 | — | 13156 | 13155 |
| 容器构建 | `docker build` 装配 | `docker compose build` | `docker compose build` |
| 分发形态 | 源码分发 | 源码分发 | 源码分发 |
| 旧脚本 | 参考源 | 已删 `.dev/release-script` | 已删 `.dev/release-script` |

synth-loop 独有差异：运行包是 `src/sl-py/` 而非 `src/`；包内目录名为 `sl-py/`，启动脚本 `cd sl-py && python -m app.main`。

---

## 2. win / linux 主构建脚本

**步骤：**
1. 读取版本号（仓库根 `VERSION`，可用 `--version` 覆盖）。
2. 清理旧产物（`deploy/{platform}/synth-loop-v{V}/`、`.zip`/`.tar.gz`、`.sha256`）。
3. 组装：将 `src/sl-py/` 拷贝为产出目录下的 `sl-py/`，**排除** `__pycache__`、`*.pyc`、`*.db`、`*.db-shm`、`*.db-wal`、`.venv`。
4. 生成 `start.bat` / `start.sh`。
5. 打包并写 `.sha256`。

**打包范围（仅运行所需）：**
- `sl-py/`（含 `app/`、`config.yaml`、`model_config.yaml`、`complexity_rules.yaml`、`config/`、`public/`、`requirements.txt`）
- `start.bat` / `start.sh`

**刻意不随包：** `sl-web-chat.html`、`docs/`、`README*`、`LICENSE`、`VERSION`、运行时 `gateway.db`、`.venv`、缓存。

**启动脚本关键段（不注入环境变量，靠 config.yaml 配置）：**
```bat
:: win start.bat
cd /d "%~dp0sl-py"
pip install -r requirements.txt --quiet
python -m app.main
```
```bash
# linux start.sh
cd "$(dirname "$0")/sl-py"
pip install -r requirements.txt --quiet
python3 -m app.main
```

**产物路径：**

| 平台 | 解包目录 | 压缩包 |
|------|----------|--------|
| win | `deploy/win/synth-loop-v{V}/` | `deploy/win/synth-loop-v{V}.zip` |
| linux | `deploy/linux/synth-loop-v{V}/` | `deploy/linux/synth-loop-v{V}.tar.gz` |

---

## 3. container 构建脚本

- 通过 `docker compose -f deploy/container/docker-compose.yml build` 构建。
- 先产出 `synth-loop:latest`，再 `docker tag` 为 `synth-loop:{V}`（除非 `--no-tag`）。
- 自动探测 compose：优先 `docker compose`（v2 插件），回退 `docker-compose`。
- 本机未装 Docker 时优雅报错退出，不静默失败。
- **前置修复（已随本脚本一并完成）**：原 `Dockerfile` 写 `COPY src/ /app/src/` 且引用 `src/requirements.txt`，但运行包实际在 `src/sl-py/`，会导致镜像起不来。已修正为 `COPY src/sl-py/ /app/src/` 与 `COPY src/sl-py/requirements.txt`，`PYTHONPATH=/app/src`、`WORKDIR /app/src`、`CMD uvicorn app.main:app` 现已对齐。

**设计铁律：**
1. 脚本只读 `deploy/container`，不改动仓库其它部分。
2. 镜像内数据目录 `/app/src/data` 为 VOLUME，运行时库首次启动自动建。
3. 镜像 tag 为 `synth-loop:latest` 与 `synth-loop:{V}`，不推送（如需 `--push` 另行扩展）。
4. 容器运行所需 API Key 由 `config.yaml` 或 `OPENAI_API_KEY` 环境变量提供，构建脚本不注入。

---

## 4. build_all.py 参数

| 参数 | 说明 |
|------|------|
| （无） | 依次构建 win / linux / container |
| `--skip-container` | 跳过容器构建 |
| `--only win\|linux\|container` | 只构建指定平台 |
| `--version X.Y.Z` | 覆盖所有平台的版本号 |

---

## 5. 核心约定速查

- **版本号**：仓库根 `VERSION`（当前 `0.1.2`），脚本自动读取，`--version` 可覆盖。
- **分发形态**：源码分发（拷 `src/sl-py/` + 目标机 `pip install`），不做二进制冻结。
- **平台范围**：win / linux / container；mac 暂未做（linux 脚本改 shebang 可平移）。
- **排除项**：`__pycache__`、`*.pyc`、`*.db`/`*.db-shm`/`*.db-wal`、`.venv`。
- **环境变量**：不注入；API Key / 端点一律在 `config.yaml` 配置。

---

## 6. 用法

```bash
# Windows 解包后
deploy/win/synth-loop-v0.1.2/start.bat

# Linux 解包后
bash deploy/linux/synth-loop-v0.1.2/start.sh

# 容器（装有 Docker 的机器）
python scripts/release/container/build.py
docker run -d -p 13155:13155 synth-loop:latest

# 一键三平台
python scripts/release/build_all.py
```

---

## 7. 与旧 `.dev/release-script/` 的差异（历史记录）

| 项 | 旧脚本（已删） | 新脚本（scripts/release/） |
|----|----------------|----------------------------|
| 运行包路径 | 拷整 `src/`（含冗余 ck-py / sl-web-chat） | 只拷 `src/sl-py/` |
| 依赖路径 | `src\synth-loop\requirements.txt`（错） | `sl-py/requirements.txt`（对） |
| 启动入口 | `python -m src\synth-loop.main`（错） | `cd sl-py && python -m app.main`（对） |
| 项目根 | 需手动 `--project-root` | 脚本位置自动推断 |
| 容器 | 装配式 `docker build` | `docker compose build`（并修 Dockerfile） |
| db 排除 | 无 | 排除 `gateway.db` 等运行时库 |

---

## 8. 典型症状排查

| 症状 | 根因 / 排查 |
|------|-------------|
| `zip failed` / `tar failed` | 产物目录被占用或权限不足；确认无其它进程占用 `deploy/{platform}` |
| `invalid version` | `VERSION` 文件内容非 `X.Y.Z`；或 `--version` 传参格式错 |
| `VERSION not found` | 脚本被移出 `scripts/release/{platform}/` 层级，导致根推断失败 |
| 启动后 `ModuleNotFoundError: app` | 误在包外运行；必须 `cd sl-py` 后再 `python -m app.main` |
| 启动后连不上策略服务（13156） | synth-loop 依赖 strata-match；配置 `config.yaml` 中策略服务地址 |
| 容器 `uvicorn app.main:app` 报找不到模块 | 旧 Dockerfile 未修；确认已用 `COPY src/sl-py/` 版本 |
| 容器内 500 / 缺 Key | `config.yaml` 未配 API Key，且未注入 `OPENAI_API_KEY` |
| `docker: not found` | 当前机器无 Docker；容器构建需在装有 Docker 环境运行 |

---

_以脚本源码为准。_
