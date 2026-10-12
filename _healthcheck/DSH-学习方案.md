# DeepSeek Harness 学习方案（新手版）

> 面向：**第一次使用 DSH 的新手**
> 针对安装：**Desktop 桌面版 0.2.0-rc.2**（`D:\DeepSeek Harness`，本机实际安装）
> 生成日期：2026-10-12
> 证据基础：本机 `app.asar` 内随包官方文档（279 份 README 全部提取）+ 官方 CLI 实测 + 社区资料联网核查
> 交叉验证：**是**。官方文档 / 社区说法 / 本机实测 三方比对，冲突处已标注（见第六章）
> **修订 2026-10-12 10:0x**：第三方 skill 已全部移除，本方案第〇章与第 3.1 节已相应改写

---

## 〇、当前状态：已恢复纯净的官方 DSH

### 结论：53 个第三方 skill 已全部移除，DSH 回到官方初始状态

原问题（`C:\Users\wengw\.agents\skills` 里的 53 个 skill 全部由 OpenClaw 体系带入）**已经处理完毕**。

### 移除依据（哈希级取证，不是靠名字猜）

用回收站里残留的隔离区元数据重建原目录清单，逐文件比对 SHA-256：

| 证据 | 结果 |
|---|---|
| 隔离区里存在的 `skills` 根目录 | **11 个** |
| 隔离区 skill 名集合 | 65 个 |
| `.agents\skills` 文件夹 | **53 个** |
| **交集** | **53 个 = 100%** |
| **无法解释的（S2_ONLY）** | **0 个** |
| 逐文件比对 | 295 个文件，**290 个 SHA-256 逐字节相同**，5 个不同（不同修订版），0 个无法判定 |
| 47/52 个技能 | **该技能全部文件哈希全等** |

品牌字符串铁证（152+ 处命中，21 个文件）：`ClawHub`、`npx clawhub install`、`openclaw.json`、`~/.clawdbot/`、`AutoClaw.app`、`metadata: {"clawdbot":…}` 等。

### 执行结果（2026-10-12 09:33）

| 项目 | 结果 |
|---|---|
| 移除的文件夹 | **53 个**（297 个文件 / 48.4 MB） |
| 失败 | **0 个** |
| 移除方式 | **移动，不是删除**（同盘重命名） |
| 现 DSH 扫描根 | **0 个文件夹、0 个文件** |
| 官方自带 skill | **完好无损** |
| 生效方式 | **即时生效** —— DSH watcher 在下一个模型步骤就更新了 skill 目录，**无需重启** |

**可一键还原**，备份位置：
```
C:\Users\wengw\Documents\deepseek-harness\default-workspace\_removed-skills-backup\20261012-093104\
├── skills\                          ← 53 个文件夹原样
├── manifest-20261012-093332.csv     ← 53 行清单（文件数/字节数/SKILL.md 的 SHA-256）
├── skill-lock.json.bak              ← 原来源溯源记录
└── REMOVAL-RECORD.md                ← 完整记录 + 恢复命令
```

完整性已核对：清单声称 297 个文件，备份实际 297 个，**完全吻合**。

### 现在 DSH 里剩哪些 skill

| Skill | 官方来源包 | 可见性 |
|---|---|---|
| `office-docx` / `office-pptx` / `office-xlsx` | `dsh-skill-office` | 标准模式可见 |
| `diagnose-windows-sandbox-acl` | `dsh-sandbox-windows-acl` | 标准模式可见 |
| `agent-experience` / `cordis-composition-reference` / `cordis-plugin-development` / `editing-cordis-compositions` | `dsh-agent-preset` | **仅 `cordis` preset** |
| `dsh-badge` | `dsh-skill-badge` | 默认禁用 |

### 六个 skill 扫描根目录的当前状态（官方机制）

| rank | 根目录 | 状态 |
|---|---|---|
| 100 | `<项目根>/.dsh/skills` | 不存在 |
| 200 | `<项目根>/.agents/skills` | 不存在 |
| 300 | `Config.customSkillDirs` | 未配置 |
| 400 | `C:\Users\wengw\.dsh\skills` | **不存在（推荐你放自己 skill 的位置）** |
| 500 | `C:\Users\wengw\.agents\skills` | **已清空（0 项）** |
| 600 | 随包目录 | DSH 自带 |

### 遗留项（未动，供你决定）

