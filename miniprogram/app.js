App({
  onLaunch() {
    // 检查本地是否已有 token
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
      this.globalData.userInfo = wx.getStorageSync('userInfo');
    }
  },
  
  updateUnreadCount() {
    if (!this.globalData.token) return;
    wx.request({
      url: this.globalData.baseUrl + '/api/mp/notifications/unread_count',
      method: 'GET',
      header: { 'Authorization': this.globalData.token },
      success: (res) => {
        if (res.data.success) {
          const count = res.data.unread_count;
          if (count > 0) {
            wx.setTabBarBadge({
              index: 1, // 确保这是正确的 index，一般个人中心在最后一个
              text: count.toString()
            });
          } else {
            wx.removeTabBarBadge({ index: 1 });
          }
        }
      }
    });
  },
  onShow() {
    this.updateUnreadCount();
    // 启动定时刷新角标，每隔 30 秒查一次
    if (!this.global_timer) {
      this.global_timer = setInterval(() => {
        this.updateUnreadCount();
      }, 30000);
    }
  },
  onHide() {
    if (this.global_timer) {
      clearInterval(this.global_timer);
      this.global_timer = null;
    }
  },
  globalData: {
    userInfo: null,
    token: null,
    baseUrl: 'https://reg.cqaibase.cn'
  }
})