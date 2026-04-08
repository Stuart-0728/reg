const app = getApp();

Page({
  data: {
    notification: {}
  },
  onLoad(options) {
    const data = wx.getStorageSync('currentNotification');
    if (data) {
      this.setData({ notification: data });
    } else {
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
  },

  deleteNotification() {
    const id = this.data.notification.id;
    if (!id) {
      wx.showToast({ title: '通知ID无效', icon: 'none' });
      return;
    }

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
            if (!res.data.success) {
              wx.showToast({ title: res.data.msg || '删除失败', icon: 'none' });
              return;
            }

            wx.removeStorageSync('currentNotification');
            if (app.updateUnreadCount) app.updateUnreadCount();

            const pages = getCurrentPages();
            const prevPage = pages.length > 1 ? pages[pages.length - 2] : null;
            if (prevPage && typeof prevPage.fetchData === 'function') {
              prevPage.fetchData();
            }

            wx.showToast({ title: '已删除', icon: 'success' });
            setTimeout(() => wx.navigateBack(), 300);
          },
          fail: () => {
            wx.showToast({ title: '网络异常', icon: 'none' });
          }
        });
      }
    });
  }
});
