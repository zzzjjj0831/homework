"""一键运行三个子项目的单元测试（纯标准库 unittest，不需要 pytest / 网络 / 真实模型）。

用法：
    python run_tests.py            # 全部
    python run_tests.py jagent     # 只跑某个子项目（jagent / pet-hospital / anythingllm）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITES = {
    "jagent": ("Agent/jagent", "tests"),
    "pet-hospital": ("PetHospitalmcp", "tests"),
    "anythingllm": ("AnythingLLMCP", "tests"),
}


def run(project: str, tests_dir: str) -> int:
    cwd = ROOT / project
    print(f"\n===== {project} =====", flush=True)
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", tests_dir, "-t", "."],
        cwd=str(cwd),
    )


def main(argv: list[str]) -> int:
    selected = {argv[1]: SUITES[argv[1]]} if len(argv) > 1 and argv[1] in SUITES else SUITES
    if len(argv) > 1 and argv[1] not in SUITES:
        print(f"未知子项目：{argv[1]}，可选：{', '.join(SUITES)}")
        return 2

    failures = [name for name, (project, tests) in selected.items() if run(project, tests) != 0]
    print("\n" + "=" * 40)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print(f"OK: {len(selected)} 个子项目全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
