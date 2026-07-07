#!/usr/bin/env python3
"""
CB-Remix-scripts/export_metadata_orchestrator_csv.py

Turns the raw "metadata-orchestrator" sheet — already read into a
DataFrame — into the CSV file the Jekyll site's metadata config actually
uses (_data/config-metadata.csv), applying the sheet-specific cleanup that
raw spreadsheet exports need:

  - Drops trailing "phantom" rows: rows where formulas were filled down
    past the real data, leaving a "field" of "0" or blank.
  - Resolves each row's "field" value from a human-readable, language-name
    based form into the literal field name Jekyll/CollectionBuilder
    actually expects — see resolve_field_name() below for details. This is
    the same trick used in build_pages_from_sheet.py for the "pages"
    sheet's dynamic column headers, just applied to cell VALUES here
    instead of column headers.
  - Blanks out literal "0" everywhere else: no column in this sheet
    legitimately contains a literal 0 — every occurrence comes from
    formulas resolving blank source cells to 0.
  - Writes RAGGED rows: trailing empty cells are dropped from the end of
    each row (matching how Google Sheets' own "publish to web as csv"
    export behaves), rather than padding every row out to the full column
    count like df.to_csv() would.

NOTE ON NAMING: this is deliberately NOT called export_metadata_csv.py —
that name is already taken by the script that exports the
"DO_NOT_TOUCH(Converter_Interface)" books/collection sheet to
_data/books-metadata.csv. This script's output file is _data/config-
metadata.csv, from a completely different source sheet
("metadata-orchestrator"), so it gets its own distinct filename/function
name to avoid an import clash with the existing script.

Self-contained: the function below only needs `pandas` (stdlib `csv`/`re`
for writing/matching), so this file can be copy-pasted on its own into a
new conversation/file if you just want to iterate on this piece. It does
NOT talk to the network, Google Sheets, or the ODS file directly — it only
operates on DataFrames handed to it (already produced by read_sheet() in
the root download_csv.py).

Dependencies (install once):
    pip install pandas

Usage (as a library, not run directly):
    from export_metadata_orchestrator_csv import export_metadata_orchestrator_csv
"""

import pandas as pd


