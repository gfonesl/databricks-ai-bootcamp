from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKFILE = ROOT / "requirements.txt"
PYPI_INDEX = "--index-url https://pypi.org/simple\n"
PYTORCH_CPU_INDEX = (
    "# The CPU index is added by scripts/compile_requirements.py for pip compatibility.\n"
    "--extra-index-url https://download.pytorch.org/whl/cpu\n"
)


def main() -> None:
    subprocess.run(
        [
            "uv",
            "pip",
            "compile",
            "requirements.in",
            "--universal",
            "--generate-hashes",
            "--torch-backend",
            "cpu",
            "--emit-index-url",
            "--emit-index-annotation",
            "--output-file",
            "requirements.txt",
        ],
        cwd=ROOT,
        check=True,
    )

    content = LOCKFILE.read_text(encoding="utf-8")
    if PYPI_INDEX not in content:
        raise RuntimeError("uv did not emit the expected PyPI index declaration")
    if PYTORCH_CPU_INDEX not in content:
        content = content.replace(PYPI_INDEX, PYPI_INDEX + PYTORCH_CPU_INDEX, 1)
        LOCKFILE.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