| 项 | 说明 | 建议 |
|---|---|---|
| `~\.agents\skills\`（空目录） | 扫描根本身，现在是空壳 | 留着无害 |
| `~\.agents\.skill-lock.json` | 记录那两个 skill 来自 GitHub `vercel-labs/*` 的溯源文件 | **建议保留**（已备份） |
| `~\.agents\plugins\marketplace.json` | 悬空条目，引用的 `./plugins/github` 不存在；**不含任何 claw 字符串，与 OpenClaw 无关** | 可删 |

> 📌 **回收站已于 2026-10-12 10:02 由你清空**，隔离区原始证据不再可查。但**上表所有比对结论已在清空前完成并固化**到 `manifest-20261012-093332.csv`，结论依然有效。

### 诚实交代：3 处保留判断 + 1 处无法证明

| 对象 | 为什么不能 100% 断定 |
|---|---|
| `agent-browser` | 隔离区**只剩目录名、没有文件记录**，无哈希证据；且 `.skill-lock.json` 记载它 2026-09-15 由 GitHub `vercel-labs/agent-browser` 安装 → 有**竞争性来源** |
| `find-skills` | 同样有 GitHub 来源记录（2026-09-11，`vercel-labs/skills`）；`SKILL.md` 同尺寸但哈希不同 |
| `a-stock-analysis` / `feishu-drive` / `debug-pro` / `test-runner` | `SKILL.md` 有差异（其中 `debug-pro`、`test-runner` 确认是**不同修订版**：隔离区版是纯 Markdown，`.agents` 版被加了 YAML front-matter） |
| **复制方向** | **无法证明**——不能断定是"OpenClaw 复制了 `.agents`"还是反过来。只能证明**两者高度同源**（290/295 字节相同） |

> 这三项仍被一并移除，因为你的要求是"其他 AI 工具带过来的一律不要"——它们同样不是 DSH 官方内容。如果日后想要回来，备份里都在。

### 附带结论

除回收站外，全机（用户目录 / AppData / ProgramData / 开始菜单 / 桌面 / 计划任务）**未发现任何 openclaw / autoclaw / sclaw / clawdbot 残留目录或快捷方式** → 磁盘层面已清干净。


---

## 一、先建立心智模型：DSH 到底是什么

官方原话：**「`dsh` 是唯一受支持的 Node 应用启动器；profile 由多个插件组合包 patch 层按顺序叠加而成，其上再应用用户自己的覆盖配置。」**

### 一句话理解

> **DSH 不是"一个软件"，而是"一套可组装的 Agent 运行时"。你看到的界面，只是某个 profile 装配出来的结果。**

### 三个核心概念（必须分清）

```
dsh（启动器）
 └── profile（配置集）← 决定你看到什么界面
      └── bundles（组合包，有序列表）← 一堆 patch 层
           └── plugins（插件）← 真正的功能，每个工具/技能/界面都是插件
```

| 概念 | 是什么 | 类比 |
|---|---|---|
| **profile** | 一套完整的插件装配方案。web / headless / sdk / acp / **desktop** | 不同的"整机配置单" |
| **bundle** | **patch 层，不是代码**。声明"要插入哪些插件行" | 一张"装件清单" |
| **plugin** | 真正的代码，通过 `apply(ctx)` 挂载，用 `ctx.*` 互相通信 | 实际的零件 |
| **skill** | 一个 Markdown 文件，教模型"怎么做某件事" | 给模型的说明书 |

**配置树的叠加顺序（官方唯一定义）：**
```
bundle patch（按 bundles 列表顺序）
  → profile 的 cordis.patch.yml
  → $DSH_HOME/cordis.patch.yml
  → --patch 命令行覆盖
```

### 你的机器上实际是什么

| 项目 | 你的值 | 怎么确认的 |
|---|---|---|
| 版本 | **0.2.0-rc.2**（287 个依赖全部锁死此版本） | `app.asar/dsh/package.json` |
| profile | `desktop` | `DSH_PROFILE=desktop` |
| profile 目录 | `C:\Users\wengw\.dsh\profiles\desktop\` | 含 `package.json` + `cordis.patch.yml` |
| 你的 bundle 列表 | `@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app` | profile 的 `package.json` |
| 你的个性化覆盖 | `cordis.patch.yml` 里 4 条 | 模型/账号/UI 设置 |
| 界面地址 | `http://127.0.0.1:19387` | `DSH_WEB_URL` |

**重要**：Desktop 的 `desktop` profile 被官方**禁止用 CLI 检查**（我实测 `dsh --profile desktop --dump-config` 返回 `error: profile "desktop" is managed exclusively by the Electron application`）。这是设计，不是故障。

### 会话（Session）是什么

会话是**只追加的事件日志**，不是聊天记录。模型每次看到的是**派生出来的历史**。你可以在"轨迹"里看到系统提示词、思考、每次工具调用。

---

## 二、最容易搞混的 5 组概念

初学者 90% 的困惑来自这 5 组混淆：

| 别搞混 | 区别 |
|---|---|
| **skill vs plugin** | skill = Markdown 说明书，放目录即生效，**`dsh plugin add` 装不了它**<br>plugin = 代码包，必须走 `dsh plugin` 安装 |
| **沙箱 vs 审批** | 沙箱 = "**能碰什么**"（read-only / workspace-write / full）<br>审批 = "**要不要问你**"（ask / never）<br>它俩是**两个独立旋钮**，但预设把它们捆在一起 |
| **权限 vs 实际拦截** | 文件沙箱**只管写/改，不管读**。`read-only` 挡不住模型读你的文件 |
| **profile vs preset** | profile = 你启动的是哪个应用（web/desktop）<br>preset = 会话里 Agent 拿到哪套工具（standard/ptc/minimal/cordis） |
| **压缩 vs 清空** | 压缩（compaction）只压缩**派生历史**，压缩不掉系统提示词、工具定义、会话前缀 |

---

## 三、学习路径：三个阶段

### 阶段 1 · 用起来（第 1–2 天，目标：不再怕它）

**只做一件事：学会提需求。**

新手最大的误区是"研究配置"，其实**标准模式开箱即用的能力已经很完整**。你要练的是**怎么把任务说清楚**。

**练习 1.1 — 摸清它有什么能力**（10 分钟）
```
请用一句话逐个说明你当前可以调用的每一个工具是做什么的，
并按「读 / 写 / 执行 / 搜索 / 编排」分类。
```
看它的回答，你就知道手上的工具面了。**这比读文档快**。

**练习 1.2 — 第一次真实任务**（20 分钟）
在你自己的工作区里：
```
把当前工作区的所有文件列一遍，说明每个文件是干什么的，
然后给我一个"这个目录里还缺什么"的清单。
```

**练习 1.3 — 学会用"轨迹"**（15 分钟）
任务跑完后，打开轨迹面板，看三样东西：
1. **系统提示词** —— 模型被喂了什么（你会看到那一长串 skill 目录）
2. **工具调用序列** —— 它每一步干了什么
3. **思考过程** —— 它为什么这么干

> **这一步是新手和熟手的分水岭。** 看懂轨迹，你才能判断"是模型笨"还是"我给的信息不够"。

**练习 1.4 — 观察它怎么委派子任务**（15 分钟）
```
分析这个工作区，把「读取所有文件」和「总结」拆成两个并行子任务，
用子代理执行，最后汇总。
```
你会看到 `subagent` 工具和后台任务（`job_*`）怎么工作。

---

### 阶段 2 · 用得好（第 3–5 天，目标：省心、省钱、不出事）

#### 2.1 权限与安全（**最优先，务必理解**）

这是**官方反复警告、新手最容易搞错**的地方。

**三个沙箱模式（官方原文语义）：**

| 模式 | 官方语义 |
|---|---|
| `read-only` | 「拒绝写入，必需 sink 除外」 |
| `workspace-write` | 「允许写入工作区根目录及后端定义的临时区域」 |
| `danger-full-access` | 「绕过隔离」 |

**审批策略只有两个值：**

| 策略 | 语义 |
|---|---|
| `ask` | 需要审批时**问你** |
| `never` | 「在交互式分发之前**确定性地拒绝**每个请求」——不是"自动同意"，是**自动拒绝** |

**⚠️ 四条必须记住的官方警告：**

1. **文件沙箱只管写，不管读。**
   官方原文：「**写入与删除受限；读取、网络与进程可见性不受限。**」
   → 不要把 `read-only` 当成"隐私保护"。它的作用是**防误改**，不是防偷看。

2. **`never` 下请求升权会被自动拒绝，这不是 bug。**
   官方原文：「actions that require approval are rejected automatically — do not request sandbox escalation」
   → 如果你想让它临时突破沙箱，**必须用 `ask`**。

3. **只有一次性授权**，没有"始终允许"、没有记忆规则、没有撤销。

4. **Windows 上是"部分强制执行"。**
   官方原文：「**任何 Win32 操作失败都会阻止不受限的 spawn**」，机制是「受限令牌 + Low 完整性标签」。副作用包括：
   - `read-only` 下 PowerShell 会降级到 ConstrainedLanguage（`Add-Type`、COM、反射会失败）
   - 受限模式下 **CIM cmdlet 和 `Get-ComputerInfo` 不可用**
   - 受限进程内 `spawn(..., {stdio:'pipe'})` 会 **EPERM 失败**
   - 授权会**急切遍历整棵工作区树**（大目录树上要几十秒）

   → **实用结论：工作区不要设在超大的目录（比如整个 `C:\Users\你`）上。**

**你的当前状态**：`workspace-write` + `ask` —— **这是官方推荐的日常组合，保持它。**

**练习 2.2 — 感受审批与升权**（20 分钟）
让它做一件工作区外的事，比如"把某个文件复制到桌面"。观察：
- 沙箱怎么拦（`[sandbox: file access denied under workspace-write mode]`）
- 升权提示长什么样
- 你在弹框按 Enter（批准）/ Esc（拒绝）的区别

**练习 2.3 — 理解"只有一次性授权"**（10 分钟）
让它连续做两次同样的越界操作。第二次**还是会问你** —— 这就是"没有始终允许"。

#### 2.2 省钱：理解 token 是怎么烧的

官方给出了精确的数字，新手看一眼就能省一大笔：

| 机制 | 官方默认值 | 对你的意义 |
|---|---|---|
| 工具结果修剪 | 超过 **8192** 字符的结果被裁成 前 4096 + 标记 + 后 1024 | 别让它 `read` 一个巨型日志 |
| 压缩阈值 | `floor(min(W×0.8, W−O−65536))` | 留 65536 token 余量 |
| 逐字保留近期历史 | `W−O` 的 **16%** | 近期上下文不会被摘要 |
| **工具结果反复计费** | —— | 「保留的调用与结果会**反复发送**，直到上下文压缩」 |
| **图片每次请求都计费** | —— | 「图像在之后**每次**请求中都会计费，直到压缩」 |
| 图片省略**永不回退** | —— | 「临时的小预算会**永久省略**」 |

**三条省钱铁律：**
1. **别让它读大文件全文** → 让它 `grep` 或 `read` 指定行范围
2. **别频繁贴图** → 图片的 token 成本会一直跟着你
3. **长任务让它自己 `/compact`** → 而不是开新会话从头讲

**练习 2.4**：让它读一个 >8000 字符的文件，然后看轨迹里工具结果被裁的痕迹（前 4096 + 标记 + 后 1024）。

#### 2.3 会话管理

**可用的斜杠命令（我从本机客户端包里提取的实际清单）：**

| 命令 | 作用 |
|---|---|
| `/permission` | 查看/切换当前会话权限预设（**最常用**） |
| `/compact` | 手动压缩上下文（**轮次中不可用**） |
| `/goal` | 目标管理（`minimal` 模式没有） |
| `/plan` | 计划模式 |
| `/export` | 导出会话日志 ZIP |
| `/feedback` | 消息反馈 |
| `/usage` | 用量 |
| `/<skill-name>` | 直接调用某个 skill |

**关键事实**：会话日志落在 `$DSH_HOME\sessions\`，**格式是 JSONL + zstd 压缩**（本机实测确认，不是 SQLite）。

**练习 2.5 — 会话恢复与分叉**（15 分钟）
- 关掉会话重开，确认能继续
- 注意：**恢复的会话不保留"已读状态"** → 恢复后它必须重新 `read` 文件才能改（官方设计）

---

### 阶段 3 · 改造它（第 2 周起，目标：让它长成你的形状）

#### 3.1 写你自己的第一个 skill（**性价比最高的扩展方式**）

**skill 的官方解剖：**

```markdown
---
name: release-notes-writer          # 必填，kebab-case：^[a-z0-9]+(?:-[a-z0-9]+)*$
description: 需要把一段变更整理成发布说明时使用。   # 必填，模型的唯一路由依据
whenToUse: ...                      # 可选
disable-model-invocation: false     # 可选，默认 false
user-invocable: true                # 可选，默认 true
---

正文写步骤、命令、验收标准 —— 只在模型加载它时才被读。
```

**五个必须记住的规则：**
1. **`description` 决定生死** —— 它是模型唯一能看到的路由信息（上限默认 500 字符）。写含糊了模型永远不加载，正文写得再好也没用。
2. **位置**：`<name>/SKILL.md` 或扁平 `<name>.md`。**不支持嵌套 `**/SKILL.md`**。
3. **放进去就生效，不用重启**（watcher 会在下一个模型步骤发现它）。
4. **布尔拼写错误会让整个 skill 被丢弃**（不是忽略那一行）。
5. **正文没有大小上限** —— 但工具结果渲染超过 8192 字符会被裁剪。

**六个扫描根目录（rank 越小越优先）：**

| rank | 根目录 | 你的当前状态 |
|---|---|---|
| 100 | `<项目根>/.dsh/skills` | 不存在（项目专用） |
| 200 | `<项目根>/.agents/skills` | 不存在（项目共享） |
| 300 | `Config.customSkillDirs` | 未配置 |
| 400 | `<dshHome>/skills` → **`C:\Users\wengw\.dsh\skills`** | **不存在 —— 推荐你放自己 skill 的位置** |
| 500 | `<agentsHome>/skills` → `C:\Users\wengw\.agents\skills` | **已清空（0 项）** |
| 600 | `bundledSkillDir` | DSH 自带（现在唯一在供 skill 的根） |

> **项目根 = 最近的含 `.git` 的祖先目录，找不到就用 cwd。**
> 你当前工作区 `default-workspace` **没有 `.git`**，所以项目根 = 工作区本身。

> 📌 **重要实践建议（这次清理的教训）**：
> **你自己的 skill 放 rank 400（`~\.dsh\skills`），不要放 rank 500（`~\.agents\skills`）。**
> 原因：`.agents\` 是**多个 AI 工具共享**的目录（你机器上还有 `.trae`、`.comate`、`.junie`、`.kiro`、`.pencil`、`.marscode` 各自的 skills），放进去会被交叉污染——这次 53 个 skill 就是这么来的。

**练习 3.1**：写一个你自己的 skill，放在 `C:\Users\wengw\.dsh\skills\`（rank 400，DSH 专属，不与其他工具互相污染）。

**练习 3.2（替代原"处理残留 skill"）**：验证**移除已生效** —— 让 Agent 报告它当前能看到的 skill 清单，确认只剩官方自带的那几个。这同时也验证了官方"watcher 即时生效、无需重启"的机制。

#### 3.2 用 preset 换工具面

**官方 preset 名称（我从本机 `dsh-web-app/presets/` 源码核实）：`standard`、`ptc`、`minimal`、`cordis`**

| preset | 工具面 | 什么时候用 |
|---|---|---|
| **`standard`**（你现在用的） | 全套：文件、shell、搜索、skill、计划、子代理、工作流 | **日常首选，别乱换** |
| `ptc` | 同上，但模型写 TypeScript 一次 `run_code` 编排多步 | 大量重复工具往返时；调试更难 |
| `minimal` | 只有 shell + 文件编辑器 | **基准测试用，别拿来干活** |
| `cordis` | standard + 运行时可读写 Cordis 环境，能现场造插件 | 插件开发；风险最高 |

> ⚠️ **社区文章说的 "Creator/创造模式" 在新版里叫 `cordis`**；官方部分文档里残留的 `code` 也已改名为 `ptc`。详见第六章。

#### 3.3 插件（**新手先别急**）

```bash
dsh plugin --profile <名字> add <包名>
dsh plugin --profile <名字> list
dsh plugin --profile <名字> remove <包名>
```

**安全边界必须记住（官方原文）：**
> **「已安装的 Host 代码在宿主进程内运行，不受工作区沙箱限制。」**

→ 装插件 = **给它你本机的完全执行权限**。这就是你"第三方必须经我审批"原则最该应用的场景。

**社区实测数据**：有人测了 **101 个社区插件，只有 11 个能从 npm 干净装上**（社区来源见第七章）。所以插件生态现在很不成熟，别急着堆。

#### 3.4 接入 context7：让"官方文档优先"变成可执行的能力

**为什么这一节重要**：你有一条工作习惯是"官方资料为最高宪法"。但 **DSH 的模型没有联网读文档的能力**——它只有 `web_search` / `web_fetch`（抓公开网页，质量不稳定）。要让"官方文档优先"真正落地，正确做法是**通过 MCP 接入一个官方文档检索服务**。

**好消息**：DSH 官方**自带** `@deepseek-ai/dsh-mcp-client`，不需要装任何第三方插件。

##### 官方 MCP 机制（来自随包 `dsh-mcp-client/README.zh.md`）

| 项目 | 官方说明 |
|---|---|
| 挂载方式 | 每台服务器配置一条记录；**默认不启用任何服务器** |
| 工具命名 | `mcp__<serverName>__<rawName>`，例如 `mcp__context7__query-docs` |
| 传输方式 | `stdio`（本地程序）或 `streamable-http`（远端服务） |
| 协议 | 优先 2026-07-28，回退支持的旧版 |
| 超时 | `toolCallTimeoutMs` 默认 60,000 ms |
| 断线 | `reconnect.enabled` 默认 true，500ms 起指数退避，上限 30s，最多 10 次 |
| 安全提示 | 官方明确：**「服务器指令作为字面文本加入已记录的系统提示词」** → 接 MCP = 让第三方往你的系统提示词里写字 |

##### context7 官方端点（来自 [Context7 官方 MCP Clients 文档](https://context7.com/docs/resources/all-clients)）

| 项目 | 值 |
|---|---|
| 远端 URL | `https://mcp.context7.com/mcp` |
| 认证 | `Authorization: Bearer YOUR_API_KEY` 请求头 |
| OAuth 端点 | `https://mcp.context7.com/mcp/oauth`（仅远端 HTTP 可用） |
| 提供的工具 | `resolve-library-id`（库名 → 库 ID）、`query-docs`（取该库的最新文档与代码示例） |
| 本地方式 | `npx -y @upstash/context7-mcp --api-key YOUR_API_KEY` |
| 本机前提 | `node v24.15.0` + `npx` 已就绪 ✅ |

