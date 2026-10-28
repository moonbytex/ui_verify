# devecocli verify 流程

一次 `devecocli verify` 分成四个地方跑：

| 位置 | 是什么 | 做什么 |
| --- | --- | --- |
| 本机，`devecocli` 进程 | CLI | 读参数和模型配置、选定设备序列号、拉起 MCP、收进度、把日志和截图缓存到本机 |
| 本机，另一个 Node 进程 | `ui-verification-mcp` | 多模态模型决策、调度各个智能体、通过 `hdc` 操作设备 |
| 模型服务 | `verify init` 里配置的 `baseUrl` | 看截图，返回下一步动作或当前状态。不在设备上 |
| 设备或模拟器 | HarmonyOS | 被 `hdc shell` 点击、滑动、启动应用、截图。模拟器额外会被本机的 `Emulator` 程序旋转、折叠、快速截图 |

CLI 不看截图，也不点屏幕。点屏幕和判对错都在 MCP 进程里完成。

---

## 总流程

```text
用户
  devecocli verify --test-plan "..." [--device ...] [--bundle-name ...] [--no-fresh-start]
        │
        ▼
CLI 进程
  1. 拼测试计划（最长 3000 字），读取并解密模型配置
  2. hdc list targets，把设备名解析成序列号
  3. spawn node ui-verification-mcp.cjs
     环境变量带上 UI_VERIFY_BASE_URL / API_KEY / MODEL_NAME / HDC_PATH
  4. stdin 写一行 JSON-RPC：initialize
  5. stdin 再写一行：tools/call verifyUI
     参数是 testPlan、bundleName、freshStart、device（序列号）
  6. 读 stdout。进度通知刷新命令行；整次调用最多等 10 分钟
  7. 再用 tools/call 调 getLog、saveScreenshot，写入本机缓存
  8. 关掉子进程，打印 JSON
        │  stdin / stdout，一行一条 JSON-RPC 2.0
        ▼
MCP 进程（所有智能体都在这一个进程里）
  1. 用环境变量里的地址创建模型客户端，按模型名选择坐标算法
  2. 再确认一次设备，加任务锁，后台开始截图
  3. InputValidationAgent：这份计划能不能在当前设备上做
  4. freshStart 为真时：按 Home，并让 InputMatcherAgent 找可复用的历史步骤
  5. 循环，直到 completed 或 error，最多 30 轮：
       稳定截图
       StatusAgent 看图判状态  与  ActionAgent 看图出下一步   同时进行
       normal  → 执行已经要好的那一步
       abnormal → 丢掉那一步，按最新判断再要一次动作并执行
  6. SummaryAgent 写成功步骤和失败步骤
  7. 对比任务前后的 faultlog，把结论和 id 返回给 CLI
```

`freshStart` 默认是真。命令行写 `--no-fresh-start` 才变成假：不按 Home，也不复用历史步骤。

返回给用户的 JSON 只有五字段：`success`、`reason`、`successPart`、`failPart`、`id`。`verify log --id` 和 `verify screenshot --id` 读的是 CLI 缓存在本机的副本，不再连设备。

---

## 分述

### 1. CLI 如何调用 MCP

相关代码：

- 命令入口：`deveco-cli/packages/cli/src/commands/verify.ts`
- 编排：`deveco-cli/packages/cli/src/ui-verification/verification-adapter.ts`
- 子进程和 JSON-RPC：`deveco-cli/packages/cli/src/ui-verification/mcp-session.ts`
- 选设备：`deveco-cli/packages/cli/src/ui-verification/device.ts`

`devecocli verify` 自己不实现测试。它找到依赖包里的 `node_modules/ui-verification-mcp/bin/ui-verification-mcp.cjs`，用当前 Node 把它拉起来。这个 cjs 只做一件事：再启动同包的 `dist/uiVerification.mjs`，并把标准输入输出原样接过去。所以协议的对端是 `uiVerification.mjs`。

会话固定三步：

1. `initialize`，协议版本 `2024-11-05`，客户端名字 `devecocli`。
2. `tools/call`，名字 `verifyUI`。若带了进度回调，`_meta.progressToken` 就是这次请求的 id。MCP 每判一次状态，就往 stdout 写一条 `notifications/progress`，CLI 把它显示成 `进度 原因`。
3. 成功或失败返回后，再调 `getLog`、`saveScreenshot`。这两个工具只读 MCP 进程内存里按 id 记下的 hilog 和截图，不重新操作设备。

子进程的 stderr 被丢掉。stdout 上不是合法 JSON 的行也会被忽略。用户按 Ctrl+C 时，CLI 中止等待，Windows 上用 `taskkill /t /f` 结束整棵进程。

