const app = getApp();
Page({
  data: {
    form: {
      username: '',
      password: '',
      email: '',
      real_name: '',
      student_id: '',
      grade: '',
      college: '',
      major: '',
      phone: '',
      qq: '',
      society_ids: [],
      tag_ids: [],
      wx_openid: ''
    },
    societies: [],
    tags: [],
    isSubmitting: false,
    isAgreed: false
  },

  onInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({
      [`form.${field}`]: e.detail.value
    });
  },

  onAgreeChange(e) {
    this.setData({
      isAgreed: e.detail.value.includes('agree')
    });
  },
  
  onLoad(options) {
    if (options && options.openid) {
      this.setData({ 'form.wx_openid': options.openid });
    }
    this.fetchSocieties();
    this.fetchTags();
  },

  fetchSocieties() {
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/societies',
      method: 'GET',
      success: (res) => {
        if (res.data.success) {
          const list = res.data.data.map(item => ({ ...item, checked: false }));
          this.setData({ societies: list });
        }
      }
    });
  },

  fetchTags() {
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/tags',
      method: 'GET',
      success: (res) => {
        if (res.data.success) {
          const list = res.data.data.map(item => ({ ...item, checked: false }));
          this.setData({ tags: list });
        }
      }
    });
  },

  onTagsChange(e) {
    const values = e.detail.value;
    const items = this.data.tags.map(t => {
      t.checked = values.includes(t.id.toString()) || values.includes(t.id);
      return t;
    });
    this.setData({ tags: items, 'form.tag_ids': values });
  },

  onSocietiesChange(e) {
    const values = e.detail.value;
    const items = this.data.societies.map(t => {
      t.checked = values.includes(t.id.toString()) || values.includes(t.id);
      return t;
    });
    this.setData({ societies: items, 'form.society_ids': values });
  },

  handleSubmit() {
    if (!this.data.isAgreed) {
      return wx.showToast({ title: '请先阅读并同意服务协议和隐私保护指引', icon: 'none' });
    }
    const { username, password, email, real_name, student_id, phone, qq, college, major, grade } = this.data.form;
    if (!username || !password || !email || !real_name || !student_id || !phone || !qq || !college || !major || !grade) {
      wx.showToast({ title: '请填写所有必填档案(包括联系资料)', icon: 'none' });
      return;
    }
    
    if (password.length < 6) {
      wx.showToast({ title: '密码至少6位数', icon: 'none' });
      return;
    }
    
    this.setData({ isSubmitting: true });
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/register',
      method: 'POST',
      data: this.data.form,
      success: (res) => {
        if (res.data.success) {
          if (this.data.form.wx_openid) {
            wx.showToast({ title: '注册并绑定成功', icon: 'success' });
            setTimeout(() => { wx.navigateBack(); }, 1500);
          } else {
            wx.redirectTo({ url: '/pages/verify_email/verify_email' });
          }
        } else {
          wx.showToast({ title: res.data.msg || '注册失败', icon: 'none' });
        }
      },
      fail: () => {
        wx.showToast({ title: '网络异常', icon: 'none' });
      },
      complete: () => {
        this.setData({ isSubmitting: false });
      }
    });
  }
});