> ⚠️ **交叉验证提示**：context7 官方文档站所列 "支持的客户端" 里**没有 DeepSeek Harness**。但 DSH 官方自带标准 MCP 客户端、且 context7 支持远端 Streamable HTTP + Bearer 头两种通用方式，**理论上可以直接对接**。**是否真正可用必须以实测为准——我没有实测过，不替你打包票。**

##### 在 DSH 里的配置写法（远端，推荐）

写进 `C:\Users\wengw\.dsh\profiles\desktop\cordis.patch.yml`：

```yaml
- id: mcp-context7
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: context7
    transport: streamable-http
    url: https://mcp.context7.com/mcp
    headers:
      Authorization: !!js '`Bearer ${process.env.CONTEXT7_API_KEY}`'
```

配置后模型会多出两个工具：`mcp__context7__resolve-library-id` 和 `mcp__context7__query-docs`。

> ⚠️ **配置铁律（官方）**：**patch 会替换目标行的整个 config，不做合并** —— 往 `cordis.patch.yml` 里加新条目没问题，但**改已有条目时必须重述所有想保留的字段**。另外该文件**只写注释会导致启动失败**。

##### 与"官方优先"原则的衔接

| 层次 | 来源 | 权威度 |
|---|---|---|
| 1 | **你本机的随包官方文档**（`app.asar` 内 279 份 README） | ⭐⭐⭐⭐⭐ 版本精确匹配，**最高** |
| 2 | 官方仓库 `docs/`（需要能访问 GitHub） | ⭐⭐⭐⭐⭐ |
| 3 | context7 检索到的官方文档 | ⭐⭐⭐⭐ 需确认版本对应 |
| 4 | 社区文章 | ⭐⭐⭐ **必须交叉验证** |

