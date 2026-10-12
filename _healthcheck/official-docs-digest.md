# DeepSeek Harness 0.2.0-rc.2 官方随包文档消化（初学者版）

> **来源**：本机安装包 `D:\DeepSeek Harness\resources\app.asar`（121 MB / 12,967 文件）内 `/dsh/node_modules/@deepseek-ai/*/README.zh.md`，共 **279 个中文 README**，全部提取到
> `_healthcheck\asar_dump\docs\<包名>\README.zh.md`。
> 归档内 `/dsh/package.json` 的 `version` 为 `0.2.0-rc.2`，287 个 `@deepseek-ai/*` 依赖全部锁在 `0.2.0-rc.2`。
>
> **标记约定**
> - 「官方原文」＝ 直接引用的中文文档原句。
> - `包名/README.zh.md`「章节」＝ 出处。
> - **【推断】** ＝ 我基于文档作出的推论，不是文档原话。
> - **【文档未说明】** ＝ 随包文档对该问题沉默。
>
> **重要前提**：随包中文 README 是**包级参考文档**，不是用户手册。文档里大量引用的
> `docs/user/guide/index.zh.md`、`docs/config-catalog.zh.md`、`docs/tool-catalog.zh.md`、
> `docs/subsystems/*.zh.md`、`apps/cli/reference/README.zh.md`、`.agents/notes/*` **都不在安装包内**
> （归档 `/dsh` 根目录只有 `package.json`、`desktop-runtime.json`、`node_modules`）。
> 因此本消化只覆盖"随包文档能证明的内容"，无法覆盖官方用户指南级细节。

---

## A. 心智模型：DSH 到底是什么

### A.1 一句话定义

> 「`dsh` 是唯一受支持的 Node 应用启动器；profile 由多个插件组合包 patch 层按顺序叠加而成，其上再应用用户自己的覆盖配置。SDK 与 ACP（Agent Client Protocol）都是 profile，而不是独立的公开可执行命令。」
> —— `dsh/README.zh.md`「概述」

**官方原话里的三个关键词**：
1. **唯一入口**：只有一个启动器 `dsh`，没有第二套公开 bin。`dsh-app-boot/README.zh.md`「概述」明确：「产品应用使用 `dsh` launcher 而不发布单独 bin」。
2. **profile**：同一套 dsh 安装提供不同应用界面的方式。
3. **patch 层**：配置不是一份文件，而是**从空根开始逐层叠加**。

### A.2 底层是 Cordis（插件/组合宿主）

DSH 的运行时是 **Cordis 的组合/插件宿主**：
- 配置树由 X 个 **entry（插件行）** 组成，支持 `insert`、按 id 覆盖、`group`、`disabled`、`isolate`、`!!js` 表达式。
  （来源：`dsh-agent-preset/skills/cordis-composition-reference/SKILL.md` 的 `description` 字段原文）
- Cordis Loader 提供两个 builtin：`cordis:include` 与 `cordis:group`；
  > 「group 行能把一个提供方与它的消费方放进同一个 `isolate` realm」
  > —— `dsh-app-boot/README.zh.md`「两个 Loader builtin」
- 插件之间通过 `ctx.*` 服务通信：`ctx.agents`、`ctx.tools`、`ctx.fs`、`ctx.shell`、`ctx.skills`、`ctx.jobs`、`ctx.sandbox`、`ctx.sandboxPolicy`、`ctx.approval`、`ctx.permissionPresets`、`ctx.sessionProjections`、`ctx.storageDomain`、`ctx.ptcRuntime` 等。
- 插件有 **fiber 生命周期**：加载 → apply → dispose；HMR 由 `dsh-hmr` 统一串行协调。

### A.3 profile 是什么

> 「profile 位于 `$DSH_HOME/profiles/<name>`，由可安装组合包和自身 `cordis.patch.yml` 组成。」
> —— `dsh-app-boot/README.zh.md`「Profile」

目录内容（`dsh/README.zh.md`「Profile」）：
- `package.json`：记录树外插件依赖 + profile manifest（`dsh.profile`），其中 `bundles` 是**有序列表**。
- `cordis.patch.yml`：**用户自己的 patch 层**。
- `node_modules/`：pnpm 把树外插件装到这里。
- （可选）`compatibility.json`：精确版本豁免（见 E.4）。

**配置树的叠加顺序（官方唯一定义）**——`dsh/README.zh.md`「Profile」：

```
空根
 → dsh.profile.bundles 中各组合包的 patch（按 bundles 列表顺序）
 → profile 自身的 cordis.patch.yml
 → home 级的 $DSH_HOME/cordis.patch.yml
 → --patch 指定的覆盖层
```

`dsh-app-boot`「Profile」补充：**用户 patch 层应用在所有组合包层之后（先逐 profile 文件，再 home 级文件，因此后者优先级更高）**；home/单次启动 patch 保留更高优先级（`dsh-plugin-manager/README.zh.md`「使用本包」）。

**patch 的关键语义（最容易搞错的一点）**：
> 「patch 会替换目标行的整个 `config`，而不是合并进它。」
> —— `dsh-base/README.zh.md`「组合机制」
> 「用户 patch 会替换匹配到的整个配置——按 id 定位的 patch 不做深度合并，因此 profile 覆盖必须重述需要保留的组合包字段。」
> —— `dsh-app-boot/README.zh.md`「已知限制与延期工作」

### A.4 profile 有哪些 / 怎么创建

内置 profile 名字（`dsh/README.zh.md`「入口模式」、`dsh-app-boot/README.zh.md`「Profile」）：
`web`、`headless`、`acp`、`sdk`、`sdk-minimal`。`desktop` 名字保留给 Electron 持有的 profile，CLI 会拒绝针对它的启动和配置 dump 请求。

- `web`、`headless`、`sdk`、`sdk-minimal`、`acp` 首次使用时**从随附模板自动初始化**。
- `dsh --profile <name> --from-default-profile <template>`：基于随附模板在**新的非内置名称**处创建自定义 profile。
- `dsh plugin`：初始化一个**以 base 为基础**的 profile。
- 「运行命令时所在的目录将作为默认 workspace 根目录。」——`dsh/README.zh.md`「入口模式」

### A.5 组合包（bundle）是什么

**官方定义**：
> 「组合包的 `dsh.bundle.patch` 指定一个 patch 文件或一个有序的文件列表」
> —— `dsh-app-boot/README.zh.md`「Profile」

即：**bundle ＝ 一份（或一组有序的）patch 层 + 一个包声明**，不是可执行代码。最典型的例子：
> 「本组合包是一份静态 patch 文档：一个应用到空 profile 根之上的 `insert` 列表。它不挂载任何服务、不发出任何事件、也不持有任何可变状态。」
> —— `dsh-base/README.zh.md`「理解实现」

**解析顺序**（`dsh/README.zh.md`「Profile」）：先查 dsh 安装目录，再查 profile 自身的 `node_modules`。安装目录里可解析的内置组合包正好是：
`@deepseek-ai/dsh-base`、`dsh-web-app`、`dsh-headless`、`dsh-sdk-app`、`dsh-sdk-minimal`、`dsh-acp-app`。
**【已验证】** 这 6 个包在归档里都带 `cordis.patch.yml`，且是全部 10 个 `kind: "package-bundle"` 文档中的 6 个（另外 4 个是实验性可选 bundle，见 B.5）。

**组合包加载失败 ≠ 启动失败**：
> 「组合包解析、manifest 读取或 patch 加载失败时会跳过该组合包，不改变其选择状态；加载结果在 `skippedBundles` 中列出每个被跳过的组合包……跳过组合包不保证剩余组合能够提供所需服务。」
> —— `dsh-app-boot/README.zh.md`「Profile」

### A.6 session（会话）是什么

**官方定义**：
> 「面向用户与维护者的事件溯源会话日志与内存存储说明，用于构建、检查或扩展每个 agent（智能体）交互背后的持久记录。」
> —— `dsh-session/README.zh.md` `description`

关键机制：
- **日志是唯一权威**。模型看到的是**派生历史** `deriveMessages()`；被压缩遮蔽的事件「仍保留在会话日志中，因此回放会话时能确定性地重现同一份压缩后的对话。」——`dsh-compaction/README.zh.md`「表层约定」
- **轮次（turn）与步骤（step）**：轮次是持久日志的提交/回放边界（`dsh-user-approval/README.zh.md`「分发」）。轮次边界先打开持久轮次，再原子领取 next-step 输入与一条排队提示词；步骤之间只领取 next-step 输入。（`dsh-agent-loop/README.zh.md`「轮次与步骤流程」）
- **循环做什么**：「每个步骤都会发送会话的派生历史……及其可见工具 schema；模型的工具调用经过受守卫的工具流水线」——`dsh-agent-loop/README.zh.md`「一个步骤做什么」
- **并行工具**：`maxParallelToolCalls` 默认 **10**；「独占调用单独运行并构成排序屏障」——`dsh-agent-loop/README.zh.md`「一个步骤做什么」
- **文件位置**（`dsh-session-persistence-jsonl/README.zh.md`「磁盘布局」，`root` 必填无默认值）：
  ```
  <root>/--<normalized-cwd>--/<encoded-id>/session.v3.jsonl.zstd
  ```
  默认压缩 `compression: 'zstd'`；`'none'` 时为换行分隔 UTF-8 文本。
  `dsh-sdk-minimal` 则用「位于 `$DSH_HOME/sessions` 的未压缩 JSONL 持久化」（`dsh-sdk-minimal/README.zh.md`）。
- **格式代际**：存在 v0→v1、v1→v2、v2→v3、v3→v4 迁移包。**【注意矛盾】** `dsh-session-persistence-jsonl/README.zh.md`「磁盘布局」注释写 `session.v3.jsonl.zstd  # released v3/current`，但同一文件「读取日志」章节又说「当前 V4 打开跳过发现」，且存在 `dsh-session-format-v3-to-v4` 包。详见 H.2。
- **agent 身份**：「省略 `sessionId` 时，每次启动都会创建新的 `${id}-session-<uuid>`」——`dsh-agent-loop/README.zh.md`「已知限制与延期工作」

---