模型地址、密钥、模型名不放进 `verifyUI` 的参数，只放进子进程环境变量。`hdc` 可执行文件的路径同样用 `UI_VERIFY_HDC_PATH` 传下去。CLI 传给 `verifyUI` 的 `device` 已经是序列号，例如 `127.0.0.1:5555`。

包名优先用 `--bundle-name`。没写时，从当前目录的 `AppScope/app.json5` 读。

### 2. MCP 怎么运行

`uiVerification.mjs` 作为主模块启动时做三件事：确定日志目录、按模型名准备对话方式和坐标算法、在 stdin 上开始读 JSON-RPC。

- 日志目录来自 `LOG_PATH`，否则用系统临时目录下的 `ui-verification`。每次任务一个 `sequence-log-<时间>` 目录，里面是 `history.md` 和截图。
- 模型名匹配 `/qwen2\.5/i` 时，用文本里嵌工具说明的对话方式，坐标按截图像素解释。其他模型用 OpenAI 兼容的 tools 字段，并告诉模型「屏幕是 999×999」。
- 请求发到 `{UI_VERIFY_BASE_URL}/chat/completions`。MCP 进程发，设备不发。

对外注册三个工具，都在这个进程里执行：

| 工具 | 作用 |
| --- | --- |
| `verifyUI` | 跑完整段测试，返回五字段结果 |
| `getLog` | 按 id 取这次任务收集的 hilog |
| `saveScreenshot` | 按 id 把内存里的截图写到调用方给的目录 |

`verifyUI` 一开始会在设备 `/data/local/tmp` 放一个锁文件，并每 10 秒刷新。15 秒内已经有别的锁，就拒绝并发。结束时删锁。

同一次 `verifyUI` 里，计划校验、历史匹配、按 Home 三件事并行。进入主循环后，每一轮的「判状态」和「想下一步」也并行，都拿同一份历史，都看同一批截图。只有判完状态，才决定用不用已经想好的那一步。

### 3. 智能体怎么配合

六个智能体都是 MCP 进程里的类，没有各自的进程。它们共享第 6 节的那一份历史数组。每个智能体发给模型的消息格式在第 7 节。判状态和写总结时会跳过 `log`，所以 hilog 不参与对错判断。

| 智能体 | 何时出现 | 看什么 | 必须调用的工具 | 产出 |
| --- | --- | --- | --- | --- |
| InputValidationAgent | 一开始 | 计划原文 + 设备能力清单 | `get_input_validation_result` | `valid` 或 `inValid`。不通过则直接失败，原因以 `[计划校验失败]` 开头 |
| InputMatcherAgent | 仅 `freshStart` 为真，且本机有同设备同包名的步骤记忆 | 用户计划 + 已保存计划列表 | `get_match_result` | 一份可重放的历史，或不用 |
| FakeActionAgent | 匹配到历史时，代替第一轮 ActionAgent | 保存的动作序列 | 不调模型 | 在设备上重放。新截图和旧截图像素差大于 1% 就停，后面改走正常循环 |
| ActionAgent | 每轮 | 计划 + 历史截图和以往动作 | `tap`、`startApp` 等设备工具；也可以不调用，表示这轮不做操作 | 一个动作。执行前会先清掉截图缓存，保证之后的图都是动作之后的 |
| StatusAgent | 每轮，和 ActionAgent 同时问模型 | 计划 + 历史截图 | `returnStatus` | `normal` / `abnormal` / `completed` / `error`，外加 `progress`、`total`、原因 |
| SummaryAgent | 只在 `completed` 或 `error` 之后 | 全部历史 | `get_summary_result` | `successPart`、`failPart` |

一轮里的分支：

- `normal`：把状态写入历史，执行这一轮已经要好的动作。普通动作之后最多等 4 秒，直到画面像素发生变化；`inputText` 和 `touchDown` 固定再等 0.8 秒。
- `abnormal`：这轮预取的动作作废。把异常原因写进历史，再叫 ActionAgent 基于最新截图重做一步。连续 abnormal 默认 3 次仍停在同一步，状态会被改成 `error`。
- `completed`：总结，查 faultlog，若还有没松开的长按则补一次 `touchUp`，返回成功。
- `error`：同样总结和查 faultlog。若中途没有 `abnormal`、本次 `verifyUI` 的 `freshStart` 为真、且历史里第一个动作是 `startApp`，就把走到最后一个 `normal` 为止的步骤存成 step memory，供下次匹配重放。
- 总轮数默认 30（`UI_VERIFY_MAX_EXECUTION_ROUNDS`）。到上限仍不是完成或失败，就改成 `error` 并写明是为了避免死循环。

