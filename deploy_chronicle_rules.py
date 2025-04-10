import os
import json
import requests
import logging
from pathlib import Path

# --- Configuration ---
# Load configuration from environment variables
ACCESS_TOKEN = os.environ.get("CHRONICLE_ACCESS_TOKEN")
REGION = os.environ.get("CHRONICLE_REGION")
BITBUCKET_WORKSPACE = os.environ.get("BITBUCKET_WORKSPACE")
BITBUCKET_REPO_SLUG = os.environ.get("BITBUCKET_REPO_SLUG")
BITBUCKET_ACCESS_TOKEN = os.environ.get("BITBUCKET_ACCESS_TOKEN") # Needs repo:read scope
BITBUCKET_BRANCH_OR_COMMIT = os.environ.get("BITBUCKET_BRANCH_OR_COMMIT", "main") # Default to 'main' branch
RULES_DIR = os.environ.get("RULES_DIR", "rules").strip('/') # Remove leading/trailing slashes

# --- Validation ---
if not all([ACCESS_TOKEN, REGION]):
    raise ValueError("Missing required Chronicle environment variables: CHRONICLE_ACCESS_TOKEN, CHRONICLE_REGION")
if not all([BITBUCKET_WORKSPACE, BITBUCKET_REPO_SLUG, BITBUCKET_ACCESS_TOKEN]):
    raise ValueError("Missing required Bitbucket environment variables: BITBUCKET_WORKSPACE, BITBUCKET_REPO_SLUG, BITBUCKET_ACCESS_TOKEN")

# --- API URLs and Headers ---
CHRONICLE_BASE_API_URL = f"https://{REGION}-backstory.googleapis.com/v2"
BITBUCKET_BASE_API_URL = "https://api.bitbucket.org/2.0"

CHRONICLE_HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
BITBUCKET_HEADERS = {
    "Authorization": f"Bearer {BITBUCKET_ACCESS_TOKEN}",
    "Accept": "application/json",
}

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def _make_api_request(method, url, headers, params=None, json_data=None, expected_status=200, stream=False):
    """Helper function to make generic API requests with error handling."""
    try:
        response = requests.request(method, url, headers=headers, params=params, json=json_data, stream=stream)
        if response.status_code != expected_status:
            error_details = f"Status: {response.status_code}."
            try:
                error_body = response.json()
                error_details += f" Body: {json.dumps(error_body)}"
            except json.JSONDecodeError:
                error_details += f" Body: {response.text}"
            logging.error(f"API Request Error ({method} {url}): Unexpected status code. {error_details}")
            response.raise_for_status()

        if response.status_code == 204 or not response.content:
             return None if not stream else response

        return response.content if stream else response.json()

    except requests.exceptions.RequestException as e:
        logging.error(f"API Request Error ({method} {url}): {e}")
        if e.response is not None:
            logging.error(f"Response Status: {e.response.status_code}")
            try:
                logging.error(f"Response Body: {e.response.json()}")
            except json.JSONDecodeError:
                logging.error(f"Response Body (non-JSON): {e.response.text}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON response from {method} {url}: {e}")
        logging.error(f"Response Text: {response.text}")
        return None


def get_files_from_bitbucket():
    """Fetches rule files from the specified directory in Bitbucket via API."""
    logging.info(f"Fetching rule files from Bitbucket: {BITBUCKET_WORKSPACE}/{BITBUCKET_REPO_SLUG}/{RULES_DIR} @ {BITBUCKET_BRANCH_OR_COMMIT}")
    rule_files_content = []
    list_url = f"{BITBUCKET_BASE_API_URL}/repositories/{BITBUCKET_WORKSPACE}/{BITBUCKET_REPO_SLUG}/src/{BITBUCKET_BRANCH_OR_COMMIT}/{RULES_DIR}"
    page = 1

    while list_url:
        logging.debug(f"Fetching file list page: {list_url}")
        response_data = _make_api_request("GET", list_url, headers=BITBUCKET_HEADERS)

        if response_data is None or 'values' not in response_data:
            logging.error(f"Failed to list files in Bitbucket directory: {RULES_DIR}. Check path, permissions, and branch/commit.")
            return None

        for item in response_data.get('values', []):
            if item.get('type') == 'commit_file' and item.get('path', '').endswith('.yaral'):
                file_path = item.get('path')
                file_name = Path(file_path).name
                # filename_stem will be used as the target ruleName
                filename_stem = Path(file_name).stem
                logging.info(f"Found rule file: {file_path}")

                file_content_url = f"{BITBUCKET_BASE_API_URL}/repositories/{BITBUCKET_WORKSPACE}/{BITBUCKET_REPO_SLUG}/src/{BITBUCKET_BRANCH_OR_COMMIT}/{file_path}"
                raw_content_headers = BITBUCKET_HEADERS.copy()
                file_content_bytes = _make_api_request("GET", file_content_url, headers=raw_content_headers, stream=True)

                if file_content_bytes:
                    try:
                        rule_text = file_content_bytes.decode('utf-8')
                        if rule_text.strip():
                             # Store the filename_stem as 'name' for matching
                             rule_files_content.append({'name': filename_stem, 'text': rule_text, 'path': file_path})
                             logging.debug(f"Successfully fetched content for {file_path}")
                        else:
                            logging.warning(f"Rule file '{file_path}' is empty. Skipping.")
                    except UnicodeDecodeError:
                         logging.error(f"Could not decode content of file '{file_path}' as UTF-8. Skipping.")
                    except Exception as e:
                         logging.error(f"Error processing content of file '{file_path}': {e}. Skipping.")
                else:
                    logging.error(f"Failed to fetch content for rule file: {file_path}")

        list_url = response_data.get('next')
        page += 1

    logging.info(f"Finished fetching files from Bitbucket. Found {len(rule_files_content)} rule files.")
    return rule_files_content


