"""
ergane/db/models.py
Modelo canónico de Job. Todos los scrapers producen esto.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import hashlib


@dataclass
class Job:
    url: str
    title: str
    source: str                         # 'occ'|'computrabajo'|'techjobsmx'|'getonbrd'
    company: Optional[str] = None
    location: Optional[str] = None
    salary_min: Optional[int] = None    # MXN brutos/mes
    salary_max: Optional[int] = None
    salary_raw: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    remote: bool = False
    score: float = 0.0
    posted_at: Optional[str] = None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()

    def to_dict(self) -> dict:
        import json
        return {
            "url_hash":    self.url_hash,
            "url":         self.url,
            "title":       self.title,
            "company":     self.company,
            "location":    self.location,
            "salary_min":  self.salary_min,
            "salary_max":  self.salary_max,
            "salary_raw":  self.salary_raw,
            "description": self.description,
            "tags":        json.dumps(self.tags, ensure_ascii=False),
            "source":      self.source,
            "remote":      int(self.remote),
            "score":       self.score,
            "notified":    0,
            "scraped_at":  self.scraped_at,
            "posted_at":   self.posted_at,
        }
