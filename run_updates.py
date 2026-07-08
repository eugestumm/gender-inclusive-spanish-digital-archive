#!/usr/bin/env python3
"""
This is the single entry point for syncing site content from the Google
Sheet — used both for local development AND by the GitHub Actions workflow.
It's responsible for retrieving the spreadsheet and getting its data into
memory / onto disk:

  1. Downloads a .ods (OpenDocument Spreadsheet) file from a public Google
     Sheets "publish to web" URL — done ONCE per run.
  2. Reads several sheets/tabs from that single downloaded file:
       - "main-metadata"                     -> exported to _data/main-metadata.csv
       - "nav-bar"                           -> exported to _data/config-nav.csv
       - "config-browse"                     -> exported to _data/config-browse.csv
       - "config-map"                        -> exported to _data/config-map.csv
       - "metadata-orchestrator"             -> exported to _data/config-metadata.csv
       - "config-search"                     -> exported to _data/config-search.csv
       - "config-table"                      -> exported to _data/config-table.csv
       - "translation"                       -> exported to _data/config-translation.csv
       - "pages"                             -> kept in memory only
       - "config"                            -> kept in memory only
       - "config-theme"                             -> kept in memory only
  3. Hands each sheet's data off to a dedicated script in CB-Remix-scripts/,
     each doing exactly one job:
       - CB-Remix-scripts/export_metadata_csv.py               -> cleans + writes
         the main-metadata sheet to _data/main-metadata.csv
       - CB-Remix-scripts/export_navbar_csv.py                 -> cleans + writes
         the nav-bar sheet to _data/config-nav.csv
       - CB-Remix-scripts/export_browse_csv.py                 -> cleans + writes
         the config-browse sheet to _data/config-browse.csv
       - CB-Remix-scripts/export_map_csv.py                    -> cleans + writes
         the config-map sheet to _data/config-map.csv
       - CB-Remix-scripts/export_metadata_orchestrator_csv.py  -> cleans + writes
         the metadata-orchestrator sheet to _data/config-metadata.csv (this one
         also needs the "config" sheet — see the note in load_all_sheets()
         below on why "config" is loaded earlier than the other memory-only
         sheets)
       - CB-Remix-scripts/export_search_csv.py                 -> cleans + writes
         the config-search sheet to _data/config-search.csv
       - CB-Remix-scripts/export_table_csv.py                  -> cleans + writes
         the config-table sheet to _data/config-table.csv
       - CB-Remix-scripts/export_translation_csv.py            -> cleans + writes
         the translation sheet to _data/config-translation.csv
       - CB-Remix-scripts/update_config_yml.py                 -> patches _config.yml
       - CB-Remix-scripts/export_theme.py                  -> patches
         _data/_theme.yml from the "config-theme" sheet (also needs the "config"
         sheet, to resolve "-in-<language name>" tokens in fields like
         subjects-fields/locations-fields/metadata-export-fields/
         metadata-facets-fields — see that script's docstring)
       - CB-Remix-scripts/update_home_infographic.py           -> patches
         _includes/home-infographic.html so its bilingual
         featured-terms "field=" attributes point at the CURRENT
         lang1-id/lang2-id from the "config" sheet, instead of whatever
         language codes happened to be hardcoded in that file before
         (see that script's docstring)
       - CB-Remix-scripts/build_pages_from_sheet.py            -> writes markdown pages
  4. Decides whether to launch `jekyll serve`:
       - Locally: yes, by default, so you get a live dev server.
       - In GitHub Actions: no, automatically. GitHub Actions sets the
         GITHUB_ACTIONS=true environment variable on every runner, so this
         script detects that and skips the (blocking) dev server — GitHub
         Pages builds the site itself from the synced files. See
         should_serve_jekyll() below.
       - Either behavior can also be forced manually with --serve /
         --no-serve, e.g. if you want to test the CI code path locally.

All of the "what do we do with this data" logic lives in those sibling
scripts instead, so each can be edited/iterated on independently of this
retrieval script and of each other.

Because this one script now covers both local dev and CI, there's no
second copy to keep in sync by hand — point the GitHub Actions workflow
at this same file (with no extra flags needed; it auto-detects CI).

Dependencies (install once):
    pip install requests pandas odfpy ruamel.yaml

Usage:
    python run_updates.py               # syncs data, then launches jekyll serve
                                         # (auto-skipped when GITHUB_ACTIONS=true)
    python run_updates.py --no-serve    # force-skip jekyll serve (e.g. to test
                                         # the CI path locally)
    python run_updates.py --serve       # force jekyll serve even under CI env vars
"""