# --- Chronicle API Functions (Using v2 API) ---

def get_existing_rule_names():
    """
    Retrieves rules from Chronicle, logs counts, and returns a set of
    ruleName values found for matching purposes.
    """
    existing_rule_names_set = set()
    total_rules_found_api = 0
    rules_with_rule_name = 0
    next_page_token = None
    endpoint = "detect/rules"
    logging.info(f"Fetching existing rules from Chronicle v2 ({endpoint})...")
    url = f"{CHRONICLE_BASE_API_URL}/{endpoint}"

    page_num = 1
    while True:
        logging.debug(f"Fetching page {page_num} of existing rules...")
        params = {}
        if next_page_token:
            params['pageToken'] = next_page_token

        response_data = _make_api_request("GET", url, headers=CHRONICLE_HEADERS, params=params)

        if response_data is None:
            if page_num == 1:
                 logging.error("Failed to retrieve initial page of rules from Chronicle.")
                 return None
            else:
                 logging.error(f"Failed to retrieve page {page_num} of rules from Chronicle. Proceeding with previously fetched data.")
                 break

        rules = response_data.get('rules', [])
        total_rules_found_api += len(rules)

        for rule in rules:
            rule_name_from_api = rule.get('ruleName')
            if rule_name_from_api:
                existing_rule_names_set.add(rule_name_from_api)
                rules_with_rule_name += 1
            else:
                rule_id = rule.get('ruleId', rule.get('id', 'Unknown ID'))
                logging.warning(f"Chronicle rule found without a ruleName (ID: {rule_id}). This rule cannot be matched by filename.")

        next_page_token = response_data.get('nextPageToken')
        if not next_page_token:
            break
        page_num += 1

    logging.info(f"Chronicle API returned {total_rules_found_api} total rules.")
    logging.info(f"Found {rules_with_rule_name} rules with ruleNames for matching.")
    return existing_rule_names_set


def verify_rule(target_rule_name, rule_text):
    """Verifies a rule using the Chronicle v2 verify endpoint."""
    # User confirmed :verifyRule works, let's revert endpoint if needed, but keep payload simple for now.
    # Assuming the user manually changed this back in their copy if :verify failed.
    # Sticking with :verify as per previous step unless user confirms :verifyRule worked.
    # If user confirms :verifyRule worked, change endpoint back here.
    # For now, assume :verify might work or user has fixed it locally.
    endpoint_to_use = "detect/rules:verifyRule" # Defaulting to :verify from previous step
    # If user confirms :verifyRule worked, uncomment below and comment above
    # endpoint_to_use = "detect/rules:verifyRule"

    logging.info(f"Verifying rule with Chronicle v2 using endpoint '{endpoint_to_use}' (Target Name: {target_rule_name})...")

    url = f"{CHRONICLE_BASE_API_URL}/{endpoint_to_use}"
    # Keep simple payload unless :verifyRule confirmed to need full object
    payload = {"rule_text": rule_text}

    response_data = _make_api_request("POST", url, headers=CHRONICLE_HEADERS, json_data=payload, expected_status=200)

    if response_data is not None:
        logging.info(f"Rule syntax for '{target_rule_name}' verified successfully by Chronicle v2.")
        return True
    else:
        logging.error(f"Rule syntax verification for '{target_rule_name}' failed with Chronicle v2.")
        return False


