// wx.request 封装：统一基址、JWT 头、统一错误处理与 401 重登
const app = getApp()

function getBaseUrl() {
  // 优先取全局配置，便于分环境切换域名
  const instance = app && app.globalData ? app.globalData : {}
  return instance.baseUrl || 'http://127.0.0.1:8000/api/v1'
}

function getToken() {
  const instance = app && app.globalData ? app.globalData : {}
  return instance.token || wx.getStorageSync('njxj_token') || ''
}

/** 会话失效：清空登录态并跳转（登录页接入后指向真实路径） */
function handleUnauthorized() {
  if (app && typeof app.clearSession === 'function') {
    app.clearSession()
  }
  wx.showToast({ title: '登录已过期，请重新登录', icon: 'none' })
  // TODO(登录页接入后): wx.reLaunch({ url: '/store/pages/login/login' })
}

/**
 * 请求封装
 * @param {object} options
 * @param {string} options.url    以 / 开头的相对路径，如 '/health'
 * @param {string} [options.method] GET / POST / PUT / DELETE
 * @param {object} [options.data]  请求数据
 * @param {boolean} [options.loading] 是否显示 loading，默认 false
 * @param {boolean} [options.toast]   失败是否自动 toast，默认 true
 * @returns {Promise<object>} 解析后的 data 字段（后端统一响应体的 data）
 */
function request(options = {}) {
  const { url, method = 'GET', data = {}, loading = false, toast = true } = options

  return new Promise((resolve, reject) => {
    if (loading) {
      wx.showLoading({ title: '加载中', mask: true })
    }
    wx.request({
      url: getBaseUrl() + url,
      method,
      data,
      header: {
        'content-type': 'application/json',
        Authorization: getToken() ? 'Bearer ' + getToken() : ''
      },
      success(res) {
        const { statusCode, data: body } = res
        if (statusCode === 401) {
          handleUnauthorized()
          reject(new Error('unauthorized'))
          return
        }
        if (statusCode < 200 || statusCode >= 300) {
          const msg = (body && body.message) || '请求失败(' + statusCode + ')'
          if (toast) wx.showToast({ title: msg, icon: 'none' })
          reject(new Error(msg))
          return
        }
        // 统一响应体：{ code, message, data }
        if (body && typeof body === 'object' && 'code' in body) {
          if (body.code !== 0) {
            if (toast) wx.showToast({ title: body.message || '请求失败', icon: 'none' })
            reject(new Error(body.message || 'business error'))
            return
          }
          resolve(body.data)
          return
        }
        resolve(body)
      },
      fail(err) {
        if (toast) wx.showToast({ title: '网络异常，请检查网络', icon: 'none' })
        reject(err)
      },
      complete() {
        if (loading) wx.hideLoading()
      }
    })
  })
}

// 便捷方法
request.get = (url, data, options) => request({ url, method: 'GET', data, ...options })
request.post = (url, data, options) => request({ url, method: 'POST', data, ...options })
request.put = (url, data, options) => request({ url, method: 'PUT', data, ...options })
request.del = (url, data, options) => request({ url, method: 'DELETE', data, ...options })

module.exports = { request, getBaseUrl, getToken, handleUnauthorized }
