from functools import lru_cache

import yaml
from pydantic import BaseModel, Field

from app.config import get_settings, resolve_data_file


class Region(BaseModel):
    key: str
    label: str
    country: str
    keywords: list[str]
    adzuna: dict | None = None


class Regions(BaseModel):
    regions: dict[str, Region] = Field(default_factory=dict)

    def match(self, location: str | None) -> list[str]:
        """Region keys whose keywords appear in a location string."""
        if not location:
            return []
        loc = location.lower()
        return [key for key, r in self.regions.items() if any(k in loc for k in r.keywords)]


@lru_cache
def get_regions() -> Regions:
    raw = yaml.safe_load(resolve_data_file(get_settings().regions_path).read_text())
    return Regions(regions={k: Region(key=k, **v) for k, v in raw["regions"].items()})
