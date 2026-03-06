// 主要JavaScript功能
document.addEventListener('DOMContentLoaded', function() {
    // 初始化Bootstrap提示工具
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });

    // 初始化图表（如果存在）
    initializeCharts();

    // 活动签到功能
    setupAttendanceCheckin();

    // 搜索功能优化
    setupSearchOptimization();

    // 通知系统
    // 检查是否已登录（通过查找用户菜单）
    const userMenu = document.querySelector('.user-menu');
    
    if (userMenu) {
        // 获取未读重要通知
        fetchUnreadNotifications();

        // 设置定时刷新（每10分钟，减少频率）
        setInterval(fetchUnreadNotifications, 10 * 60 * 1000);
    }
    
    // 为所有通知关闭按钮添加事件监听
    document.addEventListener('click', function(e) {
        if (e.target && e.target.classList.contains('notification-close')) {
            const notificationId = e.target.getAttribute('data-notification-id');
            const banner = e.target.closest('.notification-banner');
            
            if (notificationId) {
                markNotificationAsRead(notificationId);
            }
            
            if (banner) {
                banner.style.height = banner.offsetHeight + 'px';
                setTimeout(() => {
                    banner.style.height = '0';
                    banner.style.padding = '0';
                    banner.style.margin = '0';
                    banner.style.overflow = 'hidden';
                    banner.style.borderWidth = '0';
                }, 10);
                
                setTimeout(() => {
                    banner.remove();
                }, 500);
            }
        }
    });

    // 检查是否有通知需要显示
    displayNotifications();
    
    // 处理删除确认
    setupDeleteConfirmation();
    
    // 处理签到表单
    setupCheckinForm();
    
    // 处理活动倒计时
    setupCountdowns();

    // 初始化Toast通知系统
    initToastSystem();
    
    // 初始化统一的加载系统
    initUnifiedLoadingSystem();

    // 重置所有按钮状态（解决浏览器返回问题）
    resetAllButtonStates();
    
    // 监听浏览器前进/后退事件
    window.addEventListener('pageshow', function(event) {
        // 当页面从浏览器缓存中加载时（例如使用后退按钮）
        if (event.persisted) {
            console.log('页面从缓存加载，重置按钮状态');
            resetAllButtonStates();
        }
    });
    
    // 监听popstate事件（浏览器前进/后退按钮）
    window.addEventListener('popstate', function(event) {
        console.log('浏览器导航事件，重置按钮状态');
        resetAllButtonStates();
    });
    
    // 监听页面可见性变化
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            console.log('页面变为可见，重置按钮状态');
            resetAllButtonStates();
        }
    });

    // 特别处理登录按钮
    setupLoginButton();

    // 初始化卡片倾斜动画（VanillaTilt）
    (function initCardTilt() {
        // 移动端（触控/窄屏）不启用3D倾斜效果
        const isMobile = window.matchMedia('(max-width: 767px)').matches || window.matchMedia('(pointer:coarse)').matches;
        if (isMobile) return;

        const allCards = document.querySelectorAll('.card');
        // 仅对尺寸较小（宽高均 < 600px）的卡片启用倾斜，避免大容器晃动
        const tiltCards = Array.from(allCards).filter(c => {
            const rect = c.getBoundingClientRect();
            return rect.width < 600 && rect.height < 600;
        });

        if (typeof VanillaTilt !== 'undefined' && tiltCards.length) {
            // 为符合条件的卡片打标，便于CSS优化
            tiltCards.forEach(c => c.setAttribute('data-tilt', ''));
            VanillaTilt.init(tiltCards, {
                max: 12,       // 最大倾斜角度
                speed: 400,    // 动画速度
                glare: true,   // 高光
                'max-glare': 0.15,
                perspective: 1000,
            });
        }
    })();
});

// 统一的加载系统
function initUnifiedLoadingSystem() {
    // 创建全局加载动画
    createGlobalLoading();

    // 设置按钮加载处理
    setupButtonLoading();

    // 设置表单加载处理
    setupFormLoadingHandlers();

    // 设置AJAX加载处理
    setupAjaxLoadingHandlers();
}

