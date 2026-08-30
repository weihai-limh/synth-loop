"""
synth-loop 容器分发构建脚本
===========================
通过 docker compose build 构建 synth-loop 镜像：
  - 先由 deploy/container/docker-compose.yml 构建出 synth-loop:latest
  - 再打版本 tag: synth-loop:{V}（除非 --no-tag）

约定（与 strata-match 的对标实现一致，采用 docker compose build）：
  - 版本号取自仓库根 VERSION（可用 --version 覆盖）
  - 脚本只读 deploy/container，不修改仓库其它部分
  - 真实构建需在本机装有 Docker 的环境运行

用法:
    python scripts/release/container/build.py
    python scripts/release/container/build.py --version 0.2.0
    python scripts/release/container/build.py --no-tag
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSE = PROJECT_ROOT / "deploy" / "container" / "docker-compose.yml"


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


def resolve_compose(docker: str):
    """返回 compose 调用前缀：['docker','compose'] 或 ['docker-compose']，否则 None。"""
    p = subprocess.run([docker, "compose", "version"], capture_output=True, text=True)
    if p.returncode == 0:
        return [docker, "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def main():
    ap = argparse.ArgumentParser(description="synth-loop container release builder")
    ap.add_argument("--version", default=None, help="override version from VERSION file")
    ap.add_argument("--no-tag", action="store_true", help="只构建 latest，不打版本 tag")
    args = ap.parse_args()
    version = read_version(args.version)

    docker = shutil.which("docker")
    if not docker:
        sys.exit("[ERR] docker 未安装或不在 PATH；请在装有 Docker 的机器上运行此脚本。")

    compose = resolve_compose(docker)
    if compose is None:
        sys.exit("[ERR] 未找到 docker compose 插件或 docker-compose；请先安装。")

    if not COMPOSE.is_file():
        sys.exit(f"[ERR] compose file not found: {COMPOSE}")

    print(f"[RUN] {' '.join(compose)} -f {COMPOSE} build")
    rc = subprocess.run(compose + ["-f", str(COMPOSE), "build"]).returncode
    if rc != 0:
        sys.exit(f"[ERR] docker compose build 失败 (rc={rc})")

    if not args.no_tag:
        print(f"[RUN] {docker} tag synth-loop:latest synth-loop:{version}")
        rc = subprocess.run([docker, "tag", "synth-loop:latest", f"synth-loop:{version}"]).returncode
        if rc != 0:
            sys.exit(f"[ERR] docker tag 失败 (rc={rc})")
        print(f"[OK] tagged synth-loop:latest -> synth-loop:{version}")

    print(f"[DONE] synth-loop container v{version} built")


if __name__ == "__main__":
    main()
