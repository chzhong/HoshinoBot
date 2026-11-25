# PCR 花名册

HoshinoBot `clan` 分支的独立插件。无需启用 `priconne` 或 `priconne.gacha` 的娱乐服务，也不会登录游戏或改动新版、旧版报刀代码。

## 部署

1. 保留并备份现有的 `hoshino/modules/priconne/CHARA_NAME.json`、`CHARA_PROFILE.json`。机器人用户需要能写入这两个文件所在的目录，以及 `RES_DIR/img/priconne/unit/`、`~/.hoshino/pcr_roster/`。`CHARA_PROFILE.json` 在 `clan` 分支是 Git 跟踪文件，不要把部署环境生成的改动混进代码提交。
2. 用 Hoshino 实际运行的 Python 安装本目录 `requirements.txt`。它只加 `UnityPy`，不要求升级 Pydantic；PNG 处理使用 Hoshino 已有的 Pillow。
3. 在 `MODULES_ON` 中加入 `pcr_roster`，放在两版报刀插件之前。重启后先发 `花名册状态`；需要立即更新时发 `同步花名册`。兼容方法在插件加载时安装，日常同步不需要重启。

如果是全新部署、缺少 `CHARA_NAME.json`，先让该插件同步生成花名册，再重启一次，确保依赖原有花名册文件的报刀插件可以顺利加载。

## 可选：复用 autopcr

会自动检查 `hoshino/modules/autopcr/`。独立部署时，可以设置：

- `PCR_ROSTER_AUTOPCR_ROOT`：autopcr 仓库根目录（包含 `autopcr/util/pcr_data.py`），也接受 autopcr Python 包目录（包含 `util/pcr_data.py`）。
- `PCR_ROSTER_AUTOPCR_CACHE`：缓存父目录（包含 `db/<资源版本>.db` 和 `image/unit_icon_unit_<ID><星级>1.png`）。不设置时检查 autopcr 仓库的 `cache/`。

Docker 可分别只读挂载 autopcr 的源码资料和缓存里的 `db`、`image` 子目录，不需要共享账号目录或访问 autopcr 的 Web 服务。插件不会执行 `pcr_data.py`，也不写 autopcr 的缓存。

同步会检查国服游戏资源版本，优先复用可用的 autopcr 主数据库；没有对应缓存时从官方资源下载。本地首选名、别名和档案手工字段保留，官服资料用来补齐。上游失败时会报告正在使用缓存或静态资料，不用空结果覆盖原数据。首次冷启动会下载主数据库；后续复用 `~/.hoshino/pcr_roster/` 下按版本保存的文件。

## 命令

- `花名册状态`：看上次同步的来源、版本、时间及数量。
- `同步花名册`：立即同步。插件还会在启动后和每天北京时间 16:05 检查；同步不下载全量头像。
- `下载所有角色头像`：后台补齐角色的 1、3、6 星资源。已有有效 PNG 不重复下载，缺失星级单独计数；失败可重跑。下载前优先复用 autopcr 的图片缓存。

命令使用和 `重载花名册` 一样的超管注册方式。配置在 `SUPERUSERS` 中的账号可私聊机器人或在群里直接发送命令，不需要 @，也不受群内服务开关限制。若部署设置了非空的 `COMMAND_START`，需加上相应的命令前缀。

头像下载完成后，用新版 Web BOX 检查一个之前显示失败的角色；如果之前缓存过占位图，换无痕窗口或清理浏览器缓存再验证。不需要用正在监控的账号刷新 BOX 来检查头像读取。

本地测试（不会登录游戏或连接 QQ）：

```bash
python -m unittest discover -s hoshino/modules/pcr_roster/tests -v
```
