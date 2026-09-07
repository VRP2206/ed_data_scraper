# Ed Discussion Exporter

Exports all posts from an [Ed Discussion](https://edstem.org) course to JSON and Markdown files using the Ed API.

## Output

```
data_obtained/<course_name>/
    all_posts.json          # all threads as raw JSON
    all_posts.md            # all threads as a single Markdown file
    threads/
        000001-<title>.md   # one file per thread
        ...
```

## Setup

```bash
pip install requests
```

## Authentication

Get your API token from Ed Discussion → Account Settings → API Tokens.

Set it as an environment variable before running:

```bash
# Linux/macOS
export ED_TOKEN="your_token_here"

# Windows PowerShell
$env:ED_TOKEN="your_token_here"

# Windows CMD
set ED_TOKEN=your_token_here
```

Or create a `.env` file in the project root:

```
ED_TOKEN=your_token_here
```

If no token is found, the script will prompt for it interactively.

## Usage

```bash
python export_ed.py
```

You will be prompted for:
- **Course ID** — the numeric ID from the course URL (e.g. `edstem.org/courses/12345`)
- **Course name** — used as the output folder name

## Notes

- The script respects rate limits and retries on transient server errors.
- Only courses your account has access to can be exported.
- Exported data may contain personal information — see [PRIVACY.md](PRIVACY.md).

## License

MIT — see [LICENSE](LICENSE).