最近 3 次 `normal` 的原因、进度、总步数完全一样时，会额外塞一句系统提醒，要求 StatusAgent 重新看计划和图，不要原样重复判断。

模型每次只被允许返回一个工具调用。参数用 JSON Schema 校验，不合法就把错误塞回对话再问，最多 3 次。ActionAgent 还有一条硬约束：`touchDown` 的下一步必须是 `touchUp`，不能在中间插入等待或滑动。

### 4. 模块怎么交接

```text
CLI                          MCP 进程                         设备
 │                            │                               │
 │  verifyUI(计划,包名,序列号) │                               │
 │ ─────────────────────────► │ beforeTask                    │
 │                            │  hdc 选设备、建锁、开截图循环 ──► │
 │                            │                               │
 │                            │ 智能体 ◄──HTTP──► 模型服务     │
 │                            │    │                          │
 │                            │    └─ hdc shell uitest/aa/... ► │
 │  notifications/progress    │                               │
 │ ◄───────────────────────── │                               │
 │                            │                               │
 │  {success,reason,...,id}   │                               │
 │ ◄───────────────────────── │ afterTask：停截图、删锁        │
 │                            │                               │
 │  getLog / saveScreenshot   │ 只读本进程内存，不再碰设备      │
 │ ◄───────────────────────── │                               │
 ▼                            ▼                               ▼
CLI 结果缓存                  MCP 运行目录                   应用界面被操作
```

### 5. 目录：结果缓存和运行日志不是同一个

本机临时目录记为 `os.tmpdir()`。Windows 上一般是 `C:\Users\<用户名>\AppData\Local\Temp`。

| 目录 | 谁写入 | 内容 | 谁来读 |
| --- | --- | --- | --- |
| `<临时目录>/ui-verification/cache/<校验 id>/` | CLI，在 `verifyUI` 返回之后 | `verify.log`，以及 `screenshots/` 下的截图文件 | `devecocli verify log --id`、`devecocli verify screenshot --id` |
| `<临时目录>/ui-verification/sequence-log-<时间>/` | MCP 进程，任务进行中 | `history.md`、`log.md`、`imgN.jpeg`。这是引擎自己的运行记录 | 人直接打开这个目录看。CLI 不读它 |
| `<临时目录>/ui-verification/stepMemory/` | MCP，仅在上面说的失败保存条件成立时 | 可重放的步骤，版本号 `1.0.2`。文件名是「会话 id、设备名、包名」 | 下一次同设备、同包名、且 `freshStart` 为真的 `verifyUI` |
| `<临时目录>/ui-verification/faultlogs/` | MCP，任务结束时 `checkError` | 本次新出现的 faultlog 文件 | 路径被拼进返回的 `reason` |

`cache` 最多留 15 个 id 目录，按修改时间删最旧的。`sequence-log-*` 最多留 50 个。环境变量 `LOG_PATH` 如果已经设置，MCP 的 `sequence-log` 和 `stepMemory` 改写到那个目录；`cache` 和 `faultlogs` 仍在临时目录下的 `ui-verification` 里。CLI 拉起子进程时不会另设 `LOG_PATH`。

`verify log` 读的是 `cache/<id>/verify.log`。MCP 进程退出后，内存里的历史就没了，但这个文件还在。

### 6. 历史数组

一次 `verifyUI` 里只有一份历史，类型是数组，按时间追加，不按步骤号分组。六个智能体读的是同一份。它不是对话记录本身。每个智能体发请求前，再按自己的规则把这份数组翻译成 `system` / `user` / `assistant` / `tool` 消息。

数组元素只有四种，用 `type` 区分。

`image`**：一次采集到的一帧或多帧**

```text
type: "image"
base64List: 按时间从早到晚的 JPEG 或 PNG，base64，不带 data URI 前缀
screenSize: [屏幕宽, 屏幕高]   物理像素，取这一组帧最后一帧当时的屏幕尺寸
timestamp: 写入历史的时刻（毫秒）
```

每一帧在截图缓存里还带有 `diff` 和自己的 `timestamp`，但写入历史时 `diff` 被丢掉，只保留图像和这一组共同的 `screenSize`。

`action`**：已经决定的一步操作**

公共字段是 `id`、`type: "action"`、`name`、`reason`、`timestamp`。`name` 决定其余字段：

