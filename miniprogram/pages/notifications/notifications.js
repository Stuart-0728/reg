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
          if (app.updateUnreadCount) app.updateUnreadCount();
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
        header: { 'Authorization': app.globalData.token },
        success: (res) => {
          if (!res.data.success) {
            this.fetchData();
          } else if (app.updateUnreadCount) {
            app.updateUnreadCount();
          }
        },
        fail: () => {
          this.fetchData();
        }
      });
    }
    
    // 把通知实体存入全局或缓存给详情页用
    wx.setStorageSync('currentNotification', n);
    wx.navigateTo({
      url: `/pages/notification_detail/notification_detail?id=${id}`
    });
  },

  deleteNotification(e) {
    const { id, index } = e.currentTarget.dataset;
    wx.showModal({
      title: '删除通知',
      content: '删除后将不会在小程序和网页中显示，确定删除吗？',
      success: (md) => {
        if (!md.confirm) return;

        wx.request({
          url: app.globalData.baseUrl + '/api/mp/notifications/' + id + '/delete',
          method: 'POST',
          header: { 'Authorization': app.globalData.token },
          success: (res) => {
            if (res.data.success) {
              const list = this.data.notifications.slice();
              list.splice(index, 1);
              this.setData({ notifications: list });
              wx.showToast({ title: '已删除', icon: 'success' });
              if (app.updateUnreadCount) app.updateUnreadCount();
            } else {
              wx.showToast({ title: res.data.msg || '删除失败', icon: 'none' });
            }
          },
          fail: () => {
            wx.showToast({ title: '网络异常', icon: 'none' });
          }
        });
      }
    });
  },

  markAllRead() {
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/notifications/mark_all_read',
      method: 'POST',
      header: { 'Authorization': app.globalData.token },
      success: (res) => {
        if (res.data.success) {
          wx.showToast({ title: '已全部设为已读', icon: 'success' });
          this.fetchData();
        } else {
          wx.showToast({ title: res.data.msg || '操作失败', icon: 'none' });
        }
      },
      fail: () => {
        wx.showToast({ title: '网络异常', icon: 'none' });
      }
    });
  },

  deleteRead() {
    wx.showModal({
      title: '删除已读',
      content: '将删除全部已读通知，确定继续吗？',
      success: (md) => {
        if (!md.confirm) return;
        wx.request({
          url: app.globalData.baseUrl + '/api/mp/notifications/delete_read',
          method: 'POST',
          header: { 'Authorization': app.globalData.token },
          success: (res) => {
            if (res.data.success) {
              wx.showToast({ title: '已删除已读通知', icon: 'success' });
              this.fetchData();
            } else {
              wx.showToast({ title: res.data.msg || '删除失败', icon: 'none' });
            }
          },
          fail: () => {
            wx.showToast({ title: '网络异常', icon: 'none' });
          }
        });
      }
    });
  }
});
