"""파일 저장 추상화

설계서의 StorageProvider — 지금은 LocalStorageProvider 만 구현
향후 MinIO/S3 로 교체할 수 있도록 인터페이스를 유지
DB 에는 실제 파일이 아니라 storage_path만 저장
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class StorageProvider(Protocol):
    def save(self, relative_dir: str, filename: str, data: bytes) -> str: ...

    def resolve(self, storage_path: str) -> Path: ...

    def delete_dir(self, relative_dir: str) -> None: ...


class LocalStorageProvider:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        target_dir = (self.root / relative_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_bytes(data)
        # DB 에는 루트 기준 상대경로를 저장한다
        return (Path(relative_dir) / filename).as_posix()

    def resolve(self, storage_path: str) -> Path:
        return self.root / storage_path

    def delete_dir(self, relative_dir: str) -> None:
        target = self.root / relative_dir
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
