const app = getApp();
Page({
  data: {
    notifications: [],
    loading: true
  },
  onShow() {
    this.fetchData();
  },
  fetchData() {
    this.setData({ loading: true });
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/notifications',
      method: 'GET',
      header: { 'Authorization': app.globalData.token },
      success: (res) => {
        if(res.data.success){
          this.setData({ notifications: res.data.data });
        } else {
            if(res.data.need_login) {
                wx.showModal({
                  title: '未登录',
                  content: '请先登录以查看历史消息',
                  success: (md) => {
                      if(md.confirm) wx.navigateTo({url: '/pages/login/login'})
                      else wx.navigateBack();
                  }
                })
            } else {
                wx.showToast({ title: res.data.msg || '获取失败', icon: 'none' });
            }
        }
      },
      complete: () => {
        this.setData({ loading: false });
        wx.stopPullDownRefresh();
      }
    });
  },
  onPullDownRefresh() {
    this.fetchData();
  },
  openDetail(e) {
    const { id, index } = e.currentTarget.dataset;
    const n = this.data.notifications[index];
    
    // 如果未读，标记为已读
    if (!n.is_read) {
      this.setData({
        [`notifications[${index}].is_read`]: true
      });
      wx.request({
        url: app.globalData.baseUrl + '/api/mp/notifications/' + id + '/read',
        method: 'POST',
        header: { 'Authorization': app.globalData.token }
      });
    }
    
    // 把通知实体存入全局或缓存给详情页用
    wx.setStorageSync('currentNotification', n);
    wx.navigateTo({
      url: `/pages/notification_detail/notification_detail?id=${id}`
    });
  }
});
