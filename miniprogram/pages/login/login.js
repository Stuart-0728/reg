const app = getApp();

Page({
  data: {
    student_id: '',
    password: '',
    isSubmitting: false,
    needBind: false,
    openid: ''
  },
  
  toggleBindMode() {
    this.setData({ needBind: !this.data.needBind, openid: '' });
  },

  handleWxLogin() {
    if (!this.data.isAgreed) {
      return wx.showToast({ title: '请先阅读并同意服务协议和隐私保护指引', icon: 'none' });
    }
    this.setData({ isSubmitting: true });
    wx.login({
      success: (loginRes) => {
        if (loginRes.code) {
          wx.showLoading({ title: '安全登录中...' });
          wx.request({
            url: app.globalData.baseUrl + '/api/mp/wx_login',
            method: 'POST',
            data: { code: loginRes.code },
            success: (res) => {
              if (res.data.success) {
                if (res.data.need_bind) {
                  // 用户未绑定，需要跳转到绑定页面
                  wx.hideLoading();
                  wx.showToast({ title: '首次登录请绑定账号', icon: 'none' });
                  this.setData({ needBind: true, openid: res.data.openid });
                } else {
                  // 登录成功
                  wx.setStorageSync('token', res.data.token);
                  wx.setStorageSync('userInfo', res.data.user);
                  app.globalData.token = res.data.token;
                  app.globalData.userInfo = res.data.user;
                  wx.hideLoading();
                  wx.showToast({ title: '登录成功', icon: 'success' });
                  setTimeout(() => { wx.navigateBack(); }, 1500);
                }
              } else {
                wx.hideLoading();
                wx.showToast({ title: res.data.msg || '微信登录失败', icon: 'none' });
                // 如果后端没有配置APPID，直接让用户输入账号密码
                if (res.data.msg && res.data.msg.includes('APPID')) {
                   this.setData({ needBind: true });
                }
              }
            },
            fail: () => {
              wx.hideLoading();
              wx.showToast({ title: '网络请求失败', icon: 'none' });
            },
            complete: () => {
              this.setData({ isSubmitting: false });
            }
          });
        }
      },
      fail: () => {
         this.setData({ isSubmitting: false });
         wx.showToast({ title: '获取微信环境失败', icon: 'none' });
      }
    });
  },

  goToRegister() {
    wx.navigateTo({ url: `/pages/register/register?openid=${this.data.openid || ''}` });
  },

  handleBindAccount() {
    if (!this.data.isAgreed) {
      return wx.showToast({ title: '请先阅读并同意服务协议和隐私保护指引', icon: 'none' });
    }
    if (!this.data.student_id || !this.data.password) {
      wx.showToast({ title: '请输入完整信息', icon: 'none' });
      return;
    }
    
    this.setData({ isSubmitting: true });
    wx.showLoading({ title: this.data.openid ? '绑定中...' : '登录中...' });
    
    const requestData = {
      student_id: this.data.student_id,
      password: this.data.password
    };
    if (this.data.openid) {
      requestData.openid = this.data.openid;
    }

    wx.request({
      url: app.globalData.baseUrl + '/api/mp/login',
      method: 'POST',
      data: requestData,
      success: (res) => {
        if (res.data.success) {
          wx.setStorageSync('token', res.data.token);
          wx.setStorageSync('userInfo', res.data.user);
          app.globalData.token = res.data.token;
          app.globalData.userInfo = res.data.user;
          wx.hideLoading();
          wx.showToast({ title: this.data.openid ? '绑定成功' : '登录成功', icon: 'success' });
          setTimeout(() => { wx.navigateBack(); }, 1500);
        } else {
          wx.hideLoading();
          wx.showToast({ title: res.data.msg || '操作失败', icon: 'none' });
        }
      },
      fail: () => {
        wx.hideLoading();
        wx.showToast({ title: '网络请求失败', icon: 'none' });
      },
      complete: () => {
        this.setData({ isSubmitting: false });
      }
    });
  }
});