import os
import sys
import pathlib
import tempfile

# ── Third-party ──────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit(
        "[ERROR] 'requests' is not installed.\n"
        "Run:  pip install requests"
    )

try:
    import pandas as pd
except ImportError:
    sys.exit(
        "[ERROR] 'pandas' is not installed.\n"
        "Run:  pip install pandas odfpy"
    )

# ── Sibling scripts: CB-Remix-scripts/*.py ──────────────────────────────────
# That folder is a plain directory (not a Python package, hence the hyphens
# in its name are fine) — we just add it to sys.path so its modules can be
# imported by their own valid identifier names. Each function lives in its
# own file, so any of them can be edited/iterated on independently.
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent / "CB-Remix-scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
try:
    from update_config_yml import update_config_yml
    from export_theme import export_theme
    from update_home_infographic import update_home_infographic
    from build_pages_from_sheet import build_pages_from_sheet
    from export_metadata_csv import export_metadata_csv
    from export_navbar_csv import export_navbar_csv
    from export_browse_csv import export_browse_csv
    from export_map_csv import export_map_csv
    from export_metadata_orchestrator_csv import export_metadata_orchestrator_csv
    from export_search_csv import export_search_csv
    from export_table_csv import export_table_csv
    from export_translation_csv import export_translation_csv
except ImportError as exc:
    sys.exit(
        f"[ERROR] Could not import from {_SCRIPTS_DIR}\n"
        f"        ({exc})\n"
        f"        Make sure the following exist next to this script, inside\n"
        f"        CB-Remix-scripts/:\n"
        f"          update_config_yml.py\n"
        f"          export_theme.py\n"
        f"          update_home_infographic.py\n"
        f"          build_pages_from_sheet.py\n"
        f"          export_metadata_csv.py\n"
        f"          export_navbar_csv.py\n"
        f"          export_browse_csv.py\n"
        f"          export_map_csv.py\n"
        f"          export_metadata_orchestrator_csv.py\n"
        f"          export_search_csv.py\n"
        f"          export_table_csv.py\n"
        f"          export_translation_csv.py"
    )

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
# The Google Sheets "publish to web" .ods link is read at runtime from this
# file in the project root, so people (and CI) can swap spreadsheets without
# touching any code. See get_ods_url() below. Since GitHub Actions checks
# out the full repo, this file needs to be committed to the repo (with a
# real link in it, not the placeholder) for the workflow to find it.
LINK_FILE_NAME = "PASTE_YOUR_GOOGLE_SPREADSHEET_LINK_HERE.txt"
OUTPUT_DIR = "_data"  # relative to cwd

# Sheets that get written to disk as CSV: {sheet name in workbook -> (output
# filename, exporter function)}. Each exporter function lives in its own
# file in CB-Remix-scripts/ and knows that one sheet's specific cleanup
# rules (which column is the phantom-row key, etc.) — see the imports above.
#
# NOTE: export_metadata_orchestrator_csv (and the others in
# SHEETS_NEEDING_CONFIG below) are special-cased in load_all_sheets() —
# they also need the "config" sheet (e.g. to resolve language names/ids),
# so they're called with an extra config_df argument the others don't take.
EXPORT_SHEETS = {
    "main-metadata":         ("main-metadata.csv",   export_metadata_csv),
    "nav-bar":               ("config-nav.csv",      export_navbar_csv),
    "config-browse":         ("config-browse.csv",   export_browse_csv),
    "config-map":            ("config-map.csv",      export_map_csv),
    "metadata-orchestrator": ("config-metadata.csv", export_metadata_orchestrator_csv),
    "config-search":         ("config-search.csv",   export_search_csv),
    "config-table":          ("config-table.csv",    export_table_csv),
    "translation":           ("config-translation.csv", export_translation_csv),
}

# Sheet names that need config_df passed in alongside (output_path) — see
# the NOTE above EXPORT_SHEETS.
SHEETS_NEEDING_CONFIG = {
    "main-metadata",
    "metadata-orchestrator",
    "config-table",
    "config-map",
    "config-search",
    "config-browse",
}

