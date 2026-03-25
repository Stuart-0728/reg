/**
 * 智能社团+ - AI聊天助手
 * 
 * 实现功能：
 * 1. 聊天历史记录的数据库存储和加载
 * 2. 页面间保持聊天记录
 * 3. 会话管理
 * 4. Markdown 格式支持
 */

// 配置参数
const AI_CHAT_CONFIG = {
    cookiePrefix: 'cqnu_ai_chat_',
    maxStoredMessages: 50,  // 最大存储消息数
    cookieExpireDays: 7,    // Cookie保存天数
    initialBotMessage: '您好，欢迎来到智能社团+平台，我是基于DeepSeek大语言模型的智能助手，有什么可以帮助您的吗？',
    notLoggedInMessage: '您好！AI助手功能需要登录后使用。请先<a href="/auth/login" class="ai-chat-link">登录</a>或<a href="/auth/register" class="ai-chat-link">注册</a>。'
};

// 智能助手信息
const ASSOCIATION_INFO = {
    name: 'DeepSeek AI智能助手',
    description: '基于DeepSeek大语言模型的智能聊天助手，为智能社团+平台提供智能服务',
    model: 'deepseek-r1-distill-qwen-7b-250120',
    capabilities: [
        '回答关于活动的问题',
        '推荐适合您兴趣的活动',
        '提供活动参与和报名流程指导',
        '分析参与历史和积分情况',
        '提供平台使用帮助'
    ],
    contactInfo: {
        address: '重庆市沙坪坝区大学城中路37号',
        qqGroup: '995213034',
        adminEmail: '2023051101095@stu.cqnu.edu.cn',
        website: 'http://reg.cqaibase.cn'
    },
    features: [
        '实时对话', '历史记录保存', '个性化推荐', '多轮交互', '上下文理解'
    ],
    disclaimer: '本助手基于人工智能技术，回答可能并非完全准确，如有疑问请联系管理员'
};

