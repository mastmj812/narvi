"""Backend settings. The only thing not handled by narvi's own .env (the DB_*
keys, read by narvi.warehouse) is the PMTiles basemap path — reuse the shared
permian.pmtiles already vendored under permian_type_curve/infra/basemap."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]          # ...\narvi
_DEFAULT_PMTILES = (
    _REPO_ROOT.parent / "permian_type_curve" / "infra" / "basemap" / "permian.pmtiles"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # shared Permian basemap (overridable via PMTILES_PATH if it moves)
    pmtiles_path: Path = Field(default=_DEFAULT_PMTILES, alias="PMTILES_PATH")


settings = Settings()
