const app = getApp();

Page({
  data: {
    activities: [],
    societies: [],
    selectedSocietyId: '',
    loading: true
  },
  onLoad() {
    this.fetchSocieties();
    this.fetchActivities();
  },
  onPullDownRefresh() {
    this.fetchSocieties();
    this.fetchActivities(() => wx.stopPullDownRefresh());
  },
  fetchSocieties() {
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/societies',
      success: (res) => {
        if(res.data.success) {
          const list = [{ id: '', name: '全部' }].concat(res.data.data);
          this.setData({ societies: list });
        }
      }
    });
  },
  onSocietyChange(e) {
    const societyId = e.currentTarget.dataset.id;
    this.setData({ selectedSocietyId: societyId, loading: true });
    this.fetchActivities();
  },
  fetchActivities(cb) {
    const query = this.data.selectedSocietyId ? `?society_id=${this.data.selectedSocietyId}` : '';
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/activities' + query,
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