## B. 官方能力清单（随包组合提供什么）

### B.1 共享核心 `dsh-base`

> 「开箱即用，基于本核心构建的每个 profile 都提供：DeepSeek 模型连接（提供方与模型可配置，你还可以在设置中启用额外提供方）、完整工具集——文件编辑、shell 命令、web 搜索、公开 HTTP(S) 抓取、subagent、任务与目标跟踪——可跨重启存活的持久会话，以及默认权限策略：把文件写入限制在工作区内，危险操作前征询许可。Web 抓取无需逐次审批，其提供方会拒绝非公开目的地址。」
> —— `dsh-base/README.zh.md`「你得到什么」

### B.2 工具目录（官方 `description` 原文）

**文件与搜索**
| 工具 | 官方描述 | 包 |
|---|---|---|
| `read` / `read_image` / `write` / `edit` | 「带行号读取 UTF-8 文件、读取受支持的图片、创建或原子地替换文件，以及执行有针对性的字面量编辑」 | `dsh-tool-fs` |
| `glob` / `grep` | 「面向模型的 glob 与 grep 发现工具」（基于 ripgrep） | `dsh-tool-fs-search` |
| `str_replace_editor` | 「基于 `ctx.fs` 的独立 str_replace_editor 工具」——**默认不挂载**，需显式启用 | `dsh-tool-str-replace-editor` |

`dsh-tool-fs/README.zh.md`「工具」给出精确参数：
- `read(file_path, offset?, limit?)`：`offset` 从 1 开始；`limit` 默认与上限均为 `readLimit`（默认 **2000** 行）；`readMaxLineLength` 2000 字符；`readMaxBytes` 51200；`readStreamMinSize` 10485760。
- `write(file_path, content)`：「创建或完整替换文件；有策略插件时，覆盖要求先在未变版本上执行 `read`，创建不需要」。
- `edit(file_path, old_string, new_string, replace_all?)`：「字面量替换，除非 `replace_all` 为 true 否则要求唯一匹配」。
- 「字段名使用 snake_case，与 Claude Code 和现有 harness 工具 schema 一致。」
- `read_image` 只在 `ctx.attachments` 已挂载时注册，并「拒绝确切模型未声明图像输入的路由」。

> `dsh-base/README.zh.md`「你得到什么」：「默认文件编辑使用 `read`、`write` 和 `edit`。`str_replace_editor` 工具仍可显式启用。」

**Shell**
| 工具 | 官方描述 | 包 |
|---|---|---|
| `pwsh` | 「让 agent 通过已挂载的 shell 执行器运行 PowerShell 命令。每次调用使用全新进程；组合中有 job 注册表时，每条命令从启动那一刻起就是一个任务」 | `dsh-tool-pwsh` |
| `bash` | 「面向模型的 bash 工具，供选择、配置或排查一次性命令执行、后台任务与沙箱升权的使用者与维护者阅读」 | `dsh-tool-bash` |
| `pwsh-persistent` / `bash-persistent` | 「跨调用保留的按所有者隔离 shell 状态」 | `dsh-tool-pwsh-persistent` / `dsh-tool-bash-persistent` |

> **平台门控**：「在 macOS 与 Linux 上你获得 bash shell 工具；在 Windows 上则获得对应的 PowerShell 孪生工具，因此每台机器恰好有一套 shell 栈。各平台的安全行为完全一致。」——`dsh-base/README.zh.md`「各平台的 shell 工具」

`pwsh` 关键配置：「`enableRunInBackground` 默认 `true`」「`promoteOnTimeout` 默认 `true`：到达超时的前台命令继续作为它的后台任务运行」。
超时返回：`[still running after <timeoutMs>ms; moved to background job <id>]`。
**Windows 特有**：「非零退出以 `[exit code: N]` 报告；在 Windows 上，强制终止的命令以 `[exit code: 1]` 结算且没有信号标记」。（`dsh-tool-pwsh/README.zh.md`「运行命令」）

**Web**
| 工具 | 官方描述 | 包 |
|---|---|---|
| `web_search` | 「返回可选的答案与来源 URL」（`searchMaxResults` 默认 8，`searchMaxQueries` 默认 4） | `dsh-tool-web` |
| `web_fetch` | 「以文本形式取回页面内容」（`fetchTimeoutMs` 30000，`fetchMaxOutputChars` 200000） | `dsh-tool-web` |
| 提供方（搜索） | `deepseek-official`：DeepSeek 原生服务端搜索，「通过 Anthropic 兼容 Messages API」 | `dsh-web-search-deepseek` |
| 提供方（抓取） | HTTP(S) 抓取 | `dsh-web-fetch-http` |

> 「结果会把提供方控制的文本标记为外部不可信数据，而抓取到的 HTML 会排除活动与隐藏内容。」——`dsh-tool-web/README.zh.md`「概述」
> 「如果配置的提供方缺失或不可用，工具仍保持可见，并返回模型可据此采取行动的结构化错误。」（同上）
> `dsh-web-search-deepseek`「概述」：「当部署希望使用 DeepSeek 原生搜索、并接受一次搜索在延迟与 token 上消耗一个完整模型轮次时选择它，因为 DeepSeek 不提供专用搜索端点。」

**技能**
| 工具 | 官方描述 | 包 |
|---|---|---|
| `skill` | 「面向模型的 skill 目录与加载工具」 | `dsh-tool-skill` |

**任务/编排**
| 工具 | 官方描述 | 包 |
|---|---|---|
| `todo_write` | ——（`dsh-tool-todo`：待办清单工具） | `dsh-tool-todo` |
| `job_output` / `job_list` / `job_kill` | 「面向模型的后台任务控制」 | `dsh-tool-jobs` |
| `subagent` | 「面向模型的 subagent 委派工具」 | `dsh-tool-subagent` |
| `send_message` / `interrupt_agent` / `list_agents` | 「全局 send_message、interrupt_agent 与 list_agents 工具」 | `dsh-tool-subagent-control` |
| `workflow` | 脚本化多子代理编排（`dsh-workflow` / `dsh-tool-workflow`） | `dsh-tool-workflow` |
| `create_goal` / `get_goal` / `update_goal` | 「模型侧 goal 工具」 | `dsh-tool-goal` |
| `present` | 「通过 present 声明交付可访问的文件」 | `dsh-tool-present` |
| `ask_user_question` | 「基于 user-questions seam 的模型侧 ask_user_question 工具」 | `dsh-tool-ask-user` |
| `ralph` | 「固定前台 agent loop，让全新 agent 围绕一个不可变目标迭代」 | `dsh-tool-ralph` |
| `run_code`（PTC） | PTC 模式下的代码执行传输（见 B.4） | `dsh-tools` |
| `cordis_inspect_list` / `cordis_inspect_query` | 「为开发和配置已安装 Harness 插件的 agent 提供只读运行时 API 查询」 | `dsh-tool-cordis` |
| `plugin_manager` | 「管理当前 profile 的插件，无需手动编辑配置」 | `dsh-plugin-manager` |
| workspace-dependencies | 工作区依赖工具 | `dsh-tool-workspace-dependencies` |

**【文档未说明】** 随包文档没有一份"完整工具目录"。每个工具包的 README 都指向 `docs/tool-catalog.zh.md`——**该文件不在安装包内**。

### B.3 技能（详见 D）
`dsh-skill`（注册表）+ `dsh-skill-filesystem`（磁盘提供方）+ `dsh-tool-skill`（模型侧目录与加载器）。
随包技能：`agent-experience`、`cordis-plugin-development`、`editing-cordis-compositions`、`cordis-composition-reference`（`dsh-agent-preset/skills/`）、`office-docx`/`office-pptx`/`office-xlsx`（`dsh-skill-office/assets/`）、`dsh-badge`（`dsh-skill-badge/assets/`）、`diagnose-windows-sandbox-acl`（`dsh-sandbox-windows-acl/assets/`）。

### B.4 呈现模式与 PTC
`dsh-tools` 的 `mode` 配置：「`native`（每个可见 schema）、`ptc`（只有 `run_code` 加一份生成 SDK）或 `both`」，默认 `native`。
> 「在纯 `ptc` 下，模型直呼其他任何可见工具都会在策略之前解析为 `UNKNOWN_TOOL`」
> `run_code` Node 默认超时 120,000 ms，上限 600,000 ms，「包含嵌套工具和审批等待」。
> —— `dsh-tools/README.zh.md`「配置呈现模式」「PTC mode」

Web 侧 agent preset 通过 `dsh-agent-tool-presentation` 选择呈现方式。

### B.5 随包组合包（bundle）全名单
**【已验证】** 归档中 `kind: "package-bundle"` 的文档共 **10** 个：

**稳定（6）**
| 组合包 | 官方作用 |
|---|---|
| `dsh-base` | 「共享的 dsh 核心」 |
| `dsh-web-app` | 「dsh 的浏览器 GUI：交互式聊天、模型与设置管理、会话历史」 |
| `dsh-headless` | 「dsh 的一次性任务模式：从命令行运行单个任务并打印最终答案」 |
| `dsh-sdk-app` | 「SDK stdio 应用 profile」 |
| `dsh-sdk-minimal` | 「独立 SDK profile，默认提供一个 shell 工具」，不继承 base |
| `dsh-acp-app` | 「纯自动化 ACP stdio 应用 profile」 |

**实验性、随包提供但默认关闭（4）**
| 组合包 | 官方作用 |
|---|---|
| `dsh-experimental-auto-review` | 「为 Web profile 添加实验性逐调用 Auto review」 |
| `dsh-experimental-schedule-bundle` | 「从插件管理页加入定时服务、提醒目录与自动化任务页面」 |
| `dsh-experimental-voice-input-bundle` | 「从插件管理页启用实验性语音输入」 |
| `dsh-experimental-agent-team-profile` | 「在一个实验性组合包中启用团队协作、工具与 Web 成员和任务看板」 |

> 「启动器的 `OPTIONAL_BUNDLES` 点名的组合包是 `optional`：随安装提供、默认关闭、由用户开启，**永不可卸载**，也不被任何随附模板选中」——`dsh-plugin-manager/README.zh.md`「使用本包」

