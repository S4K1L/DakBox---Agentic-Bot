"""Backups and the restore drill.

A backup is a folder (backups/<UTC time>/) holding a consistent copy of registry.db and of every business's database, made with SQLite's online backup so the
server keeps running, plus manifest.json (every file's size and checksum, and which business each file is). A backup is only useful if it can be restored, so
`verify` checks the checksums and SQLite's own integrity check, and `drill` restores a backup into a scratch folder and opens every business from it the way the
server would (running the same upgrade step), without touching the live data.

NOT in a backup, on purpose: the master key (DAKBOX_SECRET_KEY). The databases hold stored secrets that only that key can open, so keep the key somewhere
separate and safe, and back it up separately: a backup without the key restores everything except the stored secrets (channel tokens, AI keys), which would
have to be entered again.

Command line (run from backend/):
  python -m app.backups create | list | verify <name> | drill <name> | prune | restore <name> <slug> --yes
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from . import db, registry

KEEP_DEFAULT = 14


def backup_dir() -> Path:
    return Path(os.environ.get("DAKBOX_BACKUP_DIR") or Path(db.DATA_DIR) / "backups")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy(src: sqlite3.Connection, dest: Path) -> None:
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
    finally:
        out.close()


def create(note: str | None = None) -> dict:
    """Back up the registry and every business now. Returns the manifest."""
    name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    base = backup_dir() / name
    n = 1
    while base.exists():                               # two backups in the same second
        n += 1
        base = backup_dir() / f"{name}-{n}"
    (base / "businesses").mkdir(parents=True)
    files = []
    _copy(registry._c(), base / "registry.db")
    files.append({"file": "registry.db", "kind": "registry"})
    for b in registry.all_businesses():
        rel = f"businesses/{b['id']}.db"
        with db.business(b["id"]):
            _copy(db.conn(), base / rel)
        files.append({"file": rel, "kind": "business", "id": b["id"], "slug": b["slug"], "name": b["name"]})
    for f in files:
        p = base / f["file"]
        f["bytes"], f["sha256"] = p.stat().st_size, _sha(p)
    manifest = {"name": base.name, "createdAt": registry._now(), "note": note, "files": files,
                "keyNotIncluded": "The master key (DAKBOX_SECRET_KEY) is not part of a backup. Keep it separately."}
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def list_backups() -> list[dict]:
    out = []
    root = backup_dir()
    for d in sorted(root.glob("*"), reverse=True) if root.exists() else []:
        m = d / "manifest.json"
        if m.exists():
            mm = json.loads(m.read_text())
            out.append({"name": d.name, "createdAt": mm["createdAt"], "businesses": len([f for f in mm["files"] if f["kind"] == "business"]),
                        "bytes": sum(f["bytes"] for f in mm["files"]), "note": mm.get("note")})
    return out


def _dir(name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Not a backup name.")
    d = backup_dir() / name
    if not (d / "manifest.json").exists():
        raise FileNotFoundError(f"No backup called {name}.")
    return d


def verify(name: str) -> dict:
    """Checksums match and SQLite's integrity check passes for every file. {"ok": bool, "problems": [...], "files": n}"""
    d = _dir(name)
    man = json.loads((d / "manifest.json").read_text())
    problems = []
    for f in man["files"]:
        p = d / f["file"]
        if not p.exists():
            problems.append(f"{f['file']}: missing")
            continue
        if _sha(p) != f["sha256"]:
            problems.append(f"{f['file']}: checksum does not match (the file changed or is damaged)")
            continue
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            r = c.execute("PRAGMA integrity_check").fetchone()[0]
            c.close()
            if r != "ok":
                problems.append(f"{f['file']}: integrity check says {r}")
        except sqlite3.Error as e:
            problems.append(f"{f['file']}: cannot be opened ({e})")
    return {"ok": not problems, "problems": problems, "files": len(man["files"]), "name": name}


