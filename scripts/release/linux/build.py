"""
synth-loop Linux 分发构建脚本
=============================
将 src/sl-py/ 以「源码分发」形式装配到 deploy/linux/synth-loop-v{V}/，
生成 start.sh，并打包为 .tar.gz + .sha256。

约定（与 text-cli / strata-match 的对标实现一致）：
  - 版本号取自仓库根 VERSION（可用 --version 覆盖）
  - 项目根由本脚本位置自动推断，无需 --project-root
  - 只打包运行所需：src/sl-py/（不含运行时库 / 缓存）
  - 不注入任何环境变量；API Key 等由 config.yaml 配置
  - 运行时库 gateway.db 在首次启动由 app.main 自动建库

用法:
    python scripts/release/linux/build.py
    python scripts/release/linux/build.py --version 0.2.0
"""
import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src" / "sl-py"
DEPLOY_ROOT = PROJECT_ROOT / "deploy" / "linux"

IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.db", "*.db-shm", "*.db-wal",
    ".venv", "venv", ".git",
)


def read_version(override=None) -> str:
    if override:
        v = override
    else:
        vf = PROJECT_ROOT / "VERSION"
        if not vf.is_file():
            sys.exit(f"[ERR] VERSION not found: {vf}")
        v = vf.read_text(encoding="utf-8").strip()
    if not re.match(r"^\d+\.\d+\.\d+$", v):
        sys.exit(f"[ERR] invalid version: {v!r}")
    return v


def main():
    ap = argparse.ArgumentParser(description="synth-loop Linux release builder")
    ap.add_argument("--version", default=None, help="override version from VERSION file")
    args = ap.parse_args()
    version = read_version(args.version)

    output_dir = DEPLOY_ROOT / f"synth-loop-v{version}"
    tar_path = DEPLOY_ROOT / f"synth-loop-v{version}.tar.gz"
    sha_path = DEPLOY_ROOT / f"synth-loop-v{version}.sha256"

    for p in (output_dir, tar_path, sha_path):
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    dst = output_dir / "sl-py"
    if not SRC_DIR.is_dir():
        sys.exit(f"[ERR] src not found: {SRC_DIR}")
    shutil.copytree(SRC_DIR, dst, ignore=IGNORE)
    print(f"[OK] assembled sl-py ({len(list(dst.rglob('*')))} entries)")

    sh = f"""#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/sl-py"
echo "[INFO] installing dependencies..."
pip install -r requirements.txt --quiet

echo "[OK] starting synth-loop v{version}"
echo "     configure API keys / endpoints in config.yaml"
python3 -m app.main
"""
    p = output_dir / "start.sh"
    p.write_text(sh, encoding="utf-8")
    p.chmod(0o755)
    print("[OK] start.sh generated")

    # 生成 end.sh（按端口 13155 优雅停止，对标 text-cli）
    end_sh = f"""#!/bin/bash
set -u
PORT=13155
echo "Stopping synth-loop (port $PORT)..."

pids=""
if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:$PORT 2>/dev/null || true)
fi
if [ -z "$pids" ] && command -v ss >/dev/null 2>&1; then
    pids=$(ss -ltnp 2>/dev/null | grep -E ":$PORT\\\\b" | grep -oP 'pid=\\\\K[0-9]+' | sort -u)
fi
if [ -z "$pids" ] && command -v fuser >/dev/null 2>&1; then
    pids=$(fuser $PORT/tcp 2>/dev/null | tr -s ' ' || true)
fi

if [ -z "$pids" ]; then
    echo "  no process listening on $PORT"
    exit 0
fi

echo "  found PID(s): $pids"
for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null && echo "  sent TERM to $pid"
done
sleep 2
for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null && echo "  force killed $pid"
    fi
done
echo "Done."
"""
    ep = output_dir / "end.sh"
    ep.write_text(end_sh, encoding="utf-8")
    ep.chmod(0o755)
    print("[OK] end.sh generated (stop 13155)")

    cmd = ["tar", "-czf", str(tar_path), "-C", str(DEPLOY_ROOT), f"synth-loop-v{version}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"[ERR] tar failed: {r.stderr.strip()}")

    sha = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    sha_path.write_text(sha, encoding="utf-8")
    size_mb = tar_path.stat().st_size / (1024 * 1024)
    print(f"[OK] tar.gz -> {tar_path.name} ({size_mb:.1f} MB)")
    print(f"[OK] sha256 -> {sha_path.name}")
    print(f"[DONE] synth-loop linux v{version} @ {output_dir}")


if __name__ == "__main__":
    main()
