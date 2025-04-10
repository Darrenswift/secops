# **Chronicle Detection Rule CI/CD Pipeline using Bitbucket**

## **Overview**

This project provides a Python script (deploy\_chronicle\_rules.py) and a Bitbucket Pipelines configuration file (bitbucket-pipelines.yml) to implement a "Detection-as-Code" workflow for managing Google Chronicle detection rules.

The pipeline automatically synchronizes YARA-L rules (stored as .yaral files) within a specified directory in a Bitbucket repository with a Chronicle instance. It achieves this by:

1. Fetching rules from the Bitbucket repository via API.  
2. Comparing them against existing rules in Chronicle (using the v2 API) based on ruleName.  
3. Verifying the syntax of new rules.  
4. Uploading the verified new rules to Chronicle.

## **Features**

* Fetches rule files (.yaral) directly from a Bitbucket repository via API.  
* Connects to the Chronicle v2 API.  
* Retrieves existing rules from Chronicle and identifies them by ruleName.  
* Compares rules in Bitbucket (using filename stem as target ruleName) against existing rules in Chronicle.  
* Skips rules that already exist in Chronicle with a matching ruleName.  
* Verifies the syntax of new rules using the Chronicle API before uploading.  
* Uploads verified new rules to Chronicle, setting the ruleName based on the filename stem.  
* Uses environment variables for configuration and secrets management within Bitbucket Pipelines.  
* Provides detailed logging of actions performed during pipeline execution.

## **Prerequisites**

1. **Bitbucket Repository:** A Git repository hosted on Bitbucket Cloud where your rules and pipeline configuration will reside.  
2. **Chronicle Instance:** Access to a Google Chronicle Security Operations instance.  
3. **GCP Service Account Key:** A JSON key file for a Google Cloud service account. This service account must have appropriate IAM permissions to access the Chronicle API (e.g., Chronicle API Editor role or a custom role with necessary permissions like chronicle.rules.list, chronicle.rules.create, chronicle.rules.verify).  
4. **Bitbucket App Password or Access Token:** A Bitbucket App Password or an Access Token associated with a user or service account that has **Repository Read** permissions for the target repository. This is required for the script to fetch rule files via the Bitbucket API.

## **Setup & Configuration**

1. **Files:** Place the following files in the root of your Bitbucket repository:  
   * deploy\_chronicle\_rules.py: The main Python script (content from artifact chronicle\_cicd\_script\_v2\_rulename).  
   * bitbucket-pipelines.yml: The pipeline definition file (content from artifact bitbucket\_pipeline\_yaml\_v2).  
   * **Rules Directory:** Create a directory to store your YARA-L rule files (e.g., rules/).  
     * Each rule should be in its own .yaral file.  
     * The filename stem (the part before .yaral) will be used as the ruleName in Chronicle.  
2. **Bitbucket Repository Variables:** Configure the following variables in your Bitbucket repository settings (**Repository settings** \> **Pipelines** \> **Repository variables**):  
   * GCP\_SERVICE\_ACCOUNT\_KEY (**Required, Secured**): Paste the *entire JSON content* of your GCP service account key file. Mark this variable as **Secured**.  
   * CHRONICLE\_REGION (**Required**): The Google Cloud region of your Chronicle instance (e.g., us, europe).  
   * BITBUCKET\_WORKSPACE (**Required**): Your Bitbucket workspace ID or slug.  
   * BITBUCKET\_REPO\_SLUG (**Required**): Your Bitbucket repository slug (the name of the repository as it appears in the URL).  
   * BITBUCKET\_ACCESS\_TOKEN (**Required, Secured**): Your Bitbucket App Password or Access Token with repository read scope. Mark this variable as **Secured**.  
   * BITBUCKET\_BRANCH\_OR\_COMMIT (*Optional*): The specific branch, tag, or commit hash to fetch rules from. Defaults to main if not set.  
   * RULES\_DIR (*Optional*): The path within the repository to the directory containing your .yaral rule files (relative to the repository root). Defaults to rules if not set.

## **Usage & Workflow**

