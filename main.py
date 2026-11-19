import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE = "https://arca.live"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# 시크릿 앞뒤 공백/줄바꿈 제거
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TARGET_URL = os.environ.get("TARGET_URL", "").strip()
ARCA_COOKIE = os.environ.get("ARCA_COOKIE", "").strip()

if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID and TARGET_URL):
    sys.exit("[fatal] 시크릿 누락: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / TARGET_URL 확인")
if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", TELEGRAM_TOKEN):
    sys.exit("[fatal] TELEGRAM_TOKEN 형식이 아님 (123456:ABC... 형태여야 함)")
try:
    _p = urlparse(TARGET_URL)
    _p.port  # 포트 자리가 숫자가 아니면 여기서 ValueError
    if _p.scheme not in ("http", "https") or not _p.hostname:
        raise
