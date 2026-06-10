# HoshinoBot
[![License](https://img.shields.io/github/license/Ice-Cirno/HoshinoBot)](LICENSE)
![Python Version](https://img.shields.io/badge/python-3.11+-blue)
![Nonebot Version](https://img.shields.io/badge/nonebot-1.6.0%2B%2C%202.0.0---blue)
[![试用/赞助群](https://img.shields.io/badge/试用/赞助-Hoshinoのお茶会-brightgreen)](https://jq.qq.com/?_wv=1027&k=eYGgrL4A)
[![开发交流群](https://img.shields.io/badge/开发交流-Hoshinoの后花园-brightgreen)](https://jq.qq.com/?_wv=1027&k=wgirhYYQ)

A QQ-bot for Princess Connect Re:Dive based on [Nonebot](https://github.com/nonebot/nonebot)

<details>
  <summary>开发历史</summary>

- 2019.09.20 HoshinoBot诞生
- ... (待补充)
- **2020年8月2日0点，qq机器人框架相继停止维护。** **感谢 酷Q项目 和 CQHTTP插件 的开发者们！感谢他们让Hoshino得以诞生！** **Hoshino不再对酷Q进行支持**

</details>


## 简介

**HoshinoBot:** 基于 [nonebot](https://docs.nonebot.dev/) 框架，开源、无公害、非转基因的QQ机器人。



## 功能介绍

HoshinoBot 的功能开发以服务 [公主连结☆Re:Dive](http://priconne-redive.jp) 玩家为核心。

<details>
  <summary>主要功能</summary>

- **转蛋模拟**：单抽、十连、抽一井
- **竞技场解法查询**：支持按服务器过滤，支持反馈点赞点踩
- **竞技场结算提醒**
- **公会战管理**：详细说明见[此文档](hoshino/modules/pcrclanbattle/clanbattle/README.md)
- **Rank推荐表搬运**
- **常用网址速查**
- **官方推特转发**
- **官方四格推送**
- **角色别称转换**
- **切噜语编解码**：切噜～♪
- **竞技场余矿查询**

> 由于bot的功能会快速迭代开发，使用方式这里不进行具体的说明，请向bot发送"help"或移步[此文件](hoshino/modules/botmanage/help.py)查看详细。会战管理功能的详细说明，请[点击这里](hoshino/modules/pcrclanbattle/clanbattle/README.md)

</details>

<details>
  <summary>通用功能</summary>

- **[蜜柑计划](http://mikanani.me)番剧更新订阅**
- **入群欢迎**&**退群提醒**
- **复读**
- **掷骰子**
- **精致睡眠套餐**
- **机器翻译**
- **反馈发送**：反馈内容将由bot私聊发送给维护组

</details>

此外，HoshinoBot 为 [艦隊これくしょん](http://www.dmm.com/netgame/feature/kancolle.html) 玩家开发了以下功能

<details>
  <summary>点击展开</summary>

- **官推转发**：「艦これ」開発/運営 & C2機関
- **时报**
- **演习时间提醒**
- **月度远征提醒**
- **舰娘信息查询**：`*晓改二`
- **装备信息查询**：`*震电改`
- **战果人事表查询**：`人事表191201`

> 艦これ相关功能由于个人精力实在有限，无法进行更多功能（如海图攻略）的开发/维护。
>
> 如果您有新的想法，欢迎联系我！即便您不会编程，您也可以在内容更新上帮到我们！

</details>

-------------

### 功能模块控制

HoshinoBot 的功能繁多，各群可根据自己的需要进行开关控制，群管理发送 `lssv` 即可查看功能模块的启用状态，使用以下命令进行控制：

```
启用 service-name
禁用 service-name
```


## 如何开始使用

QQ群[![试用/赞助群](https://img.shields.io/badge/试用/赞助-Hoshinoのお茶会-brightgreen)](https://jq.qq.com/?_wv=1027&k=eYGgrL4A)提供了我们部署的bot，提供Hoshino的原生服务。您可以在这里试用bot功能、赞助开发者，赞助者可邀请bot加入自己的群使用。

如果您具备基本的linux与python能力，并拥有一台服务器（轻量级即可），您可以参阅部署指南自行部署。


## 开源协议及免责声明

本项目遵守GPL-3.0协议开源，请在协议允许的条件及范围内使用本项目。本项目的开发者不会强制向您索要任何费用，同时也不会提供任何质保，一切因本项目引起的法律、利益纠纷由与本项目的开发者无关。
- 对于自行搭建、小范围私用的非营利性bot，若遇到任何部署、开发上的疑问，欢迎提交issue或加入[![开发交流群](https://img.shields.io/badge/开发交流-Hoshinoの后花园-brightgreen)](https://jq.qq.com/?_wv=1027&k=wgirhYYQ)讨论，我们欢迎有礼貌、描述详尽的提问！
- 对于以营利为目的部署的bot，由部署者负责，与本项目的开发者无关，本项目的开发者及社区没有义务回答您部署时的任何疑问。
- 对于HoshinoBot插件的开发者，在您发布插件或利用插件营利时，请遵守GPL-3.0协议将插件代码开源。

最终解释权归HoshinoBot开发组所有。



## 部署指南

HoshinoBot 通过反向 WebSocket 与 QQ 客户端通信。QQ 客户端方案迭代快、生命周期短，**本仓库不再推荐或维护任何具体客户端**，请自行搜索社区攻略并完成客户端侧配置。

### 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | **3.11** | 本地部署与 Docker 镜像一致；更高版本（如 3.12）可自行验证 |
| Debian | **13 (Trixie)** | Docker 基础镜像 `python:3.11-slim-trixie` 所用发行版 |
| 操作系统 | Debian 12+ / Ubuntu 22.04+ | 裸机部署建议；版本过低请**自行升级** |

默认启用模块见 `hoshino/config_example/__bot__.py` 的 `MODULES_ON`（当前含 `botmanage`、`groupmaster`、`tietie`、`pcrjjc2`）。

### 系统部署

```bash
git clone https://github.com/Ice-Cirno/HoshinoBot.git
cd HoshinoBot
python3 install_deps.py          # 推荐：安装框架 + 各插件依赖
cp -r hoshino/config_example hoshino/config
# 编辑 hoshino/config/__bot__.py（PORT、SUPERUSERS、MODULES_ON 等）
python3 run.py
```

依赖也可手动安装，与 `Dockerfile` 中逻辑相同：

```bash
pip install --no-cache-dir -r requirements.txt && \
find . -name "requirements.txt" -path "*/modules/*" -exec pip install --no-cache-dir -r {} \;
```

根目录 `requirements.txt` 仅含 nonebot、aiocqhttp 等框架依赖；`pcrjjc2`、`pcrdata`、`tietie` 等插件另有独立依赖（如 `pycryptodome`、`redis`、`msgpack`）。**不要只安装根目录 requirements.txt。**

`pcrjjc2` 表格图片渲染需模块内字体，首次部署执行：

```bash
bash hoshino/modules/pcrjjc2/download-fonts.sh
```

QQ 客户端的安装与对接不在本仓库维护范围内，请自行查阅攻略，并将反向 WS 地址指向 Hoshino 监听的端口（默认 `8080`）。

### Docker 镜像

`Dockerfile` 基于 `python:3.11-slim-trixie`，以专用用户 **`pcrbot`** 在虚拟环境 **`/home/pcrbot/.venv`** 中运行，监听 **8080**。构建前确保本地存在 `fonts/` 目录（已在 `.gitignore` 中，需自行准备）。

**依赖分层**：

| 层级 | 内容 | 时机 |
|------|------|------|
| 系统 `-dev` 包 | `build-essential`、`zlib1g-dev` 等常见编译库 | 镜像构建 |
| 框架 Python 包 | 根目录 `requirements.txt` | 镜像构建，装入 `.venv` |
| 插件 Python 包 | `hoshino/modules/*/requirements.txt` | **首次容器启动**自动扫描安装 |

仅挂载代码目录 `/HoshinoBot`；**勿**挂载 `/home/pcrbot`（`.venv` 随镜像，升级 OS/Python 时随新容器重建）。

#### 本机构建

```bash
cd /path/to/HoshinoBot
DOCKER_BUILDKIT=1 docker build -t pcrbot/hoshinobot:pcrjjc2 .
```

挂载目录属主与容器用户不一致时，可指定 UID/GID（默认 1000）：

```bash
DOCKER_BUILDKIT=1 docker build \
  --build-arg PUID=1000 --build-arg PGID=1000 \
  -t pcrbot/hoshinobot:pcrjjc2 .
```

#### 交叉编译（MBP Apple Silicon → Ubuntu / NAS）

```bash
cd /path/to/HoshinoBot
DOCKER_BUILDKIT=1 docker build \
  --platform linux/amd64 \
  -t pcrbot/hoshinobot:pcrjjc2 \
  .
```

验证架构：

```bash
docker inspect pcrbot/hoshinobot:pcrjjc2 --format '{{.Architecture}}'
# 应输出 amd64
```

#### 离线传输与运行

```bash
docker save pcrbot/hoshinobot:pcrjjc2 | gzip > hoshinobot-pcrjjc2.tar.gz
# 远端：gunzip -c hoshinobot-pcrjjc2.tar.gz | docker load
```

业务代码与配置需挂载；首次启动会自动安装各插件 `requirements.txt`：

```bash
docker run -d --name hoshino \
  -p 8080:8080 \
  -v /path/to/HoshinoBot:/HoshinoBot \
  pcrbot/hoshinobot:pcrjjc2
```

插件依赖较大、希望先快速启动 bot 时，可跳过启动期自动安装：

```bash
docker run -d --name hoshino -e SKIP_MODULE_DEPS=1 \
  -p 8080:8080 \
  -v /path/to/HoshinoBot:/HoshinoBot \
  pcrbot/hoshinobot:pcrjjc2
# 之后：docker exec -u pcrbot hoshino /HoshinoBot/docker/reinstall-module-deps.sh
```

#### 镜像升级（换 Python / Debian 版本）

```bash
docker build -t pcrbot/hoshinobot:pcrjjc2 .
docker rm -f hoshino
docker run -d --name hoshino -p 8080:8080 \
  -v /path/to/HoshinoBot:/HoshinoBot \
  pcrbot/hoshinobot:pcrjjc2
```

新容器自带与新 OS/Python 匹配的 `.venv`（框架依赖），并会在首次启动时重新安装插件依赖。

#### 容器内排错

日常以 **`pcrbot`** 进入容器即可；`bash` 会自动激活 `/home/pcrbot/.venv`，并打印与下文一致的常用命令提示。

**pcrbot 用户（Python 依赖、调试）**

```bash
# 交互式 shell（自动进入 venv）
docker exec -u pcrbot -it hoshino bash

# 重装全部插件依赖（git pull / git clone 新插件后）
docker exec -u pcrbot hoshino /HoshinoBot/docker/reinstall-module-deps.sh

# 单独安装 Python 包（容器内已激活 venv 时可直接 pip）
docker exec -u pcrbot hoshino /HoshinoBot/docker/pip-install.sh install <package>
docker exec -u pcrbot hoshino /HoshinoBot/docker/pip-install.sh install \
  -r hoshino/modules/<plugin>/requirements.txt
```

**root 用户（系统依赖、复杂运维）**

`pcrbot` 无 `sudo`，安装系统包或需要 root 权限的操作须从宿主机以 root 进入容器：

```bash
# 以 root 进入交互式 shell（apt、改系统配置等）
docker exec -u root -it hoshino bash

# 仅安装系统包（无需进入 shell）
docker exec -u root hoshino /HoshinoBot/docker/apt-install.sh <package>
# 示例
docker exec -u root hoshino /HoshinoBot/docker/apt-install.sh libssl-dev
```

系统包装好后，回到 `pcrbot` 重试 pip（必要时 `--force-reinstall`）：

```bash
docker exec -u pcrbot hoshino /HoshinoBot/docker/pip-install.sh install --force-reinstall <package>
```

验证框架依赖（镜像内已装）：

```bash
docker exec -u pcrbot hoshino pip show nonebot
```

裸机部署请使用 `python3 install_deps.py` 安装全部依赖。

### 更进一步

现在，机器人已经可以使用`会战管理`、`模拟抽卡(纯文字版)`等基本功能了。但还无法使用`竞技场查询`、`番剧订阅`、`推特转发`等功能。这是因为，这些功能需要对应的静态图片资源以及相应的api key。相应资源获取有难有易，您可以根据自己的需要去获取。

下面将会分别介绍资源与api key的获取方法：



#### 静态图片资源

> 发送图片的条件：  
> 1. 静态图片资源

您可能希望看到更为精致的图片版结果，若希望机器人能够发送图片，需要准备静态图片资源，其中包括：

- 公主连接角色头像（来自 [干炸里脊资源站](https://redive.estertion.win/) 的拆包）
- 公主连接官方四格漫画
- 公主连接每月rank推荐表
- 表情包杂图
- setu库
- [是谁呼叫舰队](http://fleet.diablohu.com/)舰娘&装备页面截图
- 艦これ人事表

等资源。自行收集可能较为困难，所以我们准备了一个较为精简的资源包以及下载脚本，可以满足公主连接相关功能的日常使用。如果需要，请加入QQ群 **Hoshino的后花园** 367501912，下载群文件中的`res.zip`。



#### pcrdfans授权key

竞技场查询功能的数据来自 [公主连结Re: Dive Fan Club - 硬核的竞技场数据分析站](https://pcrdfans.com/) ，查询需要授权key。您可以向pcrdfans的作者索要。（注：由于最近机器人搭建者较多，pcrdfans的作者最近常被打扰，我们**不建议**您因本项目而去联系他，推荐您前往网站[pcrdfans.com](https://pcrdfans.com)进行查询）

若您已有授权key，在文件`hoshino/config/priconne.py`中填写您的key：

```python
class arena:
    AUTH_KEY = "your_key"
```



#### 蜜柑番剧 RSS Token

> 请先在`hoshino/config/__bot__.py`的`MODULES_ON`中取消`mikan`的注释  
> 本功能默认关闭，在群内发送 "启用 bangumi" 即可开启

番剧订阅数据来自[蜜柑计划 - Mikan Project](https://mikanani.me/)，您可以注册一个账号，添加订阅的番剧，之后点击Mikan首页的RSS订阅，复制类似于下面的url地址：

```
https://mikanani.me/RSS/MyBangumi?token=abcdfegABCFEFG%2b123%3d%3d
```

保留其中的`token`参数，在文件`hoshino/config/mikan.py`中填写您的token：

```python
MIKAN_TOKEN = "abcdfegABCFEFG+123=="
```

注意：`token`中可能含有url转义，您需要将`%2b`替换为`+`，将`%2f`替换为`/`，将`%3d`替换为`=`。



#### 时报文本

> 请先在`hoshino/config/__bot__.py`的`MODULES_ON`中取消`hourcall`的注释  
> 本功能默认关闭，在群内发送 "启用 hourcall" 即可开启

报时功能使用/魔改了艦これ中各个艦娘的报时语音，您可以在[舰娘百科](https://zh.kcwiki.org/wiki/舰娘百科)或[艦これ 攻略 Wiki](https://wikiwiki.jp/kancolle/)找到相应的文本/翻译，当然您也可以自行编写台词。在此，我们向原台词作者[田中](https://bbs.nga.cn/read.php?tid=9143913)[谦介](http://bbs.nga.cn/read.php?tid=14045507)先生和他杰出的游戏作品表达诚挚的感谢！

若您已获取时报文本，在文件`hoshino/config/hourcall.py`中填写您的文本。

您可以编入多组报时文本，机器人会按`HOUR_CALLS_ON`中定义的顺序循环日替。



#### 推特转发

推特转发功能需要推特开发者账号，具体申请方法请自行[Google](http://google.com)。注：现在推特官方大概率拒绝来自中国大陆的新申请，自备海外手机号及大学邮箱可能会帮到您。

若您已有推特开发者账号，在文件`hoshino/config/twitter.py`中填写您的key：

```python
consumer_key = "your_consumer_key",
consumer_secret = "your_consumer_secret",
access_token_key = "your_access_token_key",
access_token_secret = "your_access_token_secret"
```



#### 晴乃词库

舰娘及装备查询功能使用了精简版的晴乃词库，如有需要请加 Hoshino的后花园（群号367501912）或联系晴乃维护组。





## 友情链接

**干炸里脊资源站**: https://redive.estertion.win/

**公主连结Re: Dive Fan Club - 硬核的竞技场数据分析站**: https://pcrdfans.com/

**yobot**: https://yobot.win/

