const app = getApp();

Page({
  data: {
    activity: {
      title: '活动详情',
      description: '暂无活动描述',
      start_time: '-',
      end_time: '-',
      registration_start_time: '-',
      registration_end_time: '-',
      location: '-',
      current_participants: 0,
      max_participants: 0,
      points: 0,
      organizer: '智能社团+'
    },
    buttonState: { text: '加载中...', extraClass: 'btn-disabled', disabled: true, action: 'none' },
    loading: true,
    loadError: false,
    loadErrorMsg: ''
  },
  normalizeActivityId(rawId) {
    const n = Number(rawId);
    return Number.isInteger(n) && n > 0 ? String(n) : '';
  },
  onLoad(options) {
    const rawId = (options && (options.id || options.activity_id || options.activityId)) || '';
    const normalizedId = this.normalizeActivityId(rawId);
    if (normalizedId) {
      this.activityId = normalizedId;
      this.fetchDetail(normalizedId);
    } else {
      this.setData({
        loading: false,
        loadError: true,
        loadErrorMsg: '活动参数缺失，请返回列表重试'
      });
    }
  },
  onShow() {
    if (this.normalizeActivityId(this.activityId)) {
      this.fetchDetail(this.activityId);
    }
  },
  onHide() {
    this.clearStateTimers();
  },
  onUnload() {
    this.clearStateTimers();
  },
  clearStateTimers() {
    if (this._boundaryTimer) {
      clearTimeout(this._boundaryTimer);
      this._boundaryTimer = null;
    }
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },
  scheduleStateRefresh(activity) {
    this.clearStateTimers();

    const now = Date.now();
    const toTs = (val) => {
      const n = Number(val);
      return Number.isFinite(n) && n > 0 ? n : null;
    };
    const startTs = toTs(activity.registration_start_ts);
    const deadlineTs = toTs(activity.registration_deadline_ts);
    const candidates = [];
    if (startTs && startTs > now) {
      candidates.push(startTs);
    }
    if (deadlineTs && deadlineTs > now) {
      candidates.push(deadlineTs + 1000);
    }

    if (candidates.length) {
      const nextBoundary = Math.min(...candidates);
      const delay = Math.min(Math.max(nextBoundary - now, 1000), 2147483000);
      this._boundaryTimer = setTimeout(() => {
        if (this.data.activity) {
          this.computeButtonState(this.data.activity);
          this.scheduleStateRefresh(this.data.activity);
        }
      }, delay);
    }

    const intervalMs = candidates.length && (Math.min(...candidates) - now <= 120000) ? 2000 : 15000;
    this._pollTimer = setInterval(() => {
      if (this.data.activity) {
        this.computeButtonState(this.data.activity);
      }
    }, intervalMs);
  },
  fetchDetail(id) {
    const normalizedId = this.normalizeActivityId(id);
    if (!normalizedId) {
      this.setData({
        loading: false,
        loadError: true,
        loadErrorMsg: '活动参数无效，请返回列表重试',
        buttonState: { text: '参数错误', extraClass: 'btn-disabled', disabled: true, action: 'none' }
      });
      return;
    }

    this.setData({ loadError: false, loadErrorMsg: '' });
    const headers = {};
    if (app.globalData.token) {
      headers['Authorization'] = app.globalData.token;
    }
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/activities/' + normalizedId,
      header: headers,
      success: (res) => {
        if(res.data && res.data.success && res.data.data){
          const detail = Object.assign({
            title: '活动详情',
            description: '暂无活动描述',
            start_time: '-',
            end_time: '-',
            registration_start_time: '-',
            registration_end_time: '-',
            location: '-',
            current_participants: 0,
            max_participants: 0,
            points: 0,
            organizer: '智能社团+'
          }, res.data.data);
          if (!detail.registration_end_time && detail.registration_deadline) {
            detail.registration_end_time = detail.registration_deadline;
          }
          this.setData({ activity: detail });
          this.computeButtonState(detail);
          this.scheduleStateRefresh(detail);
        } else {
          this.setData({
            loadError: true,
            loadErrorMsg: (res.data && res.data.msg) ? res.data.msg : '加载活动失败',
            buttonState: { text: '加载失败', extraClass: 'btn-disabled', disabled: true, action: 'none' }
          });
          wx.showToast({ title: (res.data && res.data.msg) ? res.data.msg : '加载活动失败', icon: 'none' });
        }
      },
      fail: () => {
        this.setData({
          loadError: true,
          loadErrorMsg: '网络异常，请稍后重试',
          buttonState: { text: '网络异常', extraClass: 'btn-disabled', disabled: true, action: 'none' }
        });
        wx.showToast({ title: '网络异常，请稍后重试', icon: 'none' });
      },
      complete: () => {
        this.setData({ loading: false });
      }
    });
  },

  computeButtonState(activity) {
    if (!activity) return;
    const now = new Date().getTime();
    const toTs = (val) => {
      const n = Number(val);
      return Number.isFinite(n) && n > 0 ? n : null;
    };
    
    // Prefer backend unix timestamps to avoid client timezone parsing issues.
    const regStartTs = toTs(activity.registration_start_ts);
    const regDeadlineTs = toTs(activity.registration_deadline_ts);

    // Fallback to parse display strings for backward compatibility.
    const regStartStr = activity.registration_start_time || '待定';
    const regEndStr = activity.registration_end_time || activity.registration_deadline || '待定';
    
    const parseTime = (timeStr) => {
      if (timeStr === '待定') return null;
      let str = String(timeStr).trim().replace(/-/g, '/');
      if (/^\d{4}\/\d{1,2}\/\d{1,2}\s\d{1,2}:\d{1,2}$/.test(str)) {
        str += ':00';
      }
      // Explicit +08:00 ensures consistent Beijing time parsing across iOS/Android.
      if (/^\d{4}\/\d{1,2}\/\d{1,2}\s\d{1,2}:\d{1,2}:\d{1,2}$/.test(str)) {
        const isoLike = str.replace(/\//g, '-').replace(' ', 'T') + '+08:00';
        const ts = new Date(isoLike).getTime();
        return Number.isNaN(ts) ? null : ts;
      }
      const ts = new Date(str).getTime();
      return Number.isNaN(ts) ? null : ts;
    };

    const parsedStart = regStartStr !== '待定' ? parseTime(regStartStr) : null;
    const parsedEnd = regEndStr !== '待定' ? parseTime(regEndStr) : null;
    const regStart = regStartTs !== null ? regStartTs : (parsedStart || 0);
    const regEnd = regDeadlineTs !== null ? regDeadlineTs : (parsedEnd || Infinity);

    let state = { text: '立即报名', extraClass: '', disabled: false, action: 'register' };

    let isTimeValid = true;
    if (regStart && now < regStart) {
        state = { text: '未到时间', extraClass: 'btn-disabled', disabled: true, action: 'none' };
        isTimeValid = false;
    } else if (regEnd !== Infinity && now > regEnd) {
        state = { text: '已过时间', extraClass: 'btn-disabled', disabled: true, action: 'none' };
        isTimeValid = false;
    }

    if (activity.user_status === 'attended') {
        state = { text: '已签到', extraClass: 'btn-disabled', disabled: true, action: 'none' };
      } else if (activity.user_status === 'registered') {
          if (activity.checkin_enabled) {
              state = { text: '立即签到', extraClass: 'btn-special', disabled: false, action: 'checkin' };
          } else if (regEnd !== Infinity && now > regEnd) {
              state = { text: '等待开始', extraClass: 'btn-disabled', disabled: true, action: 'none' };
          } else {
              state = { text: '取消报名', extraClass: 'btn-danger', disabled: false, action: 'cancel' };
          }
    } else if (activity.user_status === 'cancelled') {
        if (!isTimeValid) {
            state = { text: '已过时间', extraClass: 'btn-disabled', disabled: true, action: 'none' };
        } else {
            state = { text: '重新报名', extraClass: '', disabled: false, action: 'register' };
        }
    } else {
        // not_registered
        if (!isTimeValid) {
            // Already handled above
        } else if (activity.max_participants > 0 && activity.current_participants >= activity.max_participants) {
            state = { text: '名额已满', extraClass: 'btn-disabled', disabled: true, action: 'none' };
        }
    }

    this.setData({ buttonState: state });
  },
  
  handleAction() {
    if (!this.data.activity || !this.data.activity.id) {
      wx.showToast({ title: '活动信息未加载完成', icon: 'none' });
      return;
    }
    const action = (this.data.buttonState && this.data.buttonState.action) || 'none';
    if (action === 'none') return;
    
    if (action === 'register') {
        this.handleRegister();
    } else if (action === 'cancel') {
        wx.showModal({
            title: '提示',
            content: '确定要取消报名吗？',
            success: (res) => {
                if (res.confirm) {
                    wx.request({
                        url: app.globalData.baseUrl + '/api/mp/activities/' + this.data.activity.id + '/cancel',
                        method: 'POST',
                        header: { 'Authorization': app.globalData.token },
                        success: (res) => {
                            if (res.data.success) {
                                wx.showToast({ title: '已取消报名', icon: 'success' });
                                this.fetchDetail(this.data.activity.id);
                                if (app.updateUnreadCount) app.updateUnreadCount();
                            } else {
                                wx.showToast({ title: res.data.msg || '取消失败', icon: 'none' });
                            }
                        }
                    });
                }
            }
        });
    } else if (action === 'checkin') {
        wx.scanCode({
            success: (scanRes) => {
                wx.showLoading({title: '验证中...'});
                wx.request({
                    url: app.globalData.baseUrl + '/api/mp/checkin',
                    method: 'POST',
                    header: { 'Authorization': app.globalData.token },
                    data: { checkin_key: scanRes.result },
                    success: (apiRes) => {
                        wx.hideLoading();
                        if(apiRes.data.success) {
                            wx.showToast({title: apiRes.data.msg, icon: 'success', duration: 3000});
                            this.fetchDetail(this.data.activity.id);
                    if (app.updateUnreadCount) app.updateUnreadCount(); // Refresh status
                        } else {
                            wx.showModal({title: '签到失败', content: apiRes.data.msg || '可能是二维码已过期或非活动二维码', showCancel: false});
                        }
                    },
                    fail: () => wx.showToast({title: '网络错误', icon: 'error'})
                })
            }
        });
    }
  },

  handleRegister() {
    const token = app.globalData.token;
    if (!token) {
        wx.showModal({
            title: '未登录',
            content: '请先登录以报名参加活动',
            success: (res) => { if(res.confirm) wx.navigateTo({url: '/pages/login/login'}) }
        })
        return;
    }
    
    const tmplIds = [
        'T25ILSqS41_ZhDXZl77iQESliXV9J8na1f5IyARQDbM', // 签到提醒
        'ESmqrDAYo8rVBDq5EL8YjbKGedpxOYuPQgIZ3Nz_EZ0', // 新活动发布提醒
        '16S-vnKCWw7x2xqKi86K_mme2paucmkIl0-hkDXAkfA'  // 活动开始通知
    ];

    // 微信小程序规范要求：必须直接在用户点击手势内同步调用 requestSubscribeMessage，不能包在异步的 wx.showModal 里
    wx.requestSubscribeMessage({
        tmplIds,
        complete: () => {
            // 无论同意还是拒绝，直接进入报名流程
            wx.showLoading({title: '正在提交...'});
            wx.request({
              url: app.globalData.baseUrl + '/api/mp/activities/' + this.data.activity.id + '/register',
              method: 'POST',
              header: { 'Authorization': token },
              success: (res) => {
                if(res.data.success) {
                    wx.showToast({title: res.data.msg, icon: 'success'});
                    this.fetchDetail(this.data.activity.id);
                    if (app.updateUnreadCount) app.updateUnreadCount(); // 刷新详情
                } else {
                    wx.showModal({title: '提示', content: res.data.msg, showCancel: false});
                }
              },
              complete: () => wx.hideLoading()
            })
        }
    })
  },

  onShareAppMessage() {
    const activityId = this.normalizeActivityId(this.data.activity && this.data.activity.id) || this.normalizeActivityId(this.activityId);
    return {
      title: this.data.activity?.title || '活动详情',
      path: activityId ? ('/pages/activity/activity?id=' + activityId) : '/pages/index/index'
    }
  },

  previewPoster() {
    const url = this.data.activity?.poster_url;
    if (url) {
      wx.previewImage({
        urls: [url]
      });
    }
  },

  copyWebLink() {
    const id = this.data.activity?.id;
    if (!id) return;
    const url = `https://reg.cqaibase.cn/activity/${id}`;
    wx.setClipboardData({
      data: url,
      success: () => {
        wx.showToast({
          title: '已复制链接',
          icon: 'success'
        });
      }
    });
  },

  retryLoad() {
    if (!this.activityId) {
      wx.navigateBack({ delta: 1 });
      return;
    }
    this.setData({ loading: true, loadError: false, loadErrorMsg: '' });
    this.fetchDetail(this.activityId);
  }
});