# Sheets that are only kept in memory (as DataFrames) for later use — not
# written to disk.
MEMORY_ONLY_SHEETS = ["pages", "config", "config-theme"]

# _config.yml gets its fields patched from the "config" sheet, whose columns
# are named as below (case-insensitive match against these).
CONFIG_YML_PATH = "_config.yml"
CONFIG_SHEET_NAME = "config"

# _data/_theme.yml gets its fields patched from the "config-theme" sheet. Some of
# those fields (subjects-fields, locations-fields, metadata-export-fields,
# metadata-facets-fields) use "-in-<language name>" tokens that need the
# "config" sheet's lang1/lang2/lang1-id/lang2-id to resolve — see
# export_theme.py's docstring.
THEME_YML_PATH = "_data/theme.yml"
THEME_SHEET_NAME = "config-theme"

# _layouts/home-infographic.html has hardcoded bilingual
# featured-terms "field=" attributes (e.g. "subject-en;subject-pt") that
# need to track the "config" sheet's current lang1-id/lang2-id — see
# update_home_infographic.py's docstring.
HOME_INFOGRAPHIC_PATH = "_layouts/home-infographic.html"

# Environment variable GitHub Actions sets to "true" on every runner it
# manages. Used by should_serve_jekyll() below to auto-detect CI.
GITHUB_ACTIONS_ENV_VAR = "GITHUB_ACTIONS"
# ─────────────────────────────────────────────────────────────────────────────


def should_serve_jekyll(cli_serve: bool, cli_no_serve: bool) -> bool:
    """Decide whether to launch `jekyll serve` after syncing.

    Priority order:
      1. Explicit --serve / --no-serve on the command line always wins
         (lets you force either behavior, e.g. testing the CI path locally).
      2. Otherwise, auto-detect: skip if GITHUB_ACTIONS=true is set in the
         environment (which GitHub Actions sets on every runner it manages),
         since GitHub Pages builds the site itself there and a blocking dev
         server would just hang the job.
      3. Otherwise (plain local run), serve by default.
    """
    if cli_serve:
        return True
    if cli_no_serve:
        return False
    return os.environ.get(GITHUB_ACTIONS_ENV_VAR, "").lower() != "true"


def get_ods_url(link_file_path: pathlib.Path) -> str:
    """Read the Google Sheets "publish to web" .ods link out of
    *link_file_path* (PASTE_YOUR_GOOGLE_SPREADSHEET_LINK_HERE.txt in the
    project root), so switching spreadsheets is a matter of editing that
    text file instead of this script.

    Uses the first non-blank line in the file, in case the file also has
    instructions/comments in it. Exits with a clear error message if the
    file is missing, empty, or still contains placeholder text — rather
    than silently trying (and failing) to download from a bad URL.
    """
    if not link_file_path.exists():
        sys.exit(
            f"[ERROR] Could not find {link_file_path.name} in the project root.\n"
            f"        Create a file called '{LINK_FILE_NAME}' there and paste your\n"
            f"        Google Sheet's 'publish to web' .ods link into it (File > Share\n"
            f"        > Publish to web > Entire document > .ods > Publish, then copy\n"
            f"        that resulting link). Make sure it's committed to the repo so\n"
            f"        CI can find it too."
        )

    raw_text = link_file_path.read_text(encoding="utf-8")
    url = next((line.strip() for line in raw_text.splitlines() if line.strip()), "")

    if not url or "PASTE_YOUR" in url.upper():
        sys.exit(
            f"[ERROR] {link_file_path.name} doesn't contain a real link yet.\n"
            f"        Paste your Google Sheet's 'publish to web' .ods link into "
            f"that file."
        )

    if not url.lower().startswith("http"):
        sys.exit(f"[ERROR] {link_file_path.name} doesn't look like a URL: {url!r}")

    if "output=ods" not in url:
        print(
            f"[WARN] The link in {link_file_path.name} doesn't contain "
            f"'output=ods' — make sure it's the 'publish to web' link with the "
            f"format set to .ods (File > Share > Publish to web), not the "
            f"regular 'Share' link, or the download below may fail or return "
            f"the wrong file type."
        )

    return url


