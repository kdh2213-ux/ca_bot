import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE = "https://arca.live"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TARGET_URL = os.environ.get("TARGET_URL", "").strip()
ARCA_COOKIE = os.environ.get("ARCA_COOKIE", "").strip()

HEADERS = {"User-Agent": UA, "Referer": BASE + "/"}
if ARCA_COOKIE:
    HEADERS["Cookie"] = ARCA_COOKIE

TG_API = "https://api.telegram.org/bot" + TELEGRAM_TOKEN


def log(msg):
    print(msg, flush=True)


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
        sys.exit("[fatal] secret missing: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / TARGET_URL")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", TELEGRAM_TOKEN):
        sys.exit("[fatal] TELEGRAM_TOKEN format wrong (must be 123456:ABC...)")
    if check_url(TARGET_URL) is None:
        sys.exit("[fatal] TARGET_URL format wrong: " + repr(TARGET_URL))


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
    r = requests.post(TG_API + "/" + method, timeout=60, **kwargs)
    data = r.json()
    if not data.get("ok"):
        log("[telegram] " + method + " failed: " + str(data))
    return data


def get_last_post_id():
    res = tg("getChat", data={"chat_id": TELEGRAM_CHAT_ID})
    if not res.get("ok"):
        sys.exit("[fatal] getChat failed - stop to protect LAST_ID")
    pinned = res.get("result", {}).get("pinned_message", {})
    m = re.search(r"LAST_ID:(\d+)", pinned.get("text", ""))
    return int(m.group(1)) if m else 0


def set_last_post_id(post_id):
    res = tg("sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "\U0001F916 LAST_ID:" + str(post_id),
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
    tg(method, data={"chat_id": TELEGRAM_CHAT_ID},
       files={field: (filename, data)})


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for row in soup.select("a.vrow.column:not(.notice)"):
        href = row.get("href", "")
        m = re.search(r"/b/[^/]+/(\d+)", href)
        if not m:
            continue
        title_el = row.select_one("span.title")
        title = title_el.get_text(strip=True) if title_el else "(no title)"
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
        raw = (tag.get("data-originalurl") or tag.get("data-src")
               or tag.get("src") or "")
        if not raw:
            continue
        url = normalize_src(raw).partition("?")[0]
        host = urlparse(url).hostname or ""
        if not host.endswith("namu.la"):
            continue
        if check_url(url) is None:
            log("[warn] bad media url skipped: " + repr(raw))
            continue
        if url not in urls:
            urls.append(url)
    return urls


def process_post(session, post):
    if check_url(post["url"]) is None:
        log("[warn] bad post url: " + repr(post["url"]))
        return
    res = session.get(post["url"], headers=HEADERS, timeout=15)
    if res.status_code != 200:
        log("[skip] post %d HTTP %d" % (post["id"], res.status_code))
        return
    media = extract_media(res.text)
    log("[info] post %d media %d" % (post["id"], len(media)))
    if not media:
        return
    tg("sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "\U0001F4CC " + post["title"] + "\n" + post["url"],
    })
    for idx, m_url in enumerate(media, start=1):
        try:
            r = session.get(m_url, headers=HEADERS, timeout=60)
            if r.status_code != 200:
                log("[warn] media HTTP %d: %s" % (r.status_code, m_url))
                continue
            ext = os.path.splitext(urlparse(m_url).path)[1].lower() or ".jpg"
            send_media(r.content, "%d_%03d%s" % (post["id"], idx, ext))
        except Exception as e:
            log("[warn] media failed %s: %r" % (m_url, e))
        time.sleep(1)


def main():
    check_secrets()
    last_id = get_last_post_id()
    session = requests.Session(impersonate="chrome")

    res = session.get(TARGET_URL, headers=HEADERS, timeout=15)
    if res.status_code != 200:
        sys.exit("[fatal] list page HTTP %d (cookie expired or blocked)"
                 % res.status_code)

    posts = parse_list(res.text)
    if not posts:
        log("[info] no posts parsed (selector or access problem)")
        return

    max_id = max(p["id"] for p in posts)
    if last_id == 0:
        set_last_post_id(max_id)
        log("[init] LAST_ID set: %d" % max_id)
        return

    new_posts = sorted((p for p in posts if p["id"] > last_id),
                       key=lambda x: x["id"])
    log("[info] LAST_ID %d, new posts %d" % (last_id, len(new_posts)))

    done = last_id
    for post in new_posts:
        try:
            process_post(session, post)
        except Exception as e:
            log("[error] post %d failed: %r -> retry next run" % (post["id"], e))
            break
        done = post["id"]
        time.sleep(2)

    if done != last_id:
        set_last_post_id(done)


if __name__ == "__main__":
    main()
