#!/usr/bin/env python3
"""
Ed API token checker.

Calls GET https://edstem.org/api/user to verify your token and list
the courses your account is enrolled in.

Usage:
    python check_ed_token.py [TOKEN]

If TOKEN is omitted, ED_TOKEN is read from the environment or a .env file.
"""

import os
import sys
from pathlib import Path

import requests

BASE_URL = "https://edstem.org/api"

# Load .env if present
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    token = sys.argv[1].strip() if len(sys.argv) > 1 else os.environ.get("ED_TOKEN", "").strip()

    if not token:
        print("No token provided. Pass it as an argument or set ED_TOKEN.", file=sys.stderr)
        sys.exit(1)

    r = requests.get(
        BASE_URL + "/user",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    if r.status_code == 401:
        print("Authentication failed (401). Check your token.")
        sys.exit(1)

    if r.status_code != 200:
        print(f"Unexpected status {r.status_code}: {r.text[:300]}")
        sys.exit(1)

    data = r.json()
    user = data.get("user", {})

    print(f"Authenticated as : {user.get('name', '—')}")
    print(f"Email            : {user.get('email', '—')}")

    courses = data.get("courses", [])
    print(f"\nEnrolled in {len(courses)} course(s):\n")

    for entry in courses:
        c = entry.get("course", {})
        role = entry.get("role", "")
        print(f"  [{c.get('id')}]  {c.get('code', '')}  {c.get('name', '')}  ({role})")


if __name__ == "__main__":
    main()