// 创建全局加载动画
function createGlobalLoading() {
    // 如果已经存在，不重复创建
    if (document.querySelector('.global-loading')) {
        return;
    }

    // 创建加载动画元素
    const loadingEl = document.createElement('div');
    loadingEl.className = 'global-loading';
    loadingEl.innerHTML = `
        <div class="loader">
            <div>
                <ul>
                    <li>
                        <svg fill="currentColor" viewBox="0 0 90 120">
                            <path d="M90,0 L90,120 L11,120 C4.92486775,120 0,115.075132 0,109 L0,11 C0,4.92486775 4.92486775,0 11,0 L90,0 Z M71.5,81 L18.5,81 C17.1192881,81 16,82.1192881 16,83.5 C16,84.8254834 17.0315359,85.9100387 18.3356243,85.9946823 L18.5,86 L71.5,86 C72.8807119,86 74,84.8807119 74,83.5 C74,82.1745166 72.9684641,81.0899613 71.6643757,81.0053177 L71.5,81 Z M71.5,57 L18.5,57 C17.1192881,57 16,58.1192881 16,59.5 C16,60.8254834 17.0315359,61.9100387 18.3356243,61.9946823 L18.5,62 L71.5,62 C72.8807119,62 74,60.8807119 74,59.5 C74,58.1192881 72.8807119,57 71.5,57 Z M71.5,33 L18.5,33 C17.1192881,33 16,34.1192881 16,35.5 C16,36.8254834 17.0315359,37.9100387 18.3356243,37.9946823 L18.5,38 L71.5,38 C72.8807119,38 74,36.8807119 74,35.5 C74,34.1192881 72.8807119,33 71.5,33 Z" />
                        </svg>
                    </li>
                    <li>
                        <svg fill="currentColor" viewBox="0 0 90 120">
                            <path d="M90,0 L90,120 L11,120 C4.92486775,120 0,115.075132 0,109 L0,11 C0,4.92486775 4.92486775,0 11,0 L90,0 Z M71.5,81 L18.5,81 C17.1192881,81 16,82.1192881 16,83.5 C16,84.8254834 17.0315359,85.9100387 18.3356243,85.9946823 L18.5,86 L71.5,86 C72.8807119,86 74,84.8807119 74,83.5 C74,82.1745166 72.9684641,81.0899613 71.6643757,81.0053177 L71.5,81 Z M71.5,57 L18.5,57 C17.1192881,57 16,58.1192881 16,59.5 C16,60.8254834 17.0315359,61.9100387 18.3356243,61.9946823 L18.5,62 L71.5,62 C72.8807119,62 74,60.8807119 74,59.5 C74,58.1192881 72.8807119,57 71.5,57 Z M71.5,33 L18.5,33 C17.1192881,33 16,34.1192881 16,35.5 C16,36.8254834 17.0315359,37.9100387 18.3356243,37.9946823 L18.5,38 L71.5,38 C72.8807119,38 74,36.8807119 74,35.5 C74,34.1192881 72.8807119,33 71.5,33 Z" />
                        </svg>
                    </li>
                    <li>
                        <svg fill="currentColor" viewBox="0 0 90 120">
                            <path d="M90,0 L90,120 L11,120 C4.92486775,120 0,115.075132 0,109 L0,11 C0,4.92486775 4.92486775,0 11,0 L90,0 Z M71.5,81 L18.5,81 C17.1192881,81 16,82.1192881 16,83.5 C16,84.8254834 17.0315359,85.9100387 18.3356243,85.9946823 L18.5,86 L71.5,86 C72.8807119,86 74,84.8807119 74,83.5 C74,82.1745166 72.9684641,81.0899613 71.6643757,81.0053177 L71.5,81 Z M71.5,57 L18.5,57 C17.1192881,57 16,58.1192881 16,59.5 C16,60.8254834 17.0315359,61.9100387 18.3356243,61.9946823 L18.5,62 L71.5,62 C72.8807119,62 74,60.8807119 74,59.5 C74,58.1192881 72.8807119,57 71.5,57 Z M71.5,33 L18.5,33 C17.1192881,33 16,34.1192881 16,35.5 C16,36.8254834 17.0315359,37.9100387 18.3356243,37.9946823 L18.5,38 L71.5,38 C72.8807119,38 74,36.8807119 74,35.5 C74,34.1192881 72.8807119,33 71.5,33 Z" />
                        </svg>
                    </li>
                    <li>
                        <svg fill="currentColor" viewBox="0 0 90 120">
                            <path d="M90,0 L90,120 L11,120 C4.92486775,120 0,115.075132 0,109 L0,11 C0,4.92486775 4.92486775,0 11,0 L90,0 Z M71.5,81 L18.5,81 C17.1192881,81 16,82.1192881 16,83.5 C16,84.8254834 17.0315359,85.9100387 18.3356243,85.9946823 L18.5,86 L71.5,86 C72.8807119,86 74,84.8807119 74,83.5 C74,82.1745166 72.9684641,81.0899613 71.6643757,81.0053177 L71.5,81 Z M71.5,57 L18.5,57 C17.1192881,57 16,58.1192881 16,59.5 C16,60.8254834 17.0315359,61.9100387 18.3356243,61.9946823 L18.5,62 L71.5,62 C72.8807119,62 74,60.8807119 74,59.5 C74,58.1192881 72.8807119,57 71.5,57 Z M71.5,33 L18.5,33 C17.1192881,33 16,34.1192881 16,35.5 C16,36.8254834 17.0315359,37.9100387 18.3356243,37.9946823 L18.5,38 L71.5,38 C72.8807119,38 74,36.8807119 74,35.5 C74,34.1192881 72.8807119,33 71.5,33 Z" />
                        </svg>
                    </li>
                    <li>
                        <svg fill="currentColor" viewBox="0 0 90 120">
                            <path d="M90,0 L90,120 L11,120 C4.92486775,120 0,115.075132 0,109 L0,11 C0,4.92486775 4.92486775,0 11,0 L90,0 Z M71.5,81 L18.5,81 C17.1192881,81 16,82.1192881 16,83.5 C16,84.8254834 17.0315359,85.9100387 18.3356243,85.9946823 L18.5,86 L71.5,86 C72.8807119,86 74,84.8807119 74,83.5 C74,82.1745166 72.9684641,81.0899613 71.6643757,81.0053177 L71.5,81 Z M71.5,57 L18.5,57 C17.1192881,57 16,58.1192881 16,59.5 C16,60.8254834 17.0315359,61.9100387 18.3356243,61.9946823 L18.5,62 L71.5,62 C72.8807119,62 74,60.8807119 74,59.5 C74,58.1192881 72.8807119,57 71.5,57 Z M71.5,33 L18.5,33 C17.1192881,33 16,34.1192881 16,35.5 C16,36.8254834 17.0315359,37.9100387 18.3356243,37.9946823 L18.5,38 L71.5,38 C72.8807119,38 74,36.8807119 74,35.5 C74,34.1192881 72.8807119,33 71.5,33 Z" />
                        </svg>
                    </li>
                    <li>
                        <svg fill="currentColor" viewBox="0 0 90 120">
                            <path d="M90,0 L90,120 L11,120 C4.92486775,120 0,115.075132 0,109 L0,11 C0,4.92486775 4.92486775,0 11,0 L90,0 Z M71.5,81 L18.5,81 C17.1192881,81 16,82.1192881 16,83.5 C16,84.8254834 17.0315359,85.9100387 18.3356243,85.9946823 L18.5,86 L71.5,86 C72.8807119,86 74,84.8807119 74,83.5 C74,82.1745166 72.9684641,81.0899613 71.6643757,81.0053177 L71.5,81 Z M71.5,57 L18.5,57 C17.1192881,57 16,58.1192881 16,59.5 C16,60.8254834 17.0315359,61.9100387 18.3356243,61.9946823 L18.5,62 L71.5,62 C72.8807119,62 74,60.8807119 74,59.5 C74,58.1192881 72.8807119,57 71.5,57 Z M71.5,33 L18.5,33 C17.1192881,33 16,34.1192881 16,35.5 C16,36.8254834 17.0315359,37.9100387 18.3356243,37.9946823 L18.5,38 L71.5,38 C72.8807119,38 74,36.8807119 74,35.5 C74,34.1192881 72.8807119,33 71.5,33 Z" />
                        </svg>
                    </li>
                </ul>
            </div>
            <span>加载中</span>
        </div>
    `;
    document.body.appendChild(loadingEl);

    // 统一的加载管理器
    window.LoadingManager = {
        timeout: null,

        show: function(message = '加载中', autoHide = true) {
            const loadingEl = document.querySelector('.global-loading');
            if (loadingEl) {
                const messageEl = loadingEl.querySelector('.loader span');
                if (messageEl) {
                    messageEl.textContent = message;
                }
                loadingEl.classList.add('show');

                // 清除之前的超时
                if (this.timeout) {
                    clearTimeout(this.timeout);
                    this.timeout = null;
                }

                // 设置自动隐藏
                if (autoHide) {
                    this.timeout = setTimeout(() => {
                        this.hide();
                        console.log('加载超时：自动隐藏');
                    }, 8000); // 统一8秒超时
                }
            }
        },

        hide: function() {
            const loadingEl = document.querySelector('.global-loading');
            if (loadingEl) {
                loadingEl.classList.remove('show');
            }

            // 清除超时
            if (this.timeout) {
                clearTimeout(this.timeout);
                this.timeout = null;
            }
        }
    };

    // 向后兼容
    window.showLoading = window.LoadingManager.show.bind(window.LoadingManager);
    window.hideLoading = window.LoadingManager.hide.bind(window.LoadingManager);
    
    // 页面事件监听 - 优化云端环境加载体验
    window.addEventListener('load', () => {
        // 页面加载完成后立即隐藏加载动画
        window.LoadingManager.hide();
    });
    
    // DOMContentLoaded事件 - 确保DOM加载完成后也隐藏加载动画
    document.addEventListener('DOMContentLoaded', () => {
        // 延迟一点时间确保页面渲染完成
        setTimeout(() => {
            window.LoadingManager.hide();
        }, 100);
    });

    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            setTimeout(() => window.LoadingManager.hide(), 500);
        }
    });
    
    // 为所有链接添加全局加载动画监听
    document.addEventListener('click', function(e) {
        const link = e.target.closest('a');
        if (!link) return;
        
        const href = link.getAttribute('href');
        // 检查是否需要显示全局加载动画
        if (href && 
            !href.startsWith('#') && 
            !href.startsWith('javascript:') && 
            !href.startsWith('mailto:') && 
            !href.startsWith('tel:') && 
            !href.includes('download') && 
            !link.hasAttribute('data-no-global-loading') && 
            !link.hasAttribute('data-bs-toggle') && 
            !link.classList.contains('btn') && // 按钮链接已在其他地方处理
            link.getAttribute('target') !== '_blank') {
            
            // 显示全局加载动画
            window.LoadingManager.show('页面加载中...', false);
            
            // 云端环境优化：确保加载动画显示足够长时间
            setTimeout(() => {
                if (window.LoadingManager) {
                    window.LoadingManager.hide();
                }
            }, 6000); // 6秒后强制隐藏
        }
    });
}

