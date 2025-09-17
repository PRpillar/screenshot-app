from __future__ import annotations

from typing import Tuple

import gspread
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials


def build_google_clients(credentials: Credentials) -> Tuple[gspread.Client, any]:
    gc = gspread.authorize(credentials)
    drive_service = build("drive", "v3", credentials=credentials)
    return gc, drive_service