### B.6 Web 随附 agent preset
「每个浏览器会话选择一个随发行版交付的 preset（默认 `standard`）。」——`dsh-web-app/README.zh.md`「按会话的 agent 设置」
`dsh-web-app/README.zh.md`「源码地图」列出 preset 目录：**`standard`、`ptc`、`minimal`、`cordis`**。
`dsh-client-ui-goal/README.zh.md`：「除 `minimal` 外，随附的 Web preset 都会向 agent 提供 `/goal`。」

### B.7 模型与凭据
- `dsh-agent-default-model`：唯一进程级默认值，`provider` 与 `model` **必填**；「`saveSelection()` 为后续 agent 保存完整选择」，「没有配置编辑器时，`saveSelection()` 不执行写入」。
- Web 默认（`dsh-web-app/README.zh.md`「启动 Web GUI」）：「默认模型为 `deepseek-official` / `deepseek-flash`（DeepSeek-V41-Flash）。DeepSeek 插件使用 Messages API。」「已保存的模型选择覆盖组合默认值。」
- 凭据：`dsh-credentials` + `dsh-credentials-local`（文件型存储，文档 `version: 1`）；也可用 `DEEPSEEK_API_KEY`；DeepSeek 账号登录走 `dsh-deepseek-account` / `dsh-deepseek-account-platform`。
- 备用适配器：`dsh-llm-pi-ai`（多提供方网关，`defaultMaxTokens` 32768）；重试由 `dsh-llm-retry` 在「持久 agent 步骤边界上配置按提供方路由的模型请求恢复」。

### B.8 MCP / Hooks / 其他
- `dsh-mcp-client`：连接外部 MCP 服务器并把工具注册到 `ctx.tools`；`dsh-mcp-resources` 按需发现与读取 MCP 资源。「本 bundle 统一挂载 MCP 资源一次。只需为所需服务器配置 MCP 客户端条目。」——`dsh-base/README.zh.md`「你得到什么」
- `dsh-hooks-claude-code` / `dsh-hooks-codex`：「在 agent 运行期间使用你现有的 Claude Code hooks.json 或 settings 钩子配置」。
- `dsh-schedule`（宿主级持久提醒）+ `dsh-client-ui-schedule`，**Web 组合默认不含**。
- `dsh-session-log-export`：`/export` 命令导出会话日志 ZIP。
- `dsh-office-to-pdf` / `libreoffice-kit`：Office 转 PDF（文档预览用）。

### B.9 遥测（涉及隐私，官方明确）
> 「[OTel 会话上传]对所有用户默认使用 `FEEDBACK_ONLY`，包括 `deepseek-official`：新的文本反馈、消息评分、编辑与撤回会释放截至该事件的完整规范会话日志前缀，包含上下文。……`DISABLED` 阻止 OTel 捕获。默认开启的 [DeepSeek 会话日志贡献器] 仍是独立的请求路径。」
> —— `dsh-base/README.zh.md`「你得到什么」

---

## C. 权限与沙箱模型（最需要精确理解的部分）

### C.1 三个沙箱模式（官方原文表）

> 「模式指明命令可以执行的文件操作；强制执行完整度报告后端对这些操作的管辖程度。」
> —— `dsh-sandbox/README.zh.md`「模式与强制执行」

| 模式 | 官方效果原文 |
|---|---|
| `read-only` | 「拒绝写入，必需 sink（如 `/dev/null`）除外」 |
| `workspace-write` | 「允许写入工作区根目录及后端定义的临时区域」 |
| `danger-full-access` | 「绕过隔离；消费方直接 spawn 原始 argv」 |

**强制执行完整度**：`full` / `partial`。
> 「`full` 表示后端管辖模式承诺的每个文件操作，`partial` 表示活动后端或较旧的内核 ABI 只管辖子集——**Windows ACL 档与较旧的 Landlock ABI 是当前的部分强制执行情形**」

**故障关闭（fail-closed）**：
> 「无法强制执行所请求的模式时，调用以 `SANDBOX_UNAVAILABLE` 失败，绝不会不受限制地运行」
> 精确错误原文（`dsh-sandbox/README.zh.md`「精确错误」）：
> `sandbox mode "<mode>" is requested but no sandbox backend is usable on this host; refusing to run the command unconfined. Install bubblewrap or run a Landlock-enforcing kernel (Linux), ensure sandbox-exec is usable (macOS), or ensure the ACL restricted-token runner can start (Windows) — otherwise switch the consumer to danger-full-access.`

**官方明确的边界**：
> 「文件操作是完整的策略词汇——该 seam 不表达网络、进程、系统调用、设备或凭据限制。」
> —— `dsh-sandbox/README.zh.md`「已知限制与延期工作」
> 「这种限制只适用于与宿主共享内核和文件系统的进程；需要隔离整个环境时，请使用容器、microVM 或远程执行器。」——`dsh-sandbox/README.zh.md`「概述」

### C.2 会话级策略解析与模型可见文本

`dsh-sandbox-policy/README.zh.md`：
- 解析优先级：「已批准的显式模式优先于会话最后一条 `sandbox/mode` 事件，后者又优先于部署默认值」（「解析优先级」）
- 「故障安全默认值是 `read-only`，需要 agent 可写入工作区的部署必须显式选择 `workspace-write`」——**注意：这是包级默认**。随包 base 组合把默认设成 `workspace-write`（见 `dsh-base/cordis.patch.yml` 语义与 `dsh-sandbox/README.zh.md`「隔离命令」示例）。
- 「每个会话只有一个主要工作区根目录——策略解析 `SessionHeader.cwd`」（「已知限制」）
- 切换事件是「仅写入日志的 `sandbox/mode` 事件」，「切换通过回放跨重启保留，每个会话保持自己的模式」。

**模型收到的三段原文**（`dsh-sandbox-policy/README.zh.md`「模型可见文本」，与本次会话实际收到的文本一致）：

```markdown
# read-only
Current DSH file policy: read-only. Any available operation enforced by the DSH file sandbox cannot modify files in the standing mode. Do not refuse a required modification from this policy alone: try an available tool normally and follow any denial and escalation guidance it returns.

# workspace-write
Current DSH file policy: workspace-write. Any available operation enforced by the DSH file sandbox may modify files under the session workspace: "<workspace root>". Some platform temporary areas may also be writable.

# danger-full-access
Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict file modifications by available operations.
```

### C.3 审批策略：只有两个值

> 「`ask` 策略将每个请求发送给部署中的人类或机器应答者；`never` 则直接拒绝，不发出提示。应答者缺失或失败时返回 `unavailable`，使操作以拒绝方式关闭；每项批准也只适用于对应请求。」
> 「`ask`（默认）委托给已组合的应答者；`never` 在交互式分发之前确定性地拒绝每个请求——这是 CI 与无人值守运行采用的严格无头模式。」
> —— `dsh-user-approval/README.zh.md`「概述」「设置策略」

**硬约束（官方"已知限制"原文）**：
- 「**请求只在尚未结束的轮次内有效**」
- 「**仅存在一次性授权**：结果词汇包含 `allowed-once`，但不含 `allow-always`、已记住的规则、撤销或授权存储；会话策略只有 `ask`／`never`。」
- 「**请求不携带工具参数**：应答者会看到工具名称、原因和可选调用 id」
- 「**没有内置应答者**：无头或组合不完整的部署会返回 `unavailable` 并以拒绝方式关闭；服务自身绝不会提示人类。」

**模型可见的两种策略原文**（`dsh-user-approval/README.zh.md`「模型看到的内容」）：
```markdown
# ask
Approval policy: ask. Operations that require approval may ask through the configured answerers; without an available answerer, the request fails closed.

# never
Approval prompts are disabled in this session: actions that require approval are rejected automatically — do not request sandbox escalation (do not set `sandbox_permissions`).
```

### C.4 权限预设：把沙箱与审批捆在一起

`dsh-permission-presets/README.zh.md`：
- 「提供具名权限模式，同时设置沙箱与审批，但各执行服务仍保留自己的值。配置预设提供**未来会话**默认值；显式加载的 Auto review integration 可以增加一个**仅限当前会话**的选项。」
- 默认预设表（「配置预设」）：
  ```yaml
  presets:
    workspace-write:      { sandbox: workspace-write,   approval: ask }
    danger-full-access:   { sandbox: danger-full-access, approval: never }
  defaultPreset: workspace-write
  ```
- 保留名：`custom`（推导出的非预设状态）与 `auto`（Auto review integration），**不能出现在配置表中**。
- 「不匹配任何预设的旋钮组合显示为 `custom`，用户可以离开该状态，但不能选择它。」
- 切换入口：「用户通过 `/permission` 命令切换：不带参数调用时报告当前预设与所有可用条目，带预设参数时切换过去。」
- 会话默认值语义：「`permission` 设置命名空间为未来会话持有 `defaultPreset`……之后的设置变更绝不会改变现有会话。」

**Web UI 的官方标签**（`dsh-client-ui-permission-presets/README.zh.md`「选择器」）：
> 「内置标签在英文界面中是 `Read Only`、`Workspace Write`、`Full access` 和 `Auto review`，在中文界面中是「仅可查看」「工作区内修改」「完全权限」和 `Auto review`。」
> 「通过可见选项选择完全权限或 Auto 时，需要分别确认对应风险；完整的 `/permission <preset>` 命令直接执行。」

注意："默认 Web 提供仅可查看、工作区内修改与完全权限"（同上「概述」）——**默认 Web 只有三种模式，Auto 需要显式安装/开启**。

### C.5 升级（escalation）机制

`dsh-sandbox/README.zh.md`「被拒绝的调用与升权」：
- 拒绝标记原文：`[sandbox: file access denied under <mode> mode]`
- 升权提示原文：`[sandbox: escalation available — retry this exact <subject> once with sandbox_permissions (the narrowest wider mode that suffices) + justification; the approval prompt asks the user]`
- 阶梯是**封闭表**（`dsh-sandbox/README.zh.md`「升权编排」）：
  > 「`read-only` 可升权到 `workspace-write` 或 `danger-full-access`，`workspace-write` 只能升权到 `danger-full-access`——在执行时检查，绝不写入工具 schema」
