#!/usr/bin/env python3
"""
CB-Remix-scripts/export_browse_csv.py

Turns the raw "config-browse" sheet — already read into a DataFrame — into
the CSV file the Jekyll site's browse config actually uses
(_data/config-browse.csv), applying the sheet-specific cleanup that raw
spreadsheet exports need:

  - Drops trailing "phantom" rows: rows where formulas were filled down
    past the real data, leaving a "field" of "0" or blank.
  - Resolves each row's "field" value from a human-readable, language-name
    based form into the literal field name Jekyll/CollectionBuilder
    actually expects — see resolve_field_name() below. Same trick as
    build_pages_from_sheet.py's dynamic column headers and
    export_metadata_orchestrator_csv.py's field resolution, just applied
    to this sheet.
  - Normalizes the "btn"/"hidden" checkbox columns to lowercase
    "true"/"false" (Google's ODS export represents a checked box as the
    literal number 1, not a real boolean — see the boolean-normalization
    step below).
  - Blanks out literal "0" everywhere else: no column in this sheet
    legitimately contains a literal 0 — every occurrence comes from
    formulas resolving blank source cells to 0.
  - Writes RAGGED rows: trailing empty cells are dropped from the end of
    each row (matching how Google Sheets' own "publish to web as csv"
    export behaves), so e.g. "subject-en,,en,true" (4 fields) is written
    as-is even though the sheet has 6 columns, rather than padded out to
    "subject-en,,en,true,,".

Self-contained: the function below only needs `pandas` (stdlib `csv`/`re`
for writing/matching), so this file can be copy-pasted on its own into a
new conversation/file if you just want to iterate on this piece. It does
NOT talk to the network, Google Sheets, or the ODS file directly — it
only operates on DataFrames handed to it (already produced by
read_sheet() in the root download_csv.py).

Dependencies (install once):
    pip install pandas

Usage (as a library, not run directly):
    from export_browse_csv import export_browse_csv
"""

import pandas as pd


