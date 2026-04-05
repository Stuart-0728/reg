const app = getApp();

Page({
  data: {
    activity: null,
    loading: true
  },
  onLoad(options) {
    if(options.id){
      this.fetchDetail(options.id);
    }
  },
  fetchDetail(id) {
    const headers = {};
    if (app.globalData.token) {
      headers['Authorization'] = app.globalData.token;
    }
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/activities/' + id,
      header: headers,
      success: (res) => {
        if(res.data.success){
          this.setData({ activity: res.data.data });
          this.computeButtonState(res.data.data);
        }
      },
      complete: () => {
        this.setData({ loading: false });
      }
    });
  },

  computeButtonState(activity) {
    if (!activity) return;
    const now = new Date().getTime();
    
    // Safely parse times
    const regStartStr = activity.registration_start_time || '待定';
    const regEndStr = activity.registration_end_time || '待定';
    
    const parseTime = (timeStr) => {
        if (timeStr === '待定') return 0;
        let str = timeStr.replace(/-/g, '/');
        if (str.split(':').length === 2) str += ':00'; // 兼容 iOS 避免 NaN
        return new Date(str).getTime();
    };

    const regStart = regStartStr !== '待定' ? parseTime(regStartStr) : 0;
    const regEnd = regEndStr !== '待定' ? (parseTime(regEndStr) || Infinity) : Infinity;

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
    const action = this.data.buttonState.action;
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
                            this.fetchDetail(this.data.activity.id); // Refresh status
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
                    this.fetchDetail(this.data.activity.id); // 刷新详情
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
    return {
      title: this.data.activity?.title || '活动详情',
      path: '/pages/activity/activity?id=' + this.data.activity?.id
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
  }
});