def download_ods(url: str) -> pathlib.Path:
    """Download the .ods file at *url* to a temp file and return its path."""
    print(f"[INFO] Downloading: {url}")
    try:
        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        sys.exit(f"[ERROR] Download failed: {exc}")

    tmp = tempfile.NamedTemporaryFile(suffix=".ods", delete=False)
    with tmp as fh:
        for chunk in response.iter_content(chunk_size=8192):
            fh.write(chunk)

    return pathlib.Path(tmp.name)


def _get_ods_cell_text(cell) -> str:
    """Extract a cell's text, preserving paragraph breaks as "\\n".

    ODS stores each line of a multi-line cell as a separate <text:p>
    element. odfpy's teletype.extractText(), when called on the *cell*
    directly, concatenates every descendant paragraph's text with NO
    separator at all — so a cell like:
        "First paragraph."
        ""
        "Second paragraph."
    comes back as "First paragraph.Second paragraph." (newlines silently
    dropped). Extracting each <text:p> individually and joining with "\\n"
    keeps the original line breaks intact.
    """
    from odf.text import P
    from odf import teletype

    paragraphs = cell.getElementsByType(P)
    if not paragraphs:
        return ""
    return "\n".join(teletype.extractText(p) for p in paragraphs)


def read_sheet(ods_path: pathlib.Path, sheet_name: str) -> pd.DataFrame:
    """Read a single named sheet from the .ods file into a DataFrame.

    Uses odfpy directly (not pandas.read_excel(engine="odf")) specifically
    to preserve line breaks inside multi-paragraph cells — see
    _get_ods_cell_text() for why that matters.
    """
    from odf.opendocument import load
    from odf.table import Table, TableRow, TableCell

    print(f"[INFO] Reading sheet: {sheet_name}")
    doc = load(str(ods_path))
    tables = doc.spreadsheet.getElementsByType(Table)
    table = next((t for t in tables if t.getAttribute("name") == sheet_name), None)

    if table is None:
        available = [t.getAttribute("name") for t in tables]
        sys.exit(
            f"[ERROR] Could not find sheet '{sheet_name}'\n"
            f"[INFO] Available sheets: {available}"
        )

    rows_data = []
    for row in table.getElementsByType(TableRow):
        row_repeat = int(row.getAttribute("numberrowsrepeated") or 1)
        row_values = []
        for cell in row.getElementsByType(TableCell):
            col_repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
            text = _get_ods_cell_text(cell)
            row_values.extend([text] * col_repeat)

        if all(v == "" for v in row_values):
            # Don't materialize huge runs of blank filler rows (common at
            # the tail of a Google Sheets ODS export).
            continue
        for _ in range(row_repeat):
            rows_data.append(list(row_values))

    while rows_data and all(v == "" for v in rows_data[-1]):
        rows_data.pop()  # defensive: trim any trailing blank row that slipped through

    if not rows_data:
        return pd.DataFrame()

    max_len = max(len(r) for r in rows_data)
    rows_data = [r + [""] * (max_len - len(r)) for r in rows_data]

    # Trim trailing columns that are blank in EVERY row (header included).
    # These come from ODS cells that exist only for formatting/theme fill
    # (e.g. banding applied across a whole sheet) and get expanded into
    # real empty-string cells above via numbercolumnsrepeated — without
    # this trim, one such cell on any row inflates every row out to that
    # width, producing dozens/hundreds of empty trailing CSV columns.
    while max_len > 0 and all(row[max_len - 1] == "" for row in rows_data):
        max_len -= 1
    rows_data = [row[:max_len] for row in rows_data]

    header, *data = rows_data
    return pd.DataFrame(data, columns=header)


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the generic cleanup rule shared by the memory-only sheets
    (pages, config, config-theme): blank out literal "0" everywhere.

    No column in these sheets legitimately contains a literal 0 — every
    occurrence comes from formulas resolving blank source cells to 0.
    Safe to strip globally rather than column-by-column.

    (Each exported sheet has its own dedicated cleanup — including this
    same zero-blanking plus phantom-row dropping — in its own script under
    CB-Remix-scripts/, since the phantom-row key column differs per sheet.)
    """
    return df.replace([0, "0", 0.0, "0.0"], "")


def load_all_sheets(ods_path: pathlib.Path, output_dir: pathlib.Path) -> dict:
    """Read every configured sheet into a DataFrame.

    - Sheets in EXPORT_SHEETS are handed to their paired exporter function
      (from CB-Remix-scripts/), which applies that sheet's specific
      cleanup and writes it to CSV in *output_dir*.
    - Sheets in MEMORY_ONLY_SHEETS get the generic clean_dataframe() cleanup
      but are NOT written to disk — they're only returned, for use later
      in the same process.

    NOTE: "config" (normally just one of MEMORY_ONLY_SHEETS) is loaded
    FIRST, ahead of the EXPORT_SHEETS loop, because several exporters (see
    SHEETS_NEEDING_CONFIG) need it already in hand — e.g.
    export_metadata_orchestrator_csv resolves the sheet's language
    names/ids from config_df to translate the "metadata-orchestrator"
    sheet's dynamic "field" values (e.g. "title-in-English") into the
    literal field names Jekyll expects (e.g. "title"). See that script's
    docstring for the full explanation.

    "config-theme" is also a memory-only sheet (see MEMORY_ONLY_SHEETS) — it
    doesn't need to be loaded early like "config" does, since
    export_theme() is only called later in main(), after
    load_all_sheets() has already returned.

    Returns a dict of {sheet_name: DataFrame} covering all loaded sheets.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dataframes = {}

    # "config" first — see NOTE above.
    config_df = read_sheet(ods_path, CONFIG_SHEET_NAME)
    config_df = clean_dataframe(config_df)
    dataframes[CONFIG_SHEET_NAME] = config_df
    print(f"[INFO] [{CONFIG_SHEET_NAME}] Loaded into memory only ({len(config_df)} rows) — not exported to CSV")

    for sheet_name, (csv_filename, exporter) in EXPORT_SHEETS.items():
        raw_df = read_sheet(ods_path, sheet_name)
        output_path = output_dir / csv_filename
        if sheet_name in SHEETS_NEEDING_CONFIG:
            dataframes[sheet_name] = exporter(raw_df, output_path, config_df)
        else:
            dataframes[sheet_name] = exporter(raw_df, output_path)

    for sheet_name in MEMORY_ONLY_SHEETS:
        if sheet_name == CONFIG_SHEET_NAME:
            continue  # already loaded above
        df = read_sheet(ods_path, sheet_name)
        df = clean_dataframe(df)
        dataframes[sheet_name] = df
        print(f"[INFO] [{sheet_name}] Loaded into memory only ({len(df)} rows) — not exported to CSV")

    return dataframes


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync site content from the Google Sheet.")
    serve_group = parser.add_mutually_exclusive_group()
    serve_group.add_argument(
        "--serve",
        action="store_true",
        help="Force-launch 'jekyll serve' after syncing, even under CI env vars.",
    )
    serve_group.add_argument(
        "--no-serve",
        action="store_true",
        help="Force-skip 'jekyll serve' after syncing, even outside CI "
             "(e.g. to test the GitHub Actions code path locally).",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path.cwd() / OUTPUT_DIR

    # The spreadsheet is downloaded exactly once per run, right here.
    ods_url = get_ods_url(pathlib.Path.cwd() / LINK_FILE_NAME)
    ods_path = download_ods(ods_url)
    try:
        dataframes = load_all_sheets(ods_path, output_dir)
    finally:
        ods_path.unlink(missing_ok=True)  # clean up temp file

    # From here on, everything works off the in-memory DataFrames above —
    # no further contact with the spreadsheet this run.
    update_config_yml(pathlib.Path.cwd() / CONFIG_YML_PATH, dataframes[CONFIG_SHEET_NAME])
    export_theme(
        pathlib.Path.cwd() / THEME_YML_PATH,
        dataframes[THEME_SHEET_NAME],
        dataframes[CONFIG_SHEET_NAME],
    )
    update_home_infographic(
        pathlib.Path.cwd() / HOME_INFOGRAPHIC_PATH,
        dataframes[CONFIG_SHEET_NAME],
    )
    build_pages_from_sheet(dataframes["pages"], dataframes[CONFIG_SHEET_NAME], base_dir=pathlib.Path.cwd())

    if not should_serve_jekyll(args.serve, args.no_serve):
        print(
            "[INFO] Sync complete. Skipping 'jekyll serve' "
            f"({'--no-serve given' if args.no_serve else 'GITHUB_ACTIONS env var detected'}); "
            "GitHub Pages will build the site itself."
        )
        return

    print("[INFO] Starting Jekyll server...")
    os.system("jekyll serve")


if __name__ == "__main__":
    main()