// Marked 库动态加载（多CDN + 超时 + 本地降级）
function buildFallbackMarked() {
    return {
        parse: function (input) {
            const text = String(input || '');
            const escaped = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
            return escaped
                .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                .replace(/\*([^*]+)\*/g, '<em>$1</em>')
                .replace(/`([^`]+)`/g, '<code>$1</code>')
                .replace(/\n/g, '<br>');
        }
    };
}

function loadScriptWithTimeout(src, timeoutMs = 5000) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        let done = false;

        const timer = setTimeout(() => {
            if (done) return;
            done = true;
            script.remove();
            reject(new Error(`Timeout loading script: ${src}`));
        }, timeoutMs);

        script.src = src;
        script.async = true;
        script.onload = () => {
            if (done) return;
            done = true;
            clearTimeout(timer);
            resolve();
        };
        script.onerror = () => {
            if (done) return;
            done = true;
            clearTimeout(timer);
            reject(new Error(`Failed loading script: ${src}`));
        };

        document.head.appendChild(script);
    });
}

function loadMarkedLibrary() {
    return new Promise(async (resolve) => {
        if (window.marked && typeof window.marked.parse === 'function') {
            resolve(window.marked);
            return;
        }

        const sources = [
            'https://cdn.jsdelivr.net/npm/marked/marked.min.js',
            'https://unpkg.com/marked/marked.min.js',
            'https://lf9-cdn-tos.bytecdntp.com/cdn/expire-1-M/marked/12.0.2/marked.min.js',
            'https://cdn.bootcdn.net/ajax/libs/marked/12.0.2/marked.min.js'
        ];

        for (const src of sources) {
            try {
                await loadScriptWithTimeout(src, 2500);
                if (window.marked && typeof window.marked.parse === 'function') {
                    resolve(window.marked);
                    return;
                }
            } catch (_) {
                // 尝试下一个源
            }
        }

        const fallback = buildFallbackMarked();
        window.marked = fallback;
        resolve(fallback);
    });
}

// 会话管理
class AIChatSession {
    constructor() {
        this.sessionId = this.getOrCreateSessionId();
        this.messages = [];
        this.isOpen = false;
        // 历史记录加载在UI初始化阶段按登录态执行，避免未登录时额外请求
    }

    // 获取或创建会话ID
    getOrCreateSessionId() {
        let sessionId = this.getCookie('session_id');
        if (!sessionId) {
            sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 15);
            this.setCookie('session_id', sessionId, AI_CHAT_CONFIG.cookieExpireDays);
        }
        return sessionId;
    }

    // 获取CSRF令牌
    getCsrfToken() {
        // 优先从当前页面DOM读取，避免使用到旧cookie中的过期token
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        if (metaToken) {
            return metaToken.getAttribute('content');
        }

        // 尝试从页面中的隐藏输入字段获取
        const csrfInput = document.querySelector('input[name="csrf_token"]');
        if (csrfInput) {
            return csrfInput.value;
        }

        // 兜底：从cookie中获取CSRF令牌
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === '_csrf_token' || name === 'csrf_token') {
                return decodeURIComponent(value || '');
            }
        }

        // 如果仍然没有找到，返回空字符串
        return '';
    }

    // 添加消息
    addMessage(content, role) {
        const message = {
            role: role,
            content: content,
            timestamp: new Date().toISOString()
        };
        
        this.messages.push(message);
        
        // 如果消息超过最大存储数，删除最早的消息
        if (this.messages.length > AI_CHAT_CONFIG.maxStoredMessages) {
            this.messages = this.messages.slice(this.messages.length - AI_CHAT_CONFIG.maxStoredMessages);
        }
        
        return message;
    }

    // 清除所有消息
    clearMessages() {
        this.messages = [];
        // 调用后端API清除历史记录
        fetch(`/utils/ai_chat/clear?session_id=${this.sessionId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            }
        })
        .catch(error => console.error('清除历史记录失败:', error));
    }
    
    // 清除所有会话历史
    clearAllHistory() {
        console.log("开始清除所有历史记录");
        
        // 获取CSRF令牌
        const csrfToken = this.getCsrfToken();
        console.log("当前CSRF令牌:", csrfToken);
        
        if (!csrfToken) {
            console.error("无法获取CSRF令牌");
            alert("无法获取安全令牌，请刷新页面后重试");
            return;
        }
        
        // 显示加载提示
        const originalButtonText = document.querySelector('.clear-history-btn') ? 
                                  document.querySelector('.clear-history-btn').innerHTML : 
                                  "清除历史";
        if (document.querySelector('.clear-history-btn')) {
            document.querySelector('.clear-history-btn').innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 处理中...';
            document.querySelector('.clear-history-btn').disabled = true;
        }
        
        // 发送清除所有历史的请求到后端
        fetch('/utils/ai_chat/clear_history', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify({
                    csrf_token: csrfToken,
                session_id: this.sessionId
            }),
            credentials: 'same-origin' // 确保包含Cookie
        })
        .then(response => {
            console.log("响应状态:", response.status, response.statusText);
            if (!response.ok) {
                return response.text().then(text => {
                    console.error("响应详情:", text);
                    throw new Error(`清除历史记录失败 (${response.status}): ${text.substring(0, 100)}`);
                });
            }
            return response.json();
        })
        .then(data => {
            console.log('清除所有历史记录成功:', data);
            // 清除本地消息
            this.messages = [];
            // 清除cookie中的消息
            this.deleteCookie('messages');
            alert('历史记录已清除！');
        })
        .catch(error => {
            console.error('清除所有历史记录失败:', error);
            alert('清除历史记录失败: ' + error.message);
            
            // 如果API失败，尝试直接清除前端消息
            try {
                this.messages = [];
                // 清除cookie中的消息
                this.deleteCookie('messages');
                console.log("已强制清除前端消息");
            } catch (e) {
                console.error("前端清除也失败:", e);
            }
        })
        .finally(() => {
            // 恢复按钮状态
            if (document.querySelector('.clear-history-btn')) {
                document.querySelector('.clear-history-btn').innerHTML = originalButtonText;
                document.querySelector('.clear-history-btn').disabled = false;
            }
        });
    }
    
    // 获取所有消息
    getMessages() {
        return this.messages;
    }
    
    // 从后端加载消息历史
    loadMessagesFromServer() {
        // 检查用户是否已登录
        const isLoggedIn = document.body.getAttribute('data-user-logged-in') === 'true';
        if (!isLoggedIn) {
            console.log("用户未登录，跳过加载历史记录");
            return Promise.resolve([]); // 返回空数组
        }
        
        // 从服务器加载消息
        return fetch(`/utils/ai_chat/history?session_id=${this.sessionId}`)
            .then(response => {
                if (response.redirected) {
                    console.log("检测到重定向，可能是未登录状态");
                    return []; // 返回空数组
                }
                if (!response.ok) {
                    throw new Error(`加载历史记录失败 (${response.status})`);
                }
                return response.json();
            })
            .then(data => {
                console.log('从服务器加载的消息:', data);
                if (!data) {
                    return [];
                }

                if (Array.isArray(data.messages)) {
                    return data.messages;
                }

                if (Array.isArray(data.data)) {
                    return data.data;
                }

                return [];
            })
            .catch(error => {
                console.error('加载历史记录出错:', error);
                return []; // 出错时返回空数组
            });
    }
    
    // 从Cookie加载消息（作为备用方案）
    loadMessagesFromCookie() {
        const messagesJson = this.getCookie('messages');
        return messagesJson ? JSON.parse(messagesJson) : null;
    }
    
    // 保存消息到Cookie（作为备用方案）
    saveMessagesToCookie() {
        const messagesJson = JSON.stringify(this.messages);
        this.setCookie('messages', messagesJson, AI_CHAT_CONFIG.cookieExpireDays);
    }
    
    // 设置Cookie
    setCookie(name, value, days) {
        let expires = '';
        if (days) {
            const date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = '; expires=' + date.toUTCString();
        }
        document.cookie = AI_CHAT_CONFIG.cookiePrefix + name + '=' + encodeURIComponent(value) + expires + '; path=/';
    }
    
    // 获取Cookie
    getCookie(name) {
        const nameEQ = AI_CHAT_CONFIG.cookiePrefix + name + '=';
        const ca = document.cookie.split(';');
        for (let i = 0; i < ca.length; i++) {
            let c = ca[i];
            while (c.charAt(0) === ' ') c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) === 0) 
                return decodeURIComponent(c.substring(nameEQ.length, c.length));
        }
        return null;
    }
    
    // 删除Cookie
    deleteCookie(name) {
        this.setCookie(name, '', -1);
    }
}

