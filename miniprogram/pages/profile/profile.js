const app = getApp();
Page({
  data: {
    form: {},
    loading: true,
    isSubmitting: false,
    grades: ['2023级', '2024级', '2025级', '2026级', '其他'],
    gradeIndex: 0
  },
  
  onShow() {
    if (!app.globalData.token) {
        wx.showModal({
            title: '未登录',
            content: '请先登录以查看个人资料',
            success: (md) => {
                if(md.confirm) wx.navigateTo({url: '/pages/login/login'})
                else wx.navigateBack();
            }
        });
        return;
    }
    this.fetchData();
  },

  fetchData() {
    this.setData({ loading: true });
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/profile',
      method: 'GET',
      header: { 'Authorization': app.globalData.token },
      success: (res) => {
        if(res.data.success){
          const form = res.data.data;
          // Set grade index
          let idx = this.data.grades.indexOf(form.grade);
          this.setData({ 
              form: form, 
              gradeIndex: idx >= 0 ? idx : 4 
          });
        } else {
            wx.showToast({ title: res.data.msg || '获取信息失败', icon: 'none' });
            if (res.data.need_login) {
                wx.removeStorageSync('token');
                app.globalData.token = null;
                setTimeout(() => wx.navigateTo({url: '/pages/login/login'}), 1000);
            }
        }
      },
      complete: () => {
        this.setData({ loading: false });
      }
    });
  },

  onGradeChange(e) {
    const val = e.detail.value;
    this.setData({
      gradeIndex: val,
      'form.grade': this.data.grades[val]
    });
  },

  handleSave() {
    const { real_name, email, grade, college, major, phone, qq } = this.data.form;
    if (!real_name || !email || !grade || !college || !major) {
      wx.showToast({ title: '姓名/邮箱/学院专业不能为空', icon: 'none' });
      return;
    }

    this.setData({ isSubmitting: true });
    wx.request({
      url: app.globalData.baseUrl + '/api/mp/profile',
      method: 'POST',
      header: { 'Authorization': app.globalData.token },
      data: { real_name, email, grade, college, major, phone, qq },
      success: (res) => {
        if (res.data.success) {
          wx.showToast({ title: '保存成功', icon: 'success' });
          setTimeout(() => { wx.navigateBack(); }, 1500);
        } else {
          wx.showToast({ title: res.data.msg || '保存失败', icon: 'none' });
        }
      },
      complete: () => {
        this.setData({ isSubmitting: false });
      }
    });
  }
});