def upload_rule(target_rule_name, rule_text):
    """Uploads a new rule using the Chronicle v2 createRule endpoint, setting ruleName."""
    logging.info(f"Uploading rule to Chronicle v2 as '{target_rule_name}'...")
    endpoint = "detect/rules"
    url = f"{CHRONICLE_BASE_API_URL}/{endpoint}"
    # Corrected Payload: Remove the nesting under "rule"
    payload = {
        "ruleName": target_rule_name,
        "ruleText": rule_text
        # Optional: Add other fields here if needed, e.g.
        # "metadata": {"description": "Uploaded via CI/CD"}
        }

    response_data = _make_api_request("POST", url, headers=CHRONICLE_HEADERS, json_data=payload, expected_status=200)

    if response_data is not None and ('ruleId' in response_data or 'id' in response_data):
        rule_id = response_data.get('ruleId', response_data.get('id'))
        logging.info(f"Rule '{target_rule_name}' uploaded successfully to Chronicle v2. Rule ID: {rule_id}")
        return True
    else:
        log_detail = f" Response: {json.dumps(response_data)}" if response_data else ""
        logging.error(f"Rule '{target_rule_name}' upload failed with Chronicle v2.{log_detail}")
        return False

# --- Main Pipeline Logic ---

def main():
    """Executes the CI/CD pipeline steps."""
    logging.info("--- Starting Chronicle Rule Deployment Pipeline (API v2 - using ruleName) ---")

    # 1. Get existing rule names from Chronicle
    logging.info("--- Step 1: Get Existing Rule Names (Chronicle v2) ---")
    existing_rule_names = get_existing_rule_names()
    if existing_rule_names is None:
        logging.error("Failed to get initial rule data from Chronicle. Aborting.")
        exit(1)
    logging.info(f"Using {len(existing_rule_names)} ruleNames for existence checks.")


    # 2. Fetch rules from Bitbucket
    logging.info(f"--- Step 2: Fetch Rules from Bitbucket Repository ---")
    rules_from_bitbucket = get_files_from_bitbucket()
    if rules_from_bitbucket is None:
        logging.error("Failed to fetch rules from Bitbucket. Aborting.")
        exit(1)
    if not rules_from_bitbucket:
        logging.warning(f"No '.yaral' rule files found in Bitbucket directory '{RULES_DIR}'. Exiting.")
        exit(0)

    # 3. Process and Upload rules
    logging.info(f"--- Step 3: Verify and Upload Rules to Chronicle v2 ---")
    rules_processed = 0
    rules_uploaded = 0
    rules_skipped = 0
    rules_failed_verification = 0
    rules_failed_upload = 0

    for rule_data in rules_from_bitbucket:
        rules_processed += 1
        target_rule_name = rule_data['name']
        rule_text = rule_data['text']
        rule_path = rule_data['path']
        logging.info(f"Processing rule from Bitbucket path: {rule_path} (Target ruleName: {target_rule_name})")

        if target_rule_name in existing_rule_names:
            logging.info(f"Rule with matching ruleName '{target_rule_name}' found in Chronicle. Skipping upload.")
            rules_skipped += 1
        else:
            logging.info(f"No rule with ruleName '{target_rule_name}' found in existing Chronicle rules. Proceeding with verification.")
            # Pass rule_text to verify_rule
            if verify_rule(target_rule_name, rule_text):
                 # Pass target_rule_name and rule_text to upload_rule
                if upload_rule(target_rule_name, rule_text):
                    rules_uploaded += 1
                else:
                    rules_failed_upload += 1
            else:
                rules_failed_verification += 1

    logging.info("--- Rule Upload Summary ---")
    logging.info(f"Rule files processed from Bitbucket: {rules_processed}")
    logging.info(f"Rules skipped (matching ruleName found in Chronicle): {rules_skipped}")
    logging.info(f"Rules successfully verified and uploaded to Chronicle: {rules_uploaded}")
    logging.info(f"Rules failed Chronicle verification: {rules_failed_verification}")
    logging.info(f"Rules failed Chronicle upload (after verification): {rules_failed_upload}")

    # 4. Count post-run rules in Chronicle (Optional final check)
    logging.info("--- Step 4: Get Final Rule Counts (Chronicle v2) ---")
    get_existing_rule_names()


    logging.info("--- Chronicle Rule Deployment Pipeline Finished ---")

    if rules_failed_verification > 0 or rules_failed_upload > 0:
        exit(1)
    else:
        exit(0)


if __name__ == "__main__":
    main()