def export_browse_csv(browse_df, output_path, config_df=None):
    """Clean the raw config-browse DataFrame and write it to *output_path*
    as CSV.

    *browse_df* is the raw "config-browse" sheet, as read straight off the
    spreadsheet (no cleanup applied yet). Expected columns include:
        field, translate_id_browse, lang, btn, hidden, translate_id_sort_name
    *output_path* is a pathlib.Path (or str) for the CSV file to write,
    e.g. _data/config-browse.csv — its parent directory is created if
    needed.

    *config_df* is the "config" tab (columns: category, content), used to
    resolve:
        - "lang1"    -> human-readable lang1 name  (e.g. "English")
        - "lang2"    -> human-readable lang2 name  (e.g. "Portuguese")
        - "lang1-id" -> short lang1 code            (e.g. "en")
        - "lang2-id" -> short lang2 code            (e.g. "pt")
    If config_df is omitted, or a category is missing/blank, sensible
    defaults are used (lang1="lang1"/"en", lang2="lang2"/"pt").

    ── Why "field" needs resolving ──────────────────────────────────────
    Instead of hand-typing Jekyll's hardcoded field names into the sheet,
    the "field" column is filled in with a formula like
    ="subject-in-"&config!B6, producing a human-readable value such as
    "subject-in-English" / "subject-in-Portuguese". resolve_field_name()
    translates that back into the literal field name Jekyll expects,
    using FIELD_RENAME_RULES — matching the example field list this was
    built against:
        subject-en / subject-pt         ("-{lang1_id}" / "-{lang2_id}")
        locations_en / locations_pt     (same idea, but underscore —
                                          NOTE this matches
                                          metadata-orchestrator's plural,
                                          underscore "locations_en"/
                                          "locations_pt", NOT
                                          config-search's singular,
                                          hyphenated "location-en"/
                                          "location-pt". Each config file
                                          genuinely uses its own naming
                                          for the same underlying concept
                                          — don't assume they match.)
    "date", "language", and "creator" have no "-in-" formula in them at
    all, so they're language-agnostic and pass straight through.

    Returns the cleaned DataFrame (the same one written to disk), in case
    the caller also wants to keep it in memory.
    """
    import csv
    import pathlib
    import re

    df = browse_df

    # ── Drop phantom rows (formulas filled down past real data) ─────────
    # Scoped to this sheet specifically, since it's keyed on "field" (a
    # spreadsheet formula filled far past the real data will show up here
    # as field == "0", "", or NaN).
    if "field" in df.columns:
        before = len(df)
        stripped_field = df["field"].astype(str).str.strip()
        df = df[(stripped_field != "0") & (stripped_field != "") & (stripped_field.str.lower() != "nan")]
        after = len(df)
        print(f"[INFO] [config-browse] Dropped {before - after} empty/formula rows (kept {after})")

    # ── Resolve language names/ids from config ───────────────────────────
    LANG1_NAME_CATEGORY = "lang1"
    LANG2_NAME_CATEGORY = "lang2"
    LANG1_ID_CATEGORY = "lang1-id"
    LANG2_ID_CATEGORY = "lang2-id"
    DEFAULT_LANG1_NAME = "lang1"
    DEFAULT_LANG2_NAME = "lang2"
    DEFAULT_LANG1_ID = "en"
    DEFAULT_LANG2_ID = "pt"
    CONFIG_CATEGORY_COL = "category"
    CONFIG_CONTENT_COL = "content"

    def clean(value) -> str:
        if pd.isna(value):
            return ""
        return str(value).strip()

    def get_config_category_value(category: str, default: str) -> str:
        if config_df is None:
            return default
        if CONFIG_CATEGORY_COL not in config_df.columns or CONFIG_CONTENT_COL not in config_df.columns:
            return default
        match = config_df[config_df[CONFIG_CATEGORY_COL].astype(str).str.strip() == category]
        if match.empty:
            return default
        value = clean(match.iloc[0][CONFIG_CONTENT_COL])
        return value or default

    lang1_name = get_config_category_value(LANG1_NAME_CATEGORY, DEFAULT_LANG1_NAME)
    lang2_name = get_config_category_value(LANG2_NAME_CATEGORY, DEFAULT_LANG2_NAME)
    lang1_id = get_config_category_value(LANG1_ID_CATEGORY, DEFAULT_LANG1_ID)
    lang2_id = get_config_category_value(LANG2_ID_CATEGORY, DEFAULT_LANG2_ID)

    print(
        f"[INFO] [config-browse] lang1 = {lang1_name!r} ({lang1_id!r}), "
        f"lang2 = {lang2_name!r} ({lang2_id!r})"
    )

    # ── Field-name rename rules ───────────────────────────────────────────
    # Maps a "base" field name (the part before "-in-<language name>" in
    # the raw sheet) to the {lang1, lang2} field-name templates Jekyll
    # actually expects for THIS sheet. Add an entry here any time a new
    # translated field is introduced and its naming doesn't fit the
    # default pattern below.
    FIELD_RENAME_RULES = {
        "subject":   {"lang1": "{base}-{lang1_id}", "lang2": "{base}-{lang2_id}"},
        "locations": {"lang1": "{base}_{lang1_id}", "lang2": "{base}_{lang2_id}"},
    }
    # Fallback for any translated base field not explicitly listed above.
    DEFAULT_RULE = {"lang1": "{base}-{lang1_id}", "lang2": "{base}-{lang2_id}"}

    # Matches e.g. "subject-in-English" -> base="subject", lang_name="English"
    FIELD_PATTERN = re.compile(r"^(.+)-in-(.+)$")

    def resolve_field_name(raw_field: str) -> str:
        """Translate one raw "field" cell into the field name Jekyll
        expects. Untranslated fields (no "-in-" formula in the cell, e.g.
        "date", "language", "creator") are passed through unchanged.
        """
        match = FIELD_PATTERN.match(raw_field)
        if not match:
            return raw_field

        base, lang_name = match.group(1), match.group(2)

        if lang_name == lang1_name:
            which = "lang1"
        elif lang_name == lang2_name:
            which = "lang2"
        else:
            print(
                f"[WARN] [config-browse] field {raw_field!r} has language "
                f"{lang_name!r}, which matches neither config's lang1 "
                f"({lang1_name!r}) nor lang2 ({lang2_name!r}) — leaving it "
                f"unchanged. Check config!B6/B8 and this row's formula."
            )
            return raw_field

        rule = FIELD_RENAME_RULES.get(base)
        if rule is None:
            print(
                f"[WARN] [config-browse] no explicit rename rule for base field "
                f"{base!r} — using default pattern '{base}-{{lang_id}}'. Add an "
                f"entry to FIELD_RENAME_RULES if Jekyll expects something else "
                f"(e.g. an underscore separator, like 'locations')."
            )
            rule = DEFAULT_RULE

        return rule[which].format(base=base, lang1_id=lang1_id, lang2_id=lang2_id)

    if "field" in df.columns:
        df = df.copy()
        df["field"] = df["field"].astype(str).map(resolve_field_name)

    # ── Normalize checkbox columns to lowercase "true"/"false" ───────────
    # Google's ODS export doesn't preserve checkboxes as real ODF booleans
    # — a checked box comes through as the literal number 1 (unchecked as
    # 0). Jekyll/Liquid's truthiness check on a CSV-sourced string is
    # case-sensitive and expects lowercase "true", so both the numeric
    # and any already-capitalized form get normalized here.
    BOOLEAN_COLUMNS = ["btn", "hidden"]
    BOOLEAN_VALUE_MAP = {"1": "true", "1.0": "true", "TRUE": "true", "0": "false", "0.0": "false", "FALSE": "false"}
    for col in BOOLEAN_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace(BOOLEAN_VALUE_MAP)

    # ── Blank out "0" everywhere ─────────────────────────────────────────
    # No column in this sheet legitimately contains a literal 0 — every
    # occurrence comes from formulas resolving blank source cells to 0.
    # Safe to strip globally rather than column-by-column. (Boolean
    # columns above are already normalized to "false"/"true" by this
    # point, so they're unaffected by this blanking step.)
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