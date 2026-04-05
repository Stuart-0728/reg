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
  }
});