// AI聊天UI管理
class AIChatUI {
    constructor(session) {
        this.session = session;
        this.isOpen = false;
        this.isProcessing = false;
        this.historyLoaded = false;
        this.historyLoading = false;
        this.container = null;
        this.messagesContainer = null;
        this.inputField = null;
        this.sendButton = null;
        this.stopButton = null;
        this.activeStream = null;
    }
    
    initialize() {
        // 检查用户是否已登录
        const isLoggedIn = document.body.getAttribute('data-user-logged-in') === 'true';
        
        // 创建聊天界面
        this.createChatUI();
        
        // 设置事件监听器
        this.setupEventListeners();
        
        // 未登录用户直接显示初始消息；登录用户延迟到“首次打开聊天窗口”再加载历史，降低首屏阻塞。
        if (!isLoggedIn) {
            // 未登录用户显示初始消息
            this.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
            this.historyLoaded = true;
            return;
        }

        if (this.container && this.container.classList.contains('visible')) {
            this.ensureHistoryLoaded();
        } else {
            this.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
        }

        this.ensureWelcomeMessageVisible();
    }

    ensureWelcomeMessageVisible() {
        const currentMessages = this.session.getMessages();
        const hasMessages = Array.isArray(currentMessages) && currentMessages.length > 0;
        const hasUiMessages = this.messagesContainer && this.messagesContainer.children.length > 0;

        if (!hasMessages && !hasUiMessages) {
            this.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
        }
    }

    ensureHistoryLoaded() {
        if (this.historyLoaded || this.historyLoading) {
            return;
        }

        const isLoggedIn = document.body.getAttribute('data-user-logged-in') === 'true';
        if (!isLoggedIn) {
            this.historyLoaded = true;
            return;
        }

        this.historyLoading = true;
        this.session.loadMessagesFromServer()
            .then(messages => {
                if (messages && messages.length > 0) {
                    this.session.messages = messages;
                    this.refreshMessages();
                } else {
                    this.ensureWelcomeMessageVisible();
                }
            })
            .catch(error => {
                console.error('加载历史消息失败:', error);
                this.ensureWelcomeMessageVisible();
            })
            .finally(() => {
                this.historyLoaded = true;
                this.historyLoading = false;
                this.ensureWelcomeMessageVisible();
            });
    }
    
    // 刷新消息显示
    refreshMessages() {
        // 清空消息区域
        this.clearMessagesUI();
        
        // 加载消息
        const messages = this.session.getMessages();
        messages.forEach(msg => {
            this.addMessageToUI(msg.content, msg.role === 'user' ? 'user' : 'bot');
        });
        
        // 滚动到最新消息
        this.scrollToBottom();
    }

