"""Load a Wasooli export from the command line (no HTTP, no login needed on the server itself).

    docker compose exec api python -m app.import_cli /data/storage/Wasooli.pdf             # parse + preview
    docker compose exec api python -m app.import_cli /data/storage/Wasooli.pdf --commit    # and import
    ... --commit --include-review     # also import "possible duplicate" rows as separate customers

Copy the PDF into the project's ./storage folder first; the container sees it under /data/storage.
Re-running with the same file is safe: nobody is created twice.
"""

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.models import ImportSession
from app.services import importer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import a Wasooli 'all connections' PDF")
    ap.add_argument("pdf")
    ap.add_argument("--commit", action="store_true", help="write to the database (default: preview only)")
    ap.add_argument("--include-review", action="store_true",
                    help="import possible duplicates as separate customers instead of holding them back")
    args = ap.parse_args(argv)

    src = Path(args.pdf)
    if not src.is_file():
        print(f"File not found: {src}", file=sys.stderr)
        return 2
    data = src.read_bytes()
    if not data.startswith(b"%PDF"):
        print("That is not a PDF file", file=sys.stderr)
        return 2
    digest = hashlib.sha256(data).hexdigest()

    with session_factory()() as db:
        sess = db.scalar(select(ImportSession).where(ImportSession.file_sha256 == digest,
                                                     ImportSession.status != "FAILED"))
        if sess is None:
            folder = Path(get_settings().storage_dir) / "imports"
            folder.mkdir(parents=True, exist_ok=True)
            sid = uuid.uuid4()
            dest = folder / f"{sid}.pdf"
            shutil.copyfile(src, dest)
            sess = ImportSession(id=sid, file_name=src.name[:300], file_size=len(data), file_sha256=digest,
                                 storage_path=str(dest), status="UPLOADED")
            db.add(sess)
            db.commit()
            print(f"Reading {src.name} (this takes about 30 seconds for 1,250 customers)...")
            importer.parse_session(sid)
            db.expire_all()
            sess = db.get(ImportSession, sid)
        else:
            print(f"This file was already read (import {sess.id}); reusing that result.")
        if sess.status == "FAILED":
            print("FAILED:", (sess.summary or {}).get("error"), file=sys.stderr)
            return 1
        print(f"Import {sess.id}: {sess.status}")
        print(json.dumps(sess.summary, indent=2, ensure_ascii=False))
        report = importer.commit_session(db, sess, user_id=None, include_review=args.include_review,
                                         dry_run=not args.commit)
        print("\n" + ("DONE" if args.commit else "PREVIEW (nothing written; add --commit to import)"))
        print(json.dumps({k: v for k, v in report.items() if k not in ("areas_to_create",)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