> **实践建议**：DSH 自身的问题**优先查本机随包文档**（它就是"官方宪法"且不会版本错位）；context7 更适合查**你写的代码所依赖的第三方库**的官方文档——那才是它最擅长的场景。

---

## 四、可直接抄的练习清单

| # | 练习 | 目标 | 预计 |
|---|---|---|---|
| 1 | 让 Agent 自我介绍全部工具 | 建立工具面认知 | 10 min |
| 2 | 分析当前工作区并输出清单 | 第一次真实任务 | 20 min |
| 3 | 读轨迹：看系统提示词 | 理解上下文构成 | 15 min |
| 4 | 派子代理并行做两件事 | 理解委派与后台任务 | 15 min |
| 5 | 故意越界操作，观察沙箱拦截 | 理解权限边界 | 20 min |
| 6 | 连续两次同样越界，体会"一次性授权" | 理解审批语义 | 10 min |
| 7 | 让它读大文件，观察 8192 字符裁剪 | 理解 token 成本 | 15 min |
| 8 | 用 `/compact` 手动压缩长会话 | 学会控制上下文 | 10 min |
| 9 | 写第一个自己的 skill（放 rank 400 的 `~\.dsh\skills`） | 学会扩展 | 30 min |
| 10 | 让 Agent 报告当前 skill 清单，确认只剩官方自带 | 验证移除已生效 | 5 min |

