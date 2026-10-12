// 常量：与后端枚举保持一致，严禁各处硬编码字符串
const ORDER_STATUS = {
  DRAFT: 'draft',
  SUBMITTED: 'submitted',
  APPROVED: 'approved',
  SUMMARIZED: 'summarized',
  PICKING: 'picking',
  DELIVERING: 'delivering',
  RECEIVED: 'received',
  SETTLED: 'settled',
  CANCELLED: 'cancelled'
}

const ORDER_STATUS_TEXT = {
  draft: '草稿',
  submitted: '待审核',
  approved: '已审核',
  summarized: '已汇总',
  picking: '分拣中',
  delivering: '配送中',
  received: '已签收',
  settled: '已对账',
  cancelled: '已取消'
}

module.exports = { ORDER_STATUS, ORDER_STATUS_TEXT }
