#!/usr/bin/env python3
"""
CB-Remix-scripts/update_home_infographic.py

Patches _includes/home-infographic.html so its bilingual
{% include index/featured-terms.html field="..." %} calls always point at
the CURRENT spreadsheet's languages, instead of whatever language codes
happened to be hardcoded in the file previously.

── Why this is needed ────────────────────────────────────────────────────
home-infographic.html hardcodes lines like:

    {% include index/featured-terms.html field="subject-en;subject-pt" ... %}
    {% include index/featured-terms.html field="locations_en;locations_pt" ... %}

"en"/"pt" here are just whatever lang1-id/lang2-id happened to be true the
day someone wrote this file. If the spreadsheet's config!lang1-id /
config!lang2-id are ever changed (e.g. swapped for "es"/"fr"), this file
silently keeps referencing the old, now-wrong CSV columns
(config-browse.csv / config-map.csv no longer HAVE a "subject-en" column
once export_browse_csv.py re-resolves against the new languages) and the
featured-terms boxes on the home page break.

This script re-resolves those hardcoded field values the same way
export_browse_csv.py / export_metadata_orchestrator_csv.py / export_theme.py
already resolve "-in-<language name>" tokens — just working in the other
direction: instead of turning "subject-in-English" into "subject-en", it
turns whatever is CURRENTLY sitting in the file ("subject-en", "subject-es",
whatever) into "subject-{current lang1-id}".

── Matching approach ──────────────────────────────────────────────────────
Rather than hardcoding "subject" / "locations" as the only fields this
script knows about (which would silently do nothing if a new bilingual
featured-terms field is added later), it matches the general SHAPE every
one of these pairs has in this project's convention:

    field="<base><sep><code1>;<base><sep><code2>"

where <sep> is "-" or "_" and <base> is identical on both sides of the
";". That's exactly the shape config-browse.csv / config-map.csv /
config-search.csv's own field-resolution rules produce (see
export_browse_csv.py's FIELD_RENAME_RULES), so any current or future
bilingual field attribute in this file gets caught automatically.

The two language codes are assumed to be in (lang1, lang2) order, matching
the order used everywhere else in this project (config!lang1-id then
config!lang2-id) — e.g. export_browse_csv.py's own FIELD_RENAME_RULES
templates always list "{lang1_id}" before "{lang2_id}".

Self-contained: only needs `pandas` (for config_df) and stdlib `re`/
`pathlib`. Does not talk to the network or the ODS file directly — it only
operates on a DataFrame and a file path handed to it, same convention as
the other CB-Remix-scripts/*.py files.

Dependencies (install once):
    pip install pandas

Usage (as a library, not run directly):
    from update_home_infographic import update_home_infographic
"""

import pathlib
import re

import pandas as pd


def update_home_infographic(html_path, config_df=None):
    """Re-resolve every bilingual field="base-XX;base-YY" (or
    "base_XX;base_YY") attribute in *html_path* to use the CURRENT
    spreadsheet's lang1-id/lang2-id, and write the result back in place.

    *html_path* is a pathlib.Path (or str) to _includes/home-infographic.html
    (or any other file using the same include convention).

    *config_df* is the "config" tab (columns: category, content), same
    DataFrame produced by read_sheet(ods_path, "config") in download_csv.py.
    Used to resolve:
        - "lang1-id" -> short lang1 code (e.g. "en")
        - "lang2-id" -> short lang2 code (e.g. "pt")
    If config_df is omitted, or a category is missing/blank, sensible
    defaults are used (lang1-id="en", lang2-id="pt") — same fallback
    convention as export_browse_csv.py.

    Returns the new file content (str) that was written, in case the
    caller wants to inspect/log it. If the file already matched (no
    hardcoded codes needed changing), the file is left untouched (no
    unnecessary write / git diff noise).
    """
    html_path = pathlib.Path(html_path)
    if not html_path.exists():
        raise FileNotFoundError(f"[ERROR] Could not find {html_path}")

    original_text = html_path.read_text(encoding="utf-8")

    # ── Resolve current language ids from config ─────────────────────────
    LANG1_ID_CATEGORY = "lang1-id"
    LANG2_ID_CATEGORY = "lang2-id"
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

    lang1_id = get_config_category_value(LANG1_ID_CATEGORY, DEFAULT_LANG1_ID)
    lang2_id = get_config_category_value(LANG2_ID_CATEGORY, DEFAULT_LANG2_ID)

    print(f"[INFO] [home-infographic] lang1-id = {lang1_id!r}, lang2-id = {lang2_id!r}")

    # ── Match field="base<sep>CODE1;base<sep>CODE2" pairs ─────────────────
    # group(1) = base, group(2) = separator ("-" or "_"), group(3) = first
    # language code, group(4) = second language code. \1\2 backreferences
    # force the second half to share the exact same base + separator as
    # the first half, so e.g. "subject-en;subject-pt" matches but
    # "subject-en;locations_pt" (mismatched base/sep) would not.
    FIELD_PAIR_PATTERN = re.compile(
        r'field="([\w-]+?)([-_])([A-Za-z]+);\1\2([A-Za-z]+)"'
    )

    replaced_count = 0

    def _replace(match: re.Match) -> str:
        nonlocal replaced_count
        base, sep, old_code1, old_code2 = match.group(1), match.group(2), match.group(3), match.group(4)
        new_value = f'field="{base}{sep}{lang1_id};{base}{sep}{lang2_id}"'
        if (old_code1, old_code2) != (lang1_id, lang2_id):
            replaced_count += 1
            print(
                f"[INFO] [home-infographic] {base!r}: "
                f"'{base}{sep}{old_code1};{base}{sep}{old_code2}' -> "
                f"'{base}{sep}{lang1_id};{base}{sep}{lang2_id}'"
            )
        return new_value

    new_text = FIELD_PAIR_PATTERN.sub(_replace, original_text)

    if new_text == original_text:
        print(f"[INFO] [home-infographic] Already up to date ({html_path.name}) — no changes written")
        return original_text

    html_path.write_text(new_text, encoding="utf-8")
    print(
        f"[DONE] [home-infographic] Updated {replaced_count} bilingual field "
        f"attribute(s) in:\n       {html_path}"
    )

    return new_text