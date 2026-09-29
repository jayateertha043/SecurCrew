"""Tests for linkedin.py and linkedin_webhook.py posting clients."""

from __future__ import annotations

import pytest
import requests

from linkedin import LinkedInClient, LinkedInError, RetryableError, _short
from linkedin_webhook import WebhookClient


class _Resp:
    def __init__(self, code, text=""):
        self.status_code = code
        self.text = text


def _mk_client(monkeypatch, responder):
    c = LinkedInClient("tok", "urn:li:organization:123")
    monkeypatch.setattr(c._session, "post", responder)
    return c


def test_linkedin_client_requires_creds():
    with pytest.raises(ValueError):
        LinkedInClient("", "urn")
    with pytest.raises(ValueError):
        LinkedInClient("tok", "")


def test_linkedin_post_success(monkeypatch):
    def ok(url, json, timeout):
        assert json["author"] == "urn:li:organization:123"
        assert json["commentary"] == "hello"
        assert json["visibility"] == "PUBLIC"
        return _Resp(201)
    c = _mk_client(monkeypatch, ok)
    c.post("hello")  # no exception


def test_linkedin_429_is_retryable(monkeypatch):
    c = _mk_client(monkeypatch, lambda url, **kw: _Resp(429, "slow down"))
    with pytest.raises(RetryableError):
        c.post("x")


def test_linkedin_5xx_is_retryable(monkeypatch):
    c = _mk_client(monkeypatch, lambda url, **kw: _Resp(503, "bad gateway"))
    with pytest.raises(RetryableError):
        c.post("x")


def test_linkedin_4xx_is_linkedin_error(monkeypatch):
    c = _mk_client(monkeypatch, lambda url, **kw: _Resp(403, "forbidden"))
    with pytest.raises(LinkedInError):
        c.post("x")


def test_linkedin_network_failure_is_retryable(monkeypatch):
    def boom(url, **kw):
        raise requests.RequestException("connection refused")
    c = _mk_client(monkeypatch, boom)
    with pytest.raises(RetryableError):
        c.post("x")


def test_short_truncates_and_collapses_newlines():
    assert _short("a" * 500) == "a" * 300
    assert _short("line1\nline2") == "line1 line2"
    assert _short(None) == ""


def test_webhook_requires_url():
    with pytest.raises(ValueError):
        WebhookClient("")


def test_webhook_post_success(monkeypatch):
    w = WebhookClient("https://hook.example/z")
    sent = {}
    def ok(url, json, timeout):
        sent["json"] = json
        return _Resp(200, '{"ok": true}')
    monkeypatch.setattr(w._session, "post", ok)
    w.post("hello")
    assert sent["json"] == {"text": "hello"}


def test_webhook_error_mapping(monkeypatch):
    w = WebhookClient("https://hook.example/z")
    monkeypatch.setattr(w._session, "post", lambda url, **kw: _Resp(429, "limit"))
    with pytest.raises(RetryableError):
        w.post("x")
    monkeypatch.setattr(w._session, "post", lambda url, **kw: _Resp(422, "bad"))
    with pytest.raises(LinkedInError):
        w.post("x")