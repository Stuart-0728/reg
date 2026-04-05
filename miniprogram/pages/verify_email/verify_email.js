Page({
  data: {},
  onLoad() {},
  
  handleGoLogin() {
    wx.navigateBack({
      delta: 1,
      fail: () => {
        wx.redirectTo({ url: '/pages/login/login' });
      }
    });
  }
});
