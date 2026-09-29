#!/usr/bin/env python3

"""
Export all accessible posts from an Ed Discussion course.

Output:
    ed_<COURSE_ID>/
        all_posts.json
        all_posts.md
        threads/
            000001-....md
            000002-....md
            ...

Authentication:
    Set the ED_TOKEN environment variable.

Windows PowerShell:
    $env:ED_TOKEN="YOUR_TOKEN_HERE"
    python export_ed.py

Windows CMD:
    set ED_TOKEN=YOUR_TOKEN_HERE
    python export_ed.py

Linux/macOS:
    export ED_TOKEN="YOUR_TOKEN_HERE"
    python3 export_ed.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

import requests

# Load .env if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


# ============================================================
# Configuration
# ============================================================

# Per Ed's own API docs: "Your current API server is
# https://edstem.org/api" -- NOT a per-region subdomain.
BASE_URL = "https://edstem.org/api"

# Threads-per-request when listing (API max is 100).
LIST_PAGE_SIZE = 100

REQUEST_DELAY = 0.15
REQUEST_TIMEOUT = 30


# ============================================================
# HTTP client
# ============================================================

class EdClient:
    def __init__(self, token: str):
        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "EdDiscussionExporter/1.0",
        })

    def get(self, endpoint: str, **kwargs) -> Any:
        """
        GET an Ed API endpoint (endpoint is relative to BASE_URL,
        e.g. "/user", "/courses/123/threads?limit=100&offset=0").
        """

        url = BASE_URL + endpoint

        for attempt in range(5):
            try:
                response = self.session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    **kwargs,
                )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")

                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except ValueError:
                            wait = 2 ** attempt
                    else:
                        wait = 2 ** attempt

                    print(f"Rate limited. Waiting {wait:.1f}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue

                if response.status_code in (500, 502, 503, 504):
                    wait = 2 ** attempt

                    print(
                        f"Server returned {response.status_code}. Retrying in {wait}s...",
                        file=sys.stderr,
                    )

                    time.sleep(wait)
                    continue

                if response.status_code == 401:
                    raise RuntimeError(
                        "Authentication failed (401).\nCheck that your ED_TOKEN is correct."
                    )

                if response.status_code == 403:
                    raise RuntimeError(
                        f"Permission denied (403): {endpoint}\n"
                        "Your account does not have access to this resource."
                    )

                if response.status_code == 404:
                    raise RuntimeError(f"Not found (404): {endpoint}")

                response.raise_for_status()

                time.sleep(REQUEST_DELAY)

                return response.json()

            except requests.RequestException as exc:
                if attempt == 4:
                    raise RuntimeError(
                        f"Request failed after several attempts:\n{url}\n{exc}"
                    ) from exc

                wait = 2 ** attempt
                print(f"Network error. Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)

        raise RuntimeError("Unexpected request failure.")


# ============================================================
# Helpers
# ============================================================

def get_token() -> str:
    token = os.environ.get("ED_TOKEN", "").strip()

    if not token:
        import getpass
        token = getpass.getpass("Ed API token: ").strip()

    if not token:
        print("No token provided. Exiting.", file=sys.stderr)
        sys.exit(1)

    return token


def safe_filename(name: str, max_length: int = 100) -> str:
    name = str(name or "untitled")
    name = re.sub(r"<[^>]+>", "", name)
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r"\s+", " ", name).strip()

    if not name:
        name = "untitled"

    return name[:max_length]


def first_value(obj: dict, *keys: str, default=None):
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]

    return default


def extract_items(data: Any) -> list:
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in ("threads", "results", "items", "data"):
        value = data.get(key)

        if isinstance(value, list):
            return value

    return []


# ============================================================
# Ed's XML document format -> Markdown
#
# Ed post bodies (the "content" field) are written in a documented
# XML dialect: <document version="2.0"><paragraph>...</paragraph></document>
# with tags like <heading>, <bold>, <italic>, <link href="">, <list>,
# <list-item>, <callout type="">, <code>, <pre>, <snippet language="">,
# <spoiler>, <image src="">, <file url="">.
# ============================================================

def _render_inline(el: ET.Element) -> str:
    parts = []

    if el.text:
        parts.append(el.text)

    for child in el:
        parts.append(_render_element(child))

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _render_element(el: ET.Element) -> str:
    tag = el.tag

    if tag == "bold":
        return f"**{_render_inline(el)}**"

    if tag == "italic":
        return f"*{_render_inline(el)}*"

    if tag == "underline":
        return f"_{_render_inline(el)}_"

    if tag == "math":
        return f"${_render_inline(el)}$"

    if tag == "link":
        href = el.get("href", "")
        return f"[{_render_inline(el)}]({href})"

    if tag == "code":
        return f"`{_render_inline(el)}`"

    if tag == "paragraph":
        return _render_inline(el).strip() + "\n\n"

    if tag == "heading":
        try:
            level = max(1, min(6, int(el.get("level", "1"))))
        except (TypeError, ValueError):
            level = 1

        return "#" * level + " " + _render_inline(el).strip() + "\n\n"

    if tag == "list":
        style = el.get("style", "bullet")
        items = []

        for i, item in enumerate(el.findall("list-item"), start=1):
            prefix = "- " if style != "number" else f"{i}. "
            items.append(prefix + _render_inline(item).strip())

        return "\n".join(items) + "\n\n"

    if tag == "list-item":
        return _render_inline(el)

    if tag == "callout":
        ctype = el.get("type", "info")
        return f"> [!{ctype}] {_render_inline(el).strip()}\n\n"

    if tag == "pre":
        return f"```\n{_render_inline(el).strip()}\n```\n\n"

    if tag == "snippet":
        lang = el.get("language", "")
        return f"```{lang}\n{_render_inline(el).strip()}\n```\n\n"

    if tag == "spoiler":
        return f"||{_render_inline(el).strip()}||"

    if tag == "figure":
        return _render_inline(el) + "\n\n"

    if tag == "image":
        src = el.get("src", "")
        return f"![image]({src})\n\n"

    if tag == "file":
        url = el.get("url", "")
        return f"[file]({url})\n\n"

    if tag == "document":
        return _render_inline(el)

    # Unknown tag: render its inline content, keeping any URL it carries
    # (lesson slides use tags such as video / iframe / web-snippet).
    inner = _render_inline(el)

    for attr in ("url", "src", "href"):
        target = el.get(attr)
        if target:
            return f"[{inner.strip() or tag}]({target})\n\n"

    return inner


def html_to_markdown(html: Any) -> str:
    """
    Fallback plain-HTML stripper, used only if a field isn't
    valid Ed XML (e.g. legacy HTML content).
    """

    if html is None:
        return ""

    text = str(html)

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</div\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    for old, new in {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<",
        "&gt;": ">", "&quot;": '"', "&#39;": "'",
    }.items():
        text = text.replace(old, new)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def ed_xml_to_markdown(xml_string: Any) -> str:
    if not xml_string:
        return ""

    text = str(xml_string).strip()

    if not text:
        return ""

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # Not valid XML -- fall back to naive tag stripping.
        return html_to_markdown(text)

    md = _render_element(root)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    return md


def get_author(obj: dict) -> str:
    author = first_value(obj, "author", "user", "creator", "owner", default=None)

    if isinstance(author, dict):
        return str(
            first_value(
                author, "name", "display_name", "username", "email", "id",
                default="Unknown",
            )
        )

    if author is not None:
        return str(author)

    if obj.get("is_anonymous"):
        return "Anonymous"

    return "Unknown"


def get_body(obj: dict) -> str:
    """
    Ed's documented Thread/Comment schema has:
      - "content": the raw XML ContentString
      - "document": a "rendered version" of content

    Prefer "content" since its tag dialect is documented; fall back
    to "document", then generic HTML stripping.
    """

    content = obj.get("content")

    if content:
        rendered = ed_xml_to_markdown(content)
        if rendered:
            return rendered

    document = obj.get("document")

    if document:
        rendered = ed_xml_to_markdown(document)
        if rendered:
            return rendered

        return html_to_markdown(document)

    return ""


def get_children(obj: dict) -> list[dict]:
    """
    Per Ed's schema, a Thread has "answers" (Comment[], type=="answer")
    and "comments" (Comment[], type=="comment"). A Comment itself has
    "comments" for nested replies.
    """

    children = []

    answers = obj.get("answers")
    if isinstance(answers, list):
        children.extend(answers)

    comments = obj.get("comments")
    if isinstance(comments, list):
        children.extend(comments)

    return children


def comment_to_markdown(comment: dict, level: int = 0) -> str:
    author = get_author(comment)

    kind = comment.get("type", "comment")
    label = "Answer" if kind == "answer" else "Comment"

    if comment.get("is_endorsed"):
        label += " (endorsed)"

    created = first_value(comment, "created_at", "created", "date", "timestamp", default="")

    body = get_body(comment)

    indent = "  " * level

    result = [f"{indent}### {label} by {author}"]

    if created:
        result.append(f"{indent}*{created}*")

    result.append("")

    if body:
        for line in body.splitlines():
            result.append(f"{indent}{line}")

    result.append("")

    for child in get_children(comment):
        result.append(comment_to_markdown(child, level + 1))

    return "\n".join(result)


def thread_to_markdown(thread: dict, number: int) -> str:
    title = first_value(thread, "title", "subject", default=f"Thread {number}")
    author = get_author(thread)
    created = first_value(thread, "created_at", "created", "date", "timestamp", default="")
    thread_id = first_value(thread, "id", "thread_id", default="")
    category = first_value(thread, "category", "type", "thread_type", default="")

    body = get_body(thread)

    lines = [f"# {title}", "", f"- **Thread ID:** {thread_id}", f"- **Author:** {author}"]

    if created:
        lines.append(f"- **Created:** {created}")

    if category:
        lines.append(f"- **Category:** {category}")

    lines.extend(["", "---", ""])

    if body:
        lines.append(body)
        lines.append("")

    children = get_children(thread)

    if children:
        lines.extend(["---", "", "# Replies", ""])
        for child in children:
            lines.append(comment_to_markdown(child))

    return "\n".join(lines).strip() + "\n"


# ============================================================
# Thread discovery (paginated via limit/offset, per Ed's API)
# ============================================================

def get_all_threads(client: EdClient, course_id: int) -> list[dict]:
    print(f"\nGetting threads for course {course_id}...")

    all_threads: list[dict] = []
    offset = 0

    while True:
        endpoint = (
            f"/courses/{course_id}/threads"
            f"?limit={LIST_PAGE_SIZE}&offset={offset}&sort=new"
        )

        data = client.get(endpoint)
        threads = extract_items(data)

        if not threads:
            break

        all_threads.extend(threads)

        print(f"  fetched {len(all_threads)} threads so far...")

        if len(threads) < LIST_PAGE_SIZE:
            break

        offset += LIST_PAGE_SIZE

    unique = {}
    for thread in all_threads:
        thread_id = first_value(thread, "id", "thread_id")
        if thread_id is not None:
            unique[str(thread_id)] = thread

    result = list(unique.values())

    print(f"Found {len(result)} unique threads.")

    return result


def get_thread_details(client: EdClient, thread: dict) -> dict:
    """
    GET /threads/<id> returns {"thread": Thread, "users": [...]} --
    unwrap to the actual Thread dict.
    """

    thread_id = first_value(thread, "id", "thread_id")

    if thread_id is None:
        return thread

    endpoint = f"/threads/{thread_id}"

    try:
        data = client.get(endpoint)

        if isinstance(data, dict) and isinstance(data.get("thread"), dict):
            return data["thread"]

        if isinstance(data, dict):
            return data

        return thread

    except Exception as exc:
        print(f"  Warning: couldn't fetch thread {thread_id}: {exc}", file=sys.stderr)
        return thread


# ============================================================
# Export
# ============================================================

def save_json(threads: list[dict], output_dir: Path, course_id: int):
    path = output_dir / "all_posts.json"

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "course_id": course_id,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "thread_count": len(threads),
                "threads": threads,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Saved JSON: {path}")


def save_markdown(threads: list[dict], output_dir: Path, course_id: int):
    path = output_dir / "all_posts.md"

    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Ed Discussion Course {course_id}\n\n")
        f.write(f"Total threads: **{len(threads)}**\n\n")
        f.write("---\n\n")

        for number, thread in enumerate(threads, start=1):
            title = first_value(thread, "title", "subject", default=f"Thread {number}")
            f.write(f"## {number}. {title}\n\n")

            thread_id = first_value(thread, "id", "thread_id", default="")
            author = get_author(thread)
            created = first_value(thread, "created_at", "created", "date", "timestamp", default="")

            f.write(f"- **Thread ID:** {thread_id}\n")
            f.write(f"- **Author:** {author}\n")

            if created:
                f.write(f"- **Created:** {created}\n")

            f.write("\n")

            body = get_body(thread)

            if body:
                f.write(body)
                f.write("\n\n")

            children = get_children(thread)

            if children:
                f.write(f"### Replies ({len(children)})\n\n")
                for child in children:
                    f.write(comment_to_markdown(child))

            f.write("\n---\n\n")

    print(f"Saved Markdown: {path}")


def save_individual_threads(threads: list[dict], output_dir: Path):
    threads_dir = output_dir / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)

    for number, thread in enumerate(threads, start=1):
        title = first_value(thread, "title", "subject", default=f"Thread {number}")
        filename = f"{number:06d}-{safe_filename(title)}.md"
        path = threads_dir / filename
        path.write_text(thread_to_markdown(thread, number), encoding="utf-8")

    print(f"Saved {len(threads)} individual Markdown files.")


# ============================================================
# Ed Lessons
#
# Endpoints (reverse-engineered, Ed's API is beta):
#   GET /courses/<id>/lessons   -> {"lessons": [...], "modules": [...]}
#   GET /lessons/<id>           -> {"lesson": {...}}
#   GET /lessons/<id>/slides    -> {"slides": [...]}
#   GET /lessons/slides/<id>    -> {"slide": {...}}
#
# Lesson results / activity endpoints return 403 for non-staff
# accounts, so they are not requested.
# ============================================================

def get_lessons_index(client: EdClient, course_id: int) -> tuple[list[dict], list[dict]]:
    print(f"\nGetting lessons for course {course_id}...")

    data = client.get(f"/courses/{course_id}/lessons")

    lessons = data.get("lessons", []) if isinstance(data, dict) else []
    modules = data.get("modules", []) if isinstance(data, dict) else []

    if not isinstance(lessons, list):
        lessons = []

    if not isinstance(modules, list):
        modules = []

    print(f"Found {len(lessons)} lessons in {len(modules)} modules.")

    return lessons, modules


def _asset_extension(url: str, content_type: str) -> str:
    """Choose a useful file extension from the URL or HTTP Content-Type."""
    path_ext = Path(urlparse(url).path).suffix.lower()
    allowed = {".html", ".htm", ".pdf", ".txt", ".xml", ".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm"}
    if path_ext in allowed:
        return ".html" if path_ext == ".htm" else path_ext
    mime = content_type.split(";", 1)[0].strip().lower()
    mapping = {
        "text/html": ".html", "application/pdf": ".pdf", "text/plain": ".txt",
        "application/xml": ".xml", "text/xml": ".xml", "application/javascript": ".js",
        "text/javascript": ".js", "application/json": ".json", "text/css": ".css",
        "image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg",
        "image/gif": ".gif", "image/webp": ".webp", "video/mp4": ".mp4",
        "video/webm": ".webm",
    }
    return mapping.get(mime, mimetypes.guess_extension(mime) or ".bin")


def download_slide_asset(client: EdClient, slide: dict, asset_dir: Path) -> None:
    """Download a slide's linked resource without assuming it is HTML.

    Ed often exposes only slide metadata and a URL. The URL may point to an
    HTML/JS lesson, PDF, plain text, XML, or another resource. Save bytes as-is
    and annotate the slide with a path relative to the lessons output folder.
    """
    url = slide.get("url")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return
    asset_dir.mkdir(parents=True, exist_ok=True)
    try:
        response = client.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        ext = _asset_extension(response.url or url, content_type)
        slide_id = slide.get("id", "slide")
        filename = f"{slide_id}{ext}"
        path = asset_dir / filename
        path.write_bytes(response.content)
        slide["downloaded_asset"] = path.name
        slide["downloaded_content_type"] = content_type
        slide["downloaded_bytes"] = len(response.content)
    except Exception as exc:
        slide["download_error"] = str(exc)
        print(f"  Warning: couldn't download slide URL {url}: {exc}", file=sys.stderr)


def get_lesson_full(client: EdClient, lesson: dict) -> dict:
    """Fetch lesson detail + every slide's full content."""

    lesson_id = lesson.get("id")
    detail = dict(lesson)

    try:
        data = client.get(f"/lessons/{lesson_id}")
        if isinstance(data, dict) and isinstance(data.get("lesson"), dict):
            detail.update(data["lesson"])
    except Exception as exc:
        print(f"  Warning: couldn't fetch lesson {lesson_id}: {exc}", file=sys.stderr)

    slides: list[dict] = []

    try:
        data = client.get(f"/lessons/{lesson_id}/slides")
        if isinstance(data, dict) and isinstance(data.get("slides"), list):
            slides = data["slides"]
        elif isinstance(data, list):
            slides = data
    except Exception as exc:
        print(f"  Warning: couldn't fetch slides for lesson {lesson_id}: {exc}", file=sys.stderr)

    if not slides and isinstance(detail.get("slides"), list):
        slides = detail["slides"]

    full_slides = []

    for slide in slides:
        slide_id = slide.get("id") if isinstance(slide, dict) else None
        merged = dict(slide) if isinstance(slide, dict) else {}

        if slide_id is not None:
            try:
                data = client.get(f"/lessons/slides/{slide_id}")
                if isinstance(data, dict) and isinstance(data.get("slide"), dict):
                    merged.update(data["slide"])
            except Exception as exc:
                print(f"  Warning: couldn't fetch slide {slide_id}: {exc}", file=sys.stderr)

        full_slides.append(merged)

    detail["slides"] = full_slides

    return detail


