#!/usr/bin/env python3
"""合并七个工作区的数字郑老师知识库，并重建共享索引。

运行前请停止 Uvicorn，避免迁移期间上传或删除文档。
本脚本只复制文档，不删除旧目录；旧目录可作为迁移备份。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import settings
from app.rag.document import SHARED_TEACHER_KB_AGENT_ID, reindex_all_documents

WORKSPACE_IDS = (
    "project-development-quality-agent",
    "process-quality-control-agent",
    "supplier-quality-agent",
    "aftersales-quality-agent",
    "quality-system-agent",
    "measurement-laboratory-agent",
    "continuous-improvement-agent",
)
TEACHER_SUFFIX = "-digital-zheng-teacher-agent"
SUPPORTED_EXTENSIONS = {
    ".pdf", ".txt", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"
}


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _unique_target(target_dir: Path, source_id: str, filename: str) -> Path:
    source_path = Path(filename)
    candidate = target_dir / f"{source_id}__{source_path.name}"
    serial = 2
    while candidate.exists():
        candidate = target_dir / f"{source_id}__{source_path.stem}__{serial}{source_path.suffix}"
        serial += 1
    return candidate


def migrate() -> dict:
    documents_root = Path(settings.DOCUMENTS_DIR)
    target_dir = documents_root / f"agent_{SHARED_TEACHER_KB_AGENT_ID}"
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    duplicates = []
    renamed_conflicts = []
    missing_sources = []

    for workspace_id in WORKSPACE_IDS:
        source_agent_id = f"{workspace_id}{TEACHER_SUFFIX}"
        source_dir = documents_root / f"agent_{source_agent_id}"
        if not source_dir.exists():
            missing_sources.append(source_agent_id)
            continue

        for source_file in sorted(source_dir.iterdir()):
            if not source_file.is_file() or source_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            destination = target_dir / source_file.name
            if destination.exists():
                if source_file.stat().st_size == destination.stat().st_size and _digest(source_file) == _digest(destination):
                    duplicates.append(str(source_file))
                    continue
                destination = _unique_target(target_dir, workspace_id, source_file.name)
                renamed_conflicts.append({"source": str(source_file), "target": str(destination)})

            shutil.copy2(source_file, destination)
            copied.append({"source": str(source_file), "target": str(destination)})

    reindex_result = reindex_all_documents(agent_id=SHARED_TEACHER_KB_AGENT_ID)
    return {
        "status": "success" if reindex_result.get("status") == "success" else "partial",
        "shared_agent_id": SHARED_TEACHER_KB_AGENT_ID,
        "shared_directory": str(target_dir),
        "copied": len(copied),
        "duplicates_skipped": len(duplicates),
        "renamed_conflicts": len(renamed_conflicts),
        "missing_source_directories": missing_sources,
        "reindex": reindex_result,
    }


if __name__ == "__main__":
    print(json.dumps(migrate(), ensure_ascii=False, indent=2))
