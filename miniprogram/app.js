App({
  onLaunch() {
    // 检查本地是否已有 token
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
      this.globalData.userInfo = wx.getStorageSync('userInfo');
    }
  },
  globalData: {
    userInfo: null,
    token: null,
    baseUrl: 'https://reg.cqaibase.cn'
  }
})