def slide_to_markdown(slide: dict, number: int) -> str:
    title = first_value(slide, "title", "name", default=f"Slide {number}")
    slide_type = slide.get("type", "")

    lines = [f"## {number}. {title}", ""]

    meta = []
    if slide_type:
        meta.append(f"- **Type:** {slide_type}")
    if slide.get("id") is not None:
        meta.append(f"- **Slide ID:** {slide['id']}")

    if meta:
        lines.extend(meta)
        lines.append("")

    slide_url = slide.get("url")
    if slide_url:
        lines.append(f"- **Source URL:** <{slide_url}>")
        lines.append("")

    if slide.get("downloaded_asset"):
        asset_path = f"{slide.get('_asset_prefix', '../assets')}/{slide['downloaded_asset']}"
        lines.append(f"- **Downloaded resource:** [{slide['downloaded_asset']}]({asset_path})")
        lines.append(f"- **Content type:** {slide.get('downloaded_content_type', 'unknown')}")
        lines.append("")
    elif slide.get("download_error"):
        lines.append(f"- **Download warning:** {slide['download_error']}")
        lines.append("")

    body = get_body(slide)

    if body:
        lines.append(body)
        lines.append("")

    # Quiz / question data: structure isn't documented, so keep it lossless.
    for key in ("questions", "quiz_questions", "question"):
        value = slide.get(key)

        if value:
            lines.append(f"**{key}:**")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(value, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def lesson_to_markdown(lesson: dict, module_name: str, asset_prefix: str = "assets") -> str:
    title = first_value(lesson, "title", "name", default=f"Lesson {lesson.get('id', '')}")

    lines = [f"# {title}", "", f"- **Lesson ID:** {lesson.get('id', '')}"]

    if module_name:
        lines.append(f"- **Module:** {module_name}")

    for label, key in (("Status", "state"), ("Type", "type"), ("Created", "created_at")):
        if lesson.get(key):
            lines.append(f"- **{label}:** {lesson[key]}")

    slides = lesson.get("slides", [])
    lines.extend([f"- **Slides:** {len(slides)}", "", "---", ""])

    for number, slide in enumerate(slides, start=1):
        slide["_asset_prefix"] = asset_prefix
        lines.append(slide_to_markdown(slide, number))
        lines.append("---")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def export_lessons(client: EdClient, course_id: int, output_dir: Path) -> bool:
    lessons, modules = get_lessons_index(client, course_id)

    if not lessons:
        print("\nNo lessons were returned.")
        return False

    module_names = {m.get("id"): first_value(m, "name", "title", default="") for m in modules}
    module_order = {m.get("id"): i for i, m in enumerate(modules, start=1)}

    print(f"\nDownloading full content for {len(lessons)} lessons...")

    full_lessons = []

    for index, lesson in enumerate(lessons, start=1):
        title = first_value(lesson, "title", "name", default="Untitled")
        print(f"[{index}/{len(lessons)}] {lesson.get('id')}: {title}")
        full_lessons.append(get_lesson_full(client, lesson))

    lessons_dir = output_dir / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    # The API often returns slide metadata and a URL, not the actual lesson.
    # Download the linked resource and preserve its original format.
    print("\nDownloading linked lesson resources (HTML/JS, PDF, text, XML, etc.)...")
    for lesson in full_lessons:
        asset_dir = lessons_dir / "assets" / str(lesson.get("id", "unknown"))
        for slide in lesson.get("slides", []):
            download_slide_asset(client, slide, asset_dir)
            if slide.get("downloaded_asset"):
                slide["downloaded_asset"] = f"{lesson.get('id', 'unknown')}/{slide['downloaded_asset']}"

    print("\nSaving lesson files...")

    # Raw JSON
    json_path = lessons_dir / "all_lessons.json"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "course_id": course_id,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "lesson_count": len(full_lessons),
                "modules": modules,
                "lessons": full_lessons,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Saved JSON: {json_path}")

    # One Markdown file per lesson, grouped by module; plus a combined file
    counters: dict = {}
    combined = [f"# Ed Lessons - Course {course_id}\n", f"Total lessons: **{len(full_lessons)}**\n", "---\n"]

    for lesson in full_lessons:
        module_id = lesson.get("module_id")
        module_name = module_names.get(module_id, "")

        if module_id in module_order:
            folder_name = f"{module_order[module_id]:02d}-{safe_filename(module_name or 'module')}"
        else:
            folder_name = "00-no-module"

        folder = lessons_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        counters[folder_name] = counters.get(folder_name, 0) + 1
        title = first_value(lesson, "title", "name", default="Untitled")
        filename = f"{counters[folder_name]:03d}-{safe_filename(title)}.md"

        markdown = lesson_to_markdown(lesson, module_name, asset_prefix="../assets")
        (folder / filename).write_text(markdown, encoding="utf-8")

        combined_markdown = lesson_to_markdown(lesson, module_name, asset_prefix="assets")
        combined.append(combined_markdown)
        combined.append("\n---\n")

    combined_path = lessons_dir / "all_lessons.md"
    combined_path.write_text("\n".join(combined), encoding="utf-8")

    print(f"Saved Markdown: {combined_path}")
    print(f"Saved {len(full_lessons)} individual lesson files.")

    return True


# ============================================================
# Threads export (wraps the functions above)
# ============================================================

def export_threads(client: EdClient, course_id: int, output_dir: Path) -> bool:
    threads = get_all_threads(client, course_id)

    if not threads:
        print("\nNo threads were returned.")
        return False

    print(f"\nDownloading full content for {len(threads)} threads...")

    full_threads = []

    for index, thread in enumerate(threads, start=1):
        thread_id = first_value(thread, "id", "thread_id", default="?")
        title = first_value(thread, "title", "subject", default="Untitled")

        print(f"[{index}/{len(threads)}] {thread_id}: {title}")

        full_threads.append(get_thread_details(client, thread))

    print("\nSaving thread files...")

    save_json(full_threads, output_dir, course_id)
    save_markdown(full_threads, output_dir, course_id)
    save_individual_threads(full_threads, output_dir)

    return True


# ============================================================
# Main
# ============================================================

def prompt_inputs() -> tuple[int, str]:
    print("=" * 60)
    print("Ed Discussion Exporter")
    print("=" * 60)
    print()

    while True:
        course_id_str = input("Course ID: ").strip()
        if course_id_str.isdigit():
            course_id = int(course_id_str)
            break
        print("  Course ID must be a number. Please try again.")

    course_name = input("Course name (used as output folder name): ").strip()
    if not course_name:
        course_name = str(course_id)

    return course_id, course_name


def prompt_export_choice() -> tuple[bool, bool]:
    """Ask what to export. Returns (want_threads, want_lessons)."""

    print()
    print("What do you want to export?")
    print("  1) Threads  (discussion posts)")
    print("  2) Lessons  (Ed Lessons: modules, slides, quizzes)")
    print("  3) Both")
    print()

    choices = {
        "1": (True, False), "threads": (True, False), "thread": (True, False),
        "2": (False, True), "lessons": (False, True), "lesson": (False, True),
        "3": (True, True), "both": (True, True),
    }

    while True:
        answer = input("Enter 1, 2 or 3: ").strip().lower()

        if answer in choices:
            return choices[answer]

        print("  Please enter 1 (threads), 2 (lessons) or 3 (both).")


def main():
    course_id, course_name = prompt_inputs()
    want_threads, want_lessons = prompt_export_choice()

    output_dir = Path("data_obtained") / course_name

    print()
    print(f"Course ID   : {course_id}")
    print(f"Exporting   : {'threads' if want_threads and not want_lessons else 'lessons' if want_lessons and not want_threads else 'threads + lessons'}")
    print(f"Output dir  : {output_dir.resolve()}")
    print()

    token = get_token()

    output_dir.mkdir(parents=True, exist_ok=True)

    client = EdClient(token)

    print("Checking authentication...")

    try:
        user = client.get("/user")
        print("Authentication successful.")

        if isinstance(user, dict):
            u = user.get("user", {})
            name = first_value(u, "name", "display_name", "username", default=None)
            if name:
                print(f"Logged in as: {name}")

    except Exception as exc:
        print(f"\nCould not authenticate:\n{exc}", file=sys.stderr)
        sys.exit(1)

    exported = []
    failed = []

    if want_threads:
        try:
            if export_threads(client, course_id, output_dir):
                exported.append("threads")
        except Exception as exc:
            print(f"\nFailed to export threads:\n{exc}", file=sys.stderr)
            failed.append("threads")

    if want_lessons:
        try:
            if export_lessons(client, course_id, output_dir):
                exported.append("lessons")
        except Exception as exc:
            print(f"\nFailed to export lessons:\n{exc}", file=sys.stderr)
            failed.append("lessons")

    print()
    print("=" * 60)
    print("EXPORT COMPLETE" if exported and not failed else "EXPORT FINISHED WITH ISSUES")
    print("=" * 60)
    print()
    print(f"Output directory: {output_dir.resolve()}")

    if "threads" in exported:
        print(f"  Threads : {output_dir / 'all_posts.json'}, all_posts.md, threads/")

    if "lessons" in exported:
        print(f"  Lessons : {output_dir / 'lessons'}/ (all_lessons.json, all_lessons.md, <module>/*.md)")

    if failed:
        print(f"\nFailed: {', '.join(failed)}")

    if not exported:
        sys.exit(1)


if __name__ == "__main__":
    main()