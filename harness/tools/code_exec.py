from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


MAX_OUTPUT = 8000


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n... truncated ..."


def _run_compiled(code: str, stdin: str, compiler_name: str, suffix: str, standard: str) -> str:
    compiler = shutil.which(compiler_name)
    if not compiler:
        return "error: gcc/g++(w64devkit)가 필요합니다."

    temp_dir = Path(tempfile.mkdtemp(prefix="openlm_code_"))
    try:
        source = temp_dir / f"main{suffix}"
        binary = temp_dir / "main.exe"
        source.write_text(code, encoding="utf-8")

        compile_result = subprocess.run(
            [compiler, str(source), "-O2", standard, "-o", str(binary)],
            input="",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
        )
        compile_output = (compile_result.stdout or "") + (compile_result.stderr or "")
        if compile_result.returncode != 0:
            return _truncate(compile_output or f"compile failed with exit code {compile_result.returncode}")

        run_result = subprocess.run(
            [str(binary)],
            input=stdin or "",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
        )
        output = (run_result.stdout or "") + (run_result.stderr or "")
        if run_result.returncode != 0 and not output:
            output = f"program exited with code {run_result.returncode}"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return "error: 실행 시간이 30초를 초과했습니다."
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_c(code: str, stdin: str = "") -> str:
    return _run_compiled(code, stdin, "gcc", ".c", "-std=c11")


def run_cpp(code: str, stdin: str = "") -> str:
    return _run_compiled(code, stdin, "g++", ".cpp", "-std=c++17")


def register(registry: Any) -> None:
    registry.add(
        "run_c",
        "C 코드를 컴파일하고 실행합니다.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "stdin": {"type": "string", "default": ""},
            },
            "required": ["code"],
        },
        run_c,
        permissions=(),
    )
    registry.add(
        "run_cpp",
        "C++ 코드를 컴파일하고 실행합니다.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "stdin": {"type": "string", "default": ""},
            },
            "required": ["code"],
        },
        run_cpp,
        permissions=(),
    )

