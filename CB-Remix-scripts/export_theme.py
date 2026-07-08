#!/usr/bin/env python3
"""
CB-Remix-scripts/export_theme.py

Patches specific fields in a CollectionBuilder _data/_theme.yml from the
"theme" spreadsheet tab, without disturbing comments or unrelated keys.

Self-contained: the function below imports everything it needs internally,
so this whole file can be copy-pasted on its own into a new
conversation/file if you just want to iterate on this piece.

Does NOT talk to the network or Google Sheets — it only operates on
DataFrames handed to it (theme_df, and optionally config_df) plus a path
to an existing _data/_theme.yml.

Dependencies (install once):
    pip install pandas ruamel.yaml

Usage (as a library, not run directly):
    from export_theme import export_theme
"""


def export_theme(
    yaml_path,
    theme_df,
    config_df=None,
    category_col: str = "category",
    content_col: str = "content",
) -> None:
    """Patch fields in a CollectionBuilder _data/_theme.yml from the "theme"
    spreadsheet tab.

    Self-contained: everything needed (the field map, the path-setter, the
    imports it uses) lives inside this function, so it can be copy-pasted
    on its own into a new conversation/file. Only needs `pandas` (as `pd`
    somewhere importable) and `ruamel.yaml` installed in the environment.

    Unlike _config.yml, _theme.yml is a flat file (no nested blocks like
    site_languages/defaults), so every field here is a simple top-level
    key. Driven entirely by FIELD_MAP below: for each (yaml_path,
    category) pair, look up *category* in the "theme" sheet and, if a
    non-blank value is found, write it to *yaml_path*.

    - All paths must already exist in _theme.yml, or the write is skipped
      and reported — this avoids silently inventing new keys with no
      surrounding comment/context. (Nothing in _theme.yml needs
      create_missing=True the way site_languages did in _config.yml,
      since there's no repeating block structure here.)
    - A blank cell in the spreadsheet is skipped rather than clearing an
      existing value.

    ── "-in-<language name>" resolution for language-coded fields ───────
    subjects-fields, locations-fields, metadata-facets-fields, and
    metadata-export-fields are fully user-authored in the "theme" sheet —
    you control the exact field list/order (e.g. adding "creator",
    "language", "vimeoid", "gender-strategy", etc.), unlike a fixed
    auto-generated list. But rather than typing literal lang codes like
    "subject-en;subject-es" (which then need hand-editing everywhere if
    the site's language ever changes), any base-column name can be tagged
    with "-in-<language name>" — the same convention
    export_metadata_csv.py already uses for the metadata sheet's column
    headers (e.g. "title-in-English"), e.g.:

        subject-in-English;subject-in-Español
        locations-in-English;locations-in-Español
        title-in-English,objectid,filename,title-in-Español,creator,description-in-English,...

    Note: "title" is special-cased the same way it is in
    export_metadata_csv.py — "title-in-<lang1 name>" resolves to bare
    "title" (no suffix at all), while "title-in-<lang2 name>" resolves to
    "title-<lang2_id>". Every other base gets a suffix on both languages.

    resolve_lang_template() (below) scans a cell's text for "<base>-in-
    <language name>" tokens and resolves each by matching the language
    name (case-insensitively) against the current lang1 / lang2 human-
    readable names pulled from *config_df* (the same "config" tab used by
    update_config_yml.py and export_metadata_csv.py) — so
    "-in-English" resolves only if lang1 is "English", "-in-Español"
    resolves only if lang2 is "Español", and so on. A matched token is
    then replaced with the corresponding lang1-id / lang2-id (not the
    name), using an underscore separator for anything based on
    "location(s)" (e.g. "locations-in-English" -> "locations_en",
    "location_first-in-Español" -> "location_first_es") and a hyphen for
    everything else (e.g. "subject-in-English" -> "subject-en") —
    matching export_metadata_csv.py's COLUMN_RENAME_RULES naming exactly.

    This means each placeholder is tied to a specific language name, not a
    position — if lang2 changes from "Español" to "Français" in the
    config sheet, existing "-in-Español" tokens for lang2 fields will stop
    matching and be left unresolved (with a warning) until you update the
    sheet to "-in-Français". This is intentionally conservative: guessing
    which language a token means from its position in the string is
    fragile (e.g. "title" for lang1 has no suffix at all, so it's not a
    reliable anchor), so an unresolved, visible token is safer than a
    silently wrong one.

    If a cell has no "-in-" tokens at all, it's written through verbatim,
    unresolved. If *config_df* is omitted, or lang1/lang2/lang1-id/lang2-id
    are missing/blank there, any "-in-" tokens found are left as-is (with
    a warning) rather than guessed at.

    Uses ruamel.yaml (round-trip mode) instead of PyYAML specifically
    because it preserves comments and key ordering, which a plain
    yaml.safe_load/yaml.dump cycle would otherwise strip out.
    """
    import re
    import pandas as pd
    from ruamel.yaml import YAML

    # ── yaml_path -> spreadsheet category ───────────────────────────────
    # One line per field. Left side is where it lives in _theme.yml (dot
    # path — _theme.yml is flat today, but the path-setter below supports
    # nesting/[N] indices in case a future field needs it, e.g. an
    # uncommented "icons" block). Right side is the "category" value to
    # look for in the spreadsheet's "theme" tab. To wire up a new field,
    # just add a line here.
    FIELD_MAP = {
        # Home page
        "featured-image":              "featured-image",
        "home-title-y-padding":        "home-title-y-padding",
        "home-banner-image-position":  "home-banner-image-position",

        # Item page
        "browse-buttons":              "browse-buttons",

        # Subjects / Locations pages
        "subjects-fields":             "subjects-fields",
        "subjects-min":                "subjects-min",
        "subjects-stopwords":          "subjects-stopwords",
        "locations-fields":            "locations-fields",
        "locations-min":               "locations-min",
        "locations-stopwords":         "locations-stopwords",

        # Map page
        "auto-center-map":             "auto-center-map",
        "latitude":                    "latitude",
        "longitude":                   "longitude",
        "zoom-level":                  "zoom-level",
        "map-base":                    "map-base",
        "map-search":                  "map-search",
        "map-search-fuzziness":        "map-search-fuzziness",
        "map-cluster":                 "map-cluster",
        "map-cluster-radius":          "map-cluster-radius",

        # Timeline page
        "year-navigation":             "year-navigation",
        "year-nav-increment":          "year-nav-increment",

        # Data
        "metadata-export-fields":      "metadata-export-fields",
        "metadata-facets-fields":      "metadata-facets-fields",

        # Compound objects
        "map-child-objects":           "map-child-objects",
        "timeline-child-objects":      "timeline-child-objects",
        "data-child-objects":          "data-child-objects",
        "carousel-child-objects":      "carousel-child-objects",
        "browse-child-objects":        "browse-child-objects",
        "search-child-objects":        "search-child-objects",

        # Advanced / navbar / fonts
        "navbar-color":                "navbar-color",
        "navbar-background":           "navbar-background",
        "bootswatch":                  "bootswatch",
        "base-font-size":              "base-font-size",
        "text-color":                  "text-color",
        "link-color":                  "link-color",
        "base-font-family":            "base-font-family",
        "font-cdn":                    "font-cdn",

        # Pajuba words page
        "pajuba-words-field":          "pajuba-words-field",
        "pajuba-words-min":            "pajuba-words-min",
        "pajuba-words-stopwords":      "pajuba-words-stopwords",
    }

    # ── "-in-<language name>" resolver ──────────────────────────────────
    # Matches e.g. "subject-in-English" -> base="subject", lang_name="English",
    # or "location_first-in-Español" -> base="location_first", lang_name="Español".
    # \w is unicode-aware in Python 3, so accented names like "Español" match fine.
    lang_token_re = re.compile(r"([\w]+)-in-([\w]+)")

    def resolve_lang_template(
        text: str, lang1_name: str, lang2_name: str, lang1_id: str, lang2_id: str
    ) -> str:
        """Replace every "<base>-in-<language name>" token in *text* with the
        real column name, mirroring export_metadata_csv.py's
        COLUMN_RENAME_RULES exactly:
            - "title-in-<lang1 name>" -> bare "title" (NO suffix at all —
              title is the one base that's special-cased: lang1 is the
              bare/default column, only lang2 gets a suffix)
            - "title-in-<lang2 name>" -> "title-<lang2_id>"
            - any other base (description, subject, etc.) -> "<base>-<lang_id>"
              on BOTH languages
            - anything starting with "location(s)" -> "<base>_<lang_id>"
              (underscore instead of hyphen) on BOTH languages
        A token's language name resolves only if it matches the current
        lang1 or lang2 name exactly (case-insensitive) — e.g. with
        lang1="English"/lang2="Español", "subject-in-English" ->
        "subject-en" and "subject-in-Español" -> "subject-es". Any name
        that doesn't match either (e.g. leftover "-in-Português" after
        lang2 changed to "Español") is left untouched, with a warning,
        rather than guessed at.
        """
        if "-in-" not in text:
            return text

        if not lang1_name or not lang2_name or not lang1_id or not lang2_id:
            print(
                f"[WARN] [theme] found '-in-' template token(s) in {text!r} "
                f"but lang1/lang2/lang1-id/lang2-id aren't all available "
                f"from config_df — leaving them unresolved."
            )
            return text

        # which -> (lang_name, lang_id), so _replace can tell whether a
        # matched token is the lang1 or lang2 side (needed for title's
        # bare-on-lang1 special case, not just which id to substitute).
        which_by_name = {
            lang1_name.lower(): ("lang1", lang1_id),
            lang2_name.lower(): ("lang2", lang2_id),
        }
        unresolved = set()

        def _replace(match: "re.Match") -> str:
            base, lang_name = match.group(1), match.group(2)
            resolved = which_by_name.get(lang_name.lower())
            if resolved is None:
                unresolved.add(lang_name)
                return match.group(0)
            which, lang_id = resolved

            if base.lower() == "title" and which == "lang1":
                return base  # bare, no suffix — lang1 title is unsuffixed

            sep = "_" if base.lower().startswith("location") else "-"
            return f"{base}{sep}{lang_id}"

        result = lang_token_re.sub(_replace, text)

        if unresolved:
            print(
                f"[WARN] [theme] language name(s) {sorted(unresolved)} in "
                f"{text!r} don't match current lang1 ({lang1_name!r}) or "
                f"lang2 ({lang2_name!r}) — left unresolved. Update the "
                f"sheet if the site's languages changed."
            )

        return result

    path_segment_re = re.compile(r"^([\w-]+)(?:\[(\d+)\])?$")

    def set_yaml_path(theme_data, path: str, value, create_missing: bool = False) -> bool:
        """Set a value at a dot/bracket path like "icons.icon-image".

        If *create_missing* is False, the path must already exist (aside
        from the final key) or nothing is changed and False is returned.
        If True, missing dicts/list slots are created along the way.
        """
        segments = path.split(".")
        node = theme_data

        for i, segment in enumerate(segments):
            match = path_segment_re.match(segment)
            key, index = match.group(1), match.group(2)
            is_last = i == len(segments) - 1

            if index is None:
                if is_last:
                    if key not in node and not create_missing:
                        return False
                    node[key] = value
                    return True
                if key not in node or node[key] is None:
                    if not create_missing:
                        return False
                    node[key] = {}
                node = node[key]
            else:
                index = int(index)
                if key not in node or node[key] is None:
                    if not create_missing:
                        return False
                    node[key] = []
                item_list = node[key]
                while len(item_list) <= index:
                    if not create_missing:
                        return False
                    item_list.append({})
                if is_last:
                    item_list[index] = value
                    return True
                node = item_list[index]

        return False

    if not yaml_path.exists():
        print(f"[WARN] {yaml_path} does not exist — skipping theme update")
        return

    if category_col not in theme_df.columns or content_col not in theme_df.columns:
        print(
            f"[WARN] theme sheet is missing '{category_col}' or '{content_col}' "
            f"column(s) — skipping theme update. Found columns: {list(theme_df.columns)}"
        )
        return

    # category -> cleaned value, straight from the spreadsheet
    values_by_category = {
        str(row[category_col]).strip(): (
            "" if pd.isna(row[content_col]) else str(row[content_col]).strip()
        )
        for _, row in theme_df.iterrows()
    }

    # lang1/lang2 names + lang1-id/lang2-id from the config sheet, for
    # resolving "-in-<language name>" tokens. Left blank if config_df
    # wasn't passed or doesn't have what we need — resolve_lang_template()
    # handles that gracefully (warns, leaves as-is).
    lang1_name, lang2_name, lang1_id, lang2_id = "", "", "", ""
    if config_df is not None and \
            category_col in config_df.columns and content_col in config_df.columns:
        config_values_by_category = {
            str(row[category_col]).strip(): (
                "" if pd.isna(row[content_col]) else str(row[content_col]).strip()
            )
            for _, row in config_df.iterrows()
        }
        lang1_name = config_values_by_category.get("lang1", "")
        lang2_name = config_values_by_category.get("lang2", "")
        lang1_id = config_values_by_category.get("lang1-id", "")
        lang2_id = config_values_by_category.get("lang2-id", "")

    yaml = YAML()
    yaml.preserve_quotes = True

    with open(yaml_path, "r", encoding="utf-8") as fh:
        theme_data = yaml.load(fh)

    updated, skipped_missing, skipped_blank = [], [], []

    for yaml_field_path, category in FIELD_MAP.items():
        if category not in values_by_category:
            continue  # this category isn't in the spreadsheet at all

        value = values_by_category[category]
        if value == "":
            skipped_blank.append(yaml_field_path)
            continue

        value = resolve_lang_template(value, lang1_name, lang2_name, lang1_id, lang2_id)

        if set_yaml_path(theme_data, yaml_field_path, value, create_missing=False):
            updated.append(yaml_field_path)
        else:
            skipped_missing.append(yaml_field_path)

    with open(yaml_path, "w", encoding="utf-8") as fh:
        yaml.dump(theme_data, fh)

    print(f"[DONE] {yaml_path} updated. Fields set: {updated}")
    if skipped_missing:
        print(
            f"[WARN] These yaml paths don't exist in {yaml_path} (and aren't "
            f"auto-created), so they were skipped: {skipped_missing}"
        )
    if skipped_blank:
        print(f"[INFO] These fields were blank in the spreadsheet, so left untouched: {skipped_blank}")