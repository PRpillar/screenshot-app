from __future__ import annotations

from typing import Tuple
import os

import gspread
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from google_auth_httplib2 import AuthorizedHttp
import httplib2


def build_google_clients(credentials: Credentials) -> Tuple[gspread.Client, any]:
    gc = gspread.authorize(credentials)
    # Ensure Google API calls have a network timeout to avoid hangs
    http_timeout = int(os.getenv("GOOGLE_HTTP_TIMEOUT", "60"))
    authed_http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=http_timeout))
    # When passing an authorized http client, do not pass credentials again
    drive_service = build("drive", "v3", cache_discovery=False, http=authed_http)
    return gc, drive_service


