from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScannerOptions(BaseModel):
    ping_concurrency: int = Field(default=128, ge=32, le=512)
    port_scan_workers: int = Field(default=32, ge=8, le=64)
    dns_resolution: bool = True
    aggressive: bool = False

    model_config = ConfigDict(extra="ignore")


class ScannerConfig(BaseModel):
    network_cidrs: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    port_preset: str = Field(default="normal")
    options: ScannerOptions = Field(default_factory=ScannerOptions)

    model_config = ConfigDict(extra="ignore")


class ScannerConfigRecord(BaseModel):
    id: int
    user_id: str
    config: ScannerConfig
    updated_at: datetime | None = None

    model_config = ConfigDict(extra="ignore")


def default_scanner_config() -> ScannerConfig:
    return ScannerConfig(
        network_cidrs=["192.168.1.0/24"],
        ports=[
            21,
            22,
            23,
            25,
            53,
            80,
            110,
            143,
            443,
            465,
            587,
            993,
            995,
            3306,
            3389,
            5432,
            8080,
            8443,
        ],
        port_preset="normal",
        options=ScannerOptions(),
    )
