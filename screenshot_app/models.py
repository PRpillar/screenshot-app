from dataclasses import dataclass
from typing import Optional


@dataclass
class RowRecord:
    link: str
    platform: str
    folder_id: str
    client: str


@dataclass
class ProcessResult:
    status: str
    error_message: Optional[str] = None


