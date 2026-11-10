# 本地 HTTP 语音桥 TTS 后端（`localbridge`）

日期：2026-11-10 ｜ 类型：新功能（新 TTS provider）｜ 状态：本地实现并实机验证

## 摘要

桌宠内置的 TTS 后端只有 `doubao` / `edge` / `mimo`（云端）与 `sapi`（Windows 离线）。
想用**自己的音色**只能二选一：连云端服务商，或被限制在系统语音上。

本 PR 增加一个 provider `localbridge`：把语音报时的合成请求转给**本机或局域网**上的
HTTP 语音桥（本项目按 lan-voice-bridge + GPT-SoVITS 验证）。协议极简——

```
GET http://127.0.0.1:<port>/<token>/tts?text=<文本>&text_lang=zh   ->  audio/wav
```

按 `docs/ADDING-A-TTS-PROVIDER.md` 接入：provider 自声明字段，`voice_chime*.py` 与设置页
**未改**。但实测发现该文档的一句说明与代码不符——见下面「配置键登记方式」一节，
因此 `config.py` 有 8 行新增。

## 修改文件说明

| 文件 | 变更 | 为什么 |
|---|---|---|
| `pet/tts/localbridge.py` | 新增 **109 行** | provider 本体：4 个字段（`base_url` / `token`(secret) / `text_lang` / `timeout`）、`plan` / `flavor` / `availability` / `synth`。`synth` 只做一次 GET、校验 RIFF 头、失败统一抛 `TtsUnavailable` |
| `pet/tts/__init__.py` | **+1 / −1** | import 即注册：`doubao, edge, localbridge, mimo, sapi` |
| `pet/config.py` | **+8 / −0** | 3 个平铺默认键 + 3 个 reload 白名单键（+2 行注释）。**必须手写**——见「配置键登记方式」 |
| `tests/test_tts_localbridge.py` | 新增 **103 行** | 契约（字段键前缀、secret 必须带 `secret_ref`）、`availability` 两种缺项、`plan` 归一化、`flavor` 不含 token、`synth` 正常写入与三类失败（非 wav / 连接被拒 / 非 2xx） |
| `tests/test_voice_chime.py` | **+3 行** | 平铺键快照补 3 个非密钥键（`token` 是 secret，按约定不进 `config.json`） |
| `tests/test_config_schema.py` | **+3 行** | reload 白名单快照补 3 个键（`DEFAULTS_SNAPSHOT` 由它派生，故一处即可） |
| `docs/PR-REPORT-TTS-LOCALBRIDGE-2026-11-10.md` | 新增 | 本报告 |
| `docs/INDEX.md` | **+1 行** | 按「新文档入场规则」登记该报告 |

新增配置键（`pet/config.py` 顶层平铺）：

```
voice_chime_localbridge_base_url    text      "http://127.0.0.1:9870"
voice_chime_localbridge_text_lang   select    "zh"
voice_chime_localbridge_timeout     number    120
voice_chime_localbridge_token       secret    → 系统钥匙串（secret_ref = tts/localbridge），不进 config
```

## 配置键登记方式（文档与实际不符，本 PR 按实际实现）

`docs/ADDING-A-TTS-PROVIDER.md` 的「第 3 步：在 `pet/config.py` 里什么都不用做」与代码不符：

- `pet/config.py::_initial_data()` 里是一张**手写**的平铺默认值表（`voice_chime_mimo_voice`
  等逐条列出），并没有遍历 `tts.providers()`；
- reload 白名单（`_initial_data()` 之后的键列表）同样是手写的。

只注册 provider 而不补这两处时，实测后果：

```
$ python -c "import pet.settings_default_marks as m; d=m._config_default_data(); print('...base_url' in d)"
False      # 设置页「已修改」标记的默认值来源里没有这个键
```

于是 `tests/test_settings_default_marks.py` 的覆盖率快照与
`tests/test_voice_chime_settings_layout.py` 会红（默认值不可比 ⇒ 行未登记）。

本 PR 因此**同时补了 `pet/config.py` 的两处**，并在两张快照里登记。文档那句可以后续再修
（本 PR 不改文档描述，避免范围膨胀）。

## 性能分析

测量环境：Windows 11（CPU 合成，无 CUDA），桌宠源码运行（CPython 3.12.15 + PySide6 6.12），
上游 GPT-SoVITS `127.0.0.1:9880`，语音桥 `0.0.0.0:9870`。