    bindTapOrClick(element, handler) {
        if (!element || typeof handler !== 'function') {
            return;
        }

        let lastTouchTriggerAt = 0;
        const invoke = (e) => {
            e.preventDefault();
            e.stopPropagation();
            handler();
        };

        if (window.PointerEvent) {
            element.addEventListener('pointerup', (e) => {
                if (e.pointerType === 'touch' || e.pointerType === 'pen') {
                    lastTouchTriggerAt = Date.now();
                    invoke(e);
                }
            }, { passive: false });
        } else {
            element.addEventListener('touchend', (e) => {
                lastTouchTriggerAt = Date.now();
                invoke(e);
            }, { passive: false });
        }

        element.addEventListener('click', (e) => {
            if (Date.now() - lastTouchTriggerAt < 450) {
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            invoke(e);
        });
    }
    
    // 设置事件监听器
    setupEventListeners() {
        // 发送按钮点击事件
        if (this.sendButton) {
            this.bindTapOrClick(this.sendButton, () => {
                this.sendMessage();
            });
        }

        if (this.stopButton) {
            this.bindTapOrClick(this.stopButton, () => {
                this.stopStreaming('已停止生成。');
            });
        }
        
        // 输入框回车事件
        if (this.inputField) {
            this.inputField.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault(); // 防止默认的换行行为
                    this.sendMessage();
                }
            });
        }
        
        // 切换聊天窗口按钮事件
        if (this.toggleButton) {
            this.bindTapOrClick(this.toggleButton, () => {
                // 防止快速多次点击
                if (this.isToggling) return;
                this.toggleChat();
            });
        }
        
        // 添加关闭按钮事件监听
        const closeButton = document.getElementById('aiChatCloseBtn');
        if (closeButton) {
            this.bindTapOrClick(closeButton, () => {
                this.closeChat();
            });
        }
    }
    
    // 切换聊天窗口显示/隐藏
    toggleChat() {
        // 防抖处理
        if (this.isToggling) return;
        this.isToggling = true;
        
        if (this.container.style.display === 'none' || this.container.style.display === '') {
            this.openChat();
        } else {
            this.closeChat();
        }
        
        // 300ms后重置标志位，防止频繁切换
        setTimeout(() => {
            this.isToggling = false;
        }, 300);
    }
    
    // 打开聊天窗口
    openChat() {
        // 先设置display为flex，然后添加visible类触发过渡动画
        this.container.style.display = 'flex';
        // 等待浏览器渲染一帧后添加visible类，触发过渡效果
        setTimeout(() => {
            this.container.classList.add('visible');
        }, 10);
        
        this.session.isOpen = true;
        this.session.setCookie('chat_open', 'true', AI_CHAT_CONFIG.cookieExpireDays);
        this.ensureHistoryLoaded();
        
        // 滚动到最新消息
        setTimeout(() => {
            this.scrollToBottom();
        }, 100);
    }
    
    // 关闭聊天窗口
    closeChat() {
        // 先移除visible类触发过渡动画
        this.container.classList.remove('visible');
        // 等待过渡动画完成后隐藏元素
        setTimeout(() => {
            this.container.style.display = 'none';
        }, 300); // 与CSS过渡时间一致
        
        this.session.isOpen = false;
        this.session.setCookie('chat_open', 'false', AI_CHAT_CONFIG.cookieExpireDays);
    }
    
    // 发送消息
    sendMessage() {
        if (!this.inputField) return;
        
        const message = this.inputField.value.trim();
        if (!message) return;
        
        // 清空输入框
        this.inputField.value = '';
        
        // 添加用户消息到UI
        this.addMessageToUI(message, 'user');
        
        // 添加消息到会话
        this.session.addMessage(message, 'user');
        
        // 禁用输入和按钮
        this.disableInput(true);
        
        // 准备接收AI响应
        this.receiveAIResponse(message);
    }
    
    // 接收AI响应
    receiveAIResponse(userMessage) {
        this.stopStreaming();

        // 创建AI消息容器
        const aiMessageDiv = document.createElement('div');
        aiMessageDiv.className = 'ai-message bot';
        this.messagesContainer.appendChild(aiMessageDiv);
        
        // 滚动到底部
        this.scrollToBottom();
        
        // 显示加载指示器
        aiMessageDiv.innerHTML = '<span class="loading-indicator">AI思考中<span class="dot-animation">...</span></span>';
        
        // 检查用户是否已登录
        const isLoggedIn = document.body.getAttribute('data-user-logged-in') === 'true';
        
        if (!isLoggedIn) {
            // 如果未登录，显示登录提示信息
            aiMessageDiv.innerHTML = AI_CHAT_CONFIG.notLoggedInMessage;
            this.disableInput(false);
            return;
        }
        
        // 创建 EventSource 连接
        const role = 'student'; // 默认角色，可扩展
        const eventSource = new EventSource(`/utils/api/ai_chat?message=${encodeURIComponent(userMessage)}&role=${role}&session_id=${this.session.sessionId}`);
        
        // 超时控制：分“首包超时”和“流式空闲超时”两段，避免长回答被误判中断
        const FIRST_TOKEN_TIMEOUT_MS = 120000;
        const STREAM_IDLE_TIMEOUT_MS = 240000;
        let timeoutHandle = null;
        let hasReceivedToken = false;

        const streamState = {
            eventSource,
            aiMessageDiv,
            timeoutHandle: null,
            fullResponse: '',
            manuallyStopped: false,
            finalized: false
        };
        this.activeStream = streamState;

        const finalizeStream = (noteText) => {
            if (streamState.finalized) {
                return;
            }
            streamState.finalized = true;

            if (streamState.timeoutHandle) {
                clearTimeout(streamState.timeoutHandle);
                streamState.timeoutHandle = null;
            }

            try {
                streamState.eventSource.close();
            } catch (e) {
                // noop
            }

            const finalText = streamState.fullResponse || '';
            if (finalText) {
                this.session.addMessage(finalText, 'assistant');
                this.session.saveMessagesToCookie();

                if (noteText) {
                    const note = document.createElement('div');
                    note.className = 'text-muted small mt-2';
                    note.textContent = noteText;
                    streamState.aiMessageDiv.appendChild(note);
                }
            } else if (!hasError && !streamState.manuallyStopped) {
                streamState.aiMessageDiv.textContent = '抱歉，AI没有返回响应。请重试。';
            }

            this.activeStream = null;
            this.disableInput(false);
            this.inputField.focus();
        };

        const armIdleTimeout = () => {
            if (streamState.timeoutHandle) {
                clearTimeout(streamState.timeoutHandle);
            }

            const timeoutMs = hasReceivedToken ? STREAM_IDLE_TIMEOUT_MS : FIRST_TOKEN_TIMEOUT_MS;
            streamState.timeoutHandle = setTimeout(() => {
                streamState.manuallyStopped = true;
                if (streamState.fullResponse) {
                    finalizeStream('响应中断：等待模型继续输出超时，请稍后重试。');
                } else {
                    streamState.aiMessageDiv.textContent = '响应超时，请稍后再试。';
                    finalizeStream();
                }
            }, timeoutMs);
        };
        armIdleTimeout();
        
        // 完整的AI响应文本
        let hasError = false;
        
        // 处理消息
        eventSource.onmessage = (event) => {
            try {
                armIdleTimeout();
                const data = JSON.parse(event.data);
                if (data.error) {
                    hasError = true;
                    aiMessageDiv.textContent = `错误: ${data.error}`;
                    finalizeStream();
                } else if (data.content) {
                    hasReceivedToken = true;
                    armIdleTimeout();

                    // 移除加载指示器
                    if (streamState.fullResponse === '') {
                        aiMessageDiv.innerHTML = '';
                    }
                    
                    streamState.fullResponse += data.content;
                    
                    // 使用Markdown渲染响应
                    if (window.marked) {
                        aiMessageDiv.innerHTML = window.marked.parse(streamState.fullResponse);
                    } else {
                        // 如果marked未加载，尝试加载
                        loadMarkedLibrary()
                            .then(marked => {
                                aiMessageDiv.innerHTML = marked.parse(streamState.fullResponse);
                            })
                            .catch(err => {
                                console.error('Markdown渲染失败:', err);
                                aiMessageDiv.textContent = streamState.fullResponse;
                            });
                    }
                    
                    // 为新添加的链接添加样式和目标
                    const links = aiMessageDiv.querySelectorAll('a');
                    links.forEach(link => {
                        if (!link.classList.contains('ai-chat-link')) {
                            link.classList.add('ai-chat-link');
                        }
                        link.setAttribute('target', '_blank');
                    });
                    
                    this.scrollToBottom();
                }
            } catch (e) {
                console.error('解析AI响应失败:', e);
            }
        };

        eventSource.addEventListener('status', () => {
            armIdleTimeout();
        });
        
        // 处理结束
        eventSource.addEventListener('done', () => {
            finalizeStream();
        });
        
        // 处理错误
        eventSource.onerror = () => {
            if (streamState.manuallyStopped) {
                return;
            }
            
            if (!streamState.fullResponse) {
                aiMessageDiv.textContent = '抱歉，服务出现错误，请稍后再试。';
                finalizeStream();
                return;
            }

            finalizeStream('连接中断：已保留已生成内容。');
        };
    }

    stopStreaming(noteText) {
        const streamState = this.activeStream;
        if (!streamState) {
            return;
        }

        streamState.manuallyStopped = true;
        if (streamState.timeoutHandle) {
            clearTimeout(streamState.timeoutHandle);
            streamState.timeoutHandle = null;
        }

        try {
            streamState.eventSource.close();
        } catch (e) {
            // noop
        }

        if (!streamState.finalized) {
            streamState.finalized = true;
            const finalText = streamState.fullResponse || '';
            if (finalText) {
                this.session.addMessage(finalText, 'assistant');
                this.session.saveMessagesToCookie();
            }
            if (noteText) {
                const note = document.createElement('div');
                note.className = 'text-muted small mt-2';
                note.textContent = noteText;
                streamState.aiMessageDiv.appendChild(note);
            }
        }

        this.activeStream = null;
        this.disableInput(false);
        if (this.inputField) {
            this.inputField.focus();
        }
    }
    
    // 添加消息到UI
    addMessageToUI(text, type) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `ai-message ${type}`;
        
        // 根据不同类型处理内容
        if (type === 'bot') {
            // 使用marked库渲染Markdown（如果已加载）
            if (window.marked) {
                messageDiv.innerHTML = window.marked.parse(text);
            } else {
                // 尝试加载marked库
                loadMarkedLibrary()
                    .then(marked => {
                        messageDiv.innerHTML = marked.parse(text);
                    })
                    .catch(err => {
                        console.error('Markdown渲染失败:', err);
                        messageDiv.textContent = text;
                    });
            }
        } else {
            // 用户消息不渲染Markdown
            messageDiv.textContent = text;
        }
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
        
        // 为消息中的链接添加点击事件
        if (type === 'bot') {
            const links = messageDiv.querySelectorAll('a');
            links.forEach(link => {
                if (!link.classList.contains('ai-chat-link')) {
                    link.classList.add('ai-chat-link');
                }
                link.setAttribute('target', '_blank');
            });
        }
    }
    
    // 清空消息UI
    clearMessagesUI() {
        while (this.messagesContainer.firstChild) {
            this.messagesContainer.removeChild(this.messagesContainer.firstChild);
        }
    }
    
    // 滚动到底部
    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
    
    // 禁用/启用输入
    disableInput(disabled) {
        if (this.inputField) this.inputField.disabled = disabled;
        if (this.sendButton) {
            this.sendButton.disabled = disabled;
            this.sendButton.style.display = disabled ? 'none' : 'inline-flex';
        }
        if (this.stopButton) {
            this.stopButton.disabled = !disabled;
            this.stopButton.style.display = disabled ? 'inline-flex' : 'none';
        }
    }

    // 创建聊天界面
    createChatUI() {
        // 查找或创建聊天容器
        this.container = document.getElementById('aiChatContainer');
        if (!this.container) {
            console.log("AI聊天容器不存在，跳过UI创建");
            return;
        }
        
        this.messagesContainer = document.getElementById('aiChatMessages');
        this.inputField = document.getElementById('aiChatInput');
        this.sendButton = document.getElementById('aiSendButton');
        this.stopButton = document.getElementById('aiStopButton');
        this.toggleButton = document.querySelector('.ai-chat-button');

        if (this.stopButton) {
            this.stopButton.disabled = true;
            this.stopButton.style.display = 'none';
        }
        if (this.sendButton) {
            this.sendButton.style.display = 'inline-flex';
        }
        
        // 恢复聊天窗口状态
        const isOpen = this.session.getCookie('chat_open') === 'true';
        if (isOpen) {
            // 初始化时如果应该打开，直接设置样式而不使用动画
            this.container.style.display = 'flex';
            this.container.classList.add('visible');
            this.isOpen = true;
            this.scrollToBottom();
        } else {
            // 确保窗口是关闭的
            this.container.style.display = 'none';
            this.container.classList.remove('visible');
            this.isOpen = false;
        }
    }
}