| name | 另外保存的字段 |
| --- | --- |
| `tap` / `doubleTap` / `touchDown` | `point: [x, y]`，仍是模型给出的坐标，不是换算后的物理像素 |
| `swipe` | `startPoint`、`endPoint` |
| `mouseClick` / `mouseDoubleClick` | `point`、`buttonId`（0 左键，1 右键） |
| `mouseScroll` | `point`、`direction`（`up` 或 `down`）、`ticks` |
| `pressKey` | `keyName`（规范化后的键名数组）、`error`（成功为 `null`） |
| `inputText` | `point`、`input`、`mode`（`clearAndInput` 或 `append`） |
| `startApp` | `bundleName`、`freshStart`、可选 `uri`、`error` |
| `sleep` | `duration`，单位毫秒 |
| `touchUp` | 无坐标。执行时回读前面最近一次 `touchDown` 的 `point` |
| `setFoldState` / `setRotation` | `state` 或 `rotation`，以及 `error` |
| `none` | 只有 `reason`。表示模型这一轮没有调用工具 |

`point` 保持模型坐标系里的数。真正发给 `uitest` 的物理像素不写入历史，下次换算时重新计算。

`status`**：StatusAgent 这一轮的判断**

```text
type: "status"
id: 这次 returnStatus 工具调用的 id
status: completed | normal | abnormal | error
reason, progress, total
abnormalRetryCount, maximalAbnormalRetries
timestamp
```

`log`**：这一段时间的 hilog 原文**

```text
type: "log"
content: 字符串，可能为空
timestamp
```

`log` 会进 `history.md` 旁的 `log.md`，也会被 `getLog` 拼起来。翻译成模型消息时，ActionAgent、StatusAgent、SummaryAgent 都跳过 `log`。

一轮正常推进时，数组尾部的顺序是：

```text
… → image → status → log → action →（下一轮再取图）→ image → …
```

`abnormal` 时预取的动作不执行，数组里先追加这条 `status`，再由新的一轮 ActionAgent 追加它自己的 `log` 和 `action`。任务开始时的第一条是当前画面的 `image`。`freshStart` 为真且按了 Home 时，Home 发生在这条 `image` 之前，不单独记成 `action`。

### 7. 每个智能体的上下文

发给模型的是消息数组。发之前还有一道公共限制：带图片的 `user` 消息最多保留 3 条、图片最多 12 张。超出时从最早的图片消息开始，把其中的图片换成文本「已省略历史截图」。图片总数已经超过 12 张时，只保留最近 2 条图片消息。文字消息不动。

下面的「计划文本」都是同一段：

```text
待测试应用bundleName：<包名>
测试开始时是否重新启动应用：true 或 false
测试计划：
<用户的 --test-plan>
```

**InputValidationAgent** 不看历史，也不看截图。两条消息：

1. `system`：计划规范性提示词。
2. `user`：一段 JSON，四项设备信息（`deviceType`、`isEmulator`、`foldableInfo`、`supportedOperations`），然后是用户测试计划原文。

**InputMatcherAgent** 也不看截图。三条消息：`system` 是匹配规则；第一条 `user` 是 `用户计划：<原文>`；第二条 `user` 是 `已执行的计划列表：` 加上 step memory 里已有计划摘要的 JSON 数组。模型返回的 `index` 用来取出对应的那份历史数组。

**ActionAgent** 的消息是：

1. `system`：操作提示词。内容随设备类型变化（手机、平板、2in1 的默认输入方式不同）。模拟器还会加上当前物理方向。最后拼上坐标约定：普通模型是「屏幕宽高为999x999，坐标原点在左上角」；`qwen2.5` 这段为空。
2. `user`：上面的计划文本。
3. 之后按历史逐条翻译：
   - `status` 变成 `user` 文本：`当前状态：<status> 原因：<reason>`。
   - `image` 变成一条 `user`，内容是 `base64List` 里的每一帧，类型为 `image_url`，URL 形如 `data:image/jpeg;base64,...`。同一条 `image` 的多帧在同一条消息里，顺序就是采集顺序。
   - `action` 且 `name` 不是 `none`：变成一条 `assistant`（`content` 是 `reason`，并带一个还原出来的 `tool_calls`），再跟一条 `tool`。`tool` 的正文一般是 `Action executed`。`touchDown` 会多一句必须再调用 `touchUp` 的提醒。`setFoldState`、`setRotation` 失败时正文是 `Action failed:` 加错误文本。
   - `name` 为 `none` 的动作只变成一条 `assistant`，内容是 `reason`，没有 `tool`。
   - `log` 不出现。

模型只能返回一个工具调用。ActionAgent 再检查：若历史里最近一个有效动作是 `touchDown`，这次必须是 `touchUp`；反过来，没有未配对的 `touchDown` 时不许直接 `touchUp`。

**StatusAgent** 的消息是：

