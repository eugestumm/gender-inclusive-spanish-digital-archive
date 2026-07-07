#!/usr/bin/env python3
"""
CB-Remix-scripts/export_translation_csv.py

Turns the raw "translation" sheet — already read into a DataFrame — into
the CSV file the Jekyll site's translation strings actually use
(_data/config-translation.csv), applying the sheet-specific cleanup that
raw spreadsheet exports need:

  - Drops trailing "phantom" rows: rows where formulas were filled down
    past the real data, leaving a "translate_id" of "0" or blank.
  - Blanks out literal "0" everywhere else: no column in this sheet
    legitimately contains a literal 0 — every occurrence comes from
    formulas resolving blank source cells to 0.
  - Writes RAGGED rows: trailing empty cells are dropped from the end of
    each row (matching how Google Sheets' own "publish to web as csv"
    export behaves), rather than padding every row out to the full column
    count like df.to_csv() would.

Self-contained: the function below only needs `pandas` (stdlib `csv` for
writing), so this file can be copy-pasted on its own into a new
conversation/file if you just want to iterate on this piece. It does NOT
talk to the network, Google Sheets, or the ODS file directly — it only
operates on a DataFrame handed to it (already produced by read_sheet() in
the root download_csv.py).

Dependencies (install once):
    pip install pandas

Usage (as a library, not run directly):
    from export_translation_csv import export_translation_csv
"""

import pandas as pd


def export_translation_csv(translation_df, output_path):
    """Clean the raw translation DataFrame and write it to *output_path* as
    CSV.

    *translation_df* is the raw "translation" sheet, as read straight off
    the spreadsheet (no cleanup applied yet). Expected columns:
        translate_id, description, en, pt, ... (one column per language)
    *output_path* is a pathlib.Path (or str) for the CSV file to write,
    e.g. _data/config-translation.csv — its parent directory is created if
    needed.

    Returns the cleaned DataFrame (the same one written to disk), in case
    the caller also wants to keep it in memory.
    """
    import csv
    import pathlib

    df = translation_df

    # ── Drop phantom rows (formulas filled down past real data) ─────────
    # Scoped to this sheet specifically, since it's keyed on
    # "translate_id" (a spreadsheet formula filled far past the real data
    # will show up here as translate_id == "0", "", or NaN).
    if "translate_id" in df.columns:
        before = len(df)
        stripped_id = df["translate_id"].astype(str).str.strip()
        df = df[(stripped_id != "0") & (stripped_id != "") & (stripped_id.str.lower() != "nan")]
        after = len(df)
        print(f"[INFO] [translation] Dropped {before - after} empty/formula rows (kept {after})")

    # ── Blank out "0" everywhere ─────────────────────────────────────────
    # No column in this sheet legitimately contains a literal 0 — every
    # occurrence comes from formulas resolving blank source cells to 0.
    # Safe to strip globally rather than column-by-column.
    df = df.replace([0, "0", 0.0, "0.0"], "")

    output_path = pathlib.Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Write as RAGGED csv ──────────────────────────────────────────────
    # Trim trailing empty cells off each row before writing, instead of
    # using df.to_csv() (which would keep every row at the full column
    # count).
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(df.columns.tolist())
        for row in df.itertuples(index=False, name=None):
            row = [("" if pd.isna(v) else str(v)) for v in row]
            while row and row[-1] == "":
                row.pop()
            writer.writerow(row)

    print(f"[DONE] {output_path.name} is ready at:\n       {output_path}")

    return df