// 统一的按钮加载处理
function setupButtonLoading() {
    // 按钮加载管理器
    window.ButtonLoadingManager = {
        loadingButtons: new Set(),

        setLoading: function(button, loadingText = '处理中...') {
            if (this.loadingButtons.has(button)) {
                return; // 避免重复设置
            }

            // 检查按钮是否已经在加载状态
            if (button.classList.contains('btn-loading') ||
                button.classList.contains('btn-loading-active') ||
                button.hasAttribute('data-loading-setup')) {
                return; // 避免与现有加载系统冲突
            }

            // 保存原始状态
            const originalText = button.innerHTML;
            const originalDisabled = button.disabled;

            // 使用不同的属性名避免冲突
            button.setAttribute('data-unified-original-text', originalText);
            button.setAttribute('data-unified-original-disabled', originalDisabled);

            // 设置加载状态
            button.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${loadingText}`;
            button.disabled = true;
            button.classList.add('btn-loading-active');

            this.loadingButtons.add(button);

            // 安全超时
            setTimeout(() => {
                this.clearLoading(button);
            }, 10000); // 10秒超时
        },

        clearLoading: function(button) {
            if (!this.loadingButtons.has(button)) {
                return;
            }

            // 恢复原始状态
            const originalText = button.getAttribute('data-unified-original-text');
            const originalDisabled = button.getAttribute('data-unified-original-disabled') === 'true';

            if (originalText) {
                button.innerHTML = originalText;
            }
            button.disabled = originalDisabled;
            button.classList.remove('btn-loading-active');

            // 清理属性
            button.removeAttribute('data-unified-original-text');
            button.removeAttribute('data-unified-original-disabled');

            this.loadingButtons.delete(button);
        },

        clearAll: function() {
            this.loadingButtons.forEach(button => {
                this.clearLoading(button);
            });
        }
    };

    // 为按钮添加加载处理 - 更精确的检测
    document.addEventListener('click', function(e) {
        const button = e.target.closest('button, a.btn');
        if (!button) return;

        // 跳过特定按钮 - 更严格的过滤
        if (button.classList.contains('ai-chat-button') ||
            button.hasAttribute('data-no-loading') ||
            button.hasAttribute('data-no-global-loading') ||
            button.closest('form[data-no-loading]') ||
            button.closest('form[data-no-global-loading]') ||  // 跳过有data-no-global-loading属性的表单中的按钮
            button.getAttribute('data-bs-toggle') === 'modal' ||
            button.getAttribute('data-bs-toggle') === 'dropdown' ||
            button.getAttribute('data-bs-toggle') === 'collapse' ||
            button.closest('.pagination') ||
            button.closest('.dropdown') ||
            button.classList.contains('dropdown-toggle') ||
            button.classList.contains('btn-close') ||
            button.classList.contains('btn-outline-secondary') ||
            button.classList.contains('btn-secondary') ||
            button.classList.contains('btn-light') ||  // 跳过浅色搜索按钮
            button.closest('.search-form') ||  // 搜索表单按钮
            button.classList.contains('btn-outline-primary') ||
            button.classList.contains('btn-outline-danger') ||
            button.classList.contains('btn-sm') ||
            button.hasAttribute('onclick') ||  // 跳过所有有onclick的按钮
            button.hasAttribute('data-loading-setup') ||  // 跳过已有加载处理的按钮
            button.closest('.btn-group') ||  // 跳过按钮组中的按钮
            button.closest('.card-header') ||  // 跳过卡片头部的按钮
            button.getAttribute('href') && button.getAttribute('href').startsWith('#') ||  // 跳过锚点链接
            button.getAttribute('download') ||  // 跳过下载按钮
            button.textContent.includes('打印') ||
            button.textContent.includes('刷新') ||
            button.textContent.includes('返回') ||
            (button.textContent.includes('关闭') && !button.textContent.includes('签到')) ||  // 跳过关闭按钮，但不包括签到相关
            button.textContent.includes('取消')) {
            return;
        }

        // 只对特定类型的按钮应用加载状态
        const shouldApplyLoading =
            button.type === 'submit' ||
            button.classList.contains('btn-primary') ||
            button.classList.contains('btn-success') ||
            button.classList.contains('btn-danger') ||
            button.classList.contains('btn-warning') ||
            button.classList.contains('btn-info') ||
            button.textContent.includes('登录') ||
            button.textContent.includes('注册') ||
            button.textContent.includes('保存') ||
            button.textContent.includes('删除') ||
            button.textContent.includes('导出') ||
            button.textContent.includes('提交') ||
            button.textContent.includes('确认') ||
            button.textContent.includes('发送') ||
            button.textContent.includes('上传') ||
            button.textContent.includes('下载') ||
            button.textContent.includes('签到');  // 添加签到相关按钮

        if (!shouldApplyLoading) {
            return;
        }

        // 确定加载文本
        let loadingText = '处理中...';
        if (button.textContent.includes('登录')) loadingText = '登录中...';
        else if (button.textContent.includes('注册')) loadingText = '注册中...';
        else if (button.textContent.includes('保存')) loadingText = '保存中...';
        else if (button.textContent.includes('删除')) loadingText = '删除中...';
        else if (button.textContent.includes('导出')) loadingText = '导出中...';
        else if (button.textContent.includes('提交')) loadingText = '提交中...';
        else if (button.textContent.includes('确认')) loadingText = '确认中...';
        else if (button.textContent.includes('发送')) loadingText = '发送中...';
        else if (button.textContent.includes('开启签到')) loadingText = '开启中...';
        else if (button.textContent.includes('关闭签到')) loadingText = '关闭中...';
        else if (button.textContent.includes('上传')) loadingText = '上传中...';
        else if (button.textContent.includes('下载')) loadingText = '下载中...';

        // 设置加载状态
        window.ButtonLoadingManager.setLoading(button, loadingText);
    });
}

// 简化的表单加载处理
function setupFormLoadingHandlers() {
    document.addEventListener('submit', function(e) {
        const form = e.target;

        // 跳过特定表单
        if (form.hasAttribute('data-no-loading') ||
            form.classList.contains('no-loading')) {
            return;
        }
        
        // 获取表单提交按钮
        const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
        if (submitBtn) {
            // 确定加载文本
            let loadingText = '提交中...';
            if (form.action?.includes('/login')) loadingText = '登录中...';
            else if (form.action?.includes('/register')) loadingText = '注册中...';

            // 使用统一的按钮管理器
            window.ButtonLoadingManager.setLoading(submitBtn, loadingText);
        }
    });
}

// 简化的AJAX加载处理
function setupAjaxLoadingHandlers() {
    // 简单的AJAX请求计数器
    let activeRequests = 0;

    // 监听fetch请求
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const url = args[0];

        // 只对特定API显示全局加载
        const showGlobalLoading = url.includes('/admin/api/') &&
                                 (url.includes('sync') || url.includes('backup') || url.includes('restore'));

        if (showGlobalLoading) {
            activeRequests++;
            if (activeRequests === 1) {
                window.LoadingManager.show('处理中...');
            }
        }

        return originalFetch.apply(this, args).finally(() => {
            if (showGlobalLoading) {
                activeRequests--;
                if (activeRequests === 0) {
                    window.LoadingManager.hide();
                }
            }
        });
    };
}

// 旧的复杂AJAX处理已被简化版本替代


// 初始化Toast通知系统
function initToastSystem() {
    // 创建Toast容器
    const toastContainer = document.createElement('div');
    toastContainer.id = 'toast-container';
    toastContainer.className = 'toast-container position-fixed bottom-0 start-0 p-3';
    toastContainer.style.zIndex = '1090';
    document.body.appendChild(toastContainer);
    
    // 添加全局showToast函数
    window.showToast = function(message, type = 'info', duration = 3000) {
        const toastId = 'toast-' + Date.now();
        const toast = document.createElement('div');
        toast.className = `toast align-items-center border-0 show`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.id = toastId;
        toast.style.maxWidth = '300px';
        toast.style.fontSize = '0.85rem';
        toast.style.padding = '0.25rem';
        
        // 设置不同类型的背景色
        switch(type) {
            case 'success':
                toast.classList.add('bg-success');
                break;
            case 'error':
                toast.classList.add('bg-danger');
                break;
            case 'warning':
                toast.classList.add('bg-warning', 'text-dark');
                break;
            case 'info':
                toast.classList.add('bg-info', 'text-dark');
                break;
            default:
                toast.classList.add('bg-primary');
                break;
        }
        
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body py-1 px-2">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-1 m-auto" data-bs-dismiss="toast" aria-label="Close" style="font-size: 0.7rem;"></button>
            </div>
        `;
        
        // 添加到容器
        toastContainer.appendChild(toast);
        
        // 添加动画
        toast.style.transform = 'translateY(100%)';
        toast.style.opacity = '0';
        toast.style.transition = 'all 0.3s ease-out';
        
        // 触发重排，然后应用动画
        setTimeout(() => {
            toast.style.transform = 'translateY(0)';
            toast.style.opacity = '1';
        }, 10);
        
        // 添加关闭按钮事件
        const closeBtn = toast.querySelector('.btn-close');
        closeBtn.addEventListener('click', () => {
            closeToast(toastId);
        });
        
        // 自动关闭
        if (duration > 0) {
            setTimeout(() => {
                closeToast(toastId);
            }, duration);
        }
        
        return toastId;
    };
    
    // 关闭Toast的函数
    function closeToast(toastId) {
        const toast = document.getElementById(toastId);
        if (toast) {
            toast.style.transform = 'translateY(100%)';
            toast.style.opacity = '0';
            
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }
    }
    
    // 添加全局closeToast函数
    window.closeToast = closeToast;
}

// 图表初始化函数
function initializeCharts() {
    // 活动统计图表
    const activityChartElement = document.getElementById('activityChart');
    if (activityChartElement) {
        fetch('/api/statistics/activities')
            .then(response => {
                if (!response.ok) {
                    throw new Error('网络响应异常');
                }
                return response.json();
            })
            .then(data => {
                const ctx = activityChartElement.getContext('2d');
                new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            label: '活动数量',
                            data: data.values,
                            backgroundColor: 'rgba(54, 162, 235, 0.5)',
                            borderColor: 'rgba(54, 162, 235, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: {
                                    precision: 0
                                }
                            }
                        }
                    }
                });
            })
            .catch(error => {
                console.error('获取活动统计数据失败:', error);
                activityChartElement.parentElement.innerHTML = '<div class="alert alert-warning">加载图表数据失败，请刷新页面重试。</div>';
            });
    }

    // 报名统计图表
    const registrationChartElement = document.getElementById('registrationChart');
    if (registrationChartElement) {
        fetch('/api/statistics/registrations')
            .then(response => {
                if (!response.ok) {
                    throw new Error('网络响应异常');
                }
                return response.json();
            })
            .then(data => {
                const ctx = registrationChartElement.getContext('2d');
                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            label: '报名人次',
                            data: data.values,
                            backgroundColor: 'rgba(75, 192, 192, 0.5)',
                            borderColor: 'rgba(75, 192, 192, 1)',
                            borderWidth: 2,
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: {
                                    precision: 0
                                }
                            }
                        }
                    }
                });
            })
            .catch(error => {
                console.error('获取报名统计数据失败:', error);
                registrationChartElement.parentElement.innerHTML = '<div class="alert alert-warning">加载图表数据失败，请刷新页面重试。</div>';
            });
    }

    // 学院分布图表
    const collegeChartElement = document.getElementById('collegeChart');
    if (collegeChartElement) {
        fetch('/api/statistics/colleges')
            .then(response => {
                if (!response.ok) {
                    throw new Error('网络响应异常');
                }
                return response.json();
            })
            .then(data => {
                const ctx = collegeChartElement.getContext('2d');
                new Chart(ctx, {
                    type: 'pie',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            data: data.values,
                            backgroundColor: [
                                'rgba(255, 99, 132, 0.7)',
                                'rgba(54, 162, 235, 0.7)',
                                'rgba(255, 206, 86, 0.7)',
                                'rgba(75, 192, 192, 0.7)',
                                'rgba(153, 102, 255, 0.7)',
                                'rgba(255, 159, 64, 0.7)',
                                'rgba(199, 199, 199, 0.7)',
                                'rgba(83, 102, 255, 0.7)',
                                'rgba(40, 159, 64, 0.7)',
                                'rgba(210, 199, 199, 0.7)'
                            ],
                            borderColor: [
                                'rgba(255, 99, 132, 1)',
                                'rgba(54, 162, 235, 1)',
                                'rgba(255, 206, 86, 1)',
                                'rgba(75, 192, 192, 1)',
                                'rgba(153, 102, 255, 1)',
                                'rgba(255, 159, 64, 1)',
                                'rgba(199, 199, 199, 1)',
                                'rgba(83, 102, 255, 1)',
                                'rgba(40, 159, 64, 1)',
                                'rgba(210, 199, 199, 1)'
                            ],
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: {
                                position: 'right',
                            }
                        }
                    }
                });
            })
            .catch(error => {
                console.error('获取学院分布数据失败:', error);
                collegeChartElement.parentElement.innerHTML = '<div class="alert alert-warning">加载图表数据失败，请刷新页面重试。</div>';
            });
    }
}

