# Privacy Notice

## What data this tool accesses

This tool uses the Ed Discussion API to export course content that your account has permission to access. This may include:

- Thread titles, bodies, and metadata (timestamps, categories, thread IDs)
- Author names as returned by the Ed API
- Replies and comments, including endorsement status
- Attached file URLs and image URLs

## What data is stored locally

All exported data is written to your local machine under `data_obtained/`. No data is sent to any third party by this tool.

## Personal information in exports

Exported content may contain **personally identifiable information (PII)** such as:

- Student and instructor names
- Post content written by course participants

You are responsible for handling exported data in accordance with your institution's data governance policies and applicable privacy laws (e.g. FERPA, GDPR, the Australian Privacy Act).

Note: Most are redacted to unknown by the API return structure, the api may change in the future where that is not the case and a redacted feature need to be implemented 

## Recommendations

- Do not share exported files publicly or with unauthorised parties.
- Delete exported data when it is no longer needed.
- Store exported data securely and restrict access appropriately.
- Do not commit exported data (the `data_obtained/` directory) to version control.

## API token

Your Ed API token is a credential that grants access to your Ed account. It is read from the `ED_TOKEN` environment variable or a local `.env` file and is never transmitted anywhere other than to `https://edstem.org/api`.

- Do not share your token or commit it to version control.
- Revoke and regenerate your token if you believe it has been compromised.

your API token only allow you to access your own courses.
