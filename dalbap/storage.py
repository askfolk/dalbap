"""JSON 저장소: 원자적 쓰기 + 하루 1회 자동 백업."""
import json, os, shutil, tempfile, datetime
from pathlib import Path


def default_data_dir() -> Path:
    env = os.environ.get("DALBAP_DATA")
    return Path(env) if env else Path.home() / "달밥데이터"


def read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json_atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # 원자적 교체
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def daily_backup(data_dir: Path, keep_days: int = 60):
    """오늘 날짜 백업 폴더가 없으면 데이터 전체를 복사. 오래된 백업은 정리."""
    today = datetime.date.today().isoformat()
    bdir = data_dir / "backups"
    target = bdir / today
    if not target.exists():
        tmp = bdir / (".tmp-" + today)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        for p in data_dir.iterdir():
            if p.name == "backups":
                continue
            if p.name == "receipts":  # 사진은 한 번 쓰고 안 바뀌므로 목록(JSON)만 백업
                if (p / "receipts.json").exists():
                    (tmp / "receipts").mkdir()
                    shutil.copy2(p / "receipts.json", tmp / "receipts" / "receipts.json")
            elif p.name == "signatures":  # 서명 목록(JSON)만 백업
                if (p / "signatures.json").exists():
                    (tmp / "signatures").mkdir()
                    shutil.copy2(p / "signatures.json", tmp / "signatures" / "signatures.json")
            elif p.is_dir():
                shutil.copytree(p, tmp / p.name)
            elif p.suffix == ".json":
                shutil.copy2(p, tmp / p.name)
        os.replace(tmp, target)
    days = sorted(d for d in bdir.iterdir() if d.is_dir() and not d.name.startswith("."))
    for old in days[:-keep_days]:
        shutil.rmtree(old, ignore_errors=True)
    return target
