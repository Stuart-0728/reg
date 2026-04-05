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
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/activities/' + id,
      success: (res) => {
        if(res.data.success){
          this.setData({ activity: res.data.data });
        }
      },
      complete: () => {
        this.setData({ loading: false });
      }
    });
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