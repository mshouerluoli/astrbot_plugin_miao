# astrbot_plugin_miao

`astrbot_plugin_miao` 是为 AstrBot 编写的插件示例，提供自动点赞、群打卡、前瞻兑换码查询、伪造聊天记录示例和“胡桃+链接”检测提醒等功能。

## 功能概览

- 捕获 `aiocqhttp` 平台的机器人实例以调用 API（`send_group_sign`、`send_private_msg` 等）。
- 定时任务：每天 00:00 执行一次“打卡 + 点赞”任务并将结果通知管理员（若配置）。
- 支持以下命令/触发器：
  - 命令：`前瞻兑换码 <游戏名>` — 查询并返回前瞻兑换码内容与封面图片。
  - 命令：`伪造聊天记录 <QQ> <昵称> <内容>` — 返回一条伪造的消息节点（仅演示用途）。
  - 正则触发：`^赞我$` — 给发送者执行点赞流程（有重试、限额与错误处理）。
  - 正则触发：包含“胡桃”且包含 `http` 的消息 — At 配置中的 QQ 并回复提示（使用 `HuTao_config`）。

## 核心实现文件

- `main.py` — 插件主入口，注册 `MiaoPlugin`，包含命令注册、事件监听、定时任务与点赞逻辑。

主要类/方法：
- `MiaoPlugin`（注册名 `astrbot_plugin_miao`）
  - `initialize`：初始化并启动 `AsyncIOScheduler`。
  - `投递任务`：注册定时任务（当前为每日 cron 任务）。
  - `打卡任务`：遍历机器人群列表并调用 `send_group_sign`。
  - `点赞任务`：读取配置 `send_like_list`，批量对列表中 QQ 执行点赞。
  - `_like_single_user` / `_execute_like_for_user`：点赞实现，包含错误与限额处理。
  - `_capture_bot_instance`：在接收到消息事件时捕获 `aiocqhttp` 平台的 bot 实例。

## 配置示例

在 AstrBot 的配置中为该插件添加配置节，例如：

```toml
[PluginConfig.astrbot_plugin_miao]
Master = 123456789       # 管理员 QQ，用于接收每日任务结果（可选）
send_like_list = [11111111, 22222222]  # 批量点赞目标 QQ 列表（可选）
HuTao_config = 987654321 # 发现“胡桃+链接”时要 At 的 QQ（可选）
```

说明：
- `Master`：若配置则每日任务结束后会把执行结果私信该 QQ。
- `send_like_list`：为空或未配置则跳过批量点赞任务。
- `HuTao_config`：指定被 At 的 QQ，用于检测到“胡桃+链接”的消息时提醒。

## 使用方法

1. 将插件目录（`astrbot_plugin_miao`）放入 AstrBot 插件目录 `data/plugins/`。
2. 在 Bot 配置中加入或修改插件配置项（如上示例）。
3. 启动或重启 AstrBot。插件在接收到事件后可自动捕获 `aiocqhttp` 的 `bot` 实例。
4. 可通过聊天发送命令触发功能或等待每日定时任务执行。

## 注意事项

- 该插件使用 `apscheduler.schedulers.asyncio.AsyncIOScheduler`，运行环境需支持异步调度。
- 点赞操作会多次调用 `send_like`，若平台有风控或权限限制，可能返回错误或被限制，插件包含基础异常处理与限额提示。
- 请勿将 `伪造聊天记录` 用于骚扰或违法活动；仅用于演示/测试。

## 开发与扩展

- 如需修改逻辑，可编辑 `main.py` 中对应方法（例如点赞策略、定时任务调度或前瞻兑换码接口）。
- 若需支持其他平台（非 `aiocqhttp`），需在 `_capture_bot_instance` 中增加相应平台的检测与赋值逻辑。

---

实现：`MiaoPlugin`（由 `register("astrbot_plugin_miao", "miao", ...)` 注册）