def drill(name: str) -> dict:
    """Restore the backup into a scratch folder and open every business from it the way the server would. Never touches live data."""
    v = verify(name)
    if not v["ok"]:
        return {**v, "restored": 0, "businesses": []}
    d = _dir(name)
    man = json.loads((d / "manifest.json").read_text())
    report, problems = [], []
    with tempfile.TemporaryDirectory(prefix="dakbox-drill-") as tmp:
        shutil.copytree(d, Path(tmp) / "restore")
        root = Path(tmp) / "restore"
        reg = sqlite3.connect(str(root / "registry.db"))
        n_biz = reg.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        n_acc = reg.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        reg.close()
        for f in man["files"]:
            if f["kind"] != "business":
                continue
            try:
                c = db._open(root / f["file"])                                   # the same open-and-upgrade the server does
                tables = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                products = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                orders = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
                c.close()
                report.append({"slug": f["slug"], "tables": tables, "products": products, "orders": orders})
            except Exception as e:  # noqa: BLE001
                problems.append(f"{f['slug']}: {type(e).__name__}: {e}")
        if n_biz != len([f for f in man["files"] if f["kind"] == "business"]):
            problems.append(f"the registry lists {n_biz} businesses but the backup holds {len(report)} databases")
    return {"ok": not problems, "problems": problems, "name": name, "restored": len(report), "businesses": report, "accounts": n_acc}


def prune(keep: int | None = None) -> list[str]:
    """Keep the newest `keep` backups (DAKBOX_BACKUP_KEEP, default 14); remove the rest. Returns what was removed."""
    k = keep if keep is not None else int(os.environ.get("DAKBOX_BACKUP_KEEP") or KEEP_DEFAULT)
    gone = []
    for b in list_backups()[max(k, 1):]:
        shutil.rmtree(backup_dir() / b["name"], ignore_errors=True)
        gone.append(b["name"])
    return gone


def restore_business(name: str, ref: str) -> dict:
    """Put ONE business's database back from a backup (the live file is kept next to it as *.before-restore-<time>). Stop writes to that business first."""
    d = _dir(name)
    v = verify(name)
    if not v["ok"]:
        raise ValueError("That backup does not verify: " + "; ".join(v["problems"]))
    man = json.loads((d / "manifest.json").read_text())
    b = registry.resolve(ref)
    f = next((x for x in man["files"] if x["kind"] == "business" and x["id"] == b["id"]), None)
    if not f:
        raise ValueError("That backup holds no database for this business.")
    live = Path(registry.path_of(b["id"]))
    db.close_business(b["id"])
    keep = live.with_name(live.name + f".before-restore-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
    if live.exists():
        shutil.copy2(live, keep)
    for suffix in ("-wal", "-shm"):
        Path(str(live) + suffix).unlink(missing_ok=True)
    shutil.copy2(d / f["file"], live)
    with db.business(b["id"]):
        db.get("SELECT COUNT(*) n FROM products")           # opens it (and runs any upgrade)
    return {"restored": b["slug"], "from": name, "previousKeptAs": keep.name}


def last_status() -> dict | None:
    r = registry._c().execute("SELECT value FROM registry_meta WHERE key='backup_status'").fetchone()
    return json.loads(r["value"]) if r else None


def run_scheduled() -> dict:
    """What the daily timer does: back up, verify the new backup, prune old ones, and remember how it went (shown on the platform health page)."""
    status = {"at": registry._now(), "ok": False}
    try:
        m = create("scheduled")
        v = verify(m["name"])
        gone = prune()
        status.update({"ok": v["ok"], "name": m["name"], "problems": v["problems"], "pruned": len(gone)})
    except Exception as e:  # noqa: BLE001
        status["problems"] = [f"{type(e).__name__}: {e}"]
    registry._c().execute("INSERT OR REPLACE INTO registry_meta(key,value) VALUES('backup_status',?)", [json.dumps(status)])
    return status


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "create":
        m = create(" ".join(argv[1:]) or "manual")
        print(f"Backed up {len([f for f in m['files'] if f['kind'] == 'business'])} businesses to {backup_dir() / m['name']}")
        print(m["keyNotIncluded"])
    elif cmd == "list":
        for b in list_backups():
            print(f"{b['name']}  {b['businesses']} businesses  {b['bytes'] // 1024} KB  {b['note'] or ''}")
        if not list_backups():
            print("No backups yet.")
    elif cmd in ("verify", "drill") and len(argv) > 1:
        r = verify(argv[1]) if cmd == "verify" else drill(argv[1])
        print(json.dumps(r, indent=2))
        return 0 if r["ok"] else 1
    elif cmd == "prune":
        print("Removed:", ", ".join(prune()) or "nothing")
    elif cmd == "restore" and len(argv) > 2:
        if "--yes" not in argv:
            print("This replaces that business's database with the backup's. Stop the server (or at least that business) first, then add --yes.")
            return 2
        print(json.dumps(restore_business(argv[1], argv[2]), indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