1. `system`：状态判断提示词。模拟器上再追加一段：当前物理方向是多少，判断横竖屏必须以这个方向为准，`reason` 里必须写明该方向。
2. `user`：`用户计划：` 加上同一段计划文本。
3. 历史的翻译和 ActionAgent 相反：
   - `status` 变成 `assistant` 的 `returnStatus` 工具调用，参数是当时的 `reason`、`status`、`progress`、`total`，再跟一条内容为 `received` 的 `tool`。
   - `action` 变成 `user` 纯文本，格式是 `思考：<reason>；执行操作：<动作的中文描述>`。描述里的坐标仍是历史里保存的模型坐标。
   - `image` 同样变成一条带多帧 `image_url` 的 `user`。
   - `log` 不出现。
4. 若最近 3 次 `status` 的 `status`、`reason`、`progress`、`total` 完全相同，并且都是 `normal`，再追加一条 `user`，正文以「【系统重复状态检测提醒】」开头。

**SummaryAgent** 在 `completed` 或 `error` 之后调用一次。`system` 是总结规则。历史不再拆成多轮工具对话：连续的文字拼进同一条 `user`，每张图片单独成一条只含这一帧的 `user`。文字包括 `当前状态：…` 和 `执行操作：…，原因：…`。`log` 仍然不出现。

**FakeActionAgent** 不调用模型。它从匹配到的历史数组第 2 项开始回放：遇到 `action` 就按其中的坐标再执行一遍，按原时间间隔等待，再截一张新图写入当前历史；遇到旧的 `image` 就和当前最后一帧做像素差，差大于 0.01 就停止回放。

---

## 重点问题

### 1. 定位：截图怎么处理，坐标怎么变成点击

定位不读控件树，也不按文本或控件 id 查找。模型只看位图，在工具参数里给出一个点；程序再把这个点换成 `uitest` 使用的物理像素。送给模型的图始终保留状态栏。状态栏只在计算像素差时从比较区域里裁掉。

用到两个坐标系：

- 屏幕坐标系：原点在左上角，x 向右，y 向下，单位是物理像素。`hidumper` 读到的 `Width`、`Height` 就是这个坐标系的宽高。`uitest uiInput click x y` 用的也是它。
- 模型坐标系：由下面两种定位器二选一。模型输出的 `point` 属于这个坐标系，写入历史时也不改成物理像素。

#### 1.1 后台持续截图

`beforeTask` 量出状态栏高度后，启动一个截图循环，任务结束才停。

状态栏高度：2in1 设备固定为 0。其他设备执行 `hidumper -s WindowManagerService -a '-a'`，在包含 `SCBStatusBar` 的那一行里取矩形的第四个整数，当作状态栏底边的 y，也就是高度。量不到就抛错，任务起不来。

循环有两条实现，任务开始时选定一条：

- 模拟器，且本机 `Emulator` 主版本不低于 26：循环调用 `Emulator -instance <实例名> -screenshot`，拿到的是帧缓冲里的原始 PNG，尚未旋转、尚未缩放。
- 其他情况（真机，或模拟器不满足上面的条件）：循环执行 `hdc shell snapshot_display`。设备直接写出 JPEG。若定位器给出了目标宽高，命令带 `-w` 和 `-h`，缩放在设备上完成。文件再用 `base64 -w 0` 读回。这条路径不做旋转。

每一帧先和上一帧算像素差，再放进内存缓存。`screenshot()` 被调用时把缓存整段取走并清空。缓存空则最多等 5 秒。模拟器路径每 50 毫秒看一次缓存，真机路径每 100 毫秒看一次。

像素差的定义：两帧解码后，只比较裁剪区域里的像素，差异像素数除以该区域的像素总数，结果在 0 到 1。裁剪区域是 `{ x: 0, y: 状态栏高度 }`，宽度取图像全宽，高度取「图像高度减 y」。也就是去掉顶部状态栏那一条，避免时钟跳动被当成界面变化。裁剪区域超出图像时，这次比较退回整幅图。这个裁剪不改变送进历史、送给模型的那张图。

`beforeTask` 只创建采集对象，不启动循环。第一次调用 `screenshot()` 时才把循环跑起来。

采集和取用是两条线：

- 采集循环只负责往缓存数组末尾追加帧，自己不决定哪一帧送给模型。真机路径成功时不插入等待，下一张紧接着拍，速度由 `snapshot_display` 本身耗时决定；失败只打印错误，下一轮继续。模拟器路径成功时同样连续抓；失败则等 500 毫秒再试。
- `screenshot()` 是取用。缓存里已经有帧，就整段拿走并清空，调用方得到这一段数组。缓存是空的，就轮询等待，最多 5 秒，超时抛「截图超时」。取走之后采集循环继续往空缓存里放新帧。
- `waitUntilChange(超时毫秒)` 不取走缓存。它记下调用时刻，然后轮询：出现「时间戳晚于该时刻，且像素差超过阈值」的帧就返回。真机阈值是 0.001，模拟器阈值是 0.01。到超时也只是返回，不报错。