- 「重复指定调用的生效模式无需审批即可成功；更窄的目标仍然无效。」
- 「更宽的模式需要审批，且只作用于该次调用。」
- `dsh-tool-fs/README.zh.md`「策略与沙箱行为」：「使用施加沙箱限制的后端（`fs-sandbox`）时，`write`/`edit` 还会公开 `sandbox_permissions` 与 `justification`」。

**【与我们当前会话的对照】** 本次会话收到的是 `never` 策略文本，所以「actions that require approval are rejected automatically — do not request sandbox escalation」。这是**官方设计行为**，不是故障。

### C.6 文件沙箱后端（`ctx.fs` 侧）

`dsh-fs-sandbox/README.zh.md`：
> 「`read-only` 拒绝所有变更；`workspace-write` 只允许目标位于会话工作区或平台临时根目录内；`danger-full-access` 不限制变更。」
> 「被拒绝的操作返回 `FS_SANDBOX_DENIED`，文件系统工具会显示当前模式和同轮次升级提示。」

**关键区别（初学者最容易搞错）**：
> 「**策略围栏，而非内核边界**：该检查是可信代码处理模型控制的路径……对抗性宿主进程不在范围内。不可信代码的内核级隔离仍属于 `ctx.shell`。」
> 「读取、列出、元数据操作与只读监听均与 `fs-local` 完全一致；**变更围栏不限制观察**。」
> —— `dsh-fs-sandbox/README.zh.md`「设计理念」「可观察的成功与失败」

即：**文件沙箱只管"写/改"，不管"读"**。

### C.7 Windows 上的文件沙箱差异（本机重点）

`dsh-sandbox-windows-acl/README.zh.md`「概述」：
> 「在 Windows 上，本包将子进程的写入与删除限制在工作区和私有临时目录内：`workspace-write` 授予这两处，`read-only` 均不授予。……**任何 Win32 操作失败都会阻止不受限制的 spawn**。……该保证仍为**部分强制**：硬链接是文件对象别名，而被其他 AppContainer 工具 ACL 过的文件不可读。」

**机制**（「机制」章节）：
- 调用者令牌被复制为 `WRITE_RESTRICTED` 受限令牌，携带**工作区能力 SID + 私有临时 SID**，并降级为 **Low 完整性**。
- 模式与令牌列表：`workspace-write`（登录 SID、Everyone、工作区 SID、临时 SID）；`read-only`（登录 SID、Everyone——不含写入 SID）。
- 每次授权同时写：能力 SID 允许 ACE + 向 world SID 拒绝 `FILE_DELETE_CHILD` + Low 完整性标签。

**临时目录语义**：
> 「`workspace-write` 把写入限制在工作区与会话自己的 temp 子目录（`<temp>\dsh-<hash>`，受限子进程的 TMP/TEMP 被改写）；`read-only` 不授予任何临时目录写入权限。」
> —— `dsh-base/README.zh.md`「已知限制与延期工作」
> 「新的提供方总会选择新的临时路径和 SID，因此崩溃残留既无法阻止恢复的会话，也无法向其授权。」——`dsh-sandbox-windows-acl/README.zh.md`「隔离给你带来什么」

**官方"已验证边界"与限制要点（逐条原文摘引）**：
- 「**写入与删除受限；读取、网络与进程可见性不受限。** 两层都不交叉检查读取，因此受限子进程可以读取调用者可读的任何文件（包括其他工作区中的文件）并打开套接字；`read-only` 因而需要读侧策略才能表达。」
- 「**硬链接是文件对象别名，而非路径别名。**……同一对象也可通过外部别名写入」
- 「**控制台隔离不可用。** 以 `CREATE_NO_WINDOW` / `CREATE_NEW_CONSOLE` 创建的子进程在 DLL 初始化期间以 `STATUS_DLL_INIT_FAILED`（`0xC0000142`）死亡」
- 「**常驻 Low 标签的生命期长于 DSH，并会向其他 Low 完整性的进程放宽该目录树。**……任何以同一用户身份运行在 Low 完整性的其他进程——别家产品的 Low-IL 沙箱、受保护模式阅读器——都能写入与删除工作区内的内容」
- 「**受限孙进程的管道 stdio 捕获不可用。**……受限进程内 `spawn(..., { stdio: 'pipe' })` 以 EPERM 失败；继承与忽略 stdio 的 spawn 可用，匿名管道（PowerShell 的管道）因受限令牌默认 DACL 携带 restricting SID 全权 ACE 而可用。」
- 「**授权物化是急切的全树传播。** 在带可继承 ACE 的目录上调用 `SetNamedSecurityInfoW` 会立即遍历每个后代（**大型工作区树上以数十秒计**）」
- 「**读取会被其他基于 AppContainer 的工具以包 SID 授权过的对象挡住。**……移除外来 ACE（或重新安装受影响的目录树）即可恢复访问。」
- 「**PowerShell 语言模式因受限模式而异。** 在 `read-only` 下，PowerShell 无法在临时目录中创建 AppLocker 探针文件，因此会保守地以 ConstrainedLanguage 启动（`Add-Type`、非核心 .NET 静态调用、COM 与反射失败）」
- 「Authenticated Users 在两种列表中都不存在——WMI 命名空间安全检查失败（`0x80041003`），因此 **CIM cmdlet 与 `Get-ComputerInfo` 在所有受限模式下都不可用**」
- 「**环境临时根目录绝不会被隐式授权。**」
- 「受限令牌下 `whoami` 与令牌检查 cmdlet 可能失败。」
- 「**常驻工作区 ACE 是不可见残留。** 工作区改名会派生新的 SID；旧路径上的旧 ACE 留在原地（失效、仅含写入 SID）」

`dsh-tool-pwsh/README.zh.md`「Windows 特有的沙箱行为」把这些转成给模型的两条提示：
> 「只读 pwsh 运行在 ConstrainedLanguage 中（`.NET` 静态调用、`Add-Type`、COM 与反射会以 "only core types" 错误失败）；两种受限模式下程序都无法打开命名管道，因此通过管道 stdio 捕获另一程序输出的命令会以 EPERM 失败——请升权该确切命令一次，或重构命令以避免捕获输出。」

**诊断技能**：`dsh-sandbox-windows-acl/README.zh.md`「失败与恢复」——随包发布 `diagnose-windows-sandbox-acl` 技能，「一次运行同时完成诊断与修复」，「仅当对象就是 `-AllowRoot` 或严格位于其内部时才会被修改」，「随包发布的诊断技能需要不受限的调用者……没有审批通道时升权 fail-closed，该路径保持未诊断」。

### C.8 编辑前读取策略（观察策略）

`dsh-fs-observation-policy/README.zh.md`：
- 「要求 agent 先读取文件，文件系统工具才可覆盖或编辑它。如果文件自读取后发生变化，它也会拒绝变更，并清楚提示重新读取后重试。」
- 错误码：`FS_NOT_OBSERVED`（策略原因 `edit requires reading "<path>" first`）、`FS_STALE_VERSION`、`FS_NOT_FOUND`。
- 工具侧统一文案：`cannot modify "<path>": file has not been read — read the file, then retry`；陈旧时追加 `— re-read the file, then retry`。
- **重要限制**：
  - 「**已观察状态无法在会话恢复后保留**……恢复的会话必须重新读取文件，才能执行防护写入与编辑。」
  - 「**直接 `ctx.fs` 读取不会发出 `fs/observed`**」
  - 「**授权依据是版本新鲜度，而非视图完整性**：任何窗口读取都会授权对未变文件执行全文件覆盖」

### C.9 审批界面（Web）
`dsh-client-ui-approval/README.zh.md`：
> 「聚焦审批详情区域后，Enter 批准，Esc 拒绝。」「**面板只提供临时决定**——它支持仅本次允许和拒绝；持久权限策略仍由 Host 侧审批包拥有。」

---

## D. 技能（Skills）

### D.1 官方定义
> 「一个 skill 是可复用的任务专项指令集合。」
> —— `dsh-tool-skill/README.zh.md`「Skill 目录模板」（模型看到的英文原文：`A skill is a reusable set of task-specific instructions.`）

架构是三层，**三件套必须一起挂**（`dsh-skill/README.zh.md`「何时选择」）：
| 角色 | 包 |
|---|---|
| 注册表（合并任意提供方） | `dsh-skill`（`ctx.skills`） |
| 本地磁盘提供方 | `dsh-skill-filesystem` |
| 模型侧目录 + `skill` 工具 | `dsh-tool-skill` |

### D.2 发现规则（精确）

`dsh-skill-filesystem/README.zh.md`「skill 格式」：
> 「skill 可以是被扫描根目录**顶层**的目录 bundle `<name>/SKILL.md`，也可以是平铺文件 `<name>.md`；**刻意不支持发现嵌套的 `**/SKILL.md`**。」

**扫描根与优先级（官方表，rank 数字越小越优先）**——「根目录与优先级」：

