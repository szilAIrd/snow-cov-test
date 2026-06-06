"""Per-analysis Copernicus S3 trace collector."""

from dataclasses import dataclass, field
from typing import List, Set

from .models import CopernicusTrace


@dataclass
class CopernicusTraceCollector:
    mode: str
    queried_s3_keys: List[str] = field(default_factory=list)
    used_s3_keys: List[str] = field(default_factory=list)
    downloaded_s3_keys: List[str] = field(default_factory=list)

    _queried_seen: Set[str] = field(default_factory=set, init=False, repr=False)
    _used_seen: Set[str] = field(default_factory=set, init=False, repr=False)
    _downloaded_seen: Set[str] = field(default_factory=set, init=False, repr=False)

    def record_queried(self, s3_key: str) -> None:
        if s3_key and s3_key not in self._queried_seen:
            self._queried_seen.add(s3_key)
            self.queried_s3_keys.append(s3_key)

    def record_used(self, s3_key: str) -> None:
        if s3_key and s3_key not in self._used_seen:
            self._used_seen.add(s3_key)
            self.used_s3_keys.append(s3_key)

    def record_downloaded(self, s3_key: str) -> None:
        if s3_key and s3_key not in self._downloaded_seen:
            self._downloaded_seen.add(s3_key)
            self.downloaded_s3_keys.append(s3_key)

    def to_model(self) -> CopernicusTrace:
        return CopernicusTrace(
            mode=self.mode,
            queried_s3_keys=self.queried_s3_keys,
            used_s3_keys=self.used_s3_keys,
            downloaded_s3_keys=self.downloaded_s3_keys,
        )
