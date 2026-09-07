#!/usr/bin/env python3
"""
Minimal Ed API auth check.

Confirms your token works before running the full exporter.

Usage:
    python3 check_ed_token.py YOUR_TOKEN_HERE
"""

import sys
import requests

ED_HOST = "https://edstem.org/api"


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 check_ed_token.py YOUR_TOKEN_HERE")
        sys.exit(1)

    token = sys.argv[1].strip()

    r = requests.get(
        ED_HOST + "/user",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    print("Status code:", r.status_code)

    if r.status_code != 200:
        print("Body:", r.text[:500])
        sys.exit(1)

    data = r.json()
    print("Logged in as:", data["user"]["email"])

    courses = data.get("courses", [])
    print(f"\nEnrolled in {len(courses)} course(s):")

    for entry in courses:
        c = entry.get("course", {})
        role = entry.get("role", "")
        print(f"  - id={c.get('id')}  code={c.get('code')}  name={c.get('name')}  role={role}")


if __name__ == "__main__":
    main()