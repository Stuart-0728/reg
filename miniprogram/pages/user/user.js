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
    userInfo: null,
    stats: { attended: 0 },
    unreadCount: 0
  },
  onShow() {
    this.setData({ userInfo: app.globalData.userInfo });
    if(app.globalData.token) {
      wx.request({
        url: app.globalData.baseUrl + '/api/mp/my_activities',
        method: 'GET',
        header: { 'Authorization': app.globalData.token },
        success: (res) => {
          if (res.data.success) {
             const attended = res.data.data.filter(a => a.status === 'attended').length;
             this.setData({ 'stats.attended': attended });
          }
        }
      });
      this.setData({ unreadCount: app.globalData.unreadCount || 0 });
      app.updateUnreadCount({
        onDone: (count) => {
          this.setData({ unreadCount: count });
        }
      });
    } else {
      this.setData({ unreadCount: 0 });
      wx.removeTabBarBadge({ index: 1 });
    }
  },
  checkLoginStatus() {
    if (!this.data.userInfo) {
      wx.navigateTo({ url: '/pages/login/login' });
    }
  },
  
  goToNotifications() {
    wx.navigateTo({ url: '/pages/notifications/notifications' });
  },
  goToProfile() {
    wx.navigateTo({ url: '/pages/profile/profile' });
  },

  goToMyActivities() {
      wx.navigateTo({ url: '/pages/my_activities/my_activities' });
  },
  handleCheckin() {
      if(!app.globalData.token) {
          wx.showToast({title: '请先登录', icon: 'none'});
          return;
      }
      wx.scanCode({
        success: (res) => {
            wx.showLoading({title: '验证中...'});
            wx.request({
                url: app.globalData.baseUrl + '/api/mp/checkin',
                method: 'POST',
                header: { 'Authorization': app.globalData.token },
                data: { checkin_key: res.result },
                success: (apiRes) => {
                    wx.hideLoading();
                    if(apiRes.data.success) {
                        wx.showToast({title: apiRes.data.msg, icon: 'success', duration: 3000});
                        this.onShow(); // Refresh points
                    } else {
                        wx.showModal({title: '签到失败', content: apiRes.data.msg, showCancel: false});
                    }
                },
                fail: () => wx.hideLoading()
            })
        }
      })
  },
  
  handleSubscribe() {
    if (!app.globalData.token) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }
    const tmplIds = [
      'T25ILSqS41_ZhDXZl77iQESliXV9J8na1f5IyARQDbM', // 签到提醒
      'ESmqrDAYo8rVBDq5EL8YjbKGedpxOYuPQgIZ3Nz_EZ0', // 新活动发布提醒
      '16S-vnKCWw7x2xqKi86K_mme2paucmkIl0-hkDXAkfA'  // 活动开始通知
    ];
    wx.requestSubscribeMessage({
      tmplIds,
      success(res) {
        let successCount = 0;
        tmplIds.forEach(id => {
          if (res[id] === 'accept') {
            successCount++;
          }
        });
        if (successCount > 0) {
          wx.showToast({ title: '订阅成功', icon: 'success' });
        } else {
          wx.showToast({ title: '未开启所有订阅', icon: 'none' });
        }
      },
      fail(err) {
        console.error('Subscribe fail:', err);
        wx.showToast({ title: '订阅失败', icon: 'none' });
      }
    });
  },

  handleLogout() {
    wx.showModal({
      title: '提示',
      content: '确定要退出登录吗？',
      success: (res) => {
        if (res.confirm) {
          wx.removeStorageSync('token');
          wx.removeStorageSync('userInfo');
          app.globalData.token = null;
          app.globalData.userInfo = null;
          this.setData({ userInfo: null, 'stats.attended': '--' });
          wx.showToast({ title: '已退出', icon: 'success' });
          this.onShow();
        }
      }
    });
  }
});