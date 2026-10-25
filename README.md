# PesaBell releases

Android install files for PesaBell (M-Pesa payment announcer). The app reads `version.json` here
every hour (and when it opens) and updates itself. Source code is not in this repository.

**First install / 第一次安装:** open this link on the phone and install:
https://github.com/yyjj2215/pesabell-releases/raw/main/PesaBell.apk

PesaBell 安装包发布仓库。App 每小时（以及每次打开时）读取这里的 `version.json`，有新版就自动下载安装。
源代码不在这里。`apk/` 里是每个版本的安装包，`PesaBell.apk` 永远是最新版。

**Server setup / 服务器初始化:** `server/bootstrap.sh` prepares a new PesaBell server (Ubuntu 24.04).
Put these two lines in the server's startup script (cloud-init user-data) when creating it:

```bash
#!/bin/bash
curl -fsSL https://raw.githubusercontent.com/yyjj2215/pesabell-releases/main/server/bootstrap.sh -o /root/bootstrap.sh && bash /root/bootstrap.sh
```
