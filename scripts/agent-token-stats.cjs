#!/usr/bin/env node
/**
 * 子智能体 / 会话 token 用量统计
 *
 * 数据来源：DSH 会话日志 ~/.dsh/sessions/<工作目录编码>/<sessionId>/session.v4.jsonl.zstd
 *   - 日志是多 zstd 帧拼接（每帧一个独立压缩块），需按 magic(28 B5 2F FD) 逐帧解压
 *   - 每轮 LLM 调用会产生一条 assistant/message 事件，内含：
 *       "usage":{"inputTokens":N,"outputTokens":N,"totalTokens":N,"cacheReadTokens":N}
 *     口径已验证：totalTokens = inputTokens + outputTokens + cacheReadTokens
 *
 * 用法：
 *   node scripts/agent-token-stats.cjs                # 统计当前工作目录下的全部会话
 *   node scripts/agent-token-stats.cjs <workspaceDir> # 指定工作目录（默认取进程 cwd）
 *   node scripts/agent-token-stats.cjs --detail       # 额外打印每个会话的模型分布
 *
 * 说明：cacheReadTokens 是「缓存命中的上下文读取」，单价远低于新输入，
 *      故同时给出「总处理量」与「非缓存输入+输出」两个口径，避免误读成本。
 */
'use strict'

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const zlib = require('node:zlib')

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

/** 多帧 zstd 解压：按 magic 切片逐帧解，失败帧跳过 */
function decodeAll(buf) {
  const offsets = []
  let i = buf.indexOf(MAGIC, 0)
  while (i >= 0) {
    offsets.push(i)
    i = buf.indexOf(MAGIC, i + 4)
  }
  const parts = []
  for (let k = 0; k < offsets.length; k++) {
    const slice = buf.subarray(offsets[k], k + 1 < offsets.length ? offsets[k + 1] : buf.length)
    try {
      parts.push(zlib.zstdDecompressSync(slice))
    } catch {
      /* 损坏帧跳过 */
    }
  }
  return parts.length ? Buffer.concat(parts).toString('utf8') : zlib.zstdDecompressSync(buf).toString('utf8')
}

/** 累加一段日志里的 usage */
function sumUsage(text) {
  const MARK = '"usage":{"inputTokens":'
  const parts = text.split(MARK).slice(1)
  let input = 0
  let output = 0
  let cache = 0
  let total = 0
  let calls = 0
  for (const p of parts) {
    const m = p.match(/^(d+),"outputTokens":(d+),"totalTokens":(d+)(?:,"cacheReadTokens":(d+))?/)
    if (!m) continue
    input += +m[1]
    output += +m[2]
    total += +m[3]
    cache += m[4] ? +m[4] : 0
    calls++
  }
  return { input, output, cache, total, calls }
}

/** 统计模型出现次数（工具定义里会罗列候选模型各 1 次，取次数最多者作为实际使用模型） */
function topModel(text) {
  const models = {}
  const re = /"model":"([^"]+)"/g
  let m
  while ((m = re.exec(text)) !== null) models[m[1]] = (models[m[1]] || 0) + 1
  const sorted = Object.entries(models).sort((a, b) => b[1] - a[1])
  return sorted.length ? sorted[0][0] : '?'
}

function main() {
  const args = process.argv.slice(2)
  const detail = args.includes('--detail')
  const workspace = args.find((a) => !a.startsWith('--')) || process.cwd()
  // DSH 把工作目录编码成目录名：非字母数字替换为 '-'，形如 --C-Users-x-proj--
  const encoded = '--' + workspace.replace(/[^a-zA-Z0-9]/g, '-') + '--'
  const base = path.join(os.homedir(), '.dsh', 'sessions', encoded)

  if (!fs.existsSync(base)) {
    console.error('未找到会话目录: ' + base)
    console.error('提示：请传工作目录，或确认 DSH 会话日志位置')
    process.exit(1)
  }

  const dirs = fs.readdirSync(base).filter((d) => fs.statSync(path.join(base, d)).isDirectory())
  let gInput = 0
  let gOutput = 0
  let gCache = 0
  let gTotal = 0
  let gCalls = 0
  const rows = []

  for (const d of dirs) {
    const file = path.join(base, d, 'session.v4.jsonl.zstd')
    if (!fs.existsSync(file)) continue
    let text = ''
    try {
      text = decodeAll(fs.readFileSync(file))
    } catch {
      continue
    }
    const u = sumUsage(text)
    if (!u.calls) continue
    const isMain = d.startsWith('session-')
    rows.push({ id: d.slice(0, 8), label: isMain ? '主会话(Lead)' : '子智能体', model: topModel(text), ...u, isMain })
    gInput += u.input
    gOutput += u.output
    gCache += u.cache
    gTotal += u.total
    gCalls += u.calls
  }

  rows.sort((a, b) => b.total - a.total)
  console.log('会话 | 类型 | 模型 | LLM调用 | 输入 | 输出 | 缓存读 | 合计')
  console.log('---|---|---|---|---|---|---|---')
  for (const r of rows) {
    console.log([r.id, r.label, r.model, r.calls, r.input, r.output, r.cache, r.total].join(' | '))
  }
  console.log('')
  const sub = rows.filter((r) => !r.isMain).reduce((a, r) => ({ calls: a.calls + r.calls, total: a.total + r.total }), { calls: 0, total: 0 })
  console.log(`子智能体会话数: ${rows.filter((r) => !r.isMain).length}（LLM 调用 ${sub.calls} 次）`)
  console.log(`全量口径（含缓存读）: 输入 ${gInput} + 输出 ${gOutput} + 缓存读 ${gCache} = ${gTotal} tokens`)
  console.log(`净口径（新输入+输出）: ${gInput + gOutput} tokens（缓存读不计）`)
  console.log(`校验: 输入+输出+缓存读 = ${gInput + gOutput + gCache}（应等于合计 ${gTotal}）`)

  if (detail) {
    console.log('')
    console.log('=== 各会话模型分布（仅出现 >1 次的模型）===')
    for (const d of dirs) {
      const file = path.join(base, d, 'session.v4.jsonl.zstd')
      if (!fs.existsSync(file)) continue
      let text = ''
      try {
        text = decodeAll(fs.readFileSync(file))
      } catch {
        continue
      }
      const models = {}
      const re = /"model":"([^"]+)"/g
      let m
      while ((m = re.exec(text)) !== null) models[m[1]] = (models[m[1]] || 0) + 1
      const real = Object.entries(models).filter(([, v]) => v > 1)
      if (real.length) console.log(`  ${d.slice(0, 8)}: ${real.map(([k, v]) => k + '×' + v).join(', ')}`)
    }
  }
}

main()