---

## 五、官方明确警告的坑（新手直接背下来）

### 配置类（改配置前必读）

| # | 坑 | 依据 |
|---|---|---|
| 1 | **patch 替换整块 config，不做合并** —— 覆盖时必须**重述每个想保留的字段** | `dsh-base` |
| 2 | `cordis.patch.yml` **里只写注释会导致启动失败** —— 要禁用该层请写 `[]` | `dsh-app-boot` |
| 3 | `.env` **只读一次，不搜索父目录** | `dsh-app-boot` |
| 4 | **`PATH` / `DSH_*` / `XDG_*` 不能写在 `.env` 里**（会被拒绝） | `dsh-app-boot` |
| 5 | **代理变量只从 harness home 的 `.env` 接受**，不从调用目录（防 clone 带毒） | `dsh-app-boot` |
| 6 | 沙箱化 fs 之上**不能再挂普通 fs**，否则 profile 拒绝加载 | `dsh-base` |

### 权限类

| # | 坑 |
|---|---|
| 7 | **以为 `read-only` 能挡住模型读文件** —— 它只管写 |
| 8 | **以为 `never` 下还能请求升权** —— 会被自动拒绝 |
| 9 | **Windows Low 完整性标签会向其他 Low 完整性进程放宽整个工作区树** |
| 10 | **工作区放在超大目录上会让授权慢到几十秒** |

