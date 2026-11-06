"""
Download the fixed dataset into data/raw/ WITHOUT changing it.

Source:
  https://github.com/HumanCenteredTechnology/SME-Manufacturing-Dataset

The files are made read-only afterwards, so nothing in this project can
modify the originals by accident. Every cleaning step writes a copy to
data/processed/ instead.

Run:  python scripts/fetch_dataset.py
      python scripts/fetch_dataset.py --force    (re-download)

Needs an internet connection. If you already have the CSVs, just drop
company_A.csv, company_A_labelled_subset.csv and company_B.csv into
data/raw/ and skip this script.
"""

import argparse
import hashlib
import io
import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# Fixed source revision used for the measured audit and saved model.
DATASET_COMMIT = "0d37af3686a0508d38516cfc1220f4bba8ccc169"
ZIP_URL = ("https://github.com/HumanCenteredTechnology/"
           f"SME-Manufacturing-Dataset/archive/{DATASET_COMMIT}.zip")
COMPANY_A_SHA256 = "888838fe508a42e83c55f39ad4898566ef5e3dcc354edbac84000c8def49629a"

# What we expect to end up with. Row counts are what WE measured on
# 2026-10-27; if yours differ, the upstream file changed - say so in your
# report rather than quietly using different numbers.
EXPECTED = {
    "company_A.csv": 1_520_330,
    "company_A_labelled_subset.csv": 14_492,
    "company_B.csv": None,          # inside company_B.zip, count not pinned
}


def make_writable(p):
    if p.exists():
        p.chmod(p.stat().st_mode | stat.S_IWUSR)


def make_read_only(p):
    p.chmod(p.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def download():
    print(f"Downloading {ZIP_URL} ...")
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=120) as r:
            return io.BytesIO(r.read())
    except Exception as e:
        print(f"\nDownload failed: {e}")
        print("\nNo internet, or GitHub is blocked. Do this instead:")
        print("  1. Open the repository in a browser:")
        print("     https://github.com/HumanCenteredTechnology/"
              "SME-Manufacturing-Dataset")
        print("  2. Download the ZIP and unpack it.")
        print(f"  3. Copy the CSV files into {RAW}")
        sys.exit(1)


def extract(buffer):
    RAW.mkdir(parents=True, exist_ok=True)
    written = []

    with zipfile.ZipFile(buffer) as z:
        for member in z.namelist():
            name = os.path.basename(member)
            if not name:
                continue

            if name.endswith(".csv") or name == "README.md":
                target = RAW / ("DATASET_README.md" if name == "README.md" else name)
                make_writable(target)
                target.write_bytes(z.read(member))
                written.append(target)

            # company_B.csv ships inside a nested zip.
            elif name == "company_B.zip":
                with zipfile.ZipFile(io.BytesIO(z.read(member))) as inner:
                    for inner_name in inner.namelist():
                        base = os.path.basename(inner_name)
                        if base.endswith(".csv"):
                            target = RAW / base
                            make_writable(target)
                            target.write_bytes(inner.read(inner_name))
                            written.append(target)
    return written


def verify_and_lock(files):
    print("\nFiles in data/raw/:")
    for f in sorted(set(files)):
        rows = None
        if f.suffix == ".csv":
            with open(f, "rb") as fh:
                rows = sum(1 for _ in fh) - 1       # minus the header
        size_mb = f.stat().st_size / (1024 * 1024)

        note = ""
        expected = EXPECTED.get(f.name)
        if expected is not None and rows is not None:
            note = " OK" if rows == expected else f" DIFFERS (we measured {expected:,})"

        if f.name == "company_A.csv":
            with f.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != COMPANY_A_SHA256:
                raise SystemExit(
                    f"Fixed Company A dataset checksum mismatch for {f}: {digest}. "
                    "Do not train or report results on a changed file.")
        make_read_only(f)
        rows_text = f"{rows:,} rows" if rows is not None else "-"
        print(f"  {f.name:<32} {size_mb:>7.1f} MB  {rows_text:>14}{note}")

    print("\nAll raw files are now READ-ONLY. Nothing in this project writes "
          "to them.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="download again even if the files are present")
    args = ap.parse_args()

    primary = RAW / "company_A.csv"
    if primary.exists() and not args.force:
        print(f"{primary} already exists. Use --force to download again.")
        verify_and_lock(list(RAW.glob("*.csv")))
        return

    files = extract(download())
    verify_and_lock(files)
    print("\nNext:  python src/audit.py")


if __name__ == "__main__":
    main()
