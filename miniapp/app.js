// 小程序入口：初始化全局数据与登录态
App({
  globalData: {
    // 本地联调直连后端；上线改为 https 正式域名并在微信后台配置合法域名
    baseUrl: 'http://127.0.0.1:8000/api/v1',
    token: '',
    userInfo: null,
    role: '' // hq | store | driver
  },

  onLaunch() {
    // 启动时恢复本地登录态
    const token = wx.getStorageSync('njxj_token')
    if (token) {
      this.globalData.token = token
      this.globalData.userInfo = wx.getStorageSync('njxj_user') || null
      this.globalData.role = wx.getStorageSync('njxj_role') || ''
    }
  },

  /** 登录成功后统一写入 */
  setSession({ token, user, role }) {
    this.globalData.token = token
    this.globalData.userInfo = user || null
    this.globalData.role = role || ''
    wx.setStorageSync('njxj_token', token)
    wx.setStorageSync('njxj_user', user)
    wx.setStorageSync('njxj_role', role)
  },

  /** 退出 / 令牌失效时清空 */
  clearSession() {
    this.globalData.token = ''
    this.globalData.userInfo = null
    this.globalData.role = ''
    wx.removeStorageSync('njxj_token')
    wx.removeStorageSync('njxj_user')
    wx.removeStorageSync('njxj_role')
  }
})
