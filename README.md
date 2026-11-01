# PesaBell releases

Android install files for PesaBell (M-Pesa payment announcer). The app reads `version.json` here
every hour (and when it opens) and updates itself. Source code is not in this repository.

**First install / 第一次安装:** open https://pesabell.com on the phone and tap Download (the website serves
`PesaBell.apk` from here, with install help). 在手机上打开 https://pesabell.com 点下载（就是这里的 `PesaBell.apk`）。

PesaBell 安装包发布仓库。App 每小时（以及每次打开时）读取这里的 `version.json`，有新版就自动下载安装。
源代码不在这里。`apk/` 里是每个版本的安装包，`PesaBell.apk` 永远是最新版。

**Server setup / 服务器初始化:** `server/bootstrap.sh` prepares a new PesaBell server (Ubuntu 24.04).
Put these two lines in the server's startup script (cloud-init user-data) when creating it:

```bash
#!/bin/bash
curl -fsSL https://raw.githubusercontent.com/yyjj2215/pesabell-releases/main/server/bootstrap.sh -o /root/bootstrap.sh && bash /root/bootstrap.sh
```

**Chinese voice / 中文语音包:** `voice/make_zh_a.py` makes the Chinese announcements the PesaBell server plays
(every amount said as one sentence, voice MeloTTS, checked by a speech recognizer); `.github/workflows/voice.yml`
runs it on GitHub's machines and publishes the release `voice-zh-a-1`. 服务器播报的中文语音包，每个金额整句合成。
`voice/fix.json` and `.github/workflows/voice-fix.yml` make a new version from an earlier one: some sentences made
again (zh-a-3), the 补报 parts `late/<hhmm>` "现在补报一笔，下午四点五十一分，" for a payment the speaker missed (zh-a-4).
