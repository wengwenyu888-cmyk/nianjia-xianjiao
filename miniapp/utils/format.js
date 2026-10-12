// 格式化纯函数：日期与重量（斤/公斤展示统一走这里）
function pad(n) {
  return n < 10 ? '0' + n : '' + n
}

/** 格式化日期：Date | number → YYYY-MM-DD */
function formatDate(value) {
  const d = value instanceof Date ? value : new Date(value)
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

/** 保留 n 位小数（四舍五入），返回字符串 */
function toFixed(value, digits = 2) {
  const num = Number(value)
  if (Number.isNaN(num)) return '0'
  return num.toFixed(digits)
}

/** 斤 → 公斤展示 */
function jinToKg(jin) {
  return toFixed(Number(jin) / 2, 3)
}

module.exports = { formatDate, toFixed, jinToKg }
