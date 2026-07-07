#!/usr/bin/env python3
"""
CB-Remix-scripts/export_metadata_csv.py

Turns the raw "main-metadata" (books/collection
metadata) sheet — already read into a DataFrame — into the CSV file
CollectionBuilder actually uses (_data/books-metadata.csv), applying the
sheet-specific cleanup that raw spreadsheet exports need:

  - Resolves dynamic, language-name-based COLUMN HEADERS (e.g.
    "title-in-English", "locations-in-Portuguese") into the literal
    column names Jekyll/CollectionBuilder expects (e.g. "title",
    "locations_pt") — see resolve_columns() below. This is the same
    trick as build_pages_from_sheet.py's dynamic column headers, just
    applied to this sheet, and it's what lets people fill in this sheet
    directly instead of going through a separate formula-based
    "converter" tab.
  - Expands the single "locations"/"latitude"/"longitude" columns into
    the numbered "location_first_en"/"latitude_first"/... through
    "_fourth" columns CollectionBuilder's map expects — see
    expand_locations() below.
  - Drops trailing "phantom" rows: rows where formulas were filled down
    past the real data, leaving a "title" of "0" or blank.
  - Blanks out literal "0" everywhere else: no column in this sheet
    legitimately contains a literal 0 — every occurrence comes from
    formulas resolving blank source cells to 0.

Self-contained: the function below only needs `pandas`, so this file can
be copy-pasted on its own into a new conversation/file if you just want to
iterate on this piece. It does NOT talk to the network, Google Sheets, or
the ODS file directly — it only operates on a DataFrame handed to it
(already produced by read_sheet() in the root download_csv.py).

Dependencies (install once):
    pip install pandas

Usage (as a library, not run directly):
    from export_metadata_csv import export_metadata_csv
"""