像素差始终相对「上一张已经拍到的帧」，跨过一次取走也一样。真机在取走时记住被拿走的最后一帧；取走后的第一张新帧跟这张比，比完就忘掉这张参照。模拟器则一直留着上一张的解码结果，每张新帧都跟紧邻的前一张比。所以一段缓存里，开头几帧的 `diff` 很小表示画面还没变，第一次变大的 `diff` 表示从这里开始画面变了。

一次点击在时间上是这样走的：

1. 模型还在思考时，采集循环已经在缓存里堆积当前画面。这些帧还没人要。
2. 决定执行动作之后、真正点击之前，先调用一次 `screenshot()`，把思考期间堆积的帧全部丢掉。这一步的返回值不写入历史。目的是让缓存从「点击前的最后一张」之后重新开始。
3. 执行 `uitest` 点击。这段时间新拍到的帧留在缓存里。
4. `sleep` 不再等待。`touchDown` 和 `inputText` 固定再等 800 毫秒。其他动作调用 `waitUntilChange(4000)`：从点击命令返回之后算起，最多等 4 秒，直到缓存里出现一张相对前一张有变化的新帧。4 秒内没有变化也继续往下走。
5. 回到主循环。此时历史最后一项是刚执行的 `action`，不是 `image`，于是进入第 1.3 节的 3 秒采集：反复 `screenshot()` 把缓存取走，直到画面稳定或满 3000 毫秒。取走的帧里，点击前没变化的开头会被丢掉，剩下的才写成一条 `image` 送给模型。

因此模型下一轮看到的，是点击之后、并且已经去掉「还没变化」开头的那几帧，不是点击前思考时拍的图。任务开始时的第一张图例外：第一次 `screenshot()` 取走的那段里，只把最后一帧写进历史。

#### 1.2 模拟器原始 PNG 如何转正、如何编码

只对 `Emulator -screenshot` 的 PNG 做。`snapshot_display` 的 JPEG 已经是当前显示方向，不再转。

方向用 0 到 3 的整数表示，每增加 1 是顺时针 90°：0 竖屏，1 向右 90°，2 旋转 180°，3 向左 90°（横屏）。

任务开始时做一次对齐，只对非 2in1 的模拟器做：

1. 取一张系统截图（`snapshot_display`，不缩放）和一张模拟器原始 PNG。
2. `compareImageRotation` 试旋转，得到一个 0 到 3 的差 `r`，含义是「原始 PNG 相对系统截图，顺时针差 `r` 个 90°」。尺寸怎么转都对不上就失败，任务终止。
3. 再读 `hidumper -s DisplayManagerService` 里 `[SCREEN INFO]` 的 `Rotation`，记为系统方向 `sys`。模拟器物理方向缓存为 `(sys + r) mod 4`。

之后每一帧：

1. 再次读取当前的 `sys`。
2. 顺时针需要补偿的 90° 个数为 `(sys - 模拟器物理方向 + 4) mod 4`。
3. 调用图像编码：先按这个圈数顺时针旋转，再缩放到目标宽高，最后编码成 JPEG，质量参数是 80。旋转为 0 且没有目标尺寸时才原样保留 PNG；当前两种定位器都会给出目标尺寸，所以实际都会变成 JPEG。

2in1 上不计算这个转角，旋转参数固定为 0。若原始 PNG 的宽等于屏幕宽，并且 `原始高度 / 2 - 40` 仍不小于屏幕高，视为磁吸状态下帧缓冲比逻辑屏幕更高，编码前先从左上角裁到屏幕宽高，再缩放。

目标宽高由定位器决定，见 1.4。编码后的图和当时的 `screenSize: [屏幕宽, 屏幕高]` 一起放进缓存。`screenSize` 是逻辑屏幕的物理像素，不是这张位图的宽高。

#### 1.3 三秒内怎么抓一批稳定帧

主循环每一轮开始时，如果历史最后一项已经是 `image`，这一轮不再抓。第一条历史就是开始时的一张图，所以第一轮直接拿它去问模型。执行完动作后，历史末尾是 `action` 或 `log`，下一轮才进入这里。

抓取函数收到上一轮留下的帧列表（每轮判断完会把这份列表清空，所以通常从空列表开始），然后：

1. 截止时间是调用时刻加 3000 毫秒。
2. 在截止时间之前反复调用 `screenshot()`。每次把后台缓存里已经积压的帧全部取走，按顺序接到列表后面。
3. 每接完一次就检查是否已经稳定。稳定的条件同时满足：至少两帧；最后一帧相对前一帧的像素差不大于 0.01；从最后一帧往前，这些帧的像素差都小于 0.01，并且这段的时间跨度不少于 800 毫秒。满足就立刻停止，不等满 3 秒。
4. 到了 3000 毫秒仍不稳定，也停止，用已经拿到的帧继续后面的挑选。