| Rank | 来源 | 路径 |
|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` |
| 300 | `custom` | `Config.customSkillDirs` |
| 400 | `user-dsh` | `<dshHome>/skills` |
| 500 | `user-agents` | `<agentsHome>/skills` |
| 600 | `bundledSkillDir` | 配置后扫描的随包技能根 |

- 「项目根目录是包含 `.git` 的最近祖先目录；如果不存在，则使用当前 cwd。」
- 「用户 DSH 根目录会跳过其 `.system` 子目录。」
- home 默认：`dshHome` = `$DSH_HOME` 或 `~/.dsh`；`agentsHome` = `$DSH_AGENTS_HOME` 或 `~/.agents`。
- 同名裁决（`dsh-skill/README.zh.md`「设计理念」）：「最近层直接赢得重名，单层内重名则依次按 rank、提供方注册顺序与提供方本地顺序裁决。」「重名项的裁决采用**先到先得**」

**热更新**（`dsh-skill-filesystem/README.zh.md`「变更检测」）：
> 「现有根目录会被监视，因此新增、改名或删除 skill（或编辑其 frontmatter）会在**下一个模型步骤**触发目录刷新；`references`、`scripts`、`assets` 等 bundle 资源下的编辑不会触发。」
> 「当第一方 `write` 与 `edit` 工具的目标可能影响受监视的 skill 时，它们会**直接使提供方失效**，因此模型无需等待宿主 watcher 即可观察到自身的文件系统变更。」
> 「尚不存在的根目录会被探测，直至其出现。」

### D.3 SKILL.md 的官方解剖（frontmatter 字段）

`dsh-skill-filesystem/README.zh.md`「skill 格式」原文：
> 「文件以 YAML frontmatter 开头：**必填 `name` 与 `description`**，另有可选 `whenToUse`、`metadata`、`disable-model-invocation` 与 `user-invocable`。」
> 「`disable-model-invocation: true` 会把 skill 从面向模型的目录和 loader 中排除；`user-invocable: false` 会把它从面向用户的命令中排除，**省略的字段默认允许对应接口调用**。」
> 「这两个键接受 YAML 布尔值，以及不区分大小写的 `true`/`false`、`yes`/`no`、`on`/`off` 和 `1`/`0` 形式；**被拒绝的拼写或非布尔值会让整个 skill 随警告一起被丢弃**，而不会静默允许某个接口。」
> 「每个文件都会解析 frontmatter——`name` 必须为 **kebab-case**，`description` 必填」（「发现流程」）

**【已验证】随包 9 个 SKILL.md 的实际 frontmatter 都只用 `name` + `description`**，例如：
```yaml
name: office-docx
description: Create, read, edit, and check Word documents (.docx), ...
```
（`dsh-skill-office/assets/office-docx/SKILL.md`）

**没有任何随包 SKILL.md 使用 `whenToUse` / `metadata` / `disable-model-invocation` / `user-invocable`。**
【文档未说明】`whenToUse` 与 `metadata` 的取值类型与语义（文档只说它们是可选字段）。

### D.4 安装/创作流程（官方）

**没有"安装"步骤**——把文件放到被扫描根目录即可：
> 「把 skill 编写为任一被扫描根目录下的目录 bundle（内含 `SKILL.md`）或平铺 `<name>.md` 文件，**它就会出现在会话目录中**。」
> 「目录与正文具有独立的生命周期：发现阶段把 frontmatter 解析进目录条目，**每次加载都会重新读取当前文件**，因此编辑 skill 正文无需版本化或缓存失效。」
> —— `dsh-skill-filesystem/README.zh.md`「概述」「skill 格式」

**推荐的渐进式披露结构**（从随包技能反推）：`SKILL.md`（短）+ `references/`（按需读）+ `scripts/` / `assets/` / `templates/`。
`dsh-agent-preset/README.zh.md`「使用此包」举例说明设计意图：
> 「`cordis-plugin-development`（简短流程，配合**按需读取**的 `references/` 与可复制的 `templates/` 组合包）」
> 「每个出货的 `SKILL.md` 作为 `skill` 工具结果渲染后都保持在 **8192 字符阈值**之下，标准 preset 的工具结果修剪器超过该阈值才会裁剪。」

### D.5 模型与用户如何调用

`dsh-tool-skill/README.zh.md`：
- **初始目录**：模型在首次请求前收到一条**持久 user 角色消息**（`<system-reminder>` + `<available_skills>`），模板原文见「Skill 目录模板」。`catalogDescriptionMaxLength` 默认 **500**。
- 目录结尾的防重复加载规则：「do not infer or follow a skill's instructions until it has been loaded」「do not call the `skill` tool again for that skill」。
- **加载**：模型用精确名称调用 `skill`，得到 `<skill_content>` 块（含 `<skill_resources>` 与 `<skill_instructions>`）。
- **用户显式调用**：`/name` 手势把同样的 `<skill_content>` 注入该步骤。**「这是 `disable-model-invocation` skill 唯一的入口，目录与 `skill` 工具永不暴露这类 skill。」**
- **目录替换是全量的**：「一个名称或描述发生变化，就会追加所有可见摘要」。

### D.6 资源指引的 4 种形态（官方原文）
```
Resources for this skill are managed by provider "<provider>".  # 提供方管理
Base directory for this skill: <path>                            # 目录
Base URL for this skill: <url>                                   # URL
Resources for this skill: <description>                          # 不透明
```
共同尾句：「Load referenced resources only as needed.」

### D.7 技能的关键限制（官方"已知限制"原文）
- 「**目录省略 `whenToUse`、来源和提供方元数据**——路由只基于名称和有长度上限的描述」
- 「**已加载指令正文没有大小上限**——提供方可返回足以占用大量下一步上下文的 skill；只有目录描述会被截断。」
- 「**资源是指引，而非附件**——工具报告基础目录/URL/不透明提示，但既不列举也不为模型获取引用文件。」
- 「**正文不做版本化**——仅修改正文不会改变目录 digest，也不会通知模型」
- 「**发现深度为一层**」「**格式错误的条目随警告消失**——模型目录不会收到逐 skill 诊断，无法区分缺失的 skill 与无效的 skill」
- `dsh-skill/README.zh.md`「已知限制」：「**失效由提供方驱动**——注册表没有 TTL」「**提供方依次查询**——一个缓慢的提供方会延迟其后注册的所有提供方」

---

## E. 插件 / 扩展官方流程

### E.1 CLI 流程
> 「`dsh plugin --profile <name> <pnpm args>` | 通过在 profile 目录中转发给 pnpm 来管理该 profile 的插件。」
> —— `dsh/README.zh.md`「入口模式」

官方示例（`dsh-experimental-auto-review/README.zh.md`「安装到 profile」，源码 checkout 语境）：
```sh
pnpm dsh plugin --profile web add ./packages/experimental/auto-review
pnpm dsh plugin --profile web remove @deepseek-ai/dsh-experimental-auto-review
```
> 「CLI 会在需要时初始化 profile，并将本包声明的 patch 追加到 base 与 Web 层之后。**Reconciliation 将 patch 激活为 profile 层；没有 `dsh.bundle.patch` 的包只是已安装依赖。**」

版本豁免子命令（`dsh-plugin-manager/README.zh.md`「版本兼容性与豁免」）：
```sh
dsh plugin --profile <profile> version-exemptions
dsh plugin --profile <profile> allow-version <package@version> --dsh-version <runtime> --accept-risk
dsh plugin --profile <profile> revoke-version <package@version> --dsh-version <runtime>
```

### E.2 Web 侧边栏流程
`dsh-client-ui-plugin-manager/README.zh.md`「使用本包」：
> 「在侧栏选择**插件**。……它说明当前页用于配置官方插件、安装和管理其他插件，**设置 → 内置插件**则展示内置插件列表及运行状态。」
> 「**官方**排在前面，列出安装随附、供开启的组合包——开启前保持关闭、没有卸载、属于实验性功能的带**实验性**标签——其后是注册了配置页的官方插件；**已安装**列出 profile 持有的组合包。」
> 「名称以 `@deepseek-ai/dsh-experimental-` 开头的官方包显示实验性标记。」

### E.3 "bundle patch"到底改什么
| 操作 | 官方落点 |
|---|---|
| 插件开关 | 「只更新 profile 的 `cordis.patch.yml` 中最后一条匹配覆盖项的 `disabled`；没有匹配项时追加。」 |
| 组合包开关 | 「修改 `package.json` 的有序 `dsh.profile.bundles` 列表。**关闭保留依赖；开启追加到列表末尾，可能改变配置优先级。**」 |
| 安装新组合包 | 「默认启用」 |
| 用户手动 patch | 「home 和单次启动 patch 保留更高优先级」 |

（均见 `dsh-plugin-manager/README.zh.md`「使用本包」）

**patch 写法（`dsh-app-boot/README.zh.md`「Profile」）**：
> 「**`cordis.patch.yml`**——你的 tweak 层，应用在所有组合包层之后……：**替换某个条目的整个配置（重述你要保留的字段）**、插入新条目，或在启动时插值 `!!js` 表达式。patch 指定的条目不存在时输出 stderr 警告；**空文件或仅含注释的文件会导致启动失败——如需禁用该层，请改用 `[]`。**」

`dsh-base/README.zh.md`「最小自定义 profile」给出最小自定义 profile：
```json
{ "name": "my-profile", "private": true,
  "dsh": { "profile": { "bundles": ["@deepseek-ai/dsh-base"] } } }
