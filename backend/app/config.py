"""Backend settings. The only thing not handled by narvi's own .env (the DB_*
keys, read by narvi.warehouse) are the basemap asset paths — reuse the shared
permian.pmtiles and the Texas/NM survey-grid GeoJSON overlays already vendored
under permian_type_curve/infra/basemap (anduin is the source of truth for these
assets; narvi points at the same files rather than duplicating the 32 MB
sections export)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]          # ...\narvi
_BASEMAP_DIR = _REPO_ROOT.parent / "permian_type_curve" / "infra" / "basemap"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # shared Permian basemap (overridable via PMTILES_PATH if it moves)
    pmtiles_path: Path = Field(
        default=_BASEMAP_DIR / "permian.pmtiles", alias="PMTILES_PATH"
    )
    # Texas/NM survey-grid overlays (OTLS data covers both states). Blocks is
    # the Texas block grid; sections is the abstract/section grid.
    blocks_geojson_path: Path = Field(
        default=_BASEMAP_DIR / "blocks_tx_nm.geojson", alias="BLOCKS_GEOJSON_PATH"
    )
    sections_geojson_path: Path = Field(
        default=_BASEMAP_DIR / "sections_tx_nm.geojson", alias="SECTIONS_GEOJSON_PATH"
    )


settings = Settings()
