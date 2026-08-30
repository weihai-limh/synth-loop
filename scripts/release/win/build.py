"""
synth-loop Windows 分发构建脚本
================================
将 src/sl-py/ 以「源码分发」形式装配到 deploy/win/synth-loop-v{V}/，
生成 start.bat，并打包为 .zip + .sha256。

约定（与 text-cli / strata-match 的对标实现一致）：
  - 版本号取自仓库根 VERSION（可用 --version 覆盖）
  - 项目根由本脚本位置自动推断，无需 --project-root
  - 只打包运行所需：src/sl-py/（不含运行时库 / 缓存）
  - 不注入任何环境变量；API Key 等由 config.yaml 配置
  - 运行时库 gateway.db 在首次启动由 app.main 自动建库

用法:
    python scripts/release/win/build.py
    python scripts/release/win/build.py --version 0.2.0
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
DEPLOY_ROOT = PROJECT_ROOT / "deploy" / "win"

# 排除运行时库 / 缓存 / 虚拟环境，保持产物纯净
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
    ap = argparse.ArgumentParser(description="synth-loop Windows release builder")
    ap.add_argument("--version", default=None, help="override version from VERSION file")
    args = ap.parse_args()
    version = read_version(args.version)

    output_dir = DEPLOY_ROOT / f"synth-loop-v{version}"
    zip_path = DEPLOY_ROOT / f"synth-loop-v{version}.zip"
    sha_path = DEPLOY_ROOT / f"synth-loop-v{version}.sha256"

    # 1. 清旧产物
    for p in (output_dir, zip_path, sha_path):
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. 组装：src/sl-py -> output/sl-py
    dst = output_dir / "sl-py"
    if not SRC_DIR.is_dir():
        sys.exit(f"[ERR] src not found: {SRC_DIR}")
    shutil.copytree(SRC_DIR, dst, ignore=IGNORE)
    print(f"[OK] assembled sl-py ({len(list(dst.rglob('*')))} entries)")

    # 3. 生成 start.bat（不注入 env，靠 config.yaml 配置）
    bat = f"""@echo off
chcp 65001 >nul
title synth-loop v{version}

cd /d "%~dp0sl-py"
echo [INFO] installing dependencies...
pip install -r requirements.txt --quiet

echo [OK] starting synth-loop v{version}
echo      configure API keys / endpoints in config.yaml
python -m app.main

pause
"""
    (output_dir / "start.bat").write_text(bat, encoding="utf-8")
    print("[OK] start.bat generated")

    # 3b. 生成 end.bat（按端口 13155 优雅停止，对标 text-cli）
    end_bat = """@echo off
chcp 65001 >nul
title synth-loop stop

echo Stopping synth-loop (port 13155)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :13155 ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>&1
    if not errorlevel 1 echo   stopped PID %%a
)
echo Done.
pause
"""
    (output_dir / "end.bat").write_text(end_bat, encoding="utf-8")
    print("[OK] end.bat generated (stop 13155)")

    # 4. 打包 zip
    cmd = [
        "powershell", "-NoProfile", "-Command",
        f"Compress-Archive -Path '{output_dir}' -DestinationPath '{zip_path}'",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"[ERR] zip failed: {r.stderr.strip()}")

    # 5. SHA256
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path.write_text(sha, encoding="utf-8")
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[OK] zip    -> {zip_path.name} ({size_mb:.1f} MB)")
    print(f"[OK] sha256 -> {sha_path.name}")
    print(f"[DONE] synth-loop win v{version} @ {output_dir}")


if __name__ == "__main__":
    main()