// 初始化
function bootstrapAIChat() {
    if (window.__aiChatBootstrapped) {
        return;
    }
    window.__aiChatBootstrapped = true;

    // 延后预热Markdown解析库，优先保证页面交互就绪。
    if (!window.marked) {
        if (window.requestIdleCallback) {
            window.requestIdleCallback(() => loadMarkedLibrary(), { timeout: 2000 });
        } else {
            setTimeout(() => loadMarkedLibrary(), 1200);
        }
    }
    
    // 创建聊天会话实例
    const chatSession = new AIChatSession();
    
    // 创建UI实例
    const chatUI = new AIChatUI(chatSession);
    
    // 初始化UI
    chatUI.initialize();

    async function refreshCsrfToken() {
        const response = await fetch('/utils/csrf_token', {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            cache: 'no-store'
        });

        if (!response.ok) {
            throw new Error(`刷新安全令牌失败 (${response.status})`);
        }

        const data = await response.json();
        if (!data || !data.success || !data.csrf_token) {
            throw new Error('刷新安全令牌失败：响应异常');
        }

        let tokenMeta = document.querySelector('meta[name="csrf-token"]');
        if (!tokenMeta) {
            tokenMeta = document.createElement('meta');
            tokenMeta.setAttribute('name', 'csrf-token');
            document.head.appendChild(tokenMeta);
        }
        tokenMeta.setAttribute('content', data.csrf_token);
        return data.csrf_token;
    }

    async function postJsonWithCsrfRetry(url, bodyObject, csrfToken, retries = 1) {
        let token = csrfToken || chatSession.getCsrfToken();

        for (let attempt = 0; attempt <= retries; attempt += 1) {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': token,
                    'X-CSRF-Token': token,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(bodyObject || {}),
                credentials: 'same-origin'
            });

            if (response.ok) {
                return response.json();
            }

            const rawText = await response.text();
            let errorMessage = rawText;
            try {
                const parsed = JSON.parse(rawText);
                if (parsed && parsed.message) {
                    errorMessage = parsed.message;
                }
            } catch (_) {
                // 保持原始文本
            }

            const isCsrfFailure = response.status === 400 && String(errorMessage).includes('安全验证失败');
            if (isCsrfFailure && attempt < retries) {
                token = await refreshCsrfToken();
                continue;
            }

            throw new Error(`请求失败 (${response.status}): ${String(errorMessage).substring(0, 120)}`);
        }

        throw new Error('请求失败：超过重试次数');
    }

    async function getFreshCsrfToken() {
        try {
            return await refreshCsrfToken();
        } catch (e) {
            console.warn('主动刷新CSRF令牌失败，回退使用当前页面令牌:', e);
            const fallbackToken = chatSession.getCsrfToken();
            if (!fallbackToken) {
                throw e;
            }
            return fallbackToken;
        }
    }
    
    // 将实例保存到全局变量
    window.aiChat = {
        session: chatSession,
        ui: chatUI,
        config: AI_CHAT_CONFIG,
        associationInfo: ASSOCIATION_INFO,
        
        // 公共API
        clearHistory: () => {
            console.log("开始清除当前对话历史记录");
            
            // 检查用户是否已登录
            const isLoggedIn = document.body.getAttribute('data-user-logged-in') === 'true';
            if (!isLoggedIn) {
                if (typeof showToast === 'function') {
                    showToast('请先登录后再清除对话历史', 'warning');
                } else {
                    alert('请先登录后再清除对话历史');
                }
                return;
            }
            
            getFreshCsrfToken()
            .then(csrfToken => {
                console.log("当前CSRF令牌:", csrfToken);
                return postJsonWithCsrfRetry(
                    `/utils/ai_chat/clear?session_id=${chatSession.sessionId}`,
                    { session_id: chatSession.sessionId },
                    csrfToken,
                    1
                );
            })
            .then(data => {
                console.log('清除历史记录成功:', data);
                // 清除本地消息
                chatSession.messages = [];
                chatUI.clearMessagesUI();
                chatUI.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
                // 清除cookie中的消息
                chatSession.deleteCookie('messages');
                if (typeof showToast === 'function') {
                    showToast('当前对话历史已清除！', 'success');
                } else {
                    alert('当前对话历史已清除！');
                }
            })
            .catch(error => {
                console.error('清除历史记录失败:', error);
                if (typeof showToast === 'function') {
                    showToast('清除历史记录失败: ' + error.message, 'error');
                } else {
                    alert('清除历史记录失败: ' + error.message);
                }
                
                // 如果API失败，尝试直接清除前端消息
                try {
                    chatSession.messages = [];
                    chatUI.clearMessagesUI();
                    chatUI.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
                    chatSession.deleteCookie('messages');
                    console.log("已强制清除前端消息");
                } catch (e) {
                    console.error("前端清除也失败:", e);
                }
            });
        },
        
        // 清除所有会话历史
        clearAllHistory: () => {
            console.log("开始清除所有历史记录");
            
            // 检查用户是否已登录
            const isLoggedIn = document.body.getAttribute('data-user-logged-in') === 'true';
            if (!isLoggedIn) {
                if (typeof showToast === 'function') {
                    showToast('请先登录后再清除对话历史', 'warning');
                } else {
                    alert('请先登录后再清除对话历史');
                }
                return;
            }
            
            // 显示加载提示
            const originalButtonText = document.querySelector('.clear-history-btn') ? 
                                      document.querySelector('.clear-history-btn').innerHTML : 
                                      "清除历史";
            if (document.querySelector('.clear-history-btn')) {
                document.querySelector('.clear-history-btn').innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 处理中...';
                document.querySelector('.clear-history-btn').disabled = true;
            }
            
            getFreshCsrfToken()
            .then(csrfToken => {
                console.log("当前CSRF令牌:", csrfToken);
                return postJsonWithCsrfRetry(
                    '/utils/ai_chat/clear_history',
                    { csrf_token: csrfToken, session_id: chatSession.sessionId || '' },
                    csrfToken,
                    1
                );
            })
            .then(data => {
                console.log('清除所有历史记录成功:', data);
                // 清除本地消息
                chatSession.messages = [];
                chatUI.clearMessagesUI();
                chatUI.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
                // 清除cookie中的消息
                chatSession.deleteCookie('messages');
                if (typeof showToast === 'function') {
                    showToast('历史记录已清除！', 'success');
                } else {
                    alert('历史记录已清除！');
                }
            })
            .catch(error => {
                console.error('清除所有历史记录失败:', error);
                if (typeof showToast === 'function') {
                    showToast('清除历史记录失败: ' + error.message, 'error');
                } else {
                    alert('清除历史记录失败: ' + error.message);
                }
                
                // 如果API失败，尝试直接清除前端消息
                try {
                    chatSession.messages = [];
                    chatUI.clearMessagesUI();
                    chatUI.addMessageToUI(AI_CHAT_CONFIG.initialBotMessage, 'bot');
                    chatSession.deleteCookie('messages');
                    console.log("已强制清除前端消息");
                } catch (e) {
                    console.error("前端清除也失败:", e);
                }
            })
            .finally(() => {
                // 恢复按钮状态
                if (document.querySelector('.clear-history-btn')) {
                    document.querySelector('.clear-history-btn').innerHTML = originalButtonText;
                    document.querySelector('.clear-history-btn').disabled = false;
                }
            });
        },
        
        // 获取平台信息
        getAssociationInfo: () => ASSOCIATION_INFO,
        
        // 设置初始消息
        setInitialMessage: (message) => {
            AI_CHAT_CONFIG.initialBotMessage = message;
        }
    };
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapAIChat);
} else {
    bootstrapAIChat();
}

