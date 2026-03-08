(function () {
  let mounted = false;
  let panel, fab, body, input, sendBtn, micBtn, ttsToggle;
  let client = null;
  let autoTTS = true;
  let sttController = null;
  let micStream = null;
  // Suggest 去抖/去重
  let lastSuggestAt = 0;
  let lastSuggestText = '';
  let suggestToast = null;
  // 语音识别基线文本，避免移动端Edge覆盖前文
  let sttBaseText = '';
  let sttAccumText = '';
  // 调试模式
  let debugMode = false;

  const defaultOptions = {
    apiKey: null,
    endpoint: null,
    model: null,
    systemPrompt: '你是物理实验助手，请用简体中文回答，条理清晰、步骤明确，结合实验数据给出结论与建议。',
    tts: true,
    stt: true,
    requireLogin: true,
    title: 'AI 实验助手',
    greeting: '你好！我是你的物理实验 AI 助手，有什么想问我的吗？',
    contextProvider: null
  };

  function el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v);
    });
    children.forEach((c) => e.appendChild(c));
    return e;
  }

  // 调试日志函数
  function debugLog(...args) {
    if (debugMode) {
      console.log('[ChatWidget Debug]', ...args);
    }
  }

  function renderMarkdown(src) {
    const esc = (s) => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let s = esc(String(src || ''));
    // fenced code blocks
    s = s.replace(/```([\s\S]*?)```/g, (_, code) => '<pre><code>' + code.replace(/\n/g, '<br/>') + '</code></pre>');
    // inline code
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // headings
    s = s.replace(/^###### (.*)$/gm, '<h6>$1</h6>')
         .replace(/^##### (.*)$/gm, '<h5>$1</h5>')
         .replace(/^#### (.*)$/gm, '<h4>$1</h4>')
         .replace(/^### (.*)$/gm, '<h3>$1</h3>')
         .replace(/^## (.*)$/gm, '<h2>$1</h2>')
         .replace(/^# (.*)$/gm, '<h1>$1</h1>');
    // bold & italic
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
         .replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // lists (naive)
    s = s.replace(/^(?:-|\*) (.*)$/gm, '<li>$1</li>');
    s = s.replace(/(?:<li>.*<\/li>\n?)+/g, m => '<ul>' + m.replace(/\n/g,'') + '</ul>');
    // line breaks
    s = s.replace(/\n/g, '<br/>');
    return s;
  }

  function addMessage(role, text) {
    const div = el('div', { class: 'cb-msg ' + (role === 'user' ? 'user' : 'bot') });
    div.innerHTML = renderMarkdown(text);
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function setLoading(loading) {
    sendBtn.disabled = loading;
    micBtn.disabled = loading && !sttController;
    if (loading) {
      sendBtn.classList.add('secondary');
      // 使用加载动画而不是改文字
      if (!sendBtn.querySelector('.cb-spinner')) {
        const sp = document.createElement('span');
        sp.className = 'cb-spinner';
        sp.style.marginLeft = '6px';
        sendBtn.appendChild(sp);
      }
    } else {
      sendBtn.classList.remove('secondary');
      const sp = sendBtn.querySelector('.cb-spinner');
      if (sp) sp.remove();
    }
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    addMessage('user', text);

    // 实验上下文
    let ctx = null;
    try {
      if (typeof client.options?.contextProvider === 'function') {
        ctx = client.options.contextProvider();
      } else if (typeof window.getExperimentContext === 'function') {
        ctx = window.getExperimentContext();
      }
    } catch (_) {}

    const msgs = [
      { role: 'system', content: client.system },
      ...(ctx ? [{ role: 'system', content: '实验上下文：' + JSON.stringify(ctx) }] : []),
      { role: 'user', content: text }
    ];

    // 对话区占位：AI 正在思考…（使用HTML字符串而不是文本）
    const typingDiv = el('div', { class: 'cb-msg bot' });
    typingDiv.innerHTML = '<span class="cb-typing"><span class="cb-spinner"></span> AI 正在思考…</span>';
    body.appendChild(typingDiv);
    body.scrollTop = body.scrollHeight;
    const typing = typingDiv;

    setLoading(true);
    try {
      const ans = await client.chat(msgs);
      typing.innerHTML = renderMarkdown(ans);
      if (autoTTS && isPanelOpen()) {
        AIUtils.speak(ans, { lang: 'zh-CN', rate: 1 });
      }
      return typing;
    } catch (e) {
      typing.innerHTML = '请求失败：' + (e.message || e);
    } finally {
      setLoading(false);
    }
  }

  function togglePanel() {
    const shown = panel.style.display !== 'none';
    if (!shown) {
      panel.style.display = 'flex';
      panel.style.opacity = '0';
      panel.style.transform = 'translateY(12px)';
      requestAnimationFrame(() => {
        panel.style.opacity = '1';
        panel.style.transform = 'translateY(0)';
      });
    } else {
      panel.style.opacity = '0';
      panel.style.transform = 'translateY(12px)';
      try { AIUtils.stopSpeak(); } catch (e) {}
      // 关闭面板时确保释放麦克风资源
      releaseMicrophoneIfActive();
      setTimeout(() => { panel.style.display = 'none'; }, 180);
    }
  }
  
  function isPanelOpen() {
    return panel && panel.style.display !== 'none';
  }

  // 释放麦克风资源的统一函数
  function releaseMicrophoneIfActive() {
    debugLog('尝试释放麦克风资源');
    // 停止语音识别控制器
    if (sttController) {
      try {
        debugLog('停止语音识别控制器');
        sttController.stop();
        sttController = null;
      } catch (e) {
        console.error('停止语音识别失败:', e);
      }
    }
    
    // 重置麦克风按钮状态
    if (micBtn) {
      micBtn.textContent = '🎤';
      micBtn.classList.remove('cb-mic-on');
    }
    
    // 释放麦克风媒体流
    if (micStream) {
      try {
        debugLog('释放麦克风媒体流');
        micStream.getTracks().forEach(track => {
          track.stop();
        });
        micStream = null;
        debugLog('麦克风资源已释放');
      } catch (e) {
        console.error('释放麦克风资源失败:', e);
      }
    }
  }

  function mountUI(opts) {
    fab = el('button', { class: 'cb-chat-fab', title: 'AI 实验助手' });
    fab.innerHTML = '<span style="font-weight:800;font-style:italic;">AI</span>';
    fab.addEventListener('click', async () => {
      if (opts.requireLogin) {
        if (opts.authenticated === null || typeof opts.authenticated === 'undefined') {
          try {
            const res = await fetch('/education/auth-status', { credentials: 'include' });
            const data = await res.json();
            opts.authenticated = !!(data && data.authenticated);
          } catch (_) {
            opts.authenticated = false;
          }
        }

        if (opts.authenticated === false) {
          suggest('AI 功能已禁用：请登录后使用。');
          return;
        }
      }
      togglePanel();
    });

    panel = el('div', { class: 'cb-chat-panel' });
    // 固定面板高度与布局（内联，避免依赖全局 CSS 未生效）
    panel.style.maxHeight = '800px';
    panel.style.minHeight = '360px';
    panel.style.height = '60vh';
    panel.style.flexDirection = 'column';

    // 全站样式增强：隐藏顶部导航（仅保留标题）+ 聊天动画与 Markdown 呈现样式
    try {
      const s = document.createElement('style');
      s.textContent = [
        '.topbar nav{display:none !important}',
        '.cb-chat-panel{transition:opacity .18s ease, transform .18s ease}',
        '.cb-msg.bot pre{background:rgba(255,255,255,0.06);padding:8px;border-radius:8px;overflow:auto}',
        '.cb-msg.bot code{background:rgba(255,255,255,0.08);padding:2px 4px;border-radius:4px}',
        '.cb-toast{position:fixed;right:94px;bottom:94px;max-width:320px;background:rgba(0,0,0,0.78);color:#fff;padding:10px 12px;border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,0.3);opacity:0;transform:translateY(8px);transition:opacity .18s ease, transform .18s ease;z-index:11010}',
        '.cb-toast.in-panel{position:absolute;right:12px;bottom:12px;max-width:calc(100% - 24px);z-index:1}',
        '.cb-toast.show{opacity:1;transform:translateY(0)}',
        '.cb-toast button{margin-left:8px}',
        '.cb-mic-on{animation:cbPulse 1s ease-in-out infinite alternate}',
        '@keyframes cbPulse{from{filter:brightness(1)}to{filter:brightness(1.5)}}',
        '.cb-spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.45);border-top-color:#fff;border-radius:50%;animation:cbSpin 1s linear infinite;vertical-align:-2px}',
        '@keyframes cbSpin{to{transform:rotate(360deg)}}',
        '.cb-typing{display:inline-flex;align-items:center;gap:6px;color:var(--muted)}',
        '.cb-debug-btn{position:fixed;bottom:10px;left:10px;background:rgba(0,0,0,0.5);color:white;border:none;border-radius:4px;padding:4px 8px;font-size:12px;cursor:pointer;z-index:10000}'
      ].join('');
      document.head.appendChild(s);
    } catch (e) {}

    const head = el('div', { class: 'cb-chat-head' });
    const htitle = el('div', { style: 'display:flex;gap:8px;align-items:center;' });
    const chip = el('span', { class: 'cb-chip', text: opts.title || 'AI 实验助手' });
    const ttsLabel = el('label', { class: 'cb-chip', title: '语音播报开关' });
    ttsToggle = el('input', { type: 'checkbox', style: 'margin-right:6px;' });
    ttsToggle.checked = !!opts.tts;
    autoTTS = ttsToggle.checked;
    ttsLabel.appendChild(ttsToggle);
    ttsLabel.appendChild(document.createTextNode('播报'));
    htitle.appendChild(chip);
    htitle.appendChild(ttsLabel);

    const closeBtn = el('button', { class: 'btn secondary' });
    closeBtn.textContent = '关闭';
    closeBtn.addEventListener('click', () => { 
      try { AIUtils.stopSpeak(); } catch (e) {} 
      releaseMicrophoneIfActive();
      panel.style.display = 'none'; 
    });

    head.appendChild(htitle);
    head.appendChild(closeBtn);

    body = el('div', { class: 'cb-chat-body' });
    body.style.flex = '1';
    body.style.overflowY = 'auto';

    const inputWrap = el('div', { class: 'cb-chat-input' });
    input = el('textarea', { placeholder: '向 AI 提问…（Enter 发送，Shift+Enter 换行）' });
    micBtn = el('button', { class: 'btn secondary', title: '语音输入' });
    micBtn.textContent = '🎤';
    sendBtn = el('button', { class: 'btn' });
    sendBtn.textContent = '发送';

    inputWrap.appendChild(input);
    inputWrap.appendChild(micBtn);
    inputWrap.appendChild(sendBtn);

    panel.appendChild(head);
    panel.appendChild(body);
    panel.appendChild(inputWrap);

    document.body.appendChild(fab);
    document.body.appendChild(panel);

    // 添加调试按钮（隐藏）
    const debugBtn = el('button', { class: 'cb-debug-btn', text: '调试模式' });
    debugBtn.style.display = 'none'; // 默认隐藏
    debugBtn.addEventListener('click', () => {
      debugMode = !debugMode;
      debugBtn.textContent = debugMode ? '关闭调试' : '调试模式';
      debugLog('调试模式:', debugMode ? '开启' : '关闭');
      
      // 显示浏览器和平台信息
      if (debugMode) {
        const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
        const isEdge = /Edg/i.test(navigator.userAgent);
        const isSafari = /Safari/i.test(navigator.userAgent) && !/Chrome/i.test(navigator.userAgent);
        const isChrome = /Chrome/i.test(navigator.userAgent) && !/Edg/i.test(navigator.userAgent);
        
        console.log('=== 浏览器环境信息 ===');
        console.log('用户代理:', navigator.userAgent);
        console.log('平台:', navigator.platform);
        console.log('浏览器检测:', { isMac, isEdge, isSafari, isChrome });
        console.log('语音识别API:', 'SpeechRecognition' in window ? '标准' : ('webkitSpeechRecognition' in window ? 'WebKit' : '不支持'));
        console.log('安全上下文:', window.isSecureContext);
        console.log('===================');
      }
    });
    document.body.appendChild(debugBtn);
    
    // 强制将所有错误信息输出到控制台
    // 启用控制台调试日志
    const debugLog = (message, ...args) => {
      try {
        if (args.length > 0) {
          console.log(`[ChatWidget] ${message}`, ...args);
        } else {
          console.log(`[ChatWidget] ${message}`);
        }
      } catch (e) {
        // 确保即使日志输出失败也不会影响功能
        console.error("[ChatWidget] 日志输出失败", e);
      }
    };
    
    // 全局错误处理器
    window.addEventListener('error', function(event) {
      console.error('[ChatWidget] 全局错误:', event.error || event.message);
      return false;
    });
    
    // 未捕获的Promise错误
    window.addEventListener('unhandledrejection', function(event) {
      console.error('[ChatWidget] Promise错误:', event.reason);
    });
    
    // 覆盖原生的语音识别错误处理
    if (window.SpeechRecognition || window.webkitSpeechRecognition) {
      const OriginalSpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const originalProto = OriginalSpeechRecognition.prototype;
      
      // 保存原始的onerror处理器
      const originalOnError = Object.getOwnPropertyDescriptor(originalProto, 'onerror');
      
      // 防重复错误处理
      let lastErrorTime = 0;
      let lastErrorType = '';
      
      // 如果可能，增强onerror处理
      if (originalOnError && originalOnError.set) {
        Object.defineProperty(originalProto, 'onerror', {
          set: function(handler) {
            originalOnError.set.call(this, function(event) {
              // 防重复错误：如果是相同类型的错误且时间间隔小于1秒，则跳过
              const currentTime = Date.now();
              const currentErrorType = event.error || 'unknown';
              if (currentErrorType === lastErrorType && (currentTime - lastErrorTime) < 1000) {
                return; // 跳过重复错误
              }
              lastErrorTime = currentTime;
              lastErrorType = currentErrorType;
              
              // 记录到控制台，包含详细信息
              console.warn('[ChatWidget] 语音识别错误:', {
                error: event.error,
                message: event.message,
                type: event.type,
                timeStamp: event.timeStamp,
                target: event.target?.constructor?.name || 'Unknown'
              });
              
              // 然后调用原始处理器
              if (handler) {
                handler.call(this, event);
              }
            });
          },
          get: originalOnError.get
        });
      }
      
      // 添加全局语音识别错误监听
      const originalStart = originalProto.start;
      if (originalStart) {
        originalProto.start = function() {
          // 为每个新的语音识别实例添加错误监听
          const instance = this;
          
          // 如果没有设置错误处理器，添加默认的
          if (!instance.onerror) {
            instance.onerror = function(event) {
              console.error('[ChatWidget] 未处理的语音识别错误:', event);
            };
          }
          
          return originalStart.call(this);
        };
      }
    }

    panel.style.display = 'none';

    ttsToggle.addEventListener('change', () => {
      autoTTS = ttsToggle.checked;
      if (!autoTTS) AIUtils.stopSpeak();
    });
    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });

    // 页面卸载时释放资源
    window.addEventListener('beforeunload', releaseMicrophoneIfActive);
    
    // 页面切换到后台时释放麦克风资源
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        releaseMicrophoneIfActive();
      }
    });

    if (opts.stt) {
      setupSpeechRecognition(opts);
    } else {
      micBtn.style.display = 'none';
    }
  }

  // 语音识别设置函数
  function setupSpeechRecognition(opts) {
    const webSpeech = ('webkitSpeechRecognition' in window) || ('SpeechRecognition' in window);
    const hasAIUtils = (typeof AIUtils !== 'undefined' && typeof AIUtils.startSTT === 'function');
    
    // 检测平台和浏览器
    const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
    const isMobile = /iPhone|iPad|iPod|Android|webOS|BlackBerry|Windows Phone/i.test(navigator.userAgent);
    const isEdge = /Edg/i.test(navigator.userAgent);
    const isSafari = /Safari/i.test(navigator.userAgent) && !/Chrome/i.test(navigator.userAgent);
    const isMacEdge = isEdge && isMac;
    
    // 检查是否为安全上下文
    const isLocalhost = (location.hostname === 'localhost' || location.hostname === '127.0.0.1');
    const isSecure = (window.isSecureContext === true) || isLocalhost;
    
    debugLog('浏览器环境:', { isMac, isMobile, isEdge, isSafari, isMacEdge, webSpeech, hasAIUtils, isSecure });
    
    // 在 macOS Edge 上，原生 Web Speech 语音识别常不可用或报 language-not-supported，提供明确的解决方案
    if (isMacEdge) {
      micBtn.title = 'Mac上的Edge浏览器不支持语音识别。建议使用Chrome或Safari浏览器。';
      micBtn.style.opacity = '0.6'; // 视觉上表示不可用
      
      micBtn.addEventListener('click', async () => {
        // 显示详细的解决方案
        const solutions = [
          '🔧 Mac Edge语音识别解决方案：',
          '',
          '✅ 推荐方案：',
          '1. 使用Chrome浏览器（完全支持）',
          '2. 使用Safari浏览器（部分支持）',
          '',
          '⚙️ 其他尝试：',
          '3. 更新Edge到最新版本',
          '4. 在Edge设置中启用实验性功能',
          '',
          '💡 临时方案：',
          '5. 手动输入文字进行对话',
          '6. 使用其他设备访问'
        ].join('\n');
        
        console.warn(solutions);
        
        // 检测是否有AIUtils备用方案（仅作为最后尝试）
        if (hasAIUtils && typeof AIUtils.startSTT === 'function') {
          const tryBackup = false; // 自动跳过备用语音识别引擎
          if (tryBackup) {
            try {
              sttBaseText = input.value;
              sttAccumText = '';
              
              const ctrl = AIUtils.startSTT({
                lang: 'en-US',
                interimResults: false,
                continuous: false,
                onStart: () => { 
                  micBtn.textContent = '🛑'; 
                  micBtn.classList.add('cb-mic-on');
                  micBtn.style.opacity = '1';
                },
                onEnd: () => { 
                  micBtn.textContent = '🎤'; 
                  micBtn.classList.remove('cb-mic-on'); 
                  micBtn.style.opacity = '0.6';
                  sttController = null; 
                },
                onResult: (txt, isFinal) => { sttMergeUpdate(txt, isFinal); },
                onError: (err) => {
                  // 防重复错误处理
                  const currentTime = Date.now();
                  const errorType = err?.error || 'backup-error';
                  if (!window._lastBackupErrorTime) window._lastBackupErrorTime = 0;
                  if (!window._lastBackupErrorType) window._lastBackupErrorType = '';
                  
                  if (errorType === window._lastBackupErrorType && (currentTime - window._lastBackupErrorTime) < 1000) {
                    return; // 跳过重复错误
                  }
                  window._lastBackupErrorTime = currentTime;
                  window._lastBackupErrorType = errorType;
                  
                  console.warn('[ChatWidget] 备用识别错误:', err);
                  micBtn.textContent = '🎤'; 
                  micBtn.classList.remove('cb-mic-on'); 
                  micBtn.style.opacity = '0.6';
                  sttController = null;
                  releaseMicrophoneIfActive();
                }
              });
              
              if (ctrl) {
                sttController = ctrl;
                return; // 成功启动备用方案
              }
            } catch (e) {
              console.error('[ChatWidget] 备用方案启动失败:', e);
            }
          }
        }
        
        // 最终提示：暂不支持
        console.warn('[ChatWidget] Mac上的Edge浏览器暂不支持语音识别功能。建议使用Chrome或Safari浏览器。');
      });
      return;
    }
    
    if (!webSpeech) {
      micBtn.title = '当前浏览器不支持语音识别（建议使用 Chrome，且需 https 或 localhost）';
      micBtn.addEventListener('click', async () => {
        try {
          if (!micStream && navigator.mediaDevices?.getUserMedia) {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          }
        } catch (e) {}
        
        let message = '当前浏览器不支持 Web Speech 语音识别。';
        
        if (isMac && isEdge) {
          message = 'Edge浏览器在Mac/iPad上可能不支持语音识别。请尝试使用Chrome浏览器。';
        } else if (isMobile) {
          message = '移动设备上的语音识别支持有限。请尝试使用Chrome浏览器，并确保使用https连接。';
        } else if (isMac) {
          message = 'Mac系统上可能需要使用Chrome浏览器并授予麦克风权限。Safari浏览器对Web Speech API支持有限。';
        }
        
        if (!isSecure) {
          message += '\n\n重要：语音识别需要安全连接(https)或本地连接(localhost)。当前连接不安全。';
        }
        
        console.warn('[ChatWidget] 语音识别不支持:', message);
        
        // 确保释放可能已获取的麦克风资源
        releaseMicrophoneIfActive();
      });
      return;
    }
    
    // 文本相似度计算函数
    function calculateTextSimilarity(text1, text2) {
      if (!text1 || !text2) return 0;
      if (text1 === text2) return 1;
      
      const words1 = text1.toLowerCase().split(/\s+/);
      const words2 = text2.toLowerCase().split(/\s+/);
      
      const set1 = new Set(words1);
      const set2 = new Set(words2);
      
      const intersection = new Set([...set1].filter(x => set2.has(x)));
      const union = new Set([...set1, ...set2]);
      
      return intersection.size / union.size;
    }

    // 通用去重函数：检测并移除重复的词和短语
    function removeRepeatedWords(text) {
      if (!text) return text;
      
      const words = text.split(/\s+/);
      if (words.length <= 1) return text;
      
      const result = [];
      const recentWords = new Map(); // 记录最近出现的词及其位置
      
      // Windows Edge特殊处理：更激进的去重策略
      const isWindowsEdge = /Edg/i.test(navigator.userAgent) && /Windows/i.test(navigator.userAgent);
      const dedupeWindow = isWindowsEdge ? 5 : 3; // Windows Edge使用更大的去重窗口
      
      for (let i = 0; i < words.length; i++) {
        const word = words[i];
        const lastPos = recentWords.get(word);
        
        // 如果这个词在最近的窗口内出现过，可能是重复
        if (lastPos !== undefined && i - lastPos <= dedupeWindow) {
          // 检查是否为连续重复模式
          let isRepeating = true;
          const gap = i - lastPos;
          
          // Windows Edge: 更严格的重复检测
          if (isWindowsEdge) {
            // 对于Windows Edge，如果词在较短时间内重复出现，直接跳过
            if (gap <= 2) {
              debugLog('Windows Edge检测到短距离重复，跳过词:', word);
              continue;
            }
          }
          
          // 检查是否存在重复模式
          for (let j = 1; j < gap && lastPos - j >= 0; j++) {
            if (words[lastPos - j] !== words[i - j]) {
              isRepeating = false;
              break;
            }
          }
          
          if (isRepeating) {
            debugLog('检测到重复模式，跳过词:', word);
            continue; // 跳过重复的词
          }
        }
        
        result.push(word);
        recentWords.set(word, i);
      }
      
      // Windows Edge额外处理：检测并移除整句重复
      if (isWindowsEdge) {
        const finalText = result.join(' ');
        const sentences = finalText.split(/[。！？.!?]/);
        const uniqueSentences = [];
        const seenSentences = new Set();
        
        for (const sentence of sentences) {
          const trimmed = sentence.trim();
          if (trimmed && !seenSentences.has(trimmed)) {
            uniqueSentences.push(trimmed);
            seenSentences.add(trimmed);
          }
        }
        
        return uniqueSentences.join('。');
      }
      
      return result.join(' ');
    }
    
    // 语音识别文本处理函数
    function sttMergeUpdate(text, isFinal = false) {
      try {
        const incoming = String(text || '').trim();
        if (!incoming) return;
        
        debugLog('语音识别文本更新:', { incoming, isFinal, current: sttAccumText });
        
        // 检测平台和浏览器特性
        const isMobile = /iPhone|iPad|iPod|Android|webOS|BlackBerry|Windows Phone/i.test(navigator.userAgent);
        const isEdge = /Edg/i.test(navigator.userAgent);
        const isSafari = /Safari/i.test(navigator.userAgent) && !/Chrome/i.test(navigator.userAgent);
        const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
        const isWindowsEdge = isEdge && /Windows/i.test(navigator.userAgent);
        
        // Windows Edge特殊处理：防止重复识别结果
        if (isWindowsEdge && !isFinal) {
          // 检查是否与上次的中间结果相同或高度相似
          if (window._lastWindowsEdgeInterimText) {
            const similarity = calculateTextSimilarity(incoming, window._lastWindowsEdgeInterimText);
            if (similarity > 0.8) {
              debugLog('Windows Edge检测到高度相似的中间结果，跳过:', incoming);
              return; // 跳过高度相似的中间结果
            }
          }
          window._lastWindowsEdgeInterimText = incoming;
        }
        
        // 全平台应用去重策略
        let processedText = removeRepeatedWords(incoming);
        debugLog('去重后文本:', processedText);
        
        // Windows Edge额外检查：避免与之前的累积文本重复
        if (isWindowsEdge && sttAccumText && processedText) {
          const accumulatedSimilarity = calculateTextSimilarity(processedText, sttAccumText);
          if (accumulatedSimilarity > 0.9 && !isFinal) {
            debugLog('Windows Edge检测到与累积文本高度重复，跳过:', processedText);
            return;
          }
        }
        
        // 如果是最终结果
        if (isFinal) {
          // 最终结果：使用去重后的文本，不累加
          sttAccumText = processedText;
          debugLog('最终结果，直接使用:', sttAccumText);
        } 
        // Windows Edge使用特殊策略：更保守的文本更新
        else if (isWindowsEdge) {
          if (isFinal) {
            // 最终结果：直接使用，但要与之前的最终结果去重
            if (window._lastWindowsEdgeFinalText !== processedText) {
              sttAccumText = processedText;
              window._lastWindowsEdgeFinalText = processedText;
              debugLog('Windows Edge最终结果:', sttAccumText);
            } else {
              debugLog('Windows Edge跳过重复的最终结果');
              return;
            }
          } else {
            // 中间结果：只有在明显更长或更完整时才更新
            if (!sttAccumText || (processedText.length > sttAccumText.length + 3)) {
              sttAccumText = processedText;
              debugLog('Windows Edge中间结果更新:', sttAccumText);
            } else {
              debugLog('Windows Edge保持当前中间结果不变');
              return; // 不更新输入框
            }
          }
        }
        // 移动设备或Safari使用保守策略
        else if (isMobile || isSafari) {
          if (!sttAccumText) {
            sttAccumText = processedText;
          } else {
            // 检查新文本是否比当前文本更长且包含当前文本
            if (processedText.length > sttAccumText.length && processedText.includes(sttAccumText)) {
              sttAccumText = processedText;
            } else if (processedText.length > sttAccumText.length) {
              // 如果新文本更长但不包含当前文本，可能是新的识别结果
              sttAccumText = processedText;
            }
            // 否则保持当前文本不变
          }
          debugLog('移动设备/Safari处理后:', sttAccumText);
        }
        // 桌面浏览器的中间结果处理
        else {
          if (!sttAccumText) {
            sttAccumText = processedText;
          } else if (processedText.startsWith(sttAccumText)) {
            // 新文本包含当前文本，是累积结果
            sttAccumText = processedText;
          } else if (sttAccumText.includes(processedText)) {
            // 当前文本已包含新文本，可能是重复，保持不变
            debugLog('当前文本已包含新文本，保持不变');
          } else if (processedText.length > sttAccumText.length) {
            // 新文本更长，可能是更完整的识别结果
            sttAccumText = processedText;
          } else {
            // 增量拼接（谨慎使用）
            const combined = sttAccumText + ' ' + processedText;
            const cleanCombined = removeRepeatedWords(combined);
            
            // 只有在合并后的文本明显更有意义时才使用
            if (cleanCombined.length > Math.max(sttAccumText.length, processedText.length)) {
              sttAccumText = cleanCombined;
            }
          }
          debugLog('桌面浏览器处理后:', sttAccumText);
        }
        
        // 最终清理：再次去重以防万一
        sttAccumText = removeRepeatedWords(sttAccumText);
        
        // 更新输入框
        if (input) {
          const newValue = (sttBaseText || '') + (sttBaseText && sttAccumText ? ' ' : '') + sttAccumText;
          debugLog('更新输入框:', newValue);
          input.value = newValue;
          try { 
            input.focus(); 
            input.selectionStart = input.selectionEnd = input.value.length; 
          } catch(e) {
            debugLog('设置光标位置失败:', e);
          }
        }
      } catch (e) {
        console.error('处理语音识别文本时出错:', e);
      }
    }
    
    // 原生 Web Speech 实现
    const startNativeSTT = () => {
      try {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
          console.error("SpeechRecognition API不可用");
          return null;
        }
        
        debugLog('创建语音识别实例');
        const rec = new SR();
        
        // 根据平台和浏览器调整设置
        const isMacEdge = isEdge && /Mac|iPhone|iPad|iPod/.test(navigator.platform);
        
        // Mac Edge特殊处理：使用更激进的语言回退策略
        if (isMacEdge) {
          debugLog('Mac Edge使用特殊语言回退策略');
          
          // Mac Edge的语言回退序列：系统默认 -> 英语 -> 不设置语言
          const macEdgeLanguages = [null, 'en-US', 'en'];
          let langIndex = 0;
          
          const tryMacEdgeLanguage = () => {
            if (langIndex >= macEdgeLanguages.length) {
              console.error('[ChatWidget] Mac Edge所有语言都不支持');
              console.warn('Mac上的Edge浏览器不支持语音识别。建议使用Chrome浏览器。');
              return null;
            }
            
            try {
              const newRec = new SR();
              const lang = macEdgeLanguages[langIndex];
              
              if (lang) {
                newRec.lang = lang;
                debugLog(`Mac Edge尝试语言: ${lang}`);
              } else {
                debugLog('Mac Edge使用系统默认语言');
              }
              
              // 使用最保守的设置
              newRec.interimResults = false;
              newRec.continuous = false;
              newRec.maxAlternatives = 1;
              
              newRec.onstart = rec.onstart;
              newRec.onresult = rec.onresult;
              newRec.onend = rec.onend;
              
              newRec.onerror = function(event) {
                debugLog(`Mac Edge语言 ${lang || '系统默认'} 失败:`, event.error);
                
                if (event.error === 'language-not-supported') {
                  langIndex++;
                  debugLog(`Mac Edge尝试下一个语言，索引: ${langIndex}`);
                  setTimeout(() => {
                    const nextRec = tryMacEdgeLanguage();
                    if (nextRec) {
                      sttController = nextRec;
                    }
                  }, 100);
                  return;
                }
                
                // 其他错误使用原始处理
                if (rec.onerror) {
                  rec.onerror.call(this, event);
                }
              };
              
              newRec.start();
              return newRec;
            } catch (e) {
              console.error(`Mac Edge语言 ${macEdgeLanguages[langIndex]} 启动失败:`, e);
              langIndex++;
              return tryMacEdgeLanguage();
            }
          };
          
          // 直接返回Mac Edge的特殊处理结果
          return tryMacEdgeLanguage();
        }
        
        // 其他浏览器的智能语言设置
        const tryLanguages = ['zh-CN', 'zh', 'en-US', null]; // null表示使用系统默认
        let currentLangIndex = 0;
        
        const setLanguageWithFallback = () => {
          if (currentLangIndex < tryLanguages.length) {
            const lang = tryLanguages[currentLangIndex];
            if (lang) {
              rec.lang = lang;
              debugLog(`尝试使用语言: ${lang}`);
            } else {
              // 不设置语言，使用系统默认
              debugLog('使用系统默认语言');
            }
          }
        };
        
        // 初始设置语言
        if (isSafari) {
          // Safari优先尝试系统默认语言
          currentLangIndex = 3; // 直接使用系统默认
          debugLog('Safari使用系统默认语言');
        } else {
          // 其他浏览器优先尝试中文
          currentLangIndex = 0;
        }
        
        setLanguageWithFallback();
        
        // 语言不支持时的回退处理
        const originalOnError = rec.onerror;
        rec.onerror = function(event) {
          if (event.error === 'language-not-supported' && currentLangIndex < tryLanguages.length - 1) {
            debugLog(`语言 ${tryLanguages[currentLangIndex]} 不支持，尝试下一个`);
            currentLangIndex++;
            
            try {
              // 创建新的识别器
              const newRec = new SR();
              setLanguageWithFallback();
              
              // 复制设置
              newRec.interimResults = rec.interimResults;
              newRec.continuous = rec.continuous;
              newRec.maxAlternatives = rec.maxAlternatives;
              
              // 复制事件处理器
              newRec.onresult = rec.onresult;
              newRec.onend = rec.onend;
              newRec.onstart = rec.onstart;
              newRec.onerror = rec.onerror; // 递归回退
              
              // 启动新的识别器
              newRec.start();
              return; // 阻止原始错误处理
            } catch (e) {
              console.error('语言回退失败:', e);
            }
          }
          
          // 调用原始错误处理或默认处理
          if (originalOnError) {
            originalOnError.call(this, event);
          } else {
            console.error('[ChatWidget] 语音识别错误:', event);
          }
        };
        
        const isWindowsEdge = isEdge && /Windows/i.test(navigator.userAgent);
        
        if (isMacEdge) {
          // Mac上的Edge浏览器特殊设置
          debugLog('使用Mac Edge特殊设置');
          rec.interimResults = true;  // 开启中间结果
          rec.continuous = false;     // 关闭连续识别
          rec.maxAlternatives = 1;    // 限制替代结果数量
        } else if (isWindowsEdge) {
          // Windows Edge浏览器使用最严格的设置
          debugLog('使用Windows Edge特殊设置');
          rec.interimResults = false; // 完全关闭中间结果，防止重复
          rec.continuous = false;     // 关闭连续识别
          rec.maxAlternatives = 1;    // 限制替代结果数量
          
          // Windows Edge特殊标记
          rec._isWindowsEdge = true;
        } else if (isEdge) {
          // 其他Edge浏览器使用保守设置
          debugLog('使用Edge浏览器设置');
          rec.interimResults = false; // 关闭中间结果，只返回最终结果
          rec.continuous = false;     // 关闭连续识别
          rec.maxAlternatives = 1;    // 限制替代结果数量
        } else if (isMac || isSafari) {
          // Mac平台或Safari上使用保守设置
          debugLog('使用Mac/Safari设置');
          rec.interimResults = true;  // 开启中间结果，但处理方式不同
          rec.continuous = false;     // 关闭连续识别，避免Safari兼容性问题
        } else {
          // 其他平台使用标准设置
          debugLog('使用标准设置');
          rec.interimResults = true;
          rec.continuous = true;
        }
      
        rec.onstart = () => { 
          debugLog('语音识别已启动');
          micBtn.textContent = '🛑'; 
          micBtn.classList.add('cb-mic-on'); 
          // 记录基线与累计文本
          sttBaseText = input.value; 
          sttAccumText = '';
        };
        
        rec.onend = () => { 
          debugLog('语音识别已结束');
          micBtn.textContent = '🎤'; 
          micBtn.classList.remove('cb-mic-on'); 
          sttController = null; 
          
          // Mac平台上可能需要手动重新启动识别
          if ((isMac || isMacEdge) && rec._macAutoRestart) {
            debugLog('尝试重新启动Mac上的语音识别');
            setTimeout(() => {
              try { 
                rec.start(); 
                debugLog('Mac上的语音识别重新启动成功');
              } catch(e) { 
                console.error("重新启动识别失败:", e);
                rec._macAutoRestart = false; 
              }
            }, 300);
          }
        };
        
        rec.onerror = (err) => {
          console.error("[ChatWidget] 语音识别错误:", err);
          debugLog('语音识别错误:', err);
          
          const reason = err?.error || '';
          
          // 如果是语言不支持错误，已经在上面的回退机制中处理了
          if (reason === 'language-not-supported') {
            return; // 让回退机制处理
          }
          
          micBtn.textContent = '🎤'; 
          micBtn.classList.remove('cb-mic-on'); 
          sttController = null;
          
          try {
            let msg = '语音识别出错';
            
            // 针对不同平台Edge浏览器的特殊错误处理
            const isMacEdge = isEdge && /Mac|iPhone|iPad|iPod/.test(navigator.platform);
            const isWindowsEdge = isEdge && /Windows/i.test(navigator.userAgent);
            
            if (isWindowsEdge) {
              debugLog('Windows Edge特殊错误处理:', reason);
              // Windows Edge浏览器特殊处理
              if (reason === 'not-allowed') {
                msg = 'Windows Edge需要麦克风权限。请点击地址栏左侧的锁图标，确保已允许使用麦克风。';
              } else if (reason === 'aborted' || reason === 'no-speech' || !reason) {
                // Windows Edge经常出现这些错误，尝试自动重启
                debugLog('尝试自动重启Windows Edge的语音识别');
                setTimeout(() => {
                  try {
                    if (!sttController) { // 确保没有其他识别在运行
                      const newCtrl = startNativeSTT();
                      if (newCtrl) {
                        sttController = newCtrl;
                        debugLog('Windows Edge语音识别重启成功');
                        return;
                      }
                    }
                  } catch(e) {
                    console.error('Windows Edge语音识别重启失败:', e);
                  }
                }, 300);
                return; // 不显示错误
              }
            } else if (isMacEdge) {
              debugLog('Mac Edge特殊错误处理:', reason);
              // Mac上的Edge浏览器特殊处理
              if (reason === 'not-allowed') {
                msg = 'Mac上的Edge浏览器需要麦克风权限。请点击地址栏左侧的锁图标，确保已允许使用麦克风。';
              } else if (reason === 'aborted' || !reason) {
                // 尝试自动重启
                debugLog('尝试自动重启Mac Edge的语音识别');
                setTimeout(() => {
                  try {
                    rec.start();
                    debugLog('Mac Edge语音识别重启成功');
                    return; // 不显示错误
                  } catch(e) {
                    console.error('Mac Edge语音识别重启失败:', e);
                  }
                }, 500);
                return; // 不显示错误
              }
            }
            // 针对Safari浏览器的特殊错误处理
            else if (isSafari) {
              debugLog('Safari特殊错误处理:', reason);
              if (reason === 'not-allowed') {
                msg = 'Safari需要麦克风权限。请在浏览器设置中允许此网站使用麦克风。';
              } else if (reason === 'aborted' || reason === 'no-speech') {
                // Safari经常报告这些"错误"，但实际上是正常的
                debugLog('Safari报告正常结束，不显示错误');
                return;
              }
            }
            // 针对Edge浏览器的特殊错误处理
            else if (isEdge && (reason === 'aborted' || reason === 'not-allowed' || !reason)) {
              // Edge浏览器可能会报告错误但实际上可以工作
              debugLog("Edge浏览器报告错误，但可能仍然可以工作");
              return; // 不显示错误消息，让用户继续尝试
            }
            
            if (reason === 'not-allowed') msg = '未授予麦克风权限，请允许浏览器使用麦克风。';
            else if (reason === 'audio-capture') msg = '未检测到麦克风设备，请检查设备连接。';
            else if (reason === 'no-speech') {
              msg = '未检测到语音，请靠近麦克风后重试。';
              // Mac和Safari上不报告no-speech错误，而是自动结束识别
              if (isMac || isSafari) return;
            }
            else if (reason === 'network') msg = '网络错误，请重试。';
            else if (reason === 'aborted') msg = '语音识别被中断，请重试。';
            else msg = `语音识别出错: ${reason || '未知错误'}`;
            
            // 平台特定提示
            if (isMacEdge) {
              msg += '\n\nMac上的Edge浏览器提示：\n1. 请确保已在系统偏好设置中允许浏览器访问麦克风\n2. 点击地址栏左侧的锁图标，确保已允许使用麦克风\n3. 如果问题持续，请尝试使用Chrome浏览器';
            } else if (isSafari) {
              msg += '\n\nSafari浏览器提示：\n1. 请确保已在系统偏好设置中允许浏览器访问麦克风\n2. 在Safari偏好设置 > 网站 > 麦克风中允许此网站\n3. 如果问题持续，请尝试使用Chrome浏览器';
            } else if (isMac) {
              msg += '\n\nMac用户提示：\n1. 请确保已在系统偏好设置中允许浏览器访问麦克风\n2. 尝试使用Chrome浏览器\n3. 如果使用Safari，请确保已启用"开发"菜单并允许媒体捕获';
            } else if (isEdge) {
              msg += '\n\nEdge浏览器提示：\n1. 请确保已授予麦克风权限\n2. 尝试刷新页面后重试\n3. 如果问题持续，请尝试使用Chrome浏览器';
            }
            
            if (!isSecure) {
              msg += '\n提示：浏览器通常要求 https 或 http://localhost 才能使用语音功能。';
            }
            
            console.error("[ChatWidget] " + msg);
            debugLog('显示语音识别错误:', msg);
            // 使用console.warn代替alert，避免强制性弹窗
            console.warn('[ChatWidget] 语音识别错误:', msg);
            
            // 确保释放麦克风资源
            releaseMicrophoneIfActive();
          } catch (e) {
            console.error("[ChatWidget] 处理语音识别错误时出错:", e);
          }
        };
        
        rec.onresult = (e) => {
          debugLog('收到语音识别结果:', e.results);
          // 处理识别结果，区分中间结果和最终结果
          let finalText = '';
          let interimText = '';
          
          for (let i = 0; i < e.results.length; i++) {
            const result = e.results[i];
            if (result.isFinal) {
              finalText += result[0].transcript;
              debugLog('最终结果:', result[0].transcript, '置信度:', result[0].confidence);
            } else {
              interimText += result[0].transcript;
              debugLog('中间结果:', result[0].transcript);
            }
          }
          
          // 优先处理最终结果
          if (finalText) {
            sttMergeUpdate(finalText, true);
          } else if (interimText) {
            sttMergeUpdate(interimText, false);
          }
          
          // Mac平台上，每次获取结果后可能需要重新启动识别
          if ((isMac || (isEdge && isMac)) && !rec.continuous) {
            rec._macAutoRestart = true;
          }
        };
        
        try {
          debugLog('尝试启动语音识别');
          rec.start();
          debugLog('语音识别启动成功');
        } catch (e) {
          console.error("语音识别启动失败:", e);
          debugLog('语音识别启动失败:', e);
          
          // Mac上的Edge浏览器特殊处理
          if (isEdge && isMac) {
            console.warn('[ChatWidget] Mac上的Edge浏览器可能需要特殊设置才能使用语音识别。建议使用Chrome浏览器。');
          } else {
            console.warn('[ChatWidget] 语音识别启动失败。在Mac上，请尝试使用Chrome浏览器并确保已授予麦克风权限。');
          }
          return null;
        }
        
        return { 
          stop: () => {
            debugLog('停止语音识别');
            rec._macAutoRestart = false;
            try { rec.stop(); } catch(e) {
              console.error("停止语音识别失败:", e);
              debugLog('停止语音识别失败:', e);
            }
          } 
        };
      } catch (e) {
        console.error("创建语音识别实例失败:", e);
        debugLog('创建语音识别实例失败:', e);
        return null;
      }
    };
    
    micBtn.addEventListener('click', async () => {
      // 如果已经在进行语音识别，则停止
      if (sttController) {
        debugLog('停止当前语音识别');
        releaseMicrophoneIfActive();
        return;
      }
      
      // 非安全环境拦截：除 localhost/127.0.0.1 外，必须在 https 环境下才可使用
      if (!isSecure) {
        console.warn('[ChatWidget] 当前为非安全环境（' + location.origin + '）。语音识别需要 https 或 http://localhost 访问。');
        return;
      }
      
      // 请求麦克风权限
      try {
        debugLog('请求麦克风权限');
        if (!micStream && navigator.mediaDevices?.getUserMedia) {
          micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          debugLog('麦克风权限获取成功');
        }
      } catch (e) {
        console.error("获取麦克风权限失败:", e);
        debugLog('获取麦克风权限失败:', e);
        
        // Mac上的Edge浏览器特殊处理
        if (isEdge && isMac) {
          console.warn('[ChatWidget] Mac上的Edge浏览器可能需要特殊设置才能访问麦克风。建议使用Chrome浏览器。');
        } else {
          console.warn('[ChatWidget] 无法访问麦克风。请确保已授予浏览器麦克风权限，并且没有其他应用正在使用麦克风。');
        }
        return;
      }
      
      // 记录基线文本，避免识别中覆盖原有内容
      sttBaseText = input.value; 
      sttAccumText = '';
      
      // 尝试使用AIUtils或原生Web Speech API
      let ctrl = null;
      if (hasAIUtils) {
        debugLog('尝试使用AIUtils.startSTT');
        ctrl = AIUtils.startSTT({
          lang: 'zh-CN',
          interimResults: true,
          continuous: true,
          onStart: () => { 
            debugLog('AIUtils语音识别已启动');
            micBtn.textContent = '🛑'; 
            micBtn.classList.add('cb-mic-on'); 
          },
          onEnd: () => { 
            debugLog('AIUtils语音识别已结束');
            micBtn.textContent = '🎤'; 
            micBtn.classList.remove('cb-mic-on'); 
            sttController = null; 
          },
          onResult: (txt, isFinal) => { 
            debugLog('AIUtils语音识别结果:', txt, isFinal);
            sttMergeUpdate(txt, isFinal); 
          },
          onError: (err) => {
            debugLog('AIUtils语音识别错误:', err);
            micBtn.textContent = '🎤';
            micBtn.classList.remove('cb-mic-on');
            sttController = null;
            
            try {
              const reason = err?.error || '';
              let msg = '语音识别出错';
              if (reason === 'not-allowed') msg = '未授予麦克风权限，请允许浏览器使用麦克风。';
              else if (reason === 'audio-capture') msg = '未检测到麦克风设备，请检查设备连接。';
              else if (reason === 'no-speech') msg = '未检测到语音，请靠近麦克风后重试。';
              else if (reason === 'network') msg = '网络错误，请重试。';
              
              if (!isSecure) {
                msg += '\n提示：浏览器通常要求 https 或 http://localhost 才能使用语音功能。';
              }
              
              console.warn('[ChatWidget] AIUtils语音识别错误:', msg);
              
              // 确保释放麦克风资源
              releaseMicrophoneIfActive();
            } catch (e) {
              console.error("处理语音识别错误时出错:", e);
            }
          }
        });
      }
      
      // 如果AIUtils不可用或启动失败，尝试使用原生Web Speech API
      if (!ctrl) {
        debugLog('AIUtils不可用或启动失败，尝试使用原生Web Speech API');
        ctrl = startNativeSTT();
      }
      
      // 如果两种方法都失败，提示用户
      if (!ctrl) {
        debugLog('两种语音识别方法都失败');
        
        // Mac上的Edge浏览器特殊处理
        if (isEdge && isMac) {
          console.warn('[ChatWidget] Mac上的Edge浏览器可能不支持语音识别。建议使用Chrome浏览器。');
        } else {
          console.warn('[ChatWidget] 此浏览器未提供语音识别接口。请使用桌面版 Chrome，并通过 https 或 http://localhost 访问。');
        }
        return;
      }
      
      // 保存控制器引用
      debugLog('语音识别控制器已保存');
      sttController = ctrl;
    });
  }

  function init(options = {}) {
    if (mounted) return;
    const opts = Object.assign({}, defaultOptions, options);

    if (opts.requireLogin) {
      const bodyAuth = document.body && document.body.getAttribute('data-ai-auth');
      if (bodyAuth === '1' || bodyAuth === 'true') {
        opts.authenticated = true;
      } else if (bodyAuth === '0' || bodyAuth === 'false') {
        opts.authenticated = false;
      } else if (typeof opts.authenticated !== 'boolean') {
        opts.authenticated = null;
      }
    }

    client = new AIClient.DeepseekClient({
      apiKey: opts.apiKey || undefined,
      endpoint: opts.endpoint || undefined,
      model: opts.model || undefined,
      system: opts.systemPrompt || defaultOptions.systemPrompt,
      context: opts.context || undefined
    });

    mountUI(opts);
    // 首条自动问候（仅在面板已打开且允许播报时朗读）
    const greet = (opts.greeting || defaultOptions.greeting);
    // 记录 opts 以便 send() 访问 contextProvider
    client.options = { contextProvider: opts.contextProvider || null };
    if (greet) {
      addMessage('assistant', greet);
      if (autoTTS && isPanelOpen()) {
        try { AIUtils.speak(greet, { lang: 'zh-CN', rate: 1 }); } catch(e) {}
      }
    }
    mounted = true;
  }

  function suggest(text, payload) {
    try {
      const now = Date.now();
      const COOLDOWN = 3000; // 3s 冷却
      const DEDUP_MS = 20000; // 20s 内相同文案不重复
      // 若已有提示在显示或处于冷却期，或短期内相同文本，则忽略
      if ((suggestToast && document.body.contains(suggestToast)) ||
          (now - lastSuggestAt < COOLDOWN) ||
          (text && text === lastSuggestText && now - lastSuggestAt < DEDUP_MS)) {
        return;
      }

      lastSuggestAt = now;
      lastSuggestText = String(text || '');

      const toast = document.createElement('div');
      suggestToast = toast;
      // 无论面板是否打开，toast 永远挂在页面右下角（面板的 z-index 更高，不会被遮挡）
      const container = document.body;
      toast.className = 'cb-toast';
      toast.innerHTML = renderMarkdown(text) + ' <button class="btn secondary" style="padding:2px 6px;">填入</button> <button class="btn secondary" style="padding:2px 6px;">关闭</button>';
      container.appendChild(toast);
      requestAnimationFrame(()=> toast.classList.add('show'));
      const btns = toast.querySelectorAll('button');
      const btn = btns[0];
      const closeBtn = btns[1];

      function dispatchInputEvents(el) {
        try { el.dispatchEvent(new Event('input', { bubbles: true })); } catch(_) {}
        try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch(_) {}
      }
      function defaultFill(obj) {
        if (!obj || typeof obj !== 'object') return false;
        let ok = false;
        Object.keys(obj).forEach((key) => {
          const spec = obj[key];
          const control = document.getElementById(key) || document.querySelector(`[name=\"${key}\"]`);
          if (!control) return;
          let nextVal;
          if (spec && typeof spec === 'object' && Object.prototype.hasOwnProperty.call(spec, 'delta')) {
            const base = parseFloat(control.value);
            const delta = parseFloat(spec.delta) || 0;
            if (!isNaN(base)) nextVal = base + delta;
          } else if (spec && typeof spec === 'object' && Object.prototype.hasOwnProperty.call(spec, 'value')) {
            nextVal = spec.value;
          } else {
            nextVal = spec;
          }
          if (typeof nextVal === 'number' && !isNaN(nextVal)) {
            control.value = String(nextVal);
            dispatchInputEvents(control);
            ok = true;
          } else if (typeof nextVal === 'string') {
            control.value = nextVal;
            dispatchInputEvents(control);
            ok = true;
          } else if (typeof nextVal === 'boolean') {
            try { control.checked = !!nextVal; } catch(_) {}
            dispatchInputEvents(control);
            ok = true;
          }
        });
        return ok;
      }

      function handleExperimentSpecificFill(payload) {
        if (!payload) return false;
        
        // 检测当前页面类型
        const currentPage = window.location.pathname;
        
        // 双缝干涉实验特殊处理
        if (currentPage.includes('double_slit') || document.getElementById('slitWidth')) {
          return handleDoubleslitFill(payload);
        }
        
        // 其他实验可以在这里添加
        
        return false;
      }

      function handleDoubleslitFill(payload) {
        try {
          // 双缝干涉实验的参数映射
          const parameterMap = {
            // 缝宽相关
            'slitWidthN': ['slitWidth', 'slitWidthN'],
            'slitWidth': ['slitWidth', 'slitWidthN'],
            // 双缝间距相关
            'slitDistanceN': ['slitDistance', 'slitDistanceN'],
            'slitDistance': ['slitDistance', 'slitDistanceN'],
            // 波长相关
            'wavelengthN': ['wavelength', 'wavelengthN'],
            'wavelength': ['wavelength', 'wavelengthN'],
            // 屏幕距离相关
            'screenDistanceN': ['screenDistance', 'screenDistanceN'],
            'screenDistance': ['screenDistance', 'screenDistanceN']
          };

          let filled = false;
          
          Object.keys(payload).forEach(key => {
            const value = payload[key];
            const targetIds = parameterMap[key];
            
            if (targetIds) {
              targetIds.forEach(targetId => {
                const control = document.getElementById(targetId);
                if (control) {
                  let newValue;
                  if (value && typeof value === 'object' && value.hasOwnProperty('value')) {
                    newValue = value.value;
                  } else {
                    newValue = value;
                  }
                  
                  if (typeof newValue === 'number' && !isNaN(newValue)) {
                    control.value = String(newValue);
                    dispatchInputEvents(control);
                    filled = true;
                  }
                }
              });
            }
          });

          return filled;
        } catch (e) {
          console.error('双缝干涉参数填入错误:', e);
          return false;
        }
      }

      btn.addEventListener('click', ()=> {
        try {
          let handled = false;
          
          // 首先尝试页面自定义的填入函数
          if (typeof window.onChatWidgetFill === 'function') {
            window.onChatWidgetFill(payload || {});
            handled = true;
          } 
          // 然后尝试通用的参数填入
          else if (payload && typeof payload === 'object') {
            handled = defaultFill(payload);
          }
          // 最后尝试实验特定的参数填入
          else {
            handled = handleExperimentSpecificFill(payload);
          }
          
          if (!handled) {
            console.warn('[ChatWidget] 此页面未实现参数填入或未提供可用参数。');
          }
        } catch (e) {
          console.error('参数填入错误:', e);
          console.warn('[ChatWidget] 参数填入失败，请手动调整。');
        }
        toast.classList.remove('show');
        setTimeout(()=> { if (suggestToast === toast) suggestToast = null; toast.remove(); }, 200);
      });

      closeBtn.addEventListener('click', ()=> {
        toast.classList.remove('show');
        setTimeout(()=> { if (suggestToast === toast) suggestToast = null; toast.remove(); }, 200);
      });

      setTimeout(()=> {
        toast.classList.remove('show');
        setTimeout(()=> { if (suggestToast === toast) suggestToast = null; toast.remove(); }, 200);
      }, 5000);
    } catch (_) {}
  }

  window.ChatWidget = { init, suggest };
})();