**稳态开销（每次报时触发一次，不是常驻）**

| 指标 | 实测 |
|---|---|
| provider 侧额外开销 | 一次回环 HTTP GET + `read()` + 一次文件写；单测替身测得 **< 1 ms**（真机耗时全在上游合成） |
| 上游合成（报时短句 ≈30 字） | **4.79 s** → 256,044 B wav；**4.85 s** → 307,244 B wav |
| 返回音频规格 | 32 kHz / 单声道 / 16 bit（上游决定） |
| 新增线程 | **0**（合成在既有 TTS worker 线程里跑） |
| 新增网络 | 每次报时 1 次 `127.0.0.1` 回环 GET；无轮询、无常驻连接、无公网请求 |
| 新增磁盘 | 每次 1 次 wav 写入（缓存目录，沿用既有合成缓存） |

**新增路径成本与触发频率**：只在语音报时真正到点时合成一次（默认整点，可配 30/15/5/1 分钟或
自定义时间点）；`availability()` 只读配置，不联网。

**内存**：无常驻对象；wav 以一次性 bytes 写出（256–307 KB 量级），写完即释放。

**缓存**：沿用既有合成缓存。`flavor()` 只放 `base_url` + `text_lang`，**token 不进缓存键**——
轮换 token 不会让旧缓存失效（有单测守着）。

## 实机运行记录

环境：本机语音桥（`0.0.0.0:9870`）+ GPT-SoVITS（`127.0.0.1:9880`），桌宠源码运行版，
配置 `voice_chime_enabled=true`、`voice_chime_tts_backend=localbridge`。

**桥日志（桌宠发出的真实请求，非构造）**

```
12:08:46  127.0.0.1 GET /tts query=text=现在中午十二点08分。…&text_lang=zh
12:08:51  127.0.0.1 GET /tts -> 200, 256044 B, 4787 ms
12:09:06  127.0.0.1 GET /tts query=text=现在中午十二点09分。…
12:09:11  127.0.0.1 GET /tts -> 200, 307244 B, 4852 ms
```

两次都由桌宠进程发起（`127.0.0.1`），200 + wav，系统扬声器可闻。

**失败路径（同一实现里实测）**

| 场景 | 结果 |
|---|---|
| token 错误 | 桥回 `HTTP 401` → provider 抛 `TtsUnavailable`（不写坏文件） |
| 返回非 wav（网关错误页） | `RIFF` 头校验失败 → `TtsUnavailable` |
| 桥未启动（连接被拒） | 异常包装为 `TtsUnavailable`，走既有「后端失败→回退」链 |

**自动化验证**

```
QT_QPA_PLATFORM=offscreen python -m pytest \
    tests/test_tts_localbridge.py tests/test_voice_chime.py \
    tests/test_voice_chime_mimo.py tests/test_config_schema.py \
    tests/test_settings_default_marks.py tests/test_settings_copy_lint.py \
    tests/test_voice_chime_settings_layout.py tests/test_pr_report_discipline.py -q
-> 512 passed

python -m ruff check pet/tts pet/config.py tests/test_tts_localbridge.py tests/test_voice_chime.py
-> All checks passed!
```

全量套件（本机，`-q`）：**9058 passed / 14 failed**。其中 10 条与本改动无关，已用 A/B 证明：
把 provider 的 import 摘掉后同一批用例**同样 10 failed**（`test_balance` 2、`test_click_sound` 6、
`test_memory_recall` 1、`test_tts_sapi_thread` 1 —— 最后一类是 SAPI COM 在本机环境取不到语音）。
另外 4 条由本改动引入、已全部修好：`test_settings_copy_lint`（label 里的 `GPT` 命中黑话 lint →
改成「本地语音桥（本机音色）」）、`test_settings_default_marks` ×2 与
`test_voice_chime_settings_layout`（hint 超过 20 字 → 缩短；默认值未登记 → 补 `pet/config.py`）。

## 已知限制

- 只支持**本机/局域网** HTTP 端点；公网 URL 需自行保证 TLS 与鉴权（provider 不做校验）。
- 返回格式必须是 wav（`RIFF`）。若桥返回 mp3，需要上游改格式或另写 provider（`ext` 不同）。
- 只覆盖报时/朗读这类 TTS 输出；**不影响**「跟随音乐唱歌」动画（另一条链路）。
