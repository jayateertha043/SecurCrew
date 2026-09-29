"""Tests for summarize.py: AI-compatible summarizer + JSON parsing helpers."""

from __future__ import annotations

import summarize

# --- _parse_json_array -------------------------------------------------------


def test_parse_json_array_clean():
    assert summarize._parse_json_array('["a", "b"]') == ["a", "b"]


def test_parse_json_array_fenced():
    assert summarize._parse_json_array('```json\n["a","b"]\n```') == ["a", "b"]


def test_parse_json_array_embedded_in_text():
    content = 'here you go: ["one", "two"] thanks'
    assert summarize._parse_json_array(content) == ["one", "two"]


def test_parse_json_array_strips_whitespace():
    assert summarize._parse_json_array('["  a  ", " b "]') == ["a", "b"]


def test_parse_json_array_invalid():
    assert summarize._parse_json_array("no brackets here") is None
    assert summarize._parse_json_array('[123, "not-all-strings"]') is None
    assert summarize._parse_json_array("") is None


# --- _parse_groups -----------------------------------------------------------


def test_parse_groups_valid():
    assert summarize._parse_groups("[[0, 2], [1]]", n=3) == [[0, 2], [1]]


def test_parse_groups_missing_coverage():
    assert summarize._parse_groups("[[0]]", n=3) is None


def test_parse_groups_duplicate_index():
    assert summarize._parse_groups("[[0, 0], [1]]", n=2) is None


def test_parse_groups_out_of_range():
    assert summarize._parse_groups("[[0, 9]]", n=2) is None


def test_parse_groups_ignores_empty_inner_groups_ok_if_still_covers():
    # coverage must still equal 0..n-1 exactly
    assert summarize._parse_groups("[[], [0, 1]]", n=2) == [[0, 1]]


def test_parse_groups_fenced_and_non_list():
    assert summarize._parse_groups('```json\n[[0,1]]\n```', n=2) == [[0, 1]]
    assert summarize._parse_groups("nope", n=2) is None
    assert summarize._parse_groups('{"a": 1}', n=2) is None


# --- _clean -------------------------------------------------------------------


def test_clean_strips_tags_collapses_truncates():
    assert summarize._clean("<b>Hello</b>   world", 100) == "Hello world"
    assert summarize._clean("<p>a</p><p>b</p>", 1) == "a"


def test_clean_handles_none():
    assert summarize._clean(None, 10) == ""


# --- _retry_after_seconds -----------------------------------------------------


class _FakeResp:
    def __init__(self, headers=None, text=""):
        self.headers = headers or {}
        self.text = text


def test_retry_after_header():
    r = _FakeResp(headers={"retry-after": "7"})
    assert summarize._retry_after_seconds(r) == 7.0


def test_retry_after_message_regex():
    r = _FakeResp(text="Rate limited, try again in 5.5 seconds.")
    assert summarize._retry_after_seconds(r) == 6.5


def test_retry_after_none():
    assert summarize._retry_after_seconds(_FakeResp()) is None


def test_retry_after_bad_header_falls_back_to_message():
    r = _FakeResp(headers={"retry-after": "soon"}, text="try again in 3s")
    assert summarize._retry_after_seconds(r) == 4.0


# --- Summarizer.from_env / _chat -------------------------------------------------


def test_from_env_none_without_key(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    assert summarize.Summarizer.from_env() is None


def test_from_env_uses_defaults(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    s = summarize.Summarizer.from_env()
    assert s is not None
    assert s._url == "https://api.groq.com/openai/v1/chat/completions"
    assert s._model == summarize.DEFAULT_MODEL


def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setenv("AI_BASE_URL", "https://my.provider/v1/")
    monkeypatch.setenv("AI_MODEL", "my-model")
    s = summarize.Summarizer.from_env()
    assert s._url == "https://my.provider/v1/chat/completions"
    assert s._model == "my-model"


def test_chat_network_error_returns_none(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")

    def boom(url, **kw):
        raise summarize.requests.RequestException("conn refused")

    monkeypatch.setattr(s._session, "post", boom)
    assert s._chat({"model": "m"}) is None


def test_chat_429_retries_then_succeeds(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")
    calls = []
    responses = [
        (429, {"retry-after": "0"}),   # fast retry
        (200, {"choices": [{"message": {"content": "ok"}}]}),
    ]

    class _Resp:
        def __init__(self, code, payload):
            self.status_code = code
            self.text = ""
            self.headers = payload.get("headers", {}) if isinstance(payload, dict) else {}
            self._json = payload
            self.content = b""
        def json(self):
            return self._json

    def fake_post(url, **kw):
        calls.append(kw)
        code, payload = responses.pop(0)
        if code == 429:
            r = _Resp(429, {"headers": {"retry-after": "0"}})
            return r
        return _Resp(200, payload)

    monkeypatch.setattr(s._session, "post", fake_post)
    assert s._chat({"model": "m"}) == "ok"
    assert len(calls) == 2  # one retry


def test_chat_non200_returns_none(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")

    class _Resp:
        status_code = 500
        text = "boom"
        content = b"boom"
        headers = {}
        def json(self):
            raise ValueError

    monkeypatch.setattr(s._session, "post", lambda url, **kw: _Resp())
    assert s._chat({"model": "m"}) is None


def test_chat_200_non_json_returns_none(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")

    class _Resp:
        status_code = 200
        text = "text-only"
        content = b"text-only"
        headers = {"content-type": "text/plain"}
        def json(self):
            raise ValueError

    monkeypatch.setattr(s._session, "post", lambda url, **kw: _Resp())
    assert s._chat({"model": "m"}) is None


def test_chat_unexpected_shape_returns_none(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")

    class _Resp:
        status_code = 200
        text = ""
        content = b""
        headers = {}
        def json(self):
            return {"nope": True}

    monkeypatch.setattr(s._session, "post", lambda url, **kw: _Resp())
    assert s._chat({"model": "m"}) is None


# --- summarize_batch ----------------------------------------------------------


def test_summarize_batch_chunks_and_mismatch_falls_back(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")
    s._summarize_chunk = lambda chunk: [f"sum{i}" for i in range(len(chunk))]
    items = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    assert s.summarize_batch(items) == ["sum0", "sum1", "sum2"]


def test_summarize_batch_failure_returns_none(monkeypatch):
    s = summarize.Summarizer("k", "https://x/v1", "m")
    s._summarize_chunk = lambda chunk: None
    assert s.summarize_batch([{"title": "a"}]) is None


# --- cluster_duplicates --------------------------------------------------------


def test_cluster_duplicates_short_circuit():
    s = summarize.Summarizer("k", "https://x/v1", "m")
    assert s.cluster_duplicates([]) == []
    assert s.cluster_duplicates([{"title": "only"}]) == [[0]]