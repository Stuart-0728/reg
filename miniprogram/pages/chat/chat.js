const app = getApp();
Page({
  data: {
    messages: [
      { role: 'assistant', content: '你好！我是智能社团+专属AI助手团小智。有什么我可以帮你的吗？' }
    ],
    inputVal: '',
    loading: false,
    scrollTo: '',
    userInfo: null
  },
  onLoad() {
      wx.setNavigationBarTitle({ title: 'AI 助手' });
      this.setData({ userInfo: app.globalData.userInfo });
  },
  onInput(e) {
    this.setData({ inputVal: e.detail.value });
  },
  send() {
    const val = this.data.inputVal.trim();
    if (!val || this.data.loading) return;

    const msgs = this.data.messages;
    msgs.push({ role: 'user', content: val });
    
    this.setData({
      messages: msgs,
      inputVal: '',
      loading: true,
      scrollTo: 'msg-' + (msgs.length - 1)
    });

    const history = msgs.slice(0, -1).map(m => ({role: m.role, content: m.content}));

    wx.request({
      url: app.globalData.baseUrl + '/api/mp/chat',
      method: 'POST',
      header: { 'Authorization': app.globalData.token },
      data: { message: val, history: history },
      success: (res) => {
        const resultMsgs = this.data.messages;
        if (res.data.success) {
          resultMsgs.push({ role: 'assistant', content: res.data.data });
        } else {
          resultMsgs.push({ role: 'assistant', content: '抱歉，系统异常：' + (res.data.msg || '') });
        }
        this.setData({
          messages: resultMsgs,
          scrollTo: 'msg-' + (resultMsgs.length - 1)
        });
      },
      fail: () => {
        const resultMsgs = this.data.messages;
        resultMsgs.push({ role: 'assistant', content: '网络请求失败，请稍后重试。' });
        this.setData({
          messages: resultMsgs,
          scrollTo: 'msg-' + (resultMsgs.length - 1)
        });
      },
      complete: () => {
        this.setData({ loading: false });
      }
    });
  }
});
