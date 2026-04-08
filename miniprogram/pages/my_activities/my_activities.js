const app = getApp();
Page({
  onPullDownRefresh() {
    if (this.onShow) {
      this.onShow();
    } else if (this.onLoad) {
      this.onLoad();
    }
    setTimeout(() => wx.stopPullDownRefresh(), 600);
  },

  data: {
    activities: [],
    filteredActivities: [],
    filterStatus: 'all',
    loading: true
  },
  onShow() {
    if (!app.globalData.token) {
        wx.showModal({
            title: '未登录',
            content: '请先登录以查看报名记录',
            success: (res) => {
                if(res.confirm) wx.navigateTo({url: '/pages/login/login'})
            }
        })
        return;
    }
    this.fetchData();
  },
  fetchData() {
    this.setData({loading: true});
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/my_activities',
      method: 'GET',
      header: { 'Authorization': app.globalData.token },
      success: (res) => {
        if(res.data.success){
          this.setData({ activities: res.data.data }, () => {
            this.applyFilter();
          });
        } else {
            if(res.data.need_login) {
                 wx.navigateTo({url: '/pages/login/login'});
            }
        }
      },
      complete: () => {
        this.setData({loading: false});
      }
    })
  },
  setFilter(e) {
    const status = e.currentTarget.dataset.status;
    this.setData({ filterStatus: status }, () => {
      this.applyFilter();
    });
  },
  applyFilter() {
    const { activities, filterStatus } = this.data;
    let filtered = activities;
    if (filterStatus !== 'all') {
      filtered = activities.filter(item => item.status === filterStatus);
    }
    this.setData({ filteredActivities: filtered });
  },
  goToDetail(e) {
    const id = e.currentTarget.dataset.id;
    const normalizedId = Number(id);
    if (!Number.isInteger(normalizedId) || normalizedId <= 0) {
      wx.showToast({ title: '活动ID无效', icon: 'none' });
      return;
    }
    wx.navigateTo({
      url: '/pages/activity/activity?id=' + normalizedId
    });
  },
  handleCancel(e) {
    const activityId = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认取消',
      content: '是否确实要取消该活动的报名？',
      success: (res) => {
        if (res.confirm) {
          wx.showLoading({ title: '处理中...', mask: true });
          wx.request({
            url: app.globalData.baseUrl + `/api/mp/activities/${activityId}/cancel`,
            method: 'POST',
            header: { 'Authorization': app.globalData.token },
            success: (apiRes) => {
              wx.hideLoading();
              if (apiRes.data.success) {
                wx.showToast({ title: '已取消报名', icon: 'success' });
                this.fetchData(); // 刷新列表
              } else {
                wx.showToast({ title: apiRes.data.msg || '取消失败', icon: 'none' });
              }
            },
            fail: () => {
              wx.hideLoading();
              wx.showToast({ title: '网络请求失败', icon: 'none' });
            }
          });
        }
      }
    });
  },
  handleRegister(e) {
    const activityId = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认重新报名',
      content: '是否要重新报名该活动？',
      success: (res) => {
        if (res.confirm) {
          wx.showLoading({ title: '处理中...', mask: true });
          wx.request({
            url: app.globalData.baseUrl + `/api/mp/activities/${activityId}/register`,
            method: 'POST',
            header: { 'Authorization': app.globalData.token },
            success: (apiRes) => {
              wx.hideLoading();
              if (apiRes.data.success) {
                wx.showToast({ title: '重新报名成功', icon: 'success' });
                this.fetchData(); // 刷新列表
              } else {
                wx.showToast({ title: apiRes.data.msg || '报名失败', icon: 'none' });
              }
            },
            fail: () => {
              wx.hideLoading();
              wx.showToast({ title: '网络请求失败', icon: 'none' });
            }
          });
        }
      }
    });
  },
  goHome() {
    wx.switchTab({ url: '/pages/index/index' });
  }
})