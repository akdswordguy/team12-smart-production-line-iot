"""Make a replay slice from the unchanged Company B ZIP."""
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/company_B.zip"
TARGET = ROOT / "data/processed/company_b_replay.csv"
START = "2022-03-28 04:00:00+00:00"
END = "2022-03-28 08:00:00+00:00"


def main():
    pieces = []
    with zipfile.ZipFile(SOURCE) as archive, archive.open("company_B.csv") as stream:
        for chunk in pd.read_csv(stream, chunksize=100000):
            selected = chunk[chunk["ts"].between(START, END, inclusive="left")]
            if len(selected):
                pieces.append(selected)
    frame = pd.concat(pieces).sort_values(["ts", "asset"]).reset_index(drop=True)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(TARGET, index=False)
    print(f"Company B replay: {len(frame)} records, {frame.asset.nunique()} machines -> {TARGET}")


if __name__ == "__main__":
    main()
