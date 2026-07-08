#!/usr/bin/env python3
"""
CB-Remix-scripts/update_home_infographic.py

Rewrites _includes/home-infographic.html from a known-good template,
substituting the CURRENT spreadsheet's lang1-id/lang2-id into the two
bilingual featured-terms field="..." attributes.

Usage (as a library, not run directly):
    from update_home_infographic import update_home_infographic
"""

import pathlib

import pandas as pd

TEMPLATE = """---
# Default home page with boxes providing collection stats
layout: page
---
{{%- assign items = site.data[site.metadata] | where_exp: 'item', 'item.objectid != nil' -%}}
<div class="row">
  <div class="col-md-8">
    {{% include index/description.html %}}
    {{% include index/carousel.html title="Sample Items" height="300" %}}
  
  </div>
  <div class="col-md-4">  
    {{% include index/time.html %}}
    {{% include index/featured-terms.html field="subject-{lang1_id};subject-{lang2_id}" title="home-subjects" btn-color="primary" %}}
    {{% include index/featured-terms.html field="locations_{lang1_id};locations_{lang2_id}" title="home-locations" btn-color="outline-secondary" %}}
    {{% include index/objects.html %}}
  </div>
  <div class="col-md-12">
    {{% include index/data-download.html %}}
  </div>
</div>
"""


def update_home_infographic(html_path, config_df=None):
    """Rewrite *html_path* from the known-good template, substituting the
    current spreadsheet's lang1-id/lang2-id into the two bilingual
    featured-terms field="..." attributes.

    *config_df* is the "config" tab (columns: category, content). Used to
    resolve "lang1-id" / "lang2-id". If omitted or missing, defaults to
    "en" / "pt".

    Returns the new file content (str).
    """
    html_path = pathlib.Path(html_path)

    def clean(value) -> str:
        if pd.isna(value):
            return ""
        return str(value).strip()

    def get_config_value(category: str, default: str) -> str:
        if config_df is None:
            return default
        if "category" not in config_df.columns or "content" not in config_df.columns:
            return default
        match = config_df[config_df["category"].astype(str).str.strip() == category]
        if match.empty:
            return default
        return clean(match.iloc[0]["content"]) or default

    lang1_id = get_config_value("lang1-id", "en")
    lang2_id = get_config_value("lang2-id", "pt")

    print(f"[INFO] [home-infographic] lang1-id = {lang1_id!r}, lang2-id = {lang2_id!r}")

    new_text = TEMPLATE.format(lang1_id=lang1_id, lang2_id=lang2_id)

    old_text = html_path.read_text(encoding="utf-8") if html_path.exists() else None
    if new_text == old_text:
        print(f"[INFO] [home-infographic] Already up to date ({html_path.name}) — no changes written")
        return new_text

    html_path.write_text(new_text, encoding="utf-8")
    print(f"[DONE] [home-infographic] Wrote {html_path}")
    return new_text