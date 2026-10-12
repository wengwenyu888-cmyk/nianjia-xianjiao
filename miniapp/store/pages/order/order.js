// 门店端：要货单列表（骨架，接口接入后替换 mock）
const request = require('../../../utils/request')
const { ORDER_STATUS_TEXT } = require('../../../utils/constants')

Page({
  data: {
    loading: false,
    orders: []
  },

  onShow() {
    this.fetchOrders()
  },

  /** 拉取本门店要货单；store_id 由后端从令牌解析，前端不传 */
  fetchOrders() {
    this.setData({ loading: true })
    request
      .get('/orders', { page: 1, page_size: 20 }, { toast: false })
      .then((data) => {
        const items = (data && data.items) || []
        this.setData({
          orders: items.map((item) => ({
            ...item,
            statusText: ORDER_STATUS_TEXT[item.status] || item.status
          }))
        })
      })
      .catch(() => {
        // 接口未接入时展示空态，不阻塞骨架演示
        this.setData({ orders: [] })
      })
      .finally(() => this.setData({ loading: false }))
  },

  goCreate() {
    wx.showToast({ title: '下单页开发中', icon: 'none' })
  }
})
