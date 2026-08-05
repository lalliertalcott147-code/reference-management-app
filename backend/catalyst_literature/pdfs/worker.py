from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import PdfAnalysisError, analyze_pdf, inspect_pdf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("analyze", "inspect"), default="analyze")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runtime-home")
    parser.add_argument("--cancel-file")
    parser.add_argument("--progress-file")
    arguments = parser.parse_args()
    output = Path(arguments.output)
    if arguments.mode == "inspect":
        try:
            page_count, candidates = inspect_pdf(Path(arguments.input))
            result: dict[str, object] = {
                "ok": True,
                "page_count": page_count,
                "candidates": candidates,
            }
        except PdfAnalysisError as error:
            result = {"ok": False, "error": str(error)}
        temporary = output.with_suffix(".part")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(output)
        return 0
    if not arguments.runtime_home or not arguments.cancel_file or not arguments.progress_file:
        parser.error("analyze mode requires runtime-home, cancel-file, and progress-file")
    progress_file = Path(arguments.progress_file)

    def update_progress(current: int, total: int) -> None:
        temporary_progress = progress_file.with_suffix(".part")
        temporary_progress.write_text(f"{current},{total}", encoding="ascii")
        temporary_progress.replace(progress_file)

    result = analyze_pdf(
        Path(arguments.input),
        Path(arguments.runtime_home),
        cancel_file=Path(arguments.cancel_file),
        progress=update_progress,
    )
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
