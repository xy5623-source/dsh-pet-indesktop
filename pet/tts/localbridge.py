# -*- coding: utf-8 -*-
"""本地语音桥 provider：把语音合成转给本机 lan-voice-bridge（GPT-SoVITS 一类）。

协议（见 lan-voice-bridge 的 bridge.py）::

    GET http://127.0.0.1:<port>/<token>/tts?text=<文本>&text_lang=zh  ->  audio/wav

特点：纯本机、零公网、零 Key（token 是本机桥的访问令牌，不是云服务凭据）；
音色由桥上游的合成服务决定，桥会自己补齐参考音频等默认参数。

放置：仓库 ``pet/tts/localbridge.py``，并在 ``pet/tts/__init__.py`` 里
``from . import doubao, edge, localbridge, mimo, sapi``（import 即注册）。
按 ``docs/ADDING-A-TTS-PROVIDER.md``，设置页与服务层不需要改；但 ``pet/config.py``
的平铺默认值表与 reload 白名单**需要**补这三个非密钥键（该文档第 3 步说「什么都不用做」，
与实现不符——两处都是手写的，不遍历 ``tts.providers()``）。
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request

from .base import TtsField, TtsProvider, TtsUnavailable, register

logger = logging.getLogger(__name__)

PROVIDER_ID = "localbridge"
LABEL = "本地语音桥（本机音色）"
AVAILABILITY_CODE = "localbridge-unconfigured"
MISSING_MESSAGE = "本地语音桥未配置：在「设置 → 语音 → 语音报时」里填语音桥地址与 token"


class LocalBridgeProvider(TtsProvider):
    id = PROVIDER_ID
    label = LABEL
    is_fallback = False
    availability_code = AVAILABILITY_CODE
    unavailable_message = MISSING_MESSAGE
    fields = (
        TtsField(
            "base_url", "voice_chime_localbridge_base_url", "语音桥地址",
            kind="text", default="http://127.0.0.1:9870",
            placeholder="http://127.0.0.1:9870",
            hint="本机语音桥的根地址",
        ),
        TtsField(
            "token", "voice_chime_localbridge_token", "访问令牌",
            kind="secret", default="", secret_ref="tts/localbridge",
            hint="语音桥配置文件里的 token",
        ),
        TtsField(
            "text_lang", "voice_chime_localbridge_text_lang", "语言",
            kind="select", default="zh",
            options=(("中文", "zh"), ("英文", "en"), ("日文", "ja"), ("中英混合", "auto")),
            hint="跟着文本语言自动选",
        ),
        TtsField(
            "timeout", "voice_chime_localbridge_timeout", "超时（秒）",
            kind="number", default=120, minimum=10, maximum=600,
            hint="合成长句会慢，可调大",
        ),
    )

    # ---------------------------------------------------------------- 纯层
    def plan(self, values: dict) -> dict:
        return {
            "provider": self.id,
            "base_url": str(values.get("base_url") or "").rstrip("/"),
            "token": str(values.get("token") or "").strip(),
            "text_lang": str(values.get("text_lang") or "zh"),
            "timeout": int(values.get("timeout") or 120),
            "ext": "wav",
        }

    def flavor(self, values: dict) -> str:
        # 只放影响音频内容的参数；token 不进缓存键（换了 token 音色不变）
        return "localbridge|%s|%s" % (
            str(values.get("base_url") or ""),
            str(values.get("text_lang") or "zh"),
        )

    def availability(self, values: dict) -> str:
        if not str(values.get("base_url") or "").strip():
            return AVAILABILITY_CODE
        if not str(values.get("token") or "").strip():
            return AVAILABILITY_CODE
        return ""

    # ---------------------------------------------------------------- IO 层
    def synth(self, text: str, plan: dict, out_path) -> None:
        query = urllib.parse.urlencode({"text": text, "text_lang": plan.get("text_lang") or "zh"})
        url = "%s/%s/tts?%s" % (plan["base_url"], plan["token"], query)
        request = urllib.request.Request(url, headers={"User-Agent": "dsh-pet-localbridge"})
        try:
            with urllib.request.urlopen(request, timeout=plan.get("timeout") or 120) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            raise TtsUnavailable(AVAILABILITY_CODE, "语音桥返回 HTTP %s：%s" % (exc.code, exc.reason)) from exc
        except Exception as exc:  # 连接被拒 / 超时 / DNS
            raise TtsUnavailable(AVAILABILITY_CODE, "连不上本地语音桥：%s" % exc) from exc
        if len(data) < 512 or data[:4] != b"RIFF":
            raise TtsUnavailable(AVAILABILITY_CODE, "语音桥返回的不是 wav（%d 字节）" % len(data))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)


PROVIDER = register(LocalBridgeProvider())
