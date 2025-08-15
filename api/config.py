# -*- coding: utf-8 -*-
class GlobalConst:
    AES_KEY = "u2oh6Vu^HWe4_AES"

    COOKIES_PATH = "cookies.txt"

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    SEC_CH_UA = '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"'

    HEADERS = {
        "User-Agent": USER_AGENT,
        "Sec-Ch-Ua": SEC_CH_UA,
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0"
    }
    
    VERSION = "2025-0725-1842"
    VIDEO_HEADERS = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://mooc1.chaoxing.com/ananas/modules/video/index.html?v={VERSION}"
    }
    AUDIO_HEADERS = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v={VERSION}"
    }

    DELAY = 3
