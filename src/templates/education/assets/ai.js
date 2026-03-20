(function () {
  const DEFAULT_ENDPOINT = '/api/ai/chat';
  const DEFAULT_CONTEXT = 'general';
  const DEFAULT_MODEL = 'deepseek-v3-250324';
  // 注意：现在改为站内认证AI服务，不再在前端保存密钥
  const DEFAULT_KEY = null;

  class DeepseekClient {
    constructor(opts = {}) {
      this.endpoint = opts.endpoint || DEFAULT_ENDPOINT;
      this.model = opts.model || DEFAULT_MODEL;
      this.apiKey = opts.apiKey || DEFAULT_KEY; // 留作兼容，但不会使用
      this.system = opts.system || '你是物理实验助手，请用简体中文，分步骤清晰说明，必要时给出近似公式与操作建议。';
      this.extraHeaders = opts.headers || {};
      this.context = opts.context || DEFAULT_CONTEXT;
    }

    async chat(messages, options = {}) {
      // messages 为 [{role, content}]。提取：
      // - 最后一条 user 作为当前消息
      // - 之前的 user/assistant 作为历史
      // - 所有 system 合并为文本，注入到历史中，便于后端理解实验上下文
      const chatHistory = [];
      const systemNotes = [];
      const priorUser = [];
      let userMessage = '';

      for (let i = 0; i < messages.length; i++) {
        const msg = messages[i];
        if (!msg || !msg.role) continue;
        if (msg.role === 'system' && msg.content) {
          systemNotes.push(String(msg.content));
        } else if (msg.role === 'assistant' && msg.content) {
          chatHistory.push({ role: 'assistant', content: String(msg.content) });
        } else if (msg.role === 'user' && msg.content) {
          priorUser.push(String(msg.content));
        }
      }

      if (priorUser.length > 0) {
        userMessage = priorUser[priorUser.length - 1];
        // 之前的 user 消息（如果有多轮），也放入历史
        for (let i = 0; i < priorUser.length - 1; i++) {
          chatHistory.push({ role: 'user', content: priorUser[i] });
        }
      }

      if (!userMessage) {
        throw new Error('缺少用户消息');
      }

      // 合并 system 文本，作为一条“说明”注入历史，便于后端/system prompt利用
      const sysCombined = systemNotes.filter(Boolean).join('\n');
      if (sysCombined) {
        chatHistory.unshift({ role: 'user', content: '附加说明：\n' + sysCombined });
      }

      const payload = {
        message: userMessage,
        context: this.context || DEFAULT_CONTEXT,
        chatHistory
      };

      const headers = Object.assign(
        {
          'Content-Type': 'application/json'
        },
        this.extraHeaders
      );

      const res = await fetch(this.endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
        credentials: 'include',
        signal: options.signal
      });

      if (!res.ok) {
        if (res.status === 401) {
          throw new Error('未登录，无法使用AI服务。请先登录。');
        }
        const text = await res.text().catch(() => '');
        throw new Error('AI 请求失败: ' + res.status + ' ' + text);
      }
      const data = await res.json();
      const content = data?.response || '';
      return String(content || '').trim();
    }
  }

  function voicesReady() {
    return new Promise((resolve) => {
      const have = speechSynthesis.getVoices();
      if (have && have.length) return resolve(have);
      speechSynthesis.onvoiceschanged = () => resolve(speechSynthesis.getVoices());
      // 保险：若浏览器没有触发事件，1s 后也返回
      setTimeout(() => resolve(speechSynthesis.getVoices()), 1000);
    });
  }

  async function speak(text, opts = {}) {
    if (!('speechSynthesis' in window)) return false;
    if (!text) return false;
    const { lang = 'zh-CN', rate = 1, pitch = 1, volume = 1, voiceName } = opts;
    await voicesReady();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    u.rate = rate;
    u.pitch = pitch;
    u.volume = volume;

    const vs = speechSynthesis.getVoices();
    let target = null;
    if (voiceName) {
      target = vs.find(v => v.name === voiceName);
    }
    if (!target) {
      target = vs.find(v => (v.lang || '').toLowerCase().startsWith('zh')) || vs[0];
    }
    if (target) u.voice = target;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    return true;
  }

  function stopSpeak() {
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel();
    }
  }

  function startSTT(options = {}) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return null;
    const {
      lang = 'zh-CN',
      interimResults = false,
      continuous = false,
      onResult,
      onStart,
      onEnd,
      onError
    } = options;

    const rec = new SR();
    rec.lang = lang;
    rec.interimResults = interimResults;
    rec.continuous = continuous;

    rec.onstart = () => onStart && onStart();
    rec.onend = () => onEnd && onEnd();
    rec.onerror = (e) => onError && onError(e);
    rec.onresult = (ev) => {
      let finalText = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res.isFinal) {
          finalText += res[0].transcript;
        } else if (interimResults) {
          finalText += res[0].transcript;
        }
      }
      if (finalText && onResult) onResult(finalText);
    };

    try {
      rec.start();
    } catch (e) {
      // 某些浏览器重复 start 会抛错
    }

    return {
      stop: () => {
        try { rec.stop(); } catch (e) {}
      }
    };
  }

  window.AIClient = { DeepseekClient };
  window.AIUtils = { speak, stopSpeak, startSTT, voicesReady };
})();