挑选分四步，阈值 0.001 与上面的 0.01 不是同一个数：

1. 丢掉开头连续「像素差小于 0.001」的帧。若全部都小于 0.001，只留最后一帧。
2. 按时间排序后抽样：相邻保留帧的时间间隔至少 500 毫秒，并且一定保留最后一帧。
3. 保留最后一帧，以及「下一帧相对它的像素差大于或等于 0.001」的那些帧。静止重复帧被去掉。
4. 仍多于 6 帧时，留前 3 帧、最后 1 帧，再从中间帧里取像素差最大的 2 帧，然后按时间排回原顺序。

挑出来的帧写成历史里的一条 `image`：`base64List` 按时间从早到晚，`screenSize` 用最后一帧的屏幕尺寸。模型在一条消息里按这个顺序看到多帧。提示词要求：Toast、短弹窗只要任一帧出现就算出现；暂停、停止这类状态以末尾几帧是否稳定为准。

#### 1.4 「缩到屏幕的 2/3」是什么意思

这只指导普通模型（模型名不匹配 `qwen2.5`）。它改变的是位图的像素尺寸，不改变模型坐标系。

定位器给出的目标尺寸是：

```text
目标宽 = floor(屏幕宽 × 2 / 3)
目标高 = floor(屏幕高 × 2 / 3)
```

宽和高用同一个比例，宽高比不变。1260×2720 的屏幕得到 840×1813 的位图。真机由 `snapshot_display -w 840 -h 1813` 在设备上缩放；模拟器由上面的 JPEG 编码缩放到这个尺寸。送给模型的图就是这张较小的位图，用来减少图像 token。模型并不知道 840 和 1813。它的系统提示只说屏幕是 999×999，原点在左上角。它输出的 `point` 是 999×999 里的数，不是这张位图上的像素。

`qwen2.5` 不用 999，也不用 2/3。目标宽高先各自取整到 28 的倍数；若长边超过 1424，按比例缩小后再对齐 28；若短边小于 480，按比例放大后再对齐 28。系统提示里不追加坐标说明。模型输出的数被当作这张位图上的像素。

#### 1.5 「钳制到 [1, 屏幕尺寸]」是什么意思

模型给出的点先换算成物理像素，再钳制（clamp）到屏幕范围内，最后才传给 `uitest`。两个轴分开算。设屏幕宽为 `W`、高为 `H`，都是物理像素。

普通模型，`point` 为 `[x, y]`（999×999 坐标系）：

```text
像素 x = clamp(round(x × W / 999), 1, W)
像素 y = clamp(round(y × H / 999), 1, H)
```

`clamp(v, 1, W)` 的意思是：`v < 1` 时取 1，`v > W` 时取 `W`，否则取 `v`。y 轴对 `H` 同样处理。所以结果是整数，且一定落在闭区间 `[1, W]` 和 `[1, H]` 里。不会发出 0，也不会发出超出屏幕的坐标。

例如屏幕 1260×2720，模型给出 `[0, 0]`，换算得到 0，钳制后是 `(1, 1)`。给出 `[999, 999]`，得到 `(1260, 2720)`。给出 `[1200, 500]` 时，x 的四舍五入结果是 1513，大于 1260，钳制为 1260；y 是 1361，落在区间内，保持 1361。

`qwen2.5` 把 `point` 当作位图像素。位图宽高记为 `Iw`、`Ih`：

```text
像素 x = clamp(round(x × W / Iw), 1, W)
像素 y = clamp(round(y × H / Ih), 1, H)
```

换算使用的位图尺寸，是历史里最后一张图解码得到的宽高。使用的 `W`、`H` 优先取那条 `image` 上记录的 `screenSize`；没有这份记录时，再当场调用 `hidumper` 读屏幕尺寸。`tap`、`doubleTap`、`swipe` 的起点和终点、`inputText`、`touchDown`、鼠标点击和滚轮，都用这一套。`touchUp` 不再向模型要坐标，沿用与它配对的那次 `touchDown` 的 `point`，用当前最后一张图重新换算。

换算后的整数通过 `hdc shell` 执行：`uitest uiInput click`、`doubleClick`、`swipe`，或 `uinput` 的按下、抬起和鼠标。输入文字是先在该像素上点击，再发送按键和 `uitest uiInput text`。

模型认的是图上的文字、图标和位置。点偏了，下一轮用新截图重算。`abnormal` 的提示要求按最新截图重新定位，禁止沿用上一次的坐标。