```
然后 `dsh --profile my-profile "your task"`。

### E.4 版本兼容性与豁免（非常重要）
`dsh-app-boot/README.zh.md`「Profile」：
> 「profile 导入插件前，DSH 会检查其 `peerDependencies` 中对 `@deepseek-ai/dsh` 和 `@deepseek-ai/dsh-*` 的依赖，与 `getDshRuntimeVersion()` 返回的唯一运行时版本比较。**每个声明的版本范围都必须匹配；预发布版本参与范围匹配。**……未声明 DSH peer 时不施加版本约束；无效范围视为不兼容。**这些检查使用 peer 声明，而不是 `engines.dsh`，也不是防范恶意包代码的沙箱。**」

- 「不兼容插件需要用户明确确认精确版本豁免。」
- 豁免存 `profile/compatibility.json`：「把精确的 `package-name@version` 键映射到精确 DSH 运行时版本列表；**插件升级和 DSH 升级都不继承授权**。」
- 「文件损坏绝不会阻止 profile 启动……此后该文件被视为只读」。
- **被拒绝的插件永远不会导入其模块**：「组合包本身不是行，因此 `loadProfileDirectory` 在启动和每次重新组合加载 profile 的组合包层时，检查每个组合包自己声明的 DSH peer；没有豁免的不兼容组合包会像无法读取的组合包一样被跳过，并列入 `skippedBundles`。」

### E.5 写锁与 HMR
- 「[插件管理器] 与 `dsh plugin` 共享包操作和 **profile 写锁**；更新依赖会保留已停用的组合包选择。」——`dsh/README.zh.md`「Profile」
- 「配置变化**立即生效**（HMR 启用时）；未启用 HMR 时，运行中的组合保留到重启。**改动影响使用该 profile 的全部会话。**」——`dsh-plugin-manager/README.zh.md`「概述」
- 「HMR 不获取该锁。pnpm 在 HMR 队列之外执行」——`dsh-plugin-manager/README.zh.md`「理解实现」
- `lockWaitMs` 默认 120000；`idleTimeoutMs` 默认 600000。

### E.6 加一个 bundle/插件的官方安全步骤（综合）
1. **先在 Host 侧读出 spec 指向什么**：`inspect(spec, options)`「在任何东西安装之前读出 spec 指向什么」（`dsh-plugin-manager/README.zh.md`）。
2. **走 pnpm**：`dsh plugin --profile <name> add <pkg>`，或 Web 插件页安装。
3. **关注构建脚本批准**：「依赖构建脚本仍需单独批准」；「pnpm 11 拦下依赖脚本时，失败的安装在 `pendingBuilds` 里报告 profile 中所有待决定的包名」；Web 提供「允许这些脚本并重试」。「授权按包名保存在当前 profile，**允许以宿主用户的权限执行命令**」。
4. **关注版本兼容**：不兼容会在 pnpm 运行前失败，「因此不会下载任何内容、不会运行构建脚本」。
5. **失败会回滚**：安装恢复 `package.json` 与 `pnpm-lock.yaml` 快照；「**用户编写的 patch 配置、应用数据、诊断日志以及 pnpm 已下载的文件保持原样**」。
6. **注意 patch 语义**：patch 替换整块 config，必须重述要保留的字段。
7. **注意安全边界**：「profile 变更跨会话持久化，**已安装的 Host 代码在宿主进程内运行，不受工作区沙箱限制**。」——`dsh-plugin-manager/README.zh.md`「使用本包」
8. **【推断】** 保守做法：先 `inspect`，再安装，再看 `listBundles` 的 `error`，最后显式开启。

### E.7 管理器的官方限制
> 「Web 一次批准显示出来的整组待决定包，没有逐包选择。」
> 「替换已有包后需要**重启进程**，以加载新的 JavaScript 模块版本。」
> 「仅启动时加载的 profile 不能删除当前进程启动时使用的包」
> 「管理器不能关闭自身所需的管理组件、修改其他 profile 或编辑 agent 预设组合。」
> 「失败的删除可能留下部分依赖改动，失败或被取消的安装可能在 `node_modules` 或 pnpm 缓存中留下已下载文件。」
> —— `dsh-plugin-manager/README.zh.md`「已知限制与延期工作」

---

## F. 官方明确警告的坑（最值得初学者先读）

### F.1 patch 与配置
1. **patch 不做深度合并**——「patch 条目会替换目标的整个配置，因此你的覆盖必须重述每个想保留的设置；不会自动合并。」（`dsh-base/README.zh.md`「已知限制」）
2. **空的 `cordis.patch.yml` 会让启动失败**——「如需禁用该层，请改用 `[]`。」（`dsh-app-boot/README.zh.md`「Profile」）
3. **`.env` 只读一次且不搜索父目录**——「`loadLayeredEnv` 只读取一次调用目录与 harness home 中的 `.env`；它不搜索父目录，也不跟随之后选择的 workspace。」（`dsh-app-boot/README.zh.md`「已知限制」）
4. **`PATH`/`DSH_*`/`XDG_*` 不能写在 `.env` 里**——「在文件中设置的进程启动变量（如 `PATH`、`DSH_*`、`XDG_*`）会被拒绝：请改为导出这些变量。」（同上「Profile」）
5. **代理变量只从 harness home 接受**——「四个代理名（`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`）只从 harness home 的文件接受，绝不从调用目录的文件接受——后者随 clone 一起到来。」（同上）
6. **`BROWSER` 只能来自环境**——「被发现的 `.env` 不能设置 `BROWSER`。」（`dsh-web-app/README.zh.md`「已知限制」）
7. **沙箱化 fs 之上不能再挂普通 fs**——「在其之上再添加普通文件系统提供方会导致 profile 加载失败……二选一。」（`dsh-base/README.zh.md`「更改默认值」）

### F.2 上下文 / token / 压缩
8. **压缩缩减不了系统提示词、工具或会话前缀**——「压缩缩减派生历史，绝不缩减系统提示词、工具或会话前缀。」（`dsh-compaction/README.zh.md`「已知限制」）
9. **压缩无法拆分不可分单元**——「例如一次超大工具调用」（`dsh-compaction-basic/README.zh.md`「概述」）
10. **压缩只保留摘要文本，且要多花一次模型请求**——「压缩使用一次额外的模型请求，并且**只保留该请求返回的摘要文本**。」（同上）
11. **工具结果修剪器有官方默认值**：「默认会把文本超过 **8,192** 个字符的结果修剪为其前 **4,096** 加后 **1,024** 个字符，并用标记连接」；`thresholdChars` 默认 `8192`（「合并文本超过此 Unicode 码点数时修剪」）。「**字符预算不是 token 预算**——不同提供方的 token 密度各异，因此 `ctx.tokenMeter` 仍负责判定修剪是否缓解了请求压力。」「完整原始结果仍保留在会话日志中，可供精确回放与检查。」（`dsh-compaction-tool-result-pruner/README.zh.md`）
12. **阈值公式（官方）**：`floor(min(W × 0.8, W − O − B))`，其中 `W` = 上下文窗口，`O` = 生效请求输出上限，`B = 65,536` tokens（`headroomTokens`）；**逐字保留的近期历史预算是 `W − O` 的 16%**（`retainRatio` 默认 0.16）。`maxOverflowRetries` 默认 **1**（「`0` 只禁用恢复」）。
13. **配置错误会在加载时快速失败**：「保留比例不小于阈值比例」也会被拒绝（同上）。
14. **摘要失败会保留最新持久表层**，但「因达到 `maxTokens` 而发生的摘要截断（**隐藏推理 token 可能会耗尽该额度**）」也会发生（`dsh-compaction-basic/README.zh.md`「已知限制」）。
15. **`/compact` 在轮次中不可用**：「当 agent 正在轮次中或压缩已在运行时，`/compact` 会报告压缩暂不可用」（同上「通过 /compact 按需压缩」）。
16. **压缩不暴露给模型**：「**面向用户的命令，而非模型工具**——压缩由 `/compact` 命令与自动压力触发；不会注册面向模型的压缩工具。」（`dsh-compaction/README.zh.md`「已知限制」）
17. **工具结果会一直重发到压缩为止**——`dsh-tool-fs/README.zh.md`「读取结果」：「保留的调用与结果会反复发送，直到上下文压缩（compaction）。」
18. **图片每次请求都计费**：「图像在之后每次请求中都会计费，直到压缩。……内容寻址只去重存储的字节，**不去重每次请求的 token 成本**。」（`dsh-tool-fs/README.zh.md`「图像读取结果」）
19. **图片省略永不回退**：「**被省略的图片不会自动回归**——更大的预算、更大的路由或 compaction 降低总量都不会移除标记」「**临时的小预算会永久省略**」（`dsh-compaction-image-offload/README.zh.md`「已知限制」）
20. **技能已加载正文没有大小上限**（见 D.7）。
21. **指令文件有字节预算，且宽泛文件先被丢弃**：「较宽泛的文件先被省略，最具体的文件最后被截断」（`dsh-agent-instructions/README.zh.md`「概述」）。base 给 **65,536 字节**预算；`maxSourceBytes` 默认 1048576；「**指令内容受限但不会被摘要**」。
22. **重复工具调用提醒是"建议性"的**：`dsh-repeat-tool-reminder` 是「建议性循环卫生 guard」。
23. **没有内置轮次预算**：「工具调用或 steering 会让当前轮次继续；限制失控轮次的策略必须从既有生命周期扩展点（如 `agent/turn-stopping`）执行取消。」（`dsh-agent-loop/README.zh.md`「已知限制」）
24. **jobs 输出保留有界且低读会丢字节**：「追加超出运行期上限时丢弃最老的保留块……低于保留窗口的读取得到 lossy 结果而非错误。」（`dsh-jobs-local/README.zh.md`「已知限制」）默认 `retainBytes` 262144 / `settledRetainBytes` 16384。
25. **shell 输出上限**：`dsh-bash-local` 默认 `maxOutputBytes` 64000 / `maxSpillBytes` 67108864 / `maxTimeoutMs` 600000；溢出「spill 到临时文件」（「配置」）。

### F.3 权限 / 沙箱
26. **文件沙箱不限制读**（见 C.6、C.7）。
27. **"请求沙箱升权"在 `never` 下会被自动拒绝**——「actions that require approval are rejected automatically — do not request sandbox escalation」（`dsh-user-approval/README.zh.md`）。**这不是 bug。**
28. **只有一次性授权**，没有"始终允许"、没有记忆规则、没有撤销（`dsh-user-approval/README.zh.md`「已知限制」）。
29. **审批请求不带工具参数**（同上）。
30. **无应答者即拒绝**：无头部署必须自己组合最终应答者，「同级监听器的顺序不是策略优先级机制」（同上「组合应答者」）。
31. **Windows Low 标签会削弱整个工作区树对其他 Low 完整性进程的防护**（见 C.7）。
32. **Windows 授权会急切遍历整棵工作区树**，大型树「以数十秒计」（见 C.7）。
33. **Windows 受限进程内不能管道捕获子进程输出**（EPERM）（见 C.7）。
34. **`read-only` 下 PowerShell 是 ConstrainedLanguage**（见 C.7）。
35. **观察策略不跨会话恢复；直接 `ctx.fs` 读取不算"已读"**（见 C.8）。
36. **Auto review 是实验功能且有真实风险**：
> 「Auto review 是实验功能：它**可能误放行不安全动作、误拒绝有用操作，并消耗额外 token**。」
> 「**Auto 不提供文件沙箱。** 外层 `run_code` transport 及 PTC 程序内直接 Node 效果不经过 inner-tool review。」
> 「模型分类可能出错。不提供确定性工具豁免、持久 grant、可配置策略或重试层。」
> —— `dsh-experimental-auto-review/README.zh.md`「概述」「已知限制与延期工作」

### F.4 Web / 网络
37. **`web_fetch` 不请求审批**：
> 「**公开抓取不请求审批**——随产品交付的 `cordis`、`code` 与 `standard` preset 在所有 sandbox 和审批模式下公开 `web_fetch`。HTTP 提供方会阻止非公开目标，**但模型仍可向公开 URL 发送数据**。需要逐次确认的部署必须添加 `tools/pre-execute` 策略或禁用抓取。」
> —— `dsh-tool-web/README.zh.md`「已知限制」
38. **web 内容是不可信数据**：「结果会把提供方控制的文本标记为外部不可信数据」（`dsh-tool-web/README.zh.md`「概述」）。
39. **一次 `web_search` 可能是一整个模型轮次**（`dsh-web-search-deepseek/README.zh.md`「何时选择」）。
40. **前端必须先构建**：「源码 checkout 需要先运行 `pnpm run build`；dist 缺失时启动会以构建提示停止，且没有从源码直接服务的回退路径。」（`dsh-web-app/README.zh.md`「已知限制」）
41. **不能绑定所有网络接口**：「出于安全考虑，`--host 0.0.0.0` 会在启动时被拒绝」（同上）。
42. **LAN 地址只在启动时采样一次**（同上）。
43. **只报告"请求打开浏览器"，不报告真的打开了**（同上）。

### F.5 会话 / 持久化
44. **恢复的会话不携带已观察状态**（见 F.2.34）。
45. **创建但从未 append 的会话不落盘**：「已创建但从未 append 的会话不留下任何磁盘内容」（`dsh-session-persistence-jsonl/README.zh.md`「持久性与崩溃语义」）。
46. **崩溃后保留被中断的轮次**：「已存储日志保留被中断的最终轮次……由执行恢复的读方通过其写句柄追加合成 closer。」
47. **`sessionId` 不指定时每次启动都是新会话**（见 A.6）。
48. **headless 续接有严格前置条件**：「沿用要求已组合 `sessionPersistence` 与 `sessionQuery` 服务，因此缺少任一服务的 profile 会显式失败」；并且拒绝"子 agent 或 fork 会话、未记录工作目录的会话、运行在本 profile 不组合的 agent preset 下的会话"（`dsh-headless/README.zh.md`「选择 Session 标识」）。
49. **headless 一次只跑一个任务，没有交互式后续**（`dsh-headless/README.zh.md`「概述」）。

### F.6 其他
50. **goal 只有轮次预算**：「`maxGoalRounds` 不计量 token、货币、挂钟时间或提供方配额。」（`dsh-goal/README.zh.md`「已知限制」）默认 `defaultMaxGoalRounds` 256。
51. **PTC 中间值不可回放且有内存风险**：「PTC mode 中间值只存在于执行局部，且没有字节上限：它们无法从会话回放重建，并可能耗尽进程或 worker 内存」；「每次运行都会获得全新的 `run_code` 状态」（`dsh-tools/README.zh.md`「已知限制」）。
52. **工具定义里的 `timeoutMs` 只是声明**：「注册表绝不会强制执行截止时间；要强制执行，必须使用 `@deepseek-ai/dsh-tool-call-timeout-policy` 包装层。」（同上）
53. **`read` 只处理 UTF-8 文本**；「PDF、音频和视频仍延期处理」（`dsh-tool-fs/README.zh.md`「已知限制」）。
54. **`read`/`write`/`edit` 没有超时接口**（同上）。
55. **附件永不自动删除**：「已存储附件不会被自动删除」（`dsh-attachment/README.zh.md`「概述」）。
56. **`dsh-app-boot` 的 schema dump 不是沙箱**：「导入、Config getter 和 lazy builder 仍会执行可信代码；**收集不是沙箱**。」「`--dump-config-schema` 会导入每个组合模块以读取其 schema，请只对已经信任其插件的 profile 运行。」（`dsh-app-boot/README.zh.md`「检查插件配置 schema」）
57. **运行时不变量检查**：`dsh-invariants` 存在，但【文档未说明】默认是否开启。

---

## G. 版本相关（0.2.0-rc.2 的实验/EXP/RC 状态）

### G.1 版本事实
- 归档 `/dsh/package.json`：`"name": "@deepseek-ai/dsh-desktop-runtime", "version": "0.2.0-rc.2"`。
- 287 个依赖全部精确锁在 `0.2.0-rc.2`（含 `@deepseek-ai/dsh`）；另有 `@deepseek-ai/cordis` 4.0.4、`cordis-plugin-*` 1.0.x、`@deepseek-ai/schemastery` 3.18.4、`@deepseek-ai/node-addon-system` 0.1.2。
- **RC 语义**：`dsh-app-boot/README.zh.md`「Profile」明确「**预发布版本参与范围匹配**」——即 rc 版本号会参与 peer 范围比较。

### G.2 明确带"实验性"标签的全部条目（逐条原文）

| 包 | 官方原文 |
|---|---|
| `dsh-experimental-auto-review` | 「Auto review 是实验功能：它可能误放行不安全动作、误拒绝有用操作，并消耗额外 token。」「dsh 安装随附此层但**默认关闭**；在 Web 侧栏插件页开启或显式安装之前，默认 Web 保持三种权限模式。」 |
| `dsh-experimental-agent-team` | 「它以**实验性名称公开发布、不承诺稳定性**，并且需要持久会话存储才能激活。」「**实验原型，无稳定性承诺**——本包公开发布，但孵化期间约定仍可自由变更。」 |
| `dsh-experimental-agent-team-profile` | 「本包随 dsh 安装提供，**默认关闭**。」「**仅显式启用**——本包随安装提供但默认关闭；随附 CLI、Web、SDK、ACP 与 Python profile 都不会启用它。」 |
| `dsh-experimental-tool-agent-team` | 「本包以实验性名称公开发布，但不提供稳定性保证。」「**实验原型，无稳定性承诺**……孵化期间 schema 仍可自由变更。」 |
| `dsh-experimental-schedule-bundle` | 「每次安装都随包携带且**默认禁用**，插件管理页在"官方"分组中提供它。」 |
| `dsh-experimental-voice-input-bundle` | 「可选 Bundle 安装使插件管理器能够发现此包，但**不会在默认配置中选择它**。」 |
| `dsh-experimental-speech-to-text` | 「具名实验性转写 Provider 及取消操作的所有权。」 |
| `dsh-client-ui-permission-presets` | 「`auto` 带有 `EXP` badge，并在可见选择时要求实验风险确认。」 |
| `dsh-client-ui-plugin-manager` | 「名称以 `@deepseek-ai/dsh-experimental-` 开头的官方包显示实验性标记。」 |
| `dsh-session-telemetry-otel` | 「**上游实验性源码树**——`@opentelemetry/sdk-logs` 从上游实验性源码树发布」 |
| `dsh-session-query-sqlite` | 「把 **SQLite 的实验性警告**推迟到首次实际搜索」 |
| `dsh-ptc-runtime` | 「**私有实验性 Python 提供方**拒绝显式策略」 |

**实验包完整名单（11 个 `dsh-experimental-*`）**：`agent-team`、`agent-team-profile`、`api-speech-to-text`、`auto-review`、`client-ui-agent-team`、`client-ui-voice-input`、`schedule-bundle`、`speech-to-text`、`speech-to-text-sensevoice`、`tool-agent-team`、`voice-input-bundle`。

### G.3 其他"部分/受限"状态
- **Windows 沙箱是"部分强制执行"**（`dsh-sandbox/README.zh.md`「模式与强制执行」、`dsh-sandbox-windows-acl/README.zh.md`「概述」）。
- **`dsh-app-boot` 自述「已知限制与延期工作」**并声明"这些是当前包约束，不是任务积压"；多个包有 "开发备注（维护者的工作上下文，明确不具权威性）" 段落——**引用这些内容时不能当作已交付承诺**。
- **`dsh-sdk-minimal`**：「独立 SDK profile，默认提供一个 shell 工具」「它不继承其他 bundle，因此每个额外配置项都是显式 profile 变更」。
- **`dsh-ptc-runtime`**：「**提供方的约束能力不同**——已发布 Node 提供方强制执行已解析文件策略，私有实验性 Python 提供方拒绝显式策略。**不提供容器提供方。**」

### G.4 与本次会话直接相关的版本事实
本次会话（workspace-write 策略 + 审批被禁用）与文档描述完全一致：
- 会话收到的策略文本＝`dsh-sandbox-policy/README.zh.md` 的 `workspace-write` 原文逐字一致。
- 会话收到的审批文本＝`dsh-user-approval/README.zh.md` 的 `never` 原文逐字一致（"Approval prompts are disabled in this session: actions that require approval are rejected automatically — do not request sandbox escalation (do not set `sandbox_permissions`)."）。
- **【推断】** 因此本机运行在 `workspace-write` 预设 + `never` 审批策略。`dsh-permission-presets` 的默认 `danger-full-access` 预设正是 `{ sandbox: danger-full-access, approval: never }`——所以"`never` + `workspace-write`"这个组合在官方命名里不匹配任何**配置预设**，按 `custom` 推导；但 Auto review 的固定身份是 `Full access + ask`，也不匹配。**【推断】** 这更像部署方在 profile/home patch 里显式设了 `approval.policy: never`，而不是选了某个预设。

---

## H. 文档之间的矛盾（不擅自取舍，原样报告）

### H.1 preset 名称 `code` vs `ptc`（3 处不一致）
- `dsh-tool-web/README.zh.md`「已知限制」：「随产品交付的 `cordis`、**`code`** 与 `standard` preset……」
- `dsh-command-goal/README.zh.md`：「在 `standard`、**`code`** 和 `cordis` agent preset 中挂载 producer」
- `dsh-client-ui-deliverables/README.zh.md`：「Web 的 `standard`、**`ptc`** 与 `cordis` preset 提供 `present`」
- `dsh-web-app/README.zh.md`「源码地图」：preset 目录为 `standard`、**`ptc`**、`minimal`、`cordis`
- **解释（官方）**：`dsh-session-format-v2-to-v3/README.zh.md`：「在 `header.agentPreset` 和每条 `agent-preset/selected.data.agentPreset` 中，**精确匹配的预设标识 `code` 变为 `ptc`**」
- **结论**：`ptc` 是 v3 之后的新名字，`code` 是旧名字；**`dsh-tool-web` 与 `dsh-command-goal` 的中文文档未随重命名更新**。以 `dsh-web-app` 的 `standard / ptc / minimal / cordis` 为准。

### H.2 session 格式"当前版本"不一致
- `dsh-session-persistence-jsonl/README.zh.md`「磁盘布局」注释：`session.v3.jsonl.zstd  # released v3/current`
- 同一文件「读取日志」段落：「**当前 V4 打开跳过发现**，并在暴露事件前校验目录字段、唯一性及当前投递归属。」
- 归档里同时存在 `dsh-session-format-v3-to-v4`。
- **结论**：**v4 更可能是当前物理格式**，磁盘布局注释疑似文档滞后。**未能从随包文档得到唯一权威答案**（`dsh-session-format-catalog/README.zh.md` 只说它提供"构建期静态第一方 Session 格式编解码器与相邻迁移装配"，没有列版本表）。

