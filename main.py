import os
import re
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from curl_cffi import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TARGET_URL = os.environ["TARGET_URL"]
ARCA_COOKIE = os.environ.get("ARCA_COOKIE", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://arca.live",
}
if ARCA_COOKIE:
    HEADERS["Cookie"] = ARCA_COOKIE

HISTORY_FILE = "saved_posts.txt"


def load_saved_ids():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_post_id(post_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


def send_telegram_text(text):
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})


def send_telegram_media(file_bytes, filename):
    ext = os.path.splitext(filename).lower()
    if ext in [".mp4", ".mov", ".webm"]:
        method, field = "sendVideo", "video"
    elif ext == ".gif":
        method, field = "sendAnimation", "animation"
    else:
        method, field = "sendPhoto", "photo"

    url = f"https://telegram.org{TELEGRAM_TOKEN}/{method}"
    files = {field: (filename, file_bytes)}
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID}, files=files, timeout=30)


def process_post(session, post_url, post_id, title):
    res = session.get(post_url, headers=HEADERS, timeout=15)
    if res.status_code != 200:
        return

    soup = BeautifulSoup(res.text, "html.parser")
    content = soup.select_one("div.article-content")
    if not content:
        return

    media_urls = []
    for tag in content.select("img, video, video source"):
        src = tag.get("data-originalurl") or tag.get("data-src") or tag.get("src")
        if src and "namu.la" in src:
            clean_src = src.split("?")
            if clean_src not in media_urls:
                media_urls.append(clean_src)

    if not media_urls:
        return

    send_telegram_text(f"📌 새 글: {title}\n{post_url}")

    for idx, m_url in enumerate(media_urls, start=1):
        if m_url.startswith("//"):
            m_url = "https:" + m_url
        m_res = session.get(m_url, headers=HEADERS, timeout=20)
        if m_res.status_code == 200:
            ext = os.path.splitext(m_url) or ".jpg"
            send_telegram_media(m_res.content, f"{post_id}_{idx:03d}{ext}")
        time.sleep(1)


def main():
    saved_ids = load_saved_ids()
    is_first_run = len(saved_ids) == 0
    session = requests.Session(impersonate="chrome")

    res = session.get(TARGET_URL, headers=HEADERS, timeout=15)
    if res.status_code != 200:
        return

    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("a.vrow.column:not(.notice)")

    new_posts = []
    for row in rows:
        href = row.get("href", "")
        match = re.search(r"/b/[^/]+/(\d+)", href)
        if not match:
            continue
        post_id = match.group(1)
        title_el = row.select_one("span.title")
        title = title_el.get_text(strip=True) if title_el else "제목없음"
        full_url = urljoin("https://arca.live", href.split("?"))

        if is_first_run:
            save_post_id(post_id)
        elif post_id not in saved_ids:
            new_posts.append((post_id, full_url, title))

    if not is_first_run:
        for post_id, full_url, title in reversed(new_posts):
            process_post(session, full_url, post_id, title)
            save_post_id(post_id)
            time.sleep(2)


if __name__ == "__main__":
