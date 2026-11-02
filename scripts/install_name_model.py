"""파인튜닝한 이름 마스킹 모델(오닉스 int8)을 NAME_MODEL_DIR에 넣는다.

    python scripts/install_name_model.py <원본 폴더> [저장 폴더]

원본 폴더는 config.json과 onnx/model_int8.onnx, onnx/tokenizer.json이 든 폴더다
(ner_eval/finetune.py final2가 만드는 name_audit/finetuned_v2/model). 실명이 든 공지로
학습한 모델이라 저장소에 올리지 않으므로, 서버에는 이 폴더를 직접
복사한 뒤 이 스크립트로 넣는다. 저장 폴더를 생략하면 설정의 NAME_MODEL_DIR
(기본 ./models/kau-name-ner)에 넣는다.

평가한 파일(app/name_masking.MODEL_SHA256)과 같은지 SHA-256으로 확인하고, 다르면
넣지 않는다. 원본 폴더 없이 저장 폴더만 확인하려면 `--check`를 쓴다.

    python scripts/install_name_model.py --check
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.name_masking import MODEL_FILES, MODEL_SHA256  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_target() -> Path:
    from app.config import get_settings

    return Path(get_settings().name_model_dir)


def check(target: Path) -> None:
    bad = []
    for name in MODEL_FILES:
        path = target / name
        if not path.exists():
            bad.append(f"없음 {path}")
        elif sha256(path) != MODEL_SHA256[name]:
            bad.append(f"해시가 다름 {path}")
    if bad:
        raise SystemExit("\n".join(bad))
    print(f"확인 {target}")


def install(source: Path, target: Path) -> None:
    for name in MODEL_FILES:
        src = source / name
        if not src.exists():
            raise SystemExit(f"없음 {src}")
        actual = sha256(src)
        if actual != MODEL_SHA256[name]:
            raise SystemExit(f"해시가 다릅니다: {src} ({actual})")
    for name in MODEL_FILES:
        dst = target / name
        if dst.exists() and sha256(dst) == MODEL_SHA256[name]:
            print(f"있음 {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        shutil.copyfile(source / name, tmp)
        tmp.replace(dst)
        print(f"넣음 {dst}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "--check":
        check(Path(args[1]) if len(args) > 1 else default_target())
        return
    install(Path(args[0]), Path(args[1]) if len(args) > 1 else default_target())


if __name__ == "__main__":
    main()
