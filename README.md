# default-workspace

DeepSeek Harness（DSH）的默认工作区。

- **DSH 版本**：0.2.0-rc.2（Desktop 桌面版）
- **安装位置**：`D:\DeepSeek Harness`
- **DSH 配置目录**：`C:\Users\wengw\.dsh`

---

## 目录结构

| 路径 | 内容 | 是否入库 |
|---|---|---|
| `_healthcheck\DSH-学习方案.md` | DSH 新手学习方案（含官方依据与交叉验证） | ✅ |
| `_healthcheck\official-docs-digest.md` | 随包官方文档摘要（279 份 README 的消化，含官方原文引用） | ✅ |
| `recycle_i_records.csv` 等 | OpenClaw 残留取证原始数据 | ✅ |
| `_removed-skills-backup\` | 已移除的 53 个第三方 skill 备份（48 MB） | ❌ 见 `.gitignore` |

---

## 关于 `_removed-skills-backup`

2026-10-12，53 个由其他 AI 工具（OpenClaw 体系）带入的 skill 被从
`C:\Users\wengw\.agents\skills` 移除，DSH 由此恢复到官方初始状态。

移除方式是**移动而非删除**，备份包含：

| 文件 | 说明 |
|---|---|
| `skills\` | 53 个 skill 文件夹，原样保留 |
| `manifest-*.csv` | 53 行清单，含文件数、字节数、`SKILL.md` 的 SHA-256 |
| `REMOVAL-RECORD.md` | 完整移除记录与恢复说明 |
| `skill-lock.json.bak` | 原来源溯源记录 |

**还原方法**（在本机终端执行）：

```powershell
$src = 'C:\Users\wengw\.agents\skills'
$payload = 'C:\Users\wengw\Documents\deepseek-harness\default-workspace\_removed-skills-backup\20261012-093104\skills'
Get-ChildItem $payload -Directory | ForEach-Object {
    Move-Item -LiteralPath $_.FullName -Destination (Join-Path $src $_.Name)
}
```

> ⚠️ 该备份**刻意不入库**：它体积大，且一旦推送到远端等于把已清除的第三方内容重新发布。

---

## 关于 DSH 的项目根

DSH 把**包含 `.git` 的最近祖先目录**认作「项目根」。本目录初始化 Git 后，
以下两个位置随之生效（官方机制）：

| rank | 位置 | 作用 |
|---|---|---|
| 100 | `.dsh\skills\` | **本项目专属** skill（优先级最高） |
| — | `AGENTS.md` | **项目级**指令，叠加在全局 `~\.dsh\AGENTS.md` 之上（更具体者优先） |

> 全局约定见 `C:\Users\wengw\.dsh\AGENTS.md`；本文件所在目录的 `AGENTS.md` 若存在，
> 其内容在**本项目内**优先。

---

## 一些约定

- skill 一律放在 `~\.dsh\skills\`（用户级）或本项目 `.dsh\skills\`（项目级），
  **不要**放进 `~\.agents\skills\`（多工具共享目录，会交叉污染）。
- 提交前请确认 `_removed-skills-backup\` 与 `.dsh\` 未进入暂存区。
