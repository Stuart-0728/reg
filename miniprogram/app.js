App({
  onLaunch() {
    // 检查本地是否已有 token
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
      this.globalData.userInfo = wx.getStorageSync('userInfo');
    }

    const cachedUnread = wx.getStorageSync('unreadCount');
    if (typeof cachedUnread === 'number' && cachedUnread >= 0) {
      this.globalData.unreadCount = cachedUnread;
      this._applyUnreadBadge(cachedUnread);
    }
  },
  
  _applyUnreadBadge(count) {
    if (count > 0) {
      wx.setTabBarBadge({
        index: 1,
        text: count.toString()
      });
    } else {
      wx.removeTabBarBadge({ index: 1 });
    }
  },

  updateUnreadCount(options = {}) {
    if (!this.globalData.token) {
      this.globalData.unreadCount = 0;
      this._applyUnreadBadge(0);
      if (typeof options.onDone === 'function') options.onDone(0, false);
      return;
    }

    const now = Date.now();
    const minInterval = options.force ? 0 : 60000;

    if (this.globalData.unreadFetching) {
      if (typeof options.onDone === 'function') {
        options.onDone(this.globalData.unreadCount || 0, false);
      }
      return;
    }

    if (this.globalData.unreadCooldownUntil && now < this.globalData.unreadCooldownUntil) {
      const cached = this.globalData.unreadCount || 0;
      this._applyUnreadBadge(cached);
      if (typeof options.onDone === 'function') options.onDone(cached, true);
      return;
    }

    if (!options.force && (now - (this.globalData.unreadLastFetchTs || 0) < minInterval)) {
      const cached = this.globalData.unreadCount || 0;
      this._applyUnreadBadge(cached);
      if (typeof options.onDone === 'function') options.onDone(cached, true);
      return;
    }

    this.globalData.unreadFetching = true;
    wx.request({
      url: this.globalData.baseUrl + '/api/mp/notifications/unread_count',
      method: 'GET',
      timeout: 8000,
      header: { 'Authorization': this.globalData.token },
      success: (res) => {
        if (res.data.success) {
          const count = res.data.unread_count;
          this.globalData.unreadCount = count;
          this.globalData.unreadLastFetchTs = Date.now();
          this.globalData.unreadCooldownUntil = 0;
          wx.setStorageSync('unreadCount', count);
          this._applyUnreadBadge(count);
          if (typeof options.onDone === 'function') options.onDone(count, false);
        } else {
          const cached = this.globalData.unreadCount || 0;
          this._applyUnreadBadge(cached);
          if (typeof options.onDone === 'function') options.onDone(cached, false);
        }
      },
      fail: (err) => {
        const statusCode = err && err.statusCode;
        if (statusCode === 429) {
          this.globalData.unreadCooldownUntil = Date.now() + 60000;
        } else if (statusCode >= 500 || statusCode === 0 || statusCode === undefined) {
          this.globalData.unreadCooldownUntil = Date.now() + 120000;
        }
        const cached = this.globalData.unreadCount || 0;
        this._applyUnreadBadge(cached);
        if (typeof options.onDone === 'function') options.onDone(cached, false);
      },
      complete: () => {
        this.globalData.unreadFetching = false;
      }
    });
  },
  onShow() {
    this.updateUnreadCount();
    // 启动定时刷新角标，每隔 1 分钟查一次
    if (!this.global_timer) {
      this.global_timer = setInterval(() => {
        this.updateUnreadCount();
      }, 60000);
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
    baseUrl: 'https://reg.cqaibase.cn',
    unreadCount: 0,
    unreadLastFetchTs: 0,
    unreadCooldownUntil: 0,
    unreadFetching: false
  }
})