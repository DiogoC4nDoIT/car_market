"""Bundles the per-run dataframes loaded once in app.py so tab modules take
an explicit `ctx` argument instead of reaching for module-level globals."""
from dataclasses import dataclass

import pandas as pd


@dataclass
class Context:
    deals: pd.DataFrame
    ads: pd.DataFrame
    stats: pd.DataFrame
    fine_stats: pd.DataFrame
    fuel_stats: pd.DataFrame
    liq: pd.DataFrame
    flags: pd.DataFrame
    searches: pd.DataFrame
    skipped_ids: set
    fav_ids: set