### H.3 `dsh-tool-web` 的示例用了未随包发布的搜索提供方
- `dsh-tool-web/README.zh.md`「最小配置」示例：
  ```yaml
  - name: '@deepseek-ai/dsh-web'
  - name: '@deepseek-ai/dsh-web-search-exa'
  - name: '@deepseek-ai/dsh-tool-web'
  ```
- 但 0.2.0-rc.2 的 287 个依赖里**没有 `dsh-web-search-exa`**，只有 `dsh-web-search-deepseek` 与 `dsh-web-fetch-http`。
- **结论**：该示例的提供方名字与本次发布不符（可能是通用示例或来自其他发行渠道）。以 `dsh-web-search-deepseek` 为准。

### H.4 工具结果修剪阈值 8192 字符的归属（**已交叉验证，非矛盾**）
- `dsh-agent-preset/README.zh.md`「使用此包」：「每个出货的 `SKILL.md` 作为 `skill` 工具结果渲染后都保持在 8192 字符阈值之下，标准 preset 的工具结果修剪器超过该阈值才会裁剪。」
- `dsh-compaction-tool-result-pruner/README.zh.md`「调整修剪预算」给出**同一数字**：
  > 「所有设置都可选；**默认会把文本超过 8,192 个字符的结果修剪为其前 4,096 加后 1,024 个字符**，并用标记连接。」
  配置表：`thresholdChars` 默认 `8192`（「合并文本超过此 Unicode 码点数时修剪。」）
