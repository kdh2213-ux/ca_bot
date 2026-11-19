import os
import re
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from curl_cffi import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"].strip().replace(" ", "")
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()
TARGET_URL = os.environ["TARGET_URL"].strip()
ARCA_COOKIE = os.environ.get("ARCA_COOKIE", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://arca.live",
}
if ARCA_COOKIE:
    HEADERS["Cookie"] = ARCA_COOKIE

TG_API = f"https://telegram.org{TELEGRAM_TOKEN}"


def get_last_post_id():
    res = requests.post(f"{TG_API}/getChat", data={"chat_id": TELEGRAM_CHAT_ID}).json()
    pinned = res.get("result", {}).get("pinned_message", {})
    text = pinned.get("text", "")
    match = re.search(r"LAST_ID:(\d+)", text)
    return int(match.group(1)) if match else 0


def set_last_post_id(post_id):
    res = requests.post(
        f"{TG_API}/sendMessage",
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🤖 기준점 기록 (LAST_ID:{post_id})",
            "disable_notification": True,
        },
    ).json()
    msg_id = res.get("result", {}).get("message_id")
    if msg_id:
        requests.post(
            f"{TG_API}/pinChatMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "message_id": msg_id, "disable_notification": True},
        )


def send_telegram_text(text):
    requests.post(f"{TG_API}/sendMessage", data={"chat_id": TELEGRAM_CHAT_ID, "text": text})


def send_telegram_media(file_bytes, filename):
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext in [".mp4", ".mov", ".webm"]:
        method, field = "sendVideo", "video"
    elif ext == ".gif":
        method, field = "sendAnimation", "animation"
    else:
        method, field = "sendPhoto", "photo"

    files = {field: (filename, file_bytes)}
    requests.post(f"{TG_API}/{method}", data={"chat_id": TELEGRAM_CHAT_ID}, files=files, timeout=30)


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
            clean_src, _, _ = src.partition("?")
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
            _, ext = os.path.splitext(m_url)
            if not ext:
                ext = ".jpg"
            send_telegram_media(m_res.content, f"{post_id}_{idx:03d}{ext}")
        time.sleep(1)


def main():
    print(f"타겟 URL 확인: [{TARGET_URL}]")
    last_id = get_last_post_id()
    session = requests.Session(impersonate="chrome")

    res = session.get(TARGET_URL, headers=HEADERS, timeout=15)
    print(f"상태 코드: {res.status_code}, 기존 기준 ID: {last_id}")
    if res.status_code != 200:
        return

    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("a.vrow.column:not(.notice)")

    posts = []
    for row in rows:
        href = row.get("href", "")
        match = re.search(r"/b/[^/]+/(\d+)", href)
        if not match:
            continue
        post_id = int(match.group(1))
        title_el = row.select_one("span.title")
        title = title_el.get_text(strip=True) if title_el else "제목없음"
        clean_href, _, _ = href.partition("?")
        full_url = urljoin("https://arca.live", clean_href)
        posts.append({"id": post_id, "url": full_url, "title": title})

    if not posts:
        print("게시글이 0개입니다.")
        return

    max_id = max(item["id"] for item in posts)

    if last_id == 0:
        set_last_post_id(max_id)
        print(f"최초 기준점 등록 완료: {max_id}")
        return

    new_posts = [item for item in posts if item["id"] > last_id]
    if new_posts:
        for item in sorted(new_posts, key=lambda x: x["id"]):
            process_post(session, item["url"], item["id"], item["title"])
            time.sleep(2)
        set_last_post_id(max_id)


if __name__ == "__main__":
    main()
