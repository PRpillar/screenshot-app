import os
import json
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


# Load variables from .env if present (local development convenience)
load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    spreadsheet_id: str
    database_sheet_name: str
    config_sheet_name: str
    delegated_user: str
    scopes: List[str]
    debug_cloudflare: bool


def get_app_config() -> AppConfig:
    spreadsheet_id = os.getenv(
        "SPREADSHEET_ID",
        "1OHzJc9hvr6tgi2ehogkfP9sZHYkI3dW1nB62JCpM9D0",
    )
    database_sheet_name = os.getenv("DATABASE_SHEET", "Database")
    config_sheet_name = os.getenv("CONFIG_SHEET", "Configurations")
    delegated_user = os.getenv("DELEGATED_USER_EMAIL", "y.kuanysh@prpillar.com")
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    debug_cloudflare = os.getenv("DEBUG_CLOUDFLARE", "true").lower() in ("1", "true", "yes")
    return AppConfig(
        spreadsheet_id=spreadsheet_id,
        database_sheet_name=database_sheet_name,
        config_sheet_name=config_sheet_name,
        delegated_user=delegated_user,
        scopes=scopes,
        debug_cloudflare=debug_cloudflare,
    )


def load_service_account_credentials(scopes: List[str], delegated_user: str) -> Credentials:
    service_account_info = os.environ.get("GOOGLE_SERVICE_ACCOUNT")
    if not service_account_info:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT secret")
    return Credentials.from_service_account_info(
        json.loads(service_account_info), scopes=scopes, subject=delegated_user
    )