// 活动签到功能
function setupAttendanceCheckin() {
    const checkinForm = document.getElementById('checkinForm');
    if (checkinForm) {
        checkinForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const studentId = document.getElementById('studentId').value;
            const activityId = document.getElementById('activityId').value;
            
            if (!studentId || !activityId) {
                alert('请输入学号和活动ID');
                return;
            }
            
            fetch('/api/attendance/checkin', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    student_id: studentId,
                    activity_id: activityId
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('签到成功！');
                    document.getElementById('studentId').value = '';
                    // 刷新签到列表
                    if (typeof refreshAttendanceList === 'function') {
                        refreshAttendanceList();
                    }
                } else {
                    alert('签到失败: ' + data.message);
                }
            })
            .catch(error => {
                console.error('签到请求失败:', error);
                alert('签到请求失败，请重试');
            });
        });
    }
}

// 搜索功能优化
function setupSearchOptimization() {
    const searchForms = document.querySelectorAll('form[data-search-form]');
    searchForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const searchInput = form.querySelector('input[name="search"]');
            if (searchInput && searchInput.value.trim().length < 2 && searchInput.value.trim().length > 0) {
                e.preventDefault();
                alert('搜索关键词至少需要2个字符');
            }
        });
    });
}

// 更新活动状态
function updateActivityStatus(activityId, newStatus) {
    // 找到触发按钮
    const button = event.target.closest('.activity-status-btn');
    if (!button) return;
    
    // 保存原始内容
    const originalContent = button.innerHTML;
    
    // 设置加载状态
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> 处理中...';
    button.disabled = true;
    
    // 获取CSRF令牌
    const csrfToken = document.querySelector('input[name="csrf_token"]').value;
    
    // 发送请求
    fetch(`/admin/activity/${activityId}/change_status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': csrfToken
        },
        body: `status=${newStatus}&csrf_token=${csrfToken}`
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 显示成功消息
            showAlert('success', data.message || '活动状态已更新');
            
            // 延迟刷新页面，让用户看到成功消息
            setTimeout(() => {
                location.reload();
            }, 500); // 减少刷新延迟
        } else {
            // 恢复按钮状态
            button.innerHTML = originalContent;
            button.disabled = false;
            
            // 显示错误消息
            showAlert('danger', data.message || '更新活动状态失败');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        
        // 恢复按钮状态
        button.innerHTML = originalContent;
        button.disabled = false;
        
        // 显示错误消息
        showAlert('danger', '更新活动状态时出错');
    });
}

// 报名状态更新
function updateRegistrationStatus(registrationId, newStatus) {
    if (!confirm('确定要更新报名状态吗？')) {
        return;
    }
    
    fetch(`/api/registration/${registrationId}/status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            status: newStatus
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('状态更新成功！');
            window.location.reload();
        } else {
            alert('状态更新失败: ' + data.message);
        }
    })
    .catch(error => {
        console.error('状态更新请求失败:', error);
        alert('状态更新请求失败，请重试');
    });
}