1. **Trigger:** The pipeline is typically triggered automatically by commits pushed to the branch(es) configured in bitbucket-pipelines.yml (e.g., the default pipeline often runs on commits to any branch unless specified otherwise, or you can configure specific branches like main).  
2. **Authentication:** The pipeline step first authenticates to Google Cloud using the provided GCP\_SERVICE\_ACCOUNT\_KEY. It then generates a short-lived OAuth 2.0 access token specifically requesting the https://www.googleapis.com/auth/chronicle-backstory scope required for Chronicle API access.  
3. **Fetch & Compare:**  
   * The Python script calls the Chronicle API to fetch the ruleName of all existing detection rules.  
   * It then calls the Bitbucket API (using the BITBUCKET\_ACCESS\_TOKEN) to list and download the content of all .yaral files from the specified RULES\_DIR and BITBUCKET\_BRANCH\_OR\_COMMIT.  
   * It compares the filename stem of each downloaded rule file against the list of existing ruleNames fetched from Chronicle.  
4. **Process Rules:**  
   * **Existing Rules:** If a filename stem matches an existing ruleName in Chronicle, the script logs this and skips processing for that file.  
   * **New Rules:** If a filename stem does *not* match any existing ruleName, the script assumes it's a new rule:  
     * It first sends the rule text to the Chronicle API's verification endpoint to check for valid syntax.  
     * If the syntax is valid, it sends the rule text and the target ruleName (from the filename stem) to the Chronicle API's rule creation endpoint to upload the rule.  
5. **Logging & Status:** Throughout the process, the script logs its actions (fetching, comparing, skipping, verifying, uploading). It provides a final summary of processed, skipped, uploaded, and failed rules. The pipeline step will exit with an error status if any verification or upload steps failed for new rules.

## **Important Notes**

* **Rule Matching:** The script's ability to identify existing rules relies *entirely* on matching the **filename stem** (e.g., my\_rule from my\_rule.yaral) to the **ruleName** field of rules within Chronicle. Ensure your filenames accurately reflect the desired ruleName.  
* **Existing Rules without ruleName:** If you have rules currently in your Chronicle instance that were created *without* a ruleName (or where the ruleName doesn't match your intended filename), this script **cannot** automatically associate them. It will treat the corresponding files in Bitbucket as "new" during the comparison phase. This may cause warnings during the initial fetch or errors during the upload phase if Chronicle prevents duplicates based on content. For best results and reliable management via this pipeline, ensure rules in Chronicle have a ruleName that matches the filename stem in Bitbucket.

## **Troubleshooting**

* **Permissions Errors (403):**  
  * Ensure the GCP Service Account specified by GCP\_SERVICE\_ACCOUNT\_KEY has the necessary IAM roles/permissions for the Chronicle API in your GCP project.  
  * Verify the CHRONICLE\_ACCESS\_TOKEN generation line in bitbucket-pipelines.yml includes the correct scope: \--scopes=https://www.googleapis.com/auth/chronicle-backstory.  
  * Check that the BITBUCKET\_ACCESS\_TOKEN has **Repository Read** permissions in Bitbucket.  
* **Not Found Errors (404):**  
  * Double-check the values for CHRONICLE\_REGION, BITBUCKET\_WORKSPACE, BITBUCKET\_REPO\_SLUG, RULES\_DIR, and BITBUCKET\_BRANCH\_OR\_COMMIT in your Bitbucket Repository Variables. Ensure paths and names are correct.  
  * Verify the Chronicle API endpoint paths used in the Python script (deploy\_chronicle\_rules.py) are still correct for the v2 API if issues arise after API updates.  
* **Bad Request Errors (400):**  
  * Often indicates an issue with the JSON payload sent to the Chronicle API. This could be due to invalid rule syntax that wasn't caught by the basic verification step, or an incorrect structure in the payload constructed by the script (especially for the upload\_rule function). Check the detailed error message in the pipeline logs.  
* **Variable Errors:**  
  * Ensure all required Bitbucket Repository Variables are defined with the correct names (case-sensitive) and have values assigned.  
  * Check the echo commands (for non-secured variables) in the bitbucket-pipelines.yml output during a pipeline run to see the actual values being exported and used by the script. Make sure secured variables (GCP\_SERVICE\_ACCOUNT\_KEY, BITBUCKET\_ACCESS\_TOKEN) are correctly configured as "Secured" in Bitbucket settings.

\</README.md\>