import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE = "https://arca.live"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TARGET_URL = os.environ.get("TARGET_URL", "").strip()
ARCA_COOKIE = os.environ.get("ARCA_COOKIE", "").strip()

HEADERS = {"User-Agent": UA, "Referer": BASE + "/"}
if ARCA_COOKIE:
    HEADERS["Cookie"] = ARCA_COOKIE

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def check_url(url):
    try:
        p = urlparse(url)
        _ = p.port
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        return url
    except ValueError:
        return None


def check_secrets():
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID and TARGET_URL):
        sys.exit("[fatal] 시크릿 누락: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / TARGET_URL 확인")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", TELEGRAM_TOKEN):
        sys.exit("[fatal] TELEGRAM_TOKEN 형식이 아님 (123456:ABC... 형태여야 함)")
    if check_url(TARGET_URL) is None:
        sys.exit(f"[fatal] TARGET_URL 형식이 이상함: {TARGET_URL!r}")


def normalize_src(src):
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith(("http://", "https://")):
        return src
    if re.match(r"^[\w.-]+\.namu\.la/", src):
        return "https://" + src
    return urljoin(BASE, src)


def tg(method, **kwargs):
    r = requests.post(f"{TG_API}/{method}", timeout=30, **kwargs)
    data = r.json()
    if not data.get("ok"):
        print(f"[telegram] {method} 실패: {data}", flush=True)
    return data


def get_last_post_id():
    res = tg("getChat", data={"chat_id": TELEGRAM_CHAT_ID})
    if not res.get("ok"):
        sys.exit("[fatal] getChat 실패 - 기준점 덮어쓰기 방지를 위해 중단")
    pinned = res.get("result", {}).get("pinned_message", {})
    m = re.search(r"LAST_ID:(\d+)", pinned.get("text", ""))
    return int(m.group(1)) if m else 0


def set_last_post_id(post_id):
    res = tg("sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🤖 기준점 기록 (LAST_ID:{post_id})",
        "disable_notification": True,
    })
    msg_id = res.get("result", {}).get("message_id")
    if msg_id:
        tg("pinChatMessage", data={
            "chat_id": TELEGRAM_CHAT_ID,
            "message_id": msg_id,
            "disable_notification": True,
        })


def send_media(data, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".mp4", ".mov", ".webm"):
        method, field = "sendVideo", "video"
    elif ext == ".gif":
        method, field = "sendAnimation", "animation"
    else:
        method, field = "sendPhoto", "photo"
    if method == "sendPhoto" and len(data) > 10 * 1024 * 1024:
        method, field = "sendDocument", "document"
    tg(method, data={"chat_id": TELEGRAM_CHAT_ID}, files={field: (filename, data)})


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for row in soup.select("a.vrow.column:not(.notice)"):
        href = row.get("href", "")
        m = re.search(r"/b/[^/]+/(\d+)", href)
        if not m:
            continue
        title_el = row.select_one("span.title")
        title = title_el.get_text(strip=True) if title_el else "제목없음"
        url = urljoin(BASE, href.partition("?")[0])
        posts.append({"id": int(m.group(1)), "url": url, "title": title})
    return posts


def extract_media(html):
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("div.article-content")
    if not content:
        return []
    urls = []
    for tag in content.select("img, video, video source"):
        raw = tag.get("data-originalurl") or tag.get("data-src") or tag.get("src") or ""
        if not raw:
            continue
        url = normalize_src(raw).partition("?")[0]
        host = urlparse(url).hostname or ""
        if not host.endswith("namu.la"):
            continue
        url = check_url(url)
        if url is None:
            print(f"[warn] 잘못된 미디어 URL 건너뜀: {raw!r}", flush=True)
            continue
        if url not in urls:
            urls.append(url)
    return urls


def process_post(session, post):
    url = check_url(post["url"])
    if url is None:
        print(f"[warn] 잘못된 글 URL: {post['url']!r}", flush=True)
        return
    res = session.get(url, headers=HEADERS, timeout=15)
    if res.status_code != 200:
        print(f"[skip] 글 {post['id']} HTTP {res.status_code}", flush=True)
        return
    media = extract_media(res.text)
    print(f"[info] 글 {post['id']} 미디어 {len(media)}개", flush=True)
    if not media:
        return
    tg("sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"📌 새 글: {post['title']}\n{post['url']}",
    })
    for idx, m_url in enumerate(media, start=1):
        try:
            r = session.get(m_url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"[warn] 이미지 HTTP
