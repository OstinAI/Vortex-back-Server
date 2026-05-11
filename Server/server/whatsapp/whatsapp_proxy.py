# -*- coding: utf-8 -*-
import os
import requests

WA_SERVER_URL = os.getenv("WA_SERVER_URL", "http://127.0.0.1:5001")


def _auth_headers(auth_header: str):
    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def wa_get(path: str, auth_header: str = "", params=None, timeout=120):
    url = f"{WA_SERVER_URL}{path}"
    return requests.get(
        url,
        headers=_auth_headers(auth_header),
        params=params,
        timeout=timeout
    )


def wa_post(path: str, auth_header: str = "", json_data=None, timeout=120):
    url = f"{WA_SERVER_URL}{path}"
    return requests.post(
        url,
        headers=_auth_headers(auth_header),
        json=json_data,
        timeout=timeout
    )