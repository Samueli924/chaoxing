# -*- coding: utf-8 -*-
import os.path
import pickle

from api.config import GlobalConst as gc


def save_cookies(_session):
    with open(gc.COOKIES_PATH, 'wb') as f:
        pickle.dump(_session.cookies, f)


def use_cookies():
    if os.path.exists(gc.COOKIES_PATH):
        with open(gc.COOKIES_PATH, 'rb') as f:
            _cookies = pickle.load(f)
        return _cookies