// 添加样式
function injectAIChatStyles() {
    if (window.__aiChatStylesInjected) {
        return;
    }
    window.__aiChatStylesInjected = true;

    // 创建样式元素
    const style = document.createElement('style');
    style.textContent = `
        .ai-chat-link {
            color: #1a73e8;
            text-decoration: underline;
            cursor: pointer;
        }
        
        .ai-message.bot a {
            color: #1a73e8;
            text-decoration: underline;
        }
        
        .ai-message.bot strong, 
        .ai-message.bot b {
            font-weight: bold;
        }
        
        .ai-message.bot em,
        .ai-message.bot i {
            font-style: italic;
        }
        
        .ai-message.bot code {
            background-color: #f5f5f5;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: monospace;
        }
        
        .ai-message.bot pre {
            background-color: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }
        
        .ai-message.bot pre code {
            background-color: transparent;
            padding: 0;
        }
        
        .ai-message.bot ul, 
        .ai-message.bot ol {
            margin-left: 20px;
            padding-left: 0;
        }
        
        .ai-message.bot blockquote {
            border-left: 3px solid #ddd;
            margin-left: 0;
            padding-left: 10px;
            color: #555;
        }
    `;
    document.head.appendChild(style);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectAIChatStyles);
} else {
    injectAIChatStyles();
}