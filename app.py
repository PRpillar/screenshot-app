from screenshot_app.config import get_app_config, load_service_account_credentials
from screenshot_app.google_clients import build_google_clients
from screenshot_app.logging_setup import configure_logging
from screenshot_app.processor import process_batch


def main() -> bool:
    logger = configure_logging()
    cfg = get_app_config()
    logger.info("Starting screenshot batch run")
    credentials = load_service_account_credentials(cfg.scopes, cfg.delegated_user)
    gc, drive_service = build_google_clients(credentials)
    return process_batch(
        gc=gc,
        drive_service=drive_service,
        spreadsheet_id=cfg.spreadsheet_id,
        database_sheet_name=cfg.database_sheet_name,
        config_sheet_name=cfg.config_sheet_name,
        debug_cloudflare=cfg.debug_cloudflare,
    )


if __name__ == "__main__":
    done = main()
    if done:
        exit(0)
    else:
        exit(100)

