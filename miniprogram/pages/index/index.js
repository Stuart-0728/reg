const app = getApp();

Page({
  data: {
    activities: [],
    loading: true
  },
  onLoad() {
    this.fetchActivities();
  },
  onPullDownRefresh() {
    this.fetchActivities(() => wx.stopPullDownRefresh());
  },
  fetchActivities(cb) {
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/activities',
      success: (res) => {
        if(res.data.success) {
          this.setData({ activities: res.data.data });
        }
      },
      complete: () => {
        this.setData({ loading: false });
        if(cb) cb();
      }
    });
  },
  goToDetail(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/activity/activity?id=${id}` });
  }
});