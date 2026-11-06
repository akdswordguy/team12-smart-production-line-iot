"""Build a portable, complete Team 12 ZIP without machine-specific runtime files."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, is_zipfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT_FILES = {
    ".gitignore", "README.md", "SHARE_THIS_FIRST.md", "START_HERE.md",
    "requirements.txt",
}
ALLOWED_FOLDERS = {"config", "data", "db", "docs", "nodered", "results", "scripts", "src", "tests"}
EXCLUDED_DIRS = {".venv", "node_modules", "__pycache__", ".git", "logs"}
EXCLUDED_NAMES = {
    "flow.local.json", ".config.nodes.json", ".config.nodes.json.backup",
    ".config.runtime.json", ".config.runtime.json.backup",
}


def include(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return False
    if len(parts) == 1:
        return parts[0] in ALLOWED_ROOT_FILES
    if parts[0] not in ALLOWED_FOLDERS or path.name in EXCLUDED_NAMES:
        return False
    if path.suffix in {".pyc", ".db-wal", ".db-shm"}:
        return False
    if parts[0] == "nodered":
        return path.name in {"flow.json", "package.json", "package-lock.json", "settings.js"}
    if parts[0] == "db":
        return path.name in {"schema.sql", "team12.db"}
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--include-original", type=Path,
                        help="include the unchanged supplied archive as a reference")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    original = args.include_original.resolve() if args.include_original else None
    if original and not is_zipfile(original):
        raise SystemExit(f"Original archive is missing or not a valid ZIP: {original}")
    files = sorted((p for p in ROOT.rglob("*") if p.is_file() and include(p)),
                   key=lambda p: p.relative_to(ROOT).as_posix())
    required = {
        "data/raw/company_A.csv", "data/raw/company_B.zip",
        "data/processed/features.csv", "data/processed/company_b_replay.csv",
        "db/team12.db", "nodered/flow.json", "results/chosen_model.joblib",
        "results/company_b_model.joblib", "config/public_broker.json",
        "docs/PUBLIC_BROKER_DEMO.md", "SHARE_THIS_FIRST.md",
    }
    names = {p.relative_to(ROOT).as_posix() for p in files}
    missing = required - names
    if missing:
        raise SystemExit(f"Missing required package files: {sorted(missing)}")
    hashes = {}
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6,
                 allowZip64=True) as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            with path.open("rb") as stream:
                hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            archive.write(path, f"iotproject/{name}")
        original_record = None
        if original:
            with original.open("rb") as stream:
                original_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            original_name = "original_archive/iotproject-complete-akd.adding"
            archive.write(original, original_name, compress_type=ZIP_STORED)
            original_record = {"path": original_name, "sha256": original_hash,
                               "note": "Unchanged supplied reference archive; run iotproject/ instead."}
            archive.writestr("README_FIRST.txt",
                             "Run the project in iotproject/. Read iotproject/SHARE_THIS_FIRST.md.\n"
                             "original_archive/ contains the unchanged supplied .adding ZIP for reference.\n"
                             "It is not needed to run the project.\n")
        manifest = {
            "project": "Team 12 Smart Production-Line Monitoring and Bottleneck Detection",
            "packaged_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_repository_commit": "0d37af3686a0508d38516cfc1220f4bba8ccc169",
            "note": "Runnable iotproject/ includes fixed public A/B datasets, trained models and completed test database. Its Python venv, Node modules, logs and local runtime/credential files are excluded; run setup on each laptop. The optional original_archive/ is an unchanged reference copy.",
            "files": hashes,
        }
        if original_record:
            manifest["original_archive"] = original_record
        archive.writestr("iotproject/PACKAGE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    with ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"ZIP integrity check failed: {bad}")
    print(f"Created {output} ({output.stat().st_size:,} bytes; "
          f"{len(files) + 1 + (2 if original else 0)} files)")


if __name__ == "__main__":
    main()