### 上下文类

| # | 坑 |
|---|---|
| 11 | **压缩缩不掉系统提示词、工具定义、会话前缀** |
| 12 | **工具结果会一直重发到压缩为止** —— 这是持续成本 |
| 13 | **图片每次请求都计费，且被省略后永不回归** |
| 14 | **`/compact` 在轮次中不可用** |
| 15 | **没有内置轮次预算** —— 失控的长轮次需要你自己用生命周期扩展点取消 |

### 网络类

| # | 坑 |
|---|---|
| 16 | **`web_fetch` 不请求审批** —— 官方原文：HTTP 提供方会阻止非公开目标，**「但模型仍可向公开 URL 发送数据」**。需要逐次确认必须自己加策略 |
| 17 | **一次 `web_search` 可能消耗一整个模型轮次**（DeepSeek 无专用搜索端点） |
| 18 | **不能绑定 `0.0.0.0`** —— 启动时会被拒绝 |

### 本机实测新发现的坑（社区文章都没提）

| # | 坑 | 说明 |
|---|---|---|
| 19 | **在 DSH 会话内跑 `dsh` 命令会被沙箱拦住** | 我实测 `dsh --profile headless --help` 返回 `EPERM: mkdir 'C:\Users\wengw\.dsh\profiles\headless'`。因为 `$DSH_HOME` 在工作区外，`workspace-write` 不让写。<br>**解决**：在你自己的终端里跑 `dsh`，或在会话里授权 `danger-full-access` |
| 20 | **Desktop 的 desktop profile 禁止 CLI 检查** | `dsh --profile desktop --dump-config` → `error: profile "desktop" is managed exclusively by the Electron application` |
| 21 | **Desktop 的默认端口是 19387，不是 3080** | 网上所有教程都写 3080（那是 CLI/web 模式的默认值） |

---

## 六、交叉验证报告（你要的"严谨"在这）

### 6.1 版本时效性核对

我查到的社区资料，**版本跨度很大**，必须逐条核对：