- **结论**：两处一致。这是**官方默认**：技能正文被要求控制在 8192 字符以下，正是为了让默认修剪器不裁剪它们。（此条最初被我误记为"未列出默认值"，已更正。）

### H.5 「组合包索引」不存在
- `dsh-base/README.zh.md`、`dsh-web-app/README.zh.md` 都指向「[组合包索引](../README.zh.md)」，即 `/dsh/node_modules/@deepseek-ai/README.zh.md`。
- **【已验证】该文件在归档中不存在。** 所有 `@deepseek-ai/<pkg>/README.zh.md` 里引用的 `docs/*`、`apps/cli/*`、`.agents/notes/*`、`../../bundle/README.zh.md` 也都**不在归档内**。

---

## I. 从随包文档**无法确定**的事项（建议 Lead 联网核实）

### I.1 完全不在安装包内的官方文档（随包 README 反复引用但缺失）
1. **官方用户指南**：`docs/user/guide/index.zh.md`、`docs/user/develop/practice/index.zh.md`——`dsh/README.zh.md`「可选覆盖层」明确说"设置与安全说明由[用户指南]和[开发实战指南]负责"，即**面向初学者的部分随包缺失**。
2. **`docs/config-catalog.zh.md`**——**几乎每个包**都称它是"每个受支持字段及其 JSDoc 的穷尽式真源"。缺失意味着**配置项的完整枚举无法从随包文档得到**。
3. **`docs/tool-catalog.zh.md`**——工具 schema 的穷尽式真源。缺失意味着**无法得到工具的完整 JSON Schema**。
4. **`docs/subsystems/*.zh.md`**（core / session / tools / sandbox / filesystem / skills / compaction / approval / permission-presets / persistence-catalog）。
5. **`docs/cordis-primer.zh.md`**（Cordis 入门）。
6. **`docs/cookbook/adding-a-tool.zh.md`、`docs/cookbook/adding-a-package.zh.md`**（含"插件展示元信息"格式）。
7. **`apps/cli/reference/README.zh.md`**（CLI 行为参考、启动诊断、config-schema dump）、`apps/cli/composition.md`（生成组合图）、`apps/cli/README.zh.md`。
8. **`docs/persistence-catalog.zh.md`**（持久化日志事件目录）。
9. **`.agents/notes/**`**（决策记录；随包 README 大量引用）。
10. **`/dsh/node_modules/@deepseek-ai/README.zh.md`（组合包索引）** —— 不存在。

### I.2 没有中文 README 的包（10 个）
`cordis`、`cordis-plugin-group`、`cordis-plugin-include`、`cordis-plugin-loader`、`cordis-plugin-timer`、`cosmokit`、`schemastery`（以上 7 个有英文 README）、
**`dsh-desktop-host`（连 README.md 都没有）**、`dsh-web-frontend`、`libreoffice-kit-win32-x64`。
→ **Desktop（Electron）外壳的行为、菜单、内置命令运行时** 无法从随包文档获得；`dsh/README.zh.md` 提到「Desktop 内置命令可以使用该安装的运行时管理已初始化的 Desktop profile」，但其 README 不在包内。

### I.3 随包文档明确指向"仓库内文件"的内容
- 各随附 profile 模板的**确切插件行清单**（`apps/cli/composition.md` 缺失）。虽然归档里有 `dsh-base/cordis.patch.yml`（20,780 字节）与 `dsh-web-app/cordis.patch.yml`（21,637 字节）+ `presets/*.patch.yml`，**但这些是包内容，不是"首次使用时自动初始化"的模板**。
- `OPTIONAL_BUNDLES` 的**确切数组元素**（只在文档里被点名了 schedule-bundle / auto-review / voice-input-bundle / agent-team-profile 四项；`packages/boot/app-boot/src/profile.ts` 不在归档内）。
- 各 bundle 的 `dsh.bundle.patch` **声明的确切文件列表**（文档说了机制，未列全部实例）。

### I.4 官方文档根本没提的问题
- **计费 / 配额 / 速率限制**：`dsh-client-ui-chat` 提到 UI 有 `message.failure.quota` 文案，但**没有官方配额数字**。
- **`whenToUse` / `metadata` frontmatter 字段的确切类型与语义**（只被列为"可选"）。
- **`dsh-invariants` 运行时检查默认是否启用**。
- **Web 组合默认是否挂了 `dsh-experimental-auto-review`**（文档说"随附此层但默认关闭"，但没说默认是否"安装"）。
- **具体权限预设在本机 Desktop 构建里被改成什么样**（文档只给包级默认值）。
- **`dsh-schedule` / 语音输入在本机是否可用**（需要下载模型 / 依赖 Desktop Session controller）。
- **【文档未说明】macOS/Linux 上 Seatbelt / Landlock 的确切可写集合**（只说与 `writableRoots` 共享）。
- **`dsh-desktop-host` 与 `dsh-web-frontend` 的接口**（无文档）。
- **随包技能在本机是否已注册**：`dsh-skill-filesystem` 的 `bundledSkillDir` 默认未设置（表里写 `—`），随包技能通过 `dsh-agent-preset` 在**创造模式**下挂载 `skills/` 目录——但"创造模式"的确切启用条件**文档未说明**（只在 `dsh-client-ui-agent-preset` 说"当 `cordis` preset 在列表中且存在会话流程时提供"）。

### I.5 需要联网/官方渠道确认的高风险点
1. **`0.2.0-rc.2` 是否有更新版本**，以及 rc → 正式版的兼容承诺。
2. **peer 范围检查的确切失败行为**在网络不可达时（文档说"注册表包名通过 `pnpm view` 询问注册表"）。
3. **默认 registry / 镜像端点**：文档给出 `OFFICIAL_NPM_REGISTRY`、`NPMMIRROR_REGISTRY`、`fallbackRegistries` 默认 `['https://registry.npmmirror.com/']`，但**没有给出 `OFFICIAL_NPM_REGISTRY` 的字面值**。
4. **`dsh plugin` 在 Desktop 载体下的可用范围**（文档说 Desktop 包管理操作"仍由 Desktop shell 负责"）。
5. **官方对 Auto review / Agent Teams 的稳定性路线图**。

---

## J. 给初学者的一页速查

**必须先懂的 7 句话**
1. `dsh` 是唯一入口；**profile 决定你看到什么界面**（web / headless / sdk / acp / desktop）。
2. **profile = 有序 bundle 列表 + 你自己的 `cordis.patch.yml`**；配置树 = bundle patch → profile patch → home patch → `--patch`。
3. **patch 替换整块 config，不做合并**——覆盖时必须重述要保留的字段。
4. **bundle 是 patch 层，不是代码**；能让 profile 失败的通常是没有 `dsh.bundle.patch` 的普通依赖被"选中"。
5. **权限 = 沙箱模式 × 审批策略**；默认预设把 `workspace-write + ask` 和 `danger-full-access + never` 捆在一起。
6. **文件沙箱只管写/改，不管读**；Windows 上它是"ACL 受限令牌 + Low 完整性"，并且是**部分强制执行**。
7. **技能就是磁盘上一个 `SKILL.md`**（`name` + `description` 必填），放进被扫描根目录即刻生效，无需重启。

**最常踩的 5 个坑**
| 坑 | 官方依据 |
|---|---|
| 覆盖 patch 时忘了重述其他字段 → 配置被清空 | `dsh-base/README.zh.md`「已知限制」 |
| 在 `cordis.patch.yml` 里只写注释 → **启动失败**（该用 `[]`） | `dsh-app-boot/README.zh.md`「Profile」 |
| 以为 `read-only` 能阻止模型读文件（实际只阻止写） | `dsh-fs-sandbox/README.zh.md`「设计理念」 |
| 以为 `never` 下还能请求升权（会被自动拒绝） | `dsh-user-approval/README.zh.md` |
| 在沙箱化 fs 之上再挂 `dsh-fs-local` → profile 拒绝加载 | `dsh-base/README.zh.md`「更改默认值」 |