// 通知系统
// 请求去重和频率控制
let isFetchingNotifications = false;
let lastNotificationFetch = 0;
const NOTIFICATION_FETCH_COOLDOWN = 60000; // 1分钟冷却时间

// 获取未读通知
function fetchUnreadNotifications() {
    const now = Date.now();

    // 防止重复请求
    if (isFetchingNotifications) {
        console.log('通知获取正在进行中，跳过此次请求');
        return;
    }

    // 频率限制
    if (now - lastNotificationFetch < NOTIFICATION_FETCH_COOLDOWN) {
        console.log('通知获取频率限制，跳过此次请求');
        return;
    }

    isFetchingNotifications = true;
    lastNotificationFetch = now;

    fetch('/api/notifications/unread')
        .then(response => {
            if (response.status === 429) {
                throw new Error('请求过于频繁，请稍后再试');
            }

            if (!response.ok) {
                throw new Error('网络响应异常');
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                // 更新通知徽章
                updateNotificationBadge(data.notifications.length);

                // 显示通知横幅
                if (data.notifications.length > 0) {
                    // 移除旧的通知横幅
                    removeNotificationBanner();

                    // 添加新的通知横幅
                    data.notifications.forEach((notification, index) => {
                        // 错开显示时间，避免所有通知同时出现
                        setTimeout(() => {
                            showNotificationBanner(notification);
                        }, index * 200); // 每个通知间隔200ms显示，减少等待时间
                    });
                }
            }
        })
        .catch(error => {
            console.error('获取未读通知失败:', error);

            if (error.message.includes('429') || error.message.includes('频繁')) {
                console.log('API请求频率过高，暂停通知获取');
                // 暂停更长时间
                lastNotificationFetch = now + 300000; // 额外暂停5分钟
            }
        })
        .finally(() => {
            isFetchingNotifications = false;
        });
}