def export_metadata_csv(metadata_df, output_path, config_df=None):
    """Clean the raw metadata DataFrame and write it to *output_path* as CSV.

    *metadata_df* is the raw "main-metadata" sheet, as
    read straight off the spreadsheet (no cleanup applied yet). Expected
    columns include the dynamic, language-name-based headers:
        objectid, title-in-<lang1 name>, title-in-<lang2 name>, filename,
        creator, description-in-<lang1 name>, description-in-<lang2 name>,
        date, locations-in-<lang1 name>, locations-in-<lang2 name>,
        latitude, longitude, subject-in-<lang1 name>,
        subject-in-<lang2 name>, language, source, format, type, rights,
        rightsstatement, vimeoid, youtubeid
    (plus any other language-agnostic columns, e.g. isbn, words_found —
    those pass straight through untouched.)

    *output_path* is a pathlib.Path (or str) for the CSV file to write,
    e.g. _data/books-metadata.csv — its parent directory is created if
    needed.

    *config_df* is the "config" tab (columns: category, content), used to
    resolve:
        - "lang1"    -> human-readable lang1 name  (e.g. "English")
        - "lang2"    -> human-readable lang2 name  (e.g. "Portuguese")
        - "lang1-id" -> short lang1 code            (e.g. "en")
        - "lang2-id" -> short lang2 code            (e.g. "pt")
    If config_df is omitted, or a category is missing/blank, sensible
    defaults are used (lang1="lang1"/"en", lang2="lang2"/"pt").

    ── Why columns need resolving ────────────────────────────────────────
    Instead of hand-typing CollectionBuilder's hardcoded column names into
    this sheet (or maintaining a separate "converter" tab full of formulas
    that does it), each translated column is headed with a formula like
    ="title-in-"&config!B6, producing a human-readable column name such as
    "title-in-English" / "title-in-Portuguese". resolve_columns() below
    translates those into the literal column names CollectionBuilder
    expects, using COLUMN_RENAME_RULES:
        title-in-<lang1>       -> "title"              (bare, no suffix)
        title-in-<lang2>       -> "title-{lang2_id}"
        description-in-<lang1> -> "description-{lang1_id}"
        description-in-<lang2> -> "description-{lang2_id}"
        subject-in-<lang1>     -> "subject-{lang1_id}"
        subject-in-<lang2>     -> "subject-{lang2_id}"
        locations-in-<lang1>   -> "locations_{lang1_id}"   (underscore!)
        locations-in-<lang2>   -> "locations_{lang2_id}"
    Everything else (objectid, filename, creator, date, language, source,
    format, type, rights, rightsstatement, vimeoid, youtubeid, and any
    other columns not matching a "<base>-in-<language>" pattern) is
    language-agnostic and passes straight through unchanged.

    ── Numbered location expansion ───────────────────────────────────────
    CollectionBuilder's map wants up to 4 separate locations per item,
    each with its own lat/long: location_first_en/pt + latitude_first +
    longitude_first, through location_fourth_en/pt + latitude_fourth +
    longitude_fourth. Since a row's "locations"/"latitude"/"longitude"
    cells can hold multiple semicolon-separated values (matched up by
    position — e.g. the 2nd English location corresponds to the 2nd
    Portuguese location and the 2nd latitude/longitude), expand_locations()
    splits those apart into the four numbered slots, leaving any unused
    slots (e.g. 2nd-4th, for the common case of one location) blank. Any
    locations beyond the 4th are dropped, with a warning. The original
    combined "locations_en"/"locations_pt" columns are kept as-is
    alongside the numbered breakdown (matching CollectionBuilder's
    expected schema) — only the bare "latitude"/"longitude" columns are
    consumed and replaced by the numbered latitude_first/longitude_first/etc.

    Returns the cleaned DataFrame (the same one written to disk), in case
    the caller also wants to keep it in memory.
    """
    import pathlib
    import re
    import pandas as pd

    df = metadata_df.copy()

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
        f"[INFO] [metadata] lang1 = {lang1_name!r} ({lang1_id!r}), "
        f"lang2 = {lang2_name!r} ({lang2_id!r})"
    )

    # ── Column-header rename rules ────────────────────────────────────────
    # Maps a "base" column name (the part before "-in-<language name>" in
    # the raw sheet) to the {lang1, lang2} column-name templates
    # CollectionBuilder actually expects. Add an entry here any time a new
    # translated column is introduced and its naming doesn't fit the
    # default pattern below.
    COLUMN_RENAME_RULES = {
        "title":       {"lang1": "{base}",             "lang2": "{base}-{lang2_id}"},
        "description": {"lang1": "{base}-{lang1_id}",  "lang2": "{base}-{lang2_id}"},
        "subject":     {"lang1": "{base}-{lang1_id}",  "lang2": "{base}-{lang2_id}"},
        "locations":   {"lang1": "{base}_{lang1_id}",  "lang2": "{base}_{lang2_id}"},
    }
    # Fallback for any translated base column not explicitly listed above.
    DEFAULT_RULE = {"lang1": "{base}-{lang1_id}", "lang2": "{base}-{lang2_id}"}

    # Matches e.g. "title-in-English" -> base="title", lang_name="English"
    COLUMN_PATTERN = re.compile(r"^(.+)-in-(.+)$")

    def resolve_columns(columns) -> dict:
        """Build a {raw_column_name: resolved_column_name} rename map.
        Columns with no "-in-" formula in their header (e.g. "objectid",
        "creator", "date", "isbn", "words_found") aren't in the returned
        map at all — they're left completely alone.
        """
        rename_map = {}
        for col in columns:
            match = COLUMN_PATTERN.match(col)
            if not match:
                continue  # untranslated column, passed through as-is

            base, lang_name = match.group(1), match.group(2)

            if lang_name == lang1_name:
                which = "lang1"
            elif lang_name == lang2_name:
                which = "lang2"
            else:
                print(
                    f"[WARN] [metadata] column {col!r} has language {lang_name!r}, "
                    f"which matches neither config's lang1 ({lang1_name!r}) nor "
                    f"lang2 ({lang2_name!r}) — leaving this column name unchanged. "
                    f"Check config!B6/B8 and this column's header formula."
                )
                continue

            rule = COLUMN_RENAME_RULES.get(base)
            if rule is None:
                print(
                    f"[WARN] [metadata] no explicit rename rule for base column "
                    f"{base!r} — using default pattern '{base}-{{lang_id}}'. Add "
                    f"an entry to COLUMN_RENAME_RULES if CollectionBuilder expects "
                    f"something else (e.g. an underscore separator, like "
                    f"'locations')."
                )
                rule = DEFAULT_RULE

            rename_map[col] = rule[which].format(base=base, lang1_id=lang1_id, lang2_id=lang2_id)

        return rename_map

    rename_map = resolve_columns(df.columns)
    df = df.rename(columns=rename_map)

    # ── Expand locations/latitude/longitude into numbered slots ─────────
    LOCATIONS_LANG1_COL = f"locations_{lang1_id}"
    LOCATIONS_LANG2_COL = f"locations_{lang2_id}"
    LATITUDE_COL = "latitude"
    LONGITUDE_COL = "longitude"
    ORDINALS = ["first", "second", "third", "fourth"]
    MAX_LOCATIONS = len(ORDINALS)

    def split_cell(value) -> list:
        text = clean(value)
        if not text:
            return []
        return [part.strip() for part in text.split(";")]

    def expand_locations(row):
        locs1 = split_cell(row.get(LOCATIONS_LANG1_COL, ""))
        locs2 = split_cell(row.get(LOCATIONS_LANG2_COL, ""))
        lats = split_cell(row.get(LATITUDE_COL, ""))
        longs = split_cell(row.get(LONGITUDE_COL, ""))

        count = max(len(locs1), len(locs2), len(lats), len(longs))
        if count > MAX_LOCATIONS:
            obj_id = row.get("objectid", "<unknown objectid>")
            print(
                f"[WARN] [metadata] row {obj_id!r} has {count} locations, but "
                f"only the first {MAX_LOCATIONS} are kept (CollectionBuilder's "
                f"map only supports up to {MAX_LOCATIONS})."
            )

        result = {}
        for i, ordinal in enumerate(ORDINALS):
            result[f"location_{ordinal}_{lang1_id}"] = locs1[i] if i < len(locs1) else ""
            result[f"location_{ordinal}_{lang2_id}"] = locs2[i] if i < len(locs2) else ""
            result[f"latitude_{ordinal}"] = lats[i] if i < len(lats) else ""
            result[f"longitude_{ordinal}"] = longs[i] if i < len(longs) else ""
        return pd.Series(result)

    if LATITUDE_COL in df.columns or LONGITUDE_COL in df.columns or \
            LOCATIONS_LANG1_COL in df.columns or LOCATIONS_LANG2_COL in df.columns:
        location_cols = df.apply(expand_locations, axis=1)
        df = pd.concat([df, location_cols], axis=1)
        df = df.drop(columns=[c for c in (LATITUDE_COL, LONGITUDE_COL) if c in df.columns])

    # ── Reorder columns to match CollectionBuilder's expected layout ────
    # Anything not in this preferred list (e.g. isbn, words_found, or any
    # other passthrough column) is simply appended at the end, in its
    # original relative order — reordering here is cosmetic, ONLY column
    # NAMES matter to CollectionBuilder, not position.
    preferred_order = [
        "title", "objectid", "filename", f"title-{lang2_id}", "creator",
        f"description-{lang1_id}", f"description-{lang2_id}", "date",
        LOCATIONS_LANG1_COL, LOCATIONS_LANG2_COL,
    ]
    for ordinal in ORDINALS:
        preferred_order += [
            f"location_{ordinal}_{lang1_id}", f"location_{ordinal}_{lang2_id}",
            f"latitude_{ordinal}", f"longitude_{ordinal}",
        ]
    preferred_order += [
        f"subject-{lang1_id}", f"subject-{lang2_id}",
        "language", "source", "format", "type", "rights", "rightsstatement",
        "vimeoid", "youtubeid",
    ]
    ordered_cols = [c for c in preferred_order if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in ordered_cols]
    df = df[ordered_cols + remaining_cols]

    # ── Drop trailing "phantom" rows (formulas filled down past real data) ──
    # Scoped to this sheet specifically, since it's the one keyed on a
    # "title" column (a spreadsheet formula filled far past the real data
    # will show up here as title == "0", "", or NaN). Done AFTER the
    # column rename above, since the raw title column isn't called
    # "title" until then.
    if "title" in df.columns:
        before = len(df)
        stripped_title = df["title"].astype(str).str.strip()
        df = df[(stripped_title != "0") & (stripped_title != "") & (stripped_title.str.lower() != "nan")]
        after = len(df)
        print(f"[INFO] [metadata] Dropped {before - after} empty/formula rows (kept {after})")

    # ── Blank out "0" everywhere ─────────────────────────────────────────
    # No column in this sheet legitimately contains a literal 0 — every
    # occurrence comes from formulas resolving blank source cells to 0.
    # Safe to strip globally rather than column-by-column.
    df = df.replace([0, "0", 0.0, "0.0"], "")

    output_path = pathlib.Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"[DONE] {output_path.name} is ready at:\n       {output_path}")

    return df