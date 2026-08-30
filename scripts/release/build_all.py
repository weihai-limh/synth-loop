"""
synth-loop 一键分发入口
=======================
依次调用 win / linux / container 三个平台的构建脚本，等价于对标
text-cli / strata-match 的 build-all 总入口。

用法:
    python scripts/release/build_all.py
    python scripts/release/build_all.py --skip-container
    python scripts/release/build_all.py --only win
    python scripts/release/build_all.py --version 0.2.0
"""
import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent  # scripts/release


def main():
    ap = argparse.ArgumentParser(description="synth-loop release all platforms")
    ap.add_argument("--version", default=None, help="override version for all platforms")
    ap.add_argument("--skip-container", action="store_true", help="跳过容器构建")
    ap.add_argument("--only", choices=["win", "linux", "container"], default=None,
                    help="只构建指定平台")
    args = ap.parse_args()

    targets = ["win", "linux", "container"]
    if args.only:
        targets = [args.only]
    if args.skip_container:
        targets = [t for t in targets if t != "container"]

    for t in targets:
        script = HERE / t / "build.py"
        print(f"\n===== {t.upper()} =====")
        cmd = [sys.executable, str(script)]
        if args.version:
            cmd += ["--version", args.version]
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"[WARN] {t} build 失败 (rc={rc})，继续下一平台")


if __name__ == "__main__":
    main()