def export_metadata_orchestrator_csv(metadata_orchestrator_df, output_path, config_df=None):
    """Clean the raw metadata-orchestrator DataFrame and write it to
    *output_path* as CSV.

    *metadata_orchestrator_df* is the raw "metadata-orchestrator" sheet, as
    read straight off the spreadsheet (no cleanup applied yet). Expected
    columns include:
        field, translate_id_metadata, lang, browse_link, external_link

    *output_path* is a pathlib.Path (or str) for the CSV file to write,
    e.g. _data/config-metadata.csv — its parent directory is created if
    needed.

    *config_df* is the "config" tab (columns: category, content), used to
    resolve the same four values build_pages_from_sheet.py resolves:
        - "lang1"    -> human-readable lang1 name  (e.g. "English")
        - "lang2"    -> human-readable lang2 name  (e.g. "Portuguese")
        - "lang1-id" -> short lang1 code            (e.g. "en")
        - "lang2-id" -> short lang2 code            (e.g. "pt")
    If config_df is omitted, or a category is missing/blank, sensible
    defaults are used (lang1="lang1"/"en", lang2="lang2"/"pt") so nothing
    breaks — matching build_pages_from_sheet.py's fallback behavior.

    ── Why "field" needs resolving ──────────────────────────────────────
    Jekyll/CollectionBuilder's templates have specific, hardcoded field
    names baked into them (e.g. "title", "title-pt", "description-en"),
    which is exactly the kind of hardcoding this whole spreadsheet
    interface exists to get away from. So instead of hand-typing those
    exact names into the sheet, the "field" column is filled in with a
    formula like ="title-in-"&config!B6, which produces a human-readable,
    language-name-based value such as "title-in-English" /
    "title-in-Portuguese" (same trick as the "pages" sheet's dynamic
    column headers).

    resolve_field_name() below is what translates that human-readable
    value back into the literal field name Jekyll expects, using
    FIELD_RENAME_RULES. That table exists because the mapping isn't one
    uniform pattern — matching the example field list this was built
    against:
        title              (lang1, no suffix)
        title-pt           (lang2, "-{lang2_id}")
        description-en     (lang1, "-{lang1_id}")
        description-pt     (lang2, "-{lang2_id}")
        subject-en / subject-pt       (same pattern as description)
        locations_en / locations_pt  (like description/subject, but with
                                       an underscore separator instead of
                                       a hyphen)
    Fields with no "<base>-in-<language name>" formula in the cell at all
    (creator, language, date, source, format, rights, rightsstatement) are
    language-agnostic and pass straight through untouched.

    If a "field" cell's language name doesn't match either config's lang1
    or lang2 name, or its base isn't in FIELD_RENAME_RULES, this warns and
    falls back gracefully (see resolve_field_name()) rather than silently
    producing a bad CSV — check the warning against config!B6/B8 and the
    sheet's formulas if you see one.

    Returns the cleaned DataFrame (the same one written to disk), in case
    the caller also wants to keep it in memory.
    """
    import csv
    import pathlib
    import re

    df = metadata_orchestrator_df

    # ── Drop phantom rows (formulas filled down past real data) ─────────
    # Scoped to this sheet specifically, since it's keyed on "field" (a
    # spreadsheet formula filled far past the real data will show up here
    # as field == "0", "", or NaN).
    if "field" in df.columns:
        before = len(df)
        stripped_field = df["field"].astype(str).str.strip()
        df = df[(stripped_field != "0") & (stripped_field != "") & (stripped_field.str.lower() != "nan")]
        after = len(df)
        print(f"[INFO] [metadata-orchestrator] Dropped {before - after} empty/formula rows (kept {after})")

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
        """Same lookup helper as build_pages_from_sheet.py: falls back to
        *default* if config_df is missing, malformed, or the category
        isn't there / is blank.
        """
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
        f"[INFO] [metadata-orchestrator] lang1 = {lang1_name!r} ({lang1_id!r}), "
        f"lang2 = {lang2_name!r} ({lang2_id!r})"
    )

    # ── Field-name rename rules ───────────────────────────────────────────
    # Maps a "base" field name (the part before "-in-<language name>" in
    # the raw sheet) to the {lang1, lang2} field-name templates Jekyll
    # actually expects. Add an entry here any time a new translated field
    # is introduced and its naming doesn't fit the default pattern below.
    FIELD_RENAME_RULES = {
        "title":       {"lang1": "{base}",              "lang2": "{base}-{lang2_id}"},
        "description": {"lang1": "{base}-{lang1_id}",   "lang2": "{base}-{lang2_id}"},
        "subject":     {"lang1": "{base}-{lang1_id}",   "lang2": "{base}-{lang2_id}"},
        "locations":   {"lang1": "{base}_{lang1_id}",   "lang2": "{base}_{lang2_id}"},
    }
    # Fallback for any translated base field not explicitly listed above.
    DEFAULT_RULE = {"lang1": "{base}-{lang1_id}", "lang2": "{base}-{lang2_id}"}

    # Matches e.g. "title-in-English" -> base="title", lang_name="English"
    FIELD_PATTERN = re.compile(r"^(.+)-in-(.+)$")

    def resolve_field_name(raw_field: str) -> str:
        """Translate one raw "field" cell into the field name Jekyll
        expects. Untranslated fields (no "-in-" formula in the cell, e.g.
        "creator", "language", "date", "source", "format", "rights",
        "rightsstatement") are passed through unchanged.
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
                f"[WARN] [metadata-orchestrator] field {raw_field!r} has language "
                f"{lang_name!r}, which matches neither config's lang1 "
                f"({lang1_name!r}) nor lang2 ({lang2_name!r}) — leaving it "
                f"unchanged. Check config!B6/B8 and this row's formula."
            )
            return raw_field

        rule = FIELD_RENAME_RULES.get(base)
        if rule is None:
            print(
                f"[WARN] [metadata-orchestrator] no explicit rename rule for base "
                f"field {base!r} — using default pattern '{base}-{{lang_id}}'. Add "
                f"an entry to FIELD_RENAME_RULES if Jekyll expects something else "
                f"(e.g. an underscore separator, like 'locations')."
            )
            rule = DEFAULT_RULE

        return rule[which].format(base=base, lang1_id=lang1_id, lang2_id=lang2_id)

    if "field" in df.columns:
        df = df.copy()
        df["field"] = df["field"].astype(str).map(resolve_field_name)

    # ── Normalize checkbox columns to "true" ─────────────────────────────
    # Google's ODS export doesn't preserve checkboxes as real ODF booleans
    # — a checked box comes through as the literal number 1 (and unchecked
    # as 0). The "blank out 0" step just below already turns unchecked
    # boxes into "" (which reads as falsy), but checked boxes need an
    # explicit translation, or they show up as "1" instead of "true".
    BOOLEAN_COLUMNS = ["browse_link", "external_link"]
    for col in BOOLEAN_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace({"1": "true", "1.0": "true"})

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