// 更新通知徽章
function updateNotificationBadge(count) {
    const badge = document.querySelector('.notification-badge');
    if (badge) {
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    } else {
        // 如果不存在徽章，则创建一个
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(link => {
            if (link.href && link.href.includes('/notifications')) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-danger notification-badge';
                badge.style.marginLeft = '5px';
                badge.textContent = count;
                if (count <= 0) {
                    badge.style.display = 'none';
                }
                link.appendChild(badge);
            }
        });
    }
}

// 显示通知横幅
function showNotificationBanner(notification) {
    // 检查是否已存在相同ID的通知横幅
    const existingBanner = document.querySelector(`.notification-banner[data-notification-id="${notification.id}"]`);
    if (existingBanner) {
        return; // 已存在，不再创建
    }
    
    // 检查通知容器是否存在，如果不存在则创建
    let notificationContainer = document.getElementById('notification-container');
    if (!notificationContainer) {
        notificationContainer = document.createElement('div');
        notificationContainer.id = 'notification-container';
        notificationContainer.style.position = 'fixed';
        notificationContainer.style.top = '10px';
        notificationContainer.style.right = '10px';
        notificationContainer.style.maxWidth = '400px';
        notificationContainer.style.zIndex = '9999';
        document.body.appendChild(notificationContainer);
    }
    
    const container = document.createElement('div');
    container.className = 'notification-banner alert alert-primary alert-dismissible fade show';
    container.setAttribute('data-notification-id', notification.id);
    container.style.boxShadow = '0 4px 8px rgba(0,0,0,0.1)';
    container.style.transition = 'all 0.5s ease';
    container.style.marginBottom = '10px';
    container.style.animation = 'slideIn 0.5s ease-out';
    
    container.innerHTML = `
        <strong>${notification.title}</strong>
        <p class="mb-0">${notification.content.length > 100 ? notification.content.substring(0, 100) + '...' : notification.content}</p>
        <button type="button" class="btn-close notification-close" data-notification-id="${notification.id}" aria-label="Close"></button>
        <div class="mt-2">
            <a href="/notification/${notification.id}" class="btn btn-sm btn-primary">查看详情</a>
        </div>
    `;
    
    // 添加动画样式
    const style = document.createElement('style');
    if (!document.getElementById('notification-animation-style')) {
        style.id = 'notification-animation-style';
        style.textContent = `
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            @keyframes fadeOut {
                from {
                    opacity: 1;
                }
                to {
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }
    
    notificationContainer.appendChild(container);
    
    // 设置自动关闭（8秒后）
    setTimeout(() => {
        if (container && container.parentNode) {
            container.style.animation = 'fadeOut 0.5s ease-out';
            setTimeout(() => {
                if (container && container.parentNode) {
                    container.parentNode.removeChild(container);
                }
            }, 500);
        }
    }, 8000); // 减少通知显示时间
}

// 移除所有通知横幅
function removeNotificationBanner() {
    const banners = document.querySelectorAll('.notification-banner');
    banners.forEach(banner => {
        banner.classList.remove('show');
        setTimeout(() => {
            if (banner.parentNode) {
                banner.parentNode.removeChild(banner);
            }
        }, 500);
    });
}

// 标记通知为已读
function markNotificationAsRead(notificationId) {
    fetch(`/notification/${notificationId}/mark_read`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken() // 获取CSRF令牌的函数
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('网络响应异常');
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // 更新通知徽章
            const badge = document.querySelector('.notification-badge');
            if (badge && badge.textContent) {
                const count = parseInt(badge.textContent) - 1;
                updateNotificationBadge(count);
            }
        }
    })
    .catch(error => {
        console.error('标记通知已读失败:', error);
    });
}

// 获取CSRF令牌
function getCsrfToken() {
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    return metaTag ? metaTag.getAttribute('content') : '';
}

// 显示通知横幅
function displayNotifications() {
    // 查找页面中的所有通知
    const notifications = document.querySelectorAll('.notification-banner');
    
    if (notifications.length > 0) {
        // 如果有通知，创建通知容器
        let notificationContainer = document.querySelector('.notification-container');
        
        if (!notificationContainer) {
            notificationContainer = document.createElement('div');
            notificationContainer.className = 'notification-container';
            notificationContainer.style.position = 'fixed';
            notificationContainer.style.top = '70px';
            notificationContainer.style.right = '20px';
            notificationContainer.style.zIndex = '1050';
            notificationContainer.style.maxWidth = '350px';
            notificationContainer.style.width = '100%';
            document.body.appendChild(notificationContainer);
        }
        
        // 显示每个通知
        notifications.forEach((notification, index) => {
            const clone = notification.cloneNode(true);
            clone.style.display = 'block';
            clone.style.opacity = '0';
            clone.style.transform = 'translateY(-20px)';
            clone.style.transition = 'all 0.3s ease-in-out';
            
            // 将通知添加到容器中
            notificationContainer.appendChild(clone);
            
            // 延迟显示，使其有动画效果
            setTimeout(() => {
                clone.style.opacity = '1';
                clone.style.transform = 'translateY(0)';
            }, index * 200);
            
            // 添加关闭按钮事件
            const closeBtn = clone.querySelector('.close-btn');
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    const notificationId = this.getAttribute('data-notification-id');
                    if (notificationId) {
                        markNotificationAsRead(notificationId);
                    }
                    
                    clone.style.opacity = '0';
                    clone.style.transform = 'translateY(-20px)';
                    
                    setTimeout(() => {
                        clone.remove();
                    }, 300);
                });
            }
            
            // 10秒后自动关闭
            setTimeout(() => {
                if (clone && clone.parentNode) {
                    clone.style.opacity = '0';
                    clone.style.transform = 'translateY(-20px)';
                    
                    setTimeout(() => {
                        if (clone && clone.parentNode) {
                            clone.remove();
                        }
                    }, 300);
                }
            }, 10000 + index * 1000);
        });
    }
}

// 设置删除确认
function setupDeleteConfirmation() {
    document.querySelectorAll('.delete-confirm').forEach(function(button) {
        button.addEventListener('click', function(e) {
            if (!confirm('确定要删除吗？此操作不可撤销。')) {
                e.preventDefault();
            }
        });
    });
}

// 设置签到表单
function setupCheckinForm() {
    const checkinForm = document.getElementById('checkin-form');
    if (checkinForm) {
        checkinForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(checkinForm);
            
            fetch('/api/attendance/checkin', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showAlert('success', '签到成功！');
                    // 如果需要，可以更新UI
                } else {
                    showAlert('danger', data.message || '签到失败，请重试');
                }
            })
            .catch(error => {
                console.error('签到请求失败:', error);
                showAlert('danger', '签到请求失败，请重试');
            });
        });
    }
}

// 显示警告信息
function showAlert(type, message) {
    const alertContainer = document.getElementById('alert-container');
    if (!alertContainer) return;
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.setAttribute('role', 'alert');
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    alertContainer.appendChild(alert);
    
    // 5秒后自动关闭
    setTimeout(() => {
        const bsAlert = new bootstrap.Alert(alert);
        bsAlert.close();
    }, 5000);
}

// 设置活动倒计时
function setupCountdowns() {
    document.querySelectorAll('[data-countdown]').forEach(function(element) {
        const targetDate = new Date(element.getAttribute('data-countdown')).getTime();
        
        // 更新倒计时
        function updateCountdown() {
            const now = new Date().getTime();
            const distance = targetDate - now;
            
            if (distance < 0) {
                element.textContent = '已截止';
                return;
            }
            
            const days = Math.floor(distance / (1000 * 60 * 60 * 24));
            const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
            
            if (days > 0) {
                element.textContent = `${days}天${hours}小时`;
            } else if (hours > 0) {
                element.textContent = `${hours}小时${minutes}分钟`;
            } else {
                element.textContent = `${minutes}分钟`;
            }
        }
        
        // 立即更新一次
        updateCountdown();
        
        // 每分钟更新一次
        setInterval(updateCountdown, 60000);
    });
}

// 启动特定元素的倒计时
function startCountdown(elementId, targetDateStr) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const targetDate = new Date(targetDateStr).getTime();
    
    function update() {
        const now = new Date().getTime();
        const distance = targetDate - now;
        
        if (distance < 0) {
            element.textContent = '已截止';
            return;
        }
        
        const days = Math.floor(distance / (1000 * 60 * 60 * 24));
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
        
        if (days > 0) {
            element.textContent = `${days}天${hours}小时`;
        } else if (hours > 0) {
            element.textContent = `${hours}小时${minutes}分钟`;
        } else {
            element.textContent = `${minutes}分钟`;
        }
    }
    
    // 立即更新一次
    update();
    
    // 每分钟更新一次
    setInterval(update, 60000);
}

// 为所有按钮添加加载状态 - 已被统一加载系统替代
function setupLoadingButtons() {
    // 此函数已被统一加载系统替代，暂时禁用以避免冲突
    console.log('setupLoadingButtons已被统一加载系统替代');
    return;
    // 选择所有可能需要加载状态的按钮
    const actionButtons = document.querySelectorAll('.btn-primary, .btn-outline-primary, .btn-success, .btn-outline-success, .btn-info, .btn-outline-info, .btn-secondary, .btn-outline-secondary');
    
    actionButtons.forEach(button => {
        // 跳过已经设置过的按钮
        if (button.hasAttribute('data-loading-setup')) {
            return;
        }
        
        button.setAttribute('data-loading-setup', 'true');
        
        // 跳过标签选择页面的按钮
        if (button.closest('#tagsForm') || button.closest('.tag-btn') || 
            button.closest('form[data-no-loading="true"]') || 
            button.hasAttribute('data-no-loading')) {
            return;
        }
        
        // 跳过标签管理页面的删除和编辑按钮
        if ((button.onclick && button.onclick.toString().includes('editTag')) || 
            (button.onclick && button.onclick.toString().includes('deleteTag'))) {
            return;
        }
        
        // 特殊处理链接按钮
        if (button.tagName === 'A' && button.getAttribute('href')) {
            button.addEventListener('click', function(e) {
                // 排除某些不需要加载状态的链接
                if (this.getAttribute('data-no-loading') || 
                    this.getAttribute('data-bs-toggle') === 'modal' ||
                    this.getAttribute('href').startsWith('#') ||
                    this.getAttribute('target') === '_blank' ||
                    this.closest('.pagination')) {
                    return;
                }
                
                // 检查是否是下载链接
                const isDownloadLink = this.getAttribute('href').includes('/download') || 
                                      this.getAttribute('href').includes('/export');
                
                // 如果是下载链接，不添加加载状态，因为浏览器会自动处理下载
                if (isDownloadLink) {
                    // 为下载链接添加特殊属性
                    this.setAttribute('data-no-loading', 'true');
                    
                    // 为下载链接添加特殊处理，确保1秒后自动隐藏全局加载状态
                    setTimeout(() => {
                        if (window.hideLoading) {
                            window.hideLoading();
                        }

                        // 恢复按钮状态
                        if (this.classList.contains('disabled')) {
                            this.classList.remove('disabled');
                            if (this.hasAttribute('data-original-text')) {
                                this.innerHTML = this.getAttribute('data-original-text');
                                this.removeAttribute('data-original-text');
                            }
                        }
                    }, 1000); // 减少下载链接等待时间
                    return;
                }
                
                // 添加加载状态
                const originalText = this.innerHTML;
                
                // 检查是否为特定按钮
                const isViewAllBtn = this.textContent.includes('查看全部') || 
                                     this.textContent.includes('浏览活动') || 
                                     this.getAttribute('href').includes('/activities');
                const isLoginBtn = this.textContent.includes('登录') || 
                                   this.getAttribute('href').includes('/login');
                
                // 对特定按钮使用更明显的加载状态
                if (isViewAllBtn || isLoginBtn || this.classList.contains('btn-lg')) {
                    // 存储原始文本，以便在页面卸载时恢复
                    this.setAttribute('data-original-text', originalText);
                    
                    // 添加加载状态
                    this.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> ' + 
                                     (isViewAllBtn ? '加载活动...' : 
                                      isLoginBtn ? '正在登录...' : '加载中...');
                    this.classList.add('disabled');
                    
                    // 添加属性防止全局加载动画
                    this.setAttribute('data-no-global-loading', 'true');
                    
                    // 为页面跳转显示全局加载动画
                    const href = this.getAttribute('href');
                    if (href && !href.startsWith('#') && !href.startsWith('javascript:') && 
                        !href.includes('download') && !this.hasAttribute('data-no-global-loading')) {
                        // 显示全局加载动画，特别针对云端环境的加载延迟
                        window.showLoading('页面加载中...', false); // 不自动隐藏
                        
                        // 云端环境优化：延长显示时间，确保用户能看到加载动画
                        setTimeout(() => {
                            if (window.LoadingManager) {
                                window.LoadingManager.hide();
                            }
                        }, 5000); // 5秒后强制隐藏，适应云端加载时间
                    }
                    
                    // 添加页面卸载事件监听，确保在页面跳转前保持按钮状态
                    window.addEventListener('beforeunload', function() {
                        // 在页面卸载前保持按钮状态
                    }, { once: true });
                    
                    // 安全超时：如果10秒后仍未跳转，恢复按钮状态
                    setTimeout(() => {
                        if (document.body.contains(this) && this.classList.contains('disabled')) {
                            this.classList.remove('disabled');
                            if (this.hasAttribute('data-original-text')) {
                                this.innerHTML = this.getAttribute('data-original-text');
                            }
                        }
                    }, 10000);
                } else {
                    // 存储原始文本，以便在页面卸载时恢复
                    this.setAttribute('data-original-text', originalText);
                    
                    // 添加加载状态
                    this.classList.add('btn-loading');
                    
                    // 添加属性防止全局加载动画
                    this.setAttribute('data-no-global-loading', 'true');
                }
                
                // 如果8秒后页面还没有跳转，恢复按钮状态
                setTimeout(() => {
                    if (document.body.contains(this)) {
                        if (this.classList.contains('disabled')) {
                            this.classList.remove('disabled');
                            this.innerHTML = originalText;
                        }
                        if (this.classList.contains('btn-loading')) {
                            this.classList.remove('btn-loading');
                            this.innerHTML = originalText;
                        }
                    }
                }, 8000);
            });
            
            return;
        }
        
        button.addEventListener('click', function(e) {
            // 如果是分页按钮、模态框按钮或带有特定属性的按钮，不添加加载状态
            if (this.closest('.pagination') || 
                this.getAttribute('data-bs-toggle') === 'modal' || 
                this.hasAttribute('data-no-loading') ||
                (this.type === 'button' && !this.classList.contains('btn-export'))) {
                return;
            }
            
            // 特殊处理导出按钮
            const isExportButton = this.textContent.includes('导出') || 
                                  this.innerHTML.includes('fa-download') ||
                                  this.classList.contains('btn-export');
            
            if (isExportButton || this.getAttribute('href')?.includes('export')) {
                // 保存原始内容
                const originalText = this.innerHTML;
                
                // 存储原始文本，以便在页面卸载时恢复
                this.setAttribute('data-original-text', originalText);
                
                // 添加加载状态
                this.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> 处理中...';
                this.classList.add('disabled');
                
                // 添加属性防止全局加载动画
                this.setAttribute('data-no-global-loading', 'true');
                
                // 恢复按钮状态（如果页面加载时间过长）
                setTimeout(() => {
                    if (document.body.contains(this)) {
                        if (this.classList.contains('disabled')) {
                            this.classList.remove('disabled');
                            this.innerHTML = originalText;
                        }
                    }
                    // 确保隐藏全局加载状态
                    if (window.hideLoading) {
                        window.hideLoading();
                    }
                }, 5000); // 导出操作可能需要更长时间
                
                return;
            }
            
            // 保存原始内容
            const originalText = this.innerHTML;
            
            // 存储原始文本，以便在页面卸载时恢复
            this.setAttribute('data-original-text', originalText);
            
            // 添加加载状态
            this.classList.add('btn-loading');
            
            // 添加属性防止全局加载动画
            this.setAttribute('data-no-global-loading', 'true');
            
            // 恢复按钮状态（如果页面加载时间过长）
            setTimeout(() => {
                if (document.body.contains(this)) {
                    if (this.classList.contains('btn-loading')) {
                        this.classList.remove('btn-loading');
                        this.innerHTML = originalText;
                    }
                }
            }, 5000);
        });
    });
}

// 重置所有按钮状态 - 简化版本
function resetAllButtonStates() {
    console.log('重置所有按钮状态');

    // 使用统一的按钮管理器清理所有按钮
    if (window.ButtonLoadingManager) {
        window.ButtonLoadingManager.clearAll();
    }

    // 清理旧的加载状态类
    document.querySelectorAll('.btn-loading, .btn-loading-active').forEach(function(button) {
        button.classList.remove('btn-loading', 'btn-loading-active');
        button.disabled = false;

        // 清理旧的属性
        if (button.hasAttribute('data-original-text')) {
            button.innerHTML = button.getAttribute('data-original-text');
            button.removeAttribute('data-original-text');
        }
        if (button.hasAttribute('data-original-value')) {
            button.value = button.getAttribute('data-original-value');
            button.removeAttribute('data-original-value');
        }

        // 清理新的统一加载系统属性
        if (button.hasAttribute('data-unified-original-text')) {
            button.innerHTML = button.getAttribute('data-unified-original-text');
            button.removeAttribute('data-unified-original-text');
        }
        if (button.hasAttribute('data-unified-original-disabled')) {
            button.removeAttribute('data-unified-original-disabled');
        }
    });

    // 隐藏全局加载状态
    if (window.LoadingManager) {
        window.LoadingManager.hide();
    }
}

// 特别处理登录按钮
function setupLoginButton() {
    const loginForm = document.querySelector('form[action*="/auth/login"]');
    const loginBtn = document.querySelector('.login-btn');
    
    if (loginForm && loginBtn) {
        // 使用表单提交事件而不是按钮点击事件
        loginForm.addEventListener('submit', function(e) {
            // 不阻止默认提交行为
            
            // 保存原始文本
            const originalText = loginBtn.value || loginBtn.innerHTML;
            loginBtn.setAttribute('data-original-text', originalText);
            
            // 添加加载动画
            const loadingText = loginBtn.getAttribute('data-loading-text') || '正在登录...';
            if (loginBtn.tagName === 'INPUT') {
                loginBtn.value = loadingText;
            } else {
                loginBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> ' + loadingText;
            }
            
            // 禁用按钮
            loginBtn.disabled = true;
            loginBtn.classList.add('disabled');
            
            // 显示全局加载动画
            if (window.showLoading) {
                window.showLoading('登录中...');
            }
        });
    }
}

