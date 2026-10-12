// 门店端首页：要货入口
const request = require('../../../utils/request')
const { formatDate } = require('../../../utils/format')

Page({
  data: {
    storeName: '示例门店',
    today: formatDate(new Date()),
    apiStatus: '检测中',
    shortcuts: [
      { key: 'order', title: '我要要货', desc: '按商品清单提交今日要货单' },
      { key: 'order', title: '历史要货单', desc: '查看单据状态与总部审核结果' }
    ]
  },

  onLoad() {
    this.checkHealth()
  },

  /** 联调用：确认后端连通（失败不影响页面展示） */
  checkHealth() {
    request
      .get('/health', {}, { toast: false })
      .then((data) => {
        this.setData({ apiStatus: data && data.status === 'ok' ? '后端正常' : '后端异常' })
      })
      .catch(() => {
        this.setData({ apiStatus: '后端未连通' })
      })
  },

  goOrder() {
    wx.navigateTo({ url: '/store/pages/order/order' })
  }
})
