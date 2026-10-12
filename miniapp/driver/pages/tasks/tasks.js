// 司机端：配送任务列表（骨架，接口接入后替换 mock）
const request = require('../../../utils/request')

Page({
  data: {
    loading: false,
    tasks: []
  },

  onShow() {
    this.fetchTasks()
  },

  /** 只拉自己的配送任务：司机身份由后端从令牌解析 */
  fetchTasks() {
    this.setData({ loading: true })
    request
      .get('/delivery/tasks', { page: 1, page_size: 20 }, { toast: false })
      .then((data) => {
        this.setData({ tasks: (data && data.items) || [] })
      })
      .catch(() => {
        this.setData({ tasks: [] })
      })
      .finally(() => this.setData({ loading: false }))
  },

  goSign(e) {
    const taskId = e.currentTarget.dataset.id
    wx.showToast({ title: '签收页开发中(' + taskId + ')', icon: 'none' })
    // TODO(签收页接入后): wx.navigateTo({ url: '/driver/pages/sign/sign?taskId=' + taskId })
  }
})