### 2. 有没有把「点错」和「程序无响应」分成两类

没有单独的两类结论。返回给 CLI 的状态只有模型给出的四种：`normal`、`abnormal`、`completed`、`error`。点偏、点了没反应、页面上根本没有目标，都是 StatusAgent 看前后截图后归进这四种，不会返回「点击错误」或「无响应」这种独立原因码。

可以分开看的，是三套互不替代的信号：

| 信号 | 谁产生 | 用来判断什么 | 不用来判断什么 |
| --- | --- | --- | --- |
| 模型看图 | StatusAgent | 这一步的界面是否符合计划里写的预期。点错、没点到、弹窗挡路、目标不存在，都在这里 | 不读 hilog，也不读 faultlog |
| 像素是否变化 | 动作之后的等待，以及 FakeActionAgent 的重放比对 | 画面有没有动。4 秒内相对上一帧的差异超过阈值就认为动了；重放时差异超过 1% 就停止复用历史 | 不能区分「点偏了所以界面走错」和「进程卡住所以界面不动」。两者看起来都是图没按预期变 |
| 新增 faultlog | 任务结束时 `checkError` | 用 `hidumper` 列出 faultlogger。任务期间新出现的 `appfreeze`、`cppcrash`、`jscrash`、`serviceblock`、`sysfreeze`、`syswarning` 会被拉到本机，并在 `reason` 后面加一句下载路径 | 不改变 `success`。模型判了完成，这里仍可能附上崩溃或冻屏日志；模型判了失败，这里也只是把日志路径拼进原因 |

因此：

- 点错，体现在下一张截图不符合该步预期。还能恢复就 `abnormal`，再按新图重试；页面上明确没有计划要求的元素、或无法恢复，就 `error`。多次滑动画面都不动，提示里把这种情况说成可能已经滑到列表边缘，多次无效再判错。
- 程序无响应，没有在循环里做主线程超时检测。界面冻住时，模型只能看到「操作后图不变」，和点空了是同一类视觉结果。只有结束时如果系统已经写出 `appfreeze` 一类 faultlog，才会在最终 `reason` 里多一句话。测试过程中收集的 hilog 会存进历史和 `verify.log`，但不喂给 StatusAgent。

### 3. 走 hdc，还是走 devecocli 指令

操作设备不调用 `devecocli`。`devecocli verify` 只是用户进来的入口。进了 MCP 之后，设备动作都是 MCP 进程自己执行 `hdc`。

两条路上的 `hdc` 各干各的：

- CLI 只用 `hdc` 做 `list targets`（经 `HdcAdapter`），把「设备名或序列号」收成一个序列号，放进 `verifyUI` 的 `device` 参数。同时把本机 `hdc` 的路径放进 `UI_VERIFY_HDC_PATH`。
- MCP 用这个路径自己再执行 `hdc`。没配路径时，退回到 `DEVECO_HOME` 或 `DEVECO_PATH` 下的 `sdk/default/openharmony/toolchains/hdc`，再没有就用 `hdc` 这个命令名。它会再列一次设备，用 CLI 传来的序列号对准目标，之后所有命令都带 `-t <序列号>`。

MCP 里实际发出的命令是这些，都不是 `devecocli` 子命令：

| 目的 | 命令 |
| --- | --- |
| 点击、双击、滑动、按键、输入文字 | `hdc shell uitest uiInput ...` |
| 按下不放、松开、鼠标移动点击和滚轮 | `hdc shell uinput ...` |
| 启动、按 URI 跳转、冷启动前强停 | `hdc shell aa start` / `aa force-stop` |
| 查入口 Ability | `hdc shell bm dump -n <包名>` |
| 截图（真机，以及模拟器截图不可用时） | `hdc shell snapshot_display`，再用 `base64` 读回 |
| 屏幕尺寸、方向、状态栏、已有 faultlog | `hdc shell hidumper ...` |
| 应用日志 | `hdc shell hilog`，读完执行 `hilog -r` |
| 拉 faultlog 文件 | `hdc file recv` |

只有模拟器专有能力不走 `hdc`，改走本机的 `Emulator` 可执行文件（`DEVECO_HOME/tools/emulator/Emulator`，要求主版本不低于 26）：

- 快速截图：`Emulator -instance <名字> -screenshot`
- 横竖屏：`Emulator -instance <名字> -rotation left|right`
- 折叠状态：`Emulator -instance <名字> -foldedState <状态>`
- 识别是不是折叠屏：`Emulator -list -details`

版本不够或找不到这个程序时，截图退回 `snapshot_display`。横竖屏和折叠会直接失败并写进该步的错误信息，不会去调用 `devecocli`。
