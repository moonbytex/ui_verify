# HarmonyOS UI 意图校验

这是一个基于AI的HarmonyOS应用UI自动化验证工具。通过自然语言描述测试步骤，AI可以自动在HarmonyOS设备上执行UI操作并验证结果。

## 功能特性

- **自然语言驱动**：用自然语言描述测试步骤，无需编写代码
- **智能UI识别**：基于AI视觉分析自动识别界面元素
- **多种操作支持**：点击、滑动、输入文本、长按、启动应用等
- **实时截图验证**：每步操作后自动截图验证是否成功
- **MCP服务器集成**：可作为AI助手的工具使用
- **日志记录**：详细的测试过程日志，便于问题排查

## 环境要求

- Node.js 18+
- HarmonyOS设备（模拟器or已开启开发者模式的真机）
- AI视觉模型服务地址与密钥（如阿里云百炼），需要拥有Function Call能力

## MCP配置示例

```json
{
  "mcpServers": {
    "ui-verification-mcp": {
      "command": "npx",
      "args": ["-y", "ui-verification-mcp@latest"],
      "env": {
        "UI_VERIFY_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1", // OpenAI兼容地址
        "UI_VERIFY_API_KEY": "xxxx", // OpenAI兼容Key
        "UI_VERIFY_MODEL_NAME": "qwen3-vl-plus", // 模型名称
        "UI_VERIFY_HDC_PATH": "path/to/hdc/hdc.exe", // hdc的完整路径（如果不指定，会从系统PATH环境变量中获取）
        "UI_VERIFY_MAXIMAL_ABNORMAL_RETRIES": "3", // 单个步骤的异常重试次数上限，默认为3
        "UI_VERIFY_MAX_EXECUTION_ROUNDS": "30", // 单次校验的总执行轮数上限，默认为30
        "UI_VERIFY_MAXIMAL_REPEATED_STATUS": "3" // 重复 Status 检测，默认为3
      },
      "type": "stdio"
    }
  }
}
```

`UI_VERIFY_MAXIMAL_ABNORMAL_RETRIES`、`UI_VERIFY_MAX_EXECUTION_ROUNDS` 和 `UI_VERIFY_MAXIMAL_REPEATED_STATUS` 仅接受大于 0 的整数；未设置或配置值无效时使用上述默认值。

## 提供工具

**工具名称：** `verifyUI`（执行 UI 校验）
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bundleName` | `string` | 否 | 待测试应用的包名，不填时自动从项目 `AppScope/app.json5` 中获取 |
| `testPlan` | `string` | 是 | 自然语言描述的测试用例计划，包含每步操作和预期结果 |
| `freshStart` | `boolean` | 否 | 是否在测试前重新启动应用，默认 `false` |

返回字段：`successPart`（成功步骤描述）、`failPart`（失败步骤描述）、`id`（校验任务 ID，供后续查日志或截图使用）。

---
**工具名称：** `getLog`（获取校验运行日志，辅助定位问题）
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | `string` | 是 | 校验任务 ID |
| `maxLogSize` | `number` | 否 | 日志字符数上限，默认 5000，传 -1 不限制 |
| `searchKeywords` | `string` | 否 | 日志搜索关键词，传空字符串获取完整日志 |

---

**工具名称：** `saveScreenshot`（保存校验截图）
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | `string` | 是 | 校验任务 ID |
| `dirname` | `string` | 是 | 截图保存目录（必须为绝对路径） |

返回该次校验每步操作的截图文件名列表。

## 最佳实践

在配置完MCP服务器后，在AI代码生成工具中建议加上下列Prompt或者Rule，来让AI自我迭代修改：

```markdown
### 构建命令

"C:\Program Files\Huawei\DevEco Studio\tools\node\node.exe" "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.js" assembleHap

### 安装命令（构建完成后）

hdc install entry/build/default/outputs/default/entry-default-unsigned.hap

### 开发注意事项

- 开发完成后，经过构建、安装、运行，最后一定要用 ui-verification-mcp 的 verifyUI 工具进行功能验证，如果存在错误就按照错误原因进行修复，直到功能验证成功
- 如果你需要看日志，请使用 ui-verification-mcp 的 getLog 工具运行后查看日志，不要直接用hilog命令
- 如需查看每步截图，使用 ui-verification-mcp 的 saveScreenshot 工具将截图保存到本地目录
```
