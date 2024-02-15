# <Screenshot App>

<DESCRIPTION>

This repository contains a Python script for automatically taking screenshots of web pages listed in a Google Sheets document and uploading them to Google Drive. It is set up to run weekly using GitHub Actions.

## Features

- Automates taking screenshots of specified web pages.
- Stores webpage URLs and other metadata in a Google Sheets document for easy management.
- Uploads screenshots directly to specified folders in Google Drive.
- Scheduled to run automatically on a weekly basis via GitHub Actions.

## Setup

### Prerequisites

- Python 3.9 or higher
- A Google Cloud Platform account with a configured project
- A service account with Google Drive and Google Sheets API enabled
- Selenium and other Python dependencies listed in `requirements.txt`

### Configuration

1. Clone the repository:
   ```git clone https://github.com/Agalak567/screenshot-app.git```

2. Install the required Python dependencies:
    ```pip install -r requirements.txt```

3. Set up your Google service account and share your Google Sheets and Drive with the service account email.

4. Add your service account key JSON file to your local clone for local testing. For GitHub Actions, add the contents of the service account file to the GOOGLE_SERVICE_ACCOUNT secret in the repository settings.

5. Update the app.py script with your specific Google Sheets spreadsheet_id and sheet_name.


### Usage

To run the script locally:
```python app.py```

The script will read the URLs from the specified Google Sheets document, take screenshots of each webpage, and upload them to the specified Google Drive folders.


## GitHub Actions

This repository is configured to run the script automatically every Sunday at 6 AM (UTC) using GitHub Actions. The workflow is defined in .github/workflows/monthly.yml.

You can modify the schedule in the workflow file by changing the cron syntax in the on.schedule section.

## Contacts
For inquiries, please reach out to Alibek Zhubekov @ a.zhubekov@prpillar.com