| 资料 | 日期 | 对应版本 | 对本机的适用性 |
|---|---|---|---|
| [保姆级教程：30分钟上手](https://developer.aliyun.com/article/1756432) | 2026-08-18 | v0.1 预览 | ❌ **大量过期**：`npx` 安装、端口 3080 |
| [避坑完整指南：10 个高频踩坑](https://news.qiniu.com/archives/1787542667867) | 2026-08-24 | rc.8 | ⚠️ **部分过期**：rc.8 的 SQLite 变更警告对本机**不适用**（本机是 JSONL+zstd）；`llm-pi-ai`/`settings.yaml` 配置路径也不同 |
| [四种模式完整指南（dshbase）](https://dshbase.com/zh/blog/deepseek-harness-modes/) | 2026-08-14 | 0.1.0-rc.6 | ⚠️ **模式名过期**（见下） |
| [从零到一：四种预设模式详解](https://developer.aliyun.com/article/1763449) | 2026-09-15 | 未标 | ⚠️ 同上；架构描述准确 |
| [DSH skill 怎么安装、放哪个目录](https://developer.aliyun.com/article/1767676) | **2026-10-03** | 未标，但描述与 rc.2 一致 | ✅ **最可信**：技能 rank 表与官方文档逐条吻合 |
| [dsh-plugin.org 原文](https://dsh-plugin.org/zh/tutorials/dsh-skills-install) | 2026-09-10 | 未标 | ✅ 同上，且自述"社区维护、非官方" |

**结论：只有 10-03 / 09-10 那两篇技能文档与本机版本对齐。其余三篇请只当"概念科普"看，别照抄命令。**

### 6.2 发现的 5 处冲突（已逐条裁定）

| # | 冲突点 | 社区说法 | **权威结论（我的裁定依据）** |
|---|---|---|---|
| 1 | **preset 名称** | 社区写"标准 / PTC / 极简 / **创造(Creator)**" | ❌ 错。本机源码 `dsh-web-app/presets/` 里实际是 **`standard` / `ptc` / `minimal` / `cordis`**。"创造模式"的官方 id 是 **`cordis`**。另外官方部分旧文档残留 **`code`**，官方迁移包证实 `code`→`ptc` 是 v3 迁移中的重命名 |
| 2 | **存储格式** | 社区说"SQLite + zstd，rc.8 起多帧 zstd" | ❌ 本机实测是 **JSONL + zstd**（`session.v4.jsonl.zstd`），**不是 SQLite**。社区那条 rc.8 警告对本机不适用 |
| 3 | **端口** | 社区一律写 `127.0.0.1:3080` | ❌ 本机 Desktop 是 **`127.0.0.1:19387`** |
| 4 | **配置路径** | 社区写 `~/.dsh/settings.yaml` / `llm-pi-ai.providers` | ❌ 本机是 **`$DSH_HOME\profiles\desktop\cordis.patch.yml`**（Cordis 组合格式） |
| 5 | **安装方式** | 社区主推 `npx @deepseek-ai/dsh web` / `npm i -g` | ⚠️ **不适用于 Desktop**。你是桌面安装版，`dsh` 是随包启动器（我已帮你注册进 PATH） |

### 6.3 三方一致的结论（可放心采信）

| 结论 | 官方文档 | 社区 | 本机实测 |
|---|---|---|---|
| skill ≠ plugin，`dsh plugin add` 装不了 skill | ✅ | ✅ | ✅ |
| skill 六根目录 rank 100–600 | ✅ | ✅ | ✅（`.agents/skills` 确实以 rank 500 加载） |
| `description` 是模型唯一路由依据 | ✅ | ✅ | ✅ |
| 沙箱只管写不管读 | ✅ | ⚠️ 未提 | ✅（我实测被拦的是写操作） |
| Windows 沙箱是部分强制执行 | ✅ | ❌ 未提 | ✅ |
| 工具结果 8192 字符裁剪 | ✅ | ❌ 未提 | ✅ |
| 默认 preset 是 `standard` | ✅ | ✅ | ✅（会话日志 `agentPreset: "standard"`） |

### 6.4 官方文档本身也存在矛盾（诚实交代）

我不是把所有官方说法都当圣旨，以下 3 处**官方文档自己就不一致**：

1. **`code` vs `ptc`**：`dsh-tool-web`、`dsh-command-goal` 仍写 `code`，而 `dsh-web-app` 写 `ptc`。裁决：**用 `ptc`**（有迁移包佐证）。
2. **session 格式"当前版本"**：同一份官方文档一处写 v3、一处写 V4。裁决：**本机实测是 v4**（文件名 `session.v4.jsonl.zstd`）。
3. **`dsh-tool-web` 的示例引用了不存在的包**（`dsh-web-search-exa`）：本版 287 个依赖里只有 `dsh-web-search-deepseek` 和 `dsh-web-fetch-http`。

### 6.5 我无法核实的事项（明确告知）

- **官方完整的用户指南与配置目录不在安装包内**。随包 README 反复引用的 `docs/user/guide/index.zh.md`、`docs/config-catalog.zh.md`、`docs/tool-catalog.zh.md` **在 121 MB 归档里全部不存在**。→ 所以**没有任何一份完整的官方配置项清单**，我只能从各包 README 拼。
- **GitHub 在本机网络下不可达**（我实测超时），所以官方仓库的 `docs/` 与 discussions 我无法直接读取，只能通过第三方转述间接了解。
- **Desktop Electron 外壳的行为无随包文档**（`dsh-desktop-host` 连英文 README 都没有）。

**所以本方案里的每一条"官方"，都来自你本机安装包内 279 份 README 的原文引用；每一条"实测"，都是我在这个会话里亲手跑出来的。**

---

## 七、推荐资源（附可信度标注）

### 一手权威（强烈推荐）

| 资源 | 说明 |
|---|---|
| **你本机的随包文档** | 最权威且**版本精确匹配**。我已提取到 [_healthcheck/asar_dump/docs](_healthcheck/asar_dump/docs)（279 份）+ 消化摘要 [official-docs-digest.md](_healthcheck/official-docs-digest.md) |
| `dsh --help` / `dsh --dump-config` | 在你自己的终端跑，官方 CLI 自述 |
| GUI 里的**轨迹面板** | 最真实的"官方行为"——它怎么想、怎么调工具，全在里面 |

### 社区资源（按可信度排序）

| 资源 | 可信度 | 备注 |
|---|---|---|
| [dsh-plugin.org](https://dsh-plugin.org/zh/) 技能/插件教程 | ⭐⭐⭐⭐ | 转述官方文档，且标注了来源；自述"非官方、社区维护" |
| [dshbase.com](https://dshbase.com/zh/) 中文指南 | ⭐⭐⭐ | 概念讲得好，但版本偏旧（rc.6 实测） |
| [阿里云 10-03 技能文档](https://developer.aliyun.com/article/1767676) | ⭐⭐⭐⭐ | 时效最好，与 rc.2 行为一致 |
| [阿里云 09-15 开发实战](https://developer.aliyun.com/article/1763449) | ⭐⭐⭐ | 架构描述准确，模式名过期 |
| [七牛云避坑指南](https://news.qiniu.com/archives/1787542667867) | ⭐⭐⭐ | 坑点有价值，但版本是 rc.8 |
| ~~阿里云 08-18 保姆级教程~~ | ⭐ | **已过期，只当科普** |

> ⚠️ **所有社区资源都基于 CLI/web 模式**。你是 Desktop 版，凡是涉及 `npx` / `npm i -g` / 端口 3080 / `settings.yaml` 的段落，**一律不适用**。

---

## 八、第一周计划（可直接执行）

| 天 | 做什么 | 完成标志 |
|---|---|---|
| **D1** | 练习 1.1–1.3（工具面 + 首个任务 + 读轨迹） | 能说清它有哪些工具、看懂一次完整轨迹 |
| **D2** | 练习 1.4 + 2.5（子代理 + 会话恢复） | 会拆并行子任务；知道恢复会话的"已读状态"限制 |
| **D3** | 练习 2.2–2.3（沙箱与审批）+ 第二章概念表 | **能准确说出"沙箱"和"审批"的区别** |
| **D4** | 练习 2.4 + 第七章坑清单前 15 条 | 知道 token 花在哪，能背出配置类坑 |
| **D5** | 练习 3.1（写第一个 skill） | `C:\Users\wengw\.dsh\skills\` 下有你的 skill，且能被模型自动加载 |
| **D6** | 练习 3.2 + 3.4（验证清理结果 + 接入 context7） | 确认只剩官方 skill；context7 工具出现在模型工具列表里 |
| **D7** | 复盘：翻一遍坑清单 + 轨迹 | 能独立判断"这次是模型问题还是我的问题" |

---

## 九、一句话总结

> **你不需要"学会 DSH 的所有配置"。你需要的是：**
> **① 会说清任务；② 看得懂轨迹；③ 清楚沙箱和审批是两回事；④ 知道 token 烧在哪；⑤ 记住几条配置铁律。**
>
> 剩下的一切（插件、preset、bundle、Cordis）都是**等你真遇到需求时再学**的东西。
> 这个版本是 `rc.2` 预览版，官方明说接口会快速演化 —— **所以别去背配置细节，去练"用它干活"和"看轨迹排错"这两个可迁移的能力。**

---

### 附：本方案用到的证据文件

| 文件 | 内容 |
|---|---|
| [official-docs-digest.md](_healthcheck/official-docs-digest.md) | 279 份随包官方文档的消化摘要（821 行，含官方原文引用） |
| [_healthcheck/asar_dump/docs/](_healthcheck/asar_dump/docs) | 全部 279 份中文 README 逐字节提取 |
| [_healthcheck/asar_dump/](_healthcheck/asar_dump) | 预设定义、可选 bundle 定义、技能资产 |
| 回收站取证中间产物 | `recycle_i_records.csv`、`hash_verify2.csv`（OpenClaw 残留哈希比对原始数据） |
