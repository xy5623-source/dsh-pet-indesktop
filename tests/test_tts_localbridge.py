# -*- coding: utf-8 -*-
"""``localbridge`` provider：本机 HTTP 语音桥（GPT-SoVITS）的契约与合成路径。

设计约束（见 ``docs/ADDING-A-TTS-PROVIDER.md``）：

* 纯层（``plan`` / ``flavor`` / ``availability``）必须可离线单测；
* ``synth`` 只做一次 GET、校验 RIFF 头，失败一律抛 ``TtsUnavailable``；
* token 走 ``secret_ref``（系统钥匙串），不进 ``config.json``，也**不进缓存键**。
"""

from __future__ import annotations

import io

import pytest

from pet import tts
from pet.tts import localbridge


class _FakeResponse(io.BytesIO):
    """最小可用的 urlopen 返回值替身（支持 with 语句）。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_provider_is_registered_with_declared_fields():
    assert "localbridge" in tts.provider_ids()
    provider = tts.get("localbridge")
    keys = {spec.key for spec in provider.fields}
    assert "voice_chime_localbridge_base_url" in keys
    assert "voice_chime_localbridge_token" in keys
    secrets = [spec for spec in provider.fields if spec.kind == "secret"]
    assert secrets, "token 必须是 secret 字段"
    assert secrets[0].secret_ref, "secret 字段必须声明 secret_ref"


def test_availability_needs_both_url_and_token():
    provider = tts.get("localbridge")
    assert provider.availability({"base_url": "", "token": "x"})
    assert provider.availability({"base_url": "http://127.0.0.1:9870", "token": ""})
    assert provider.availability({"base_url": "http://127.0.0.1:9870", "token": "x"}) == ""


def test_plan_normalizes_url_and_declares_wav():
    provider = tts.get("localbridge")
    values = {"base_url": "http://127.0.0.1:9870/", "token": "x", "text_lang": "zh", "timeout": 120}
    plan = provider.plan(values)
    assert plan["provider"] == "localbridge"
    assert plan["base_url"] == "http://127.0.0.1:9870", "结尾斜杠要去掉"
    assert plan["ext"] == "wav"


def test_flavor_ignores_token_so_cache_survives_rotating_it():
    provider = tts.get("localbridge")
    values = {"base_url": "http://127.0.0.1:9870", "token": "old", "text_lang": "zh"}
    assert provider.flavor(values) == provider.flavor(dict(values, token="new"))


def test_synth_writes_the_returned_wav(monkeypatch, tmp_path):
    provider = tts.get("localbridge")
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _FakeResponse(b"RIFF" + b"\x00" * 2048)

    monkeypatch.setattr(localbridge.urllib.request, "urlopen", fake_urlopen)
    values = {"base_url": "http://127.0.0.1:9870", "token": "tok", "text_lang": "zh", "timeout": 30}
    out = tmp_path / "line.wav"
    provider.synth("整点报时", provider.plan(values), out)

    assert out.read_bytes().startswith(b"RIFF")
    assert seen["url"].startswith("http://127.0.0.1:9870/tok/tts?")
    assert "text_lang=zh" in seen["url"]
    assert seen["timeout"] == 30


def test_synth_rejects_non_wav_payload(monkeypatch, tmp_path):
    provider = tts.get("localbridge")
    monkeypatch.setattr(
        localbridge.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(b"<html>gateway error</html>"),
    )
    with pytest.raises(tts.TtsUnavailable):
        provider.synth("整点报时", provider.plan({"base_url": "http://127.0.0.1:9870", "token": "t"}), tmp_path / "bad.wav")


def test_synth_wraps_transport_errors(monkeypatch, tmp_path):
    provider = tts.get("localbridge")

    def boom(request, timeout=None):
        raise ConnectionRefusedError("bridge is down")

    monkeypatch.setattr(localbridge.urllib.request, "urlopen", boom)
    with pytest.raises(tts.TtsUnavailable):
        provider.synth("整点报时", provider.plan({"base_url": "http://127.0.0.1:9870", "token": "t"}), tmp_path / "down.wav")
