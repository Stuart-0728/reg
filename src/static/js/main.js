// 主要JavaScript功能
document.addEventListener('DOMContentLoaded', function() {
    const pathname = (window.location.pathname || '/').replace(/\/+$/, '') || '/';

    const runNonCritical = (fn, timeout = 800) => {
        if (window.requestIdleCallback) {
            window.requestIdleCallback(() => {
                try {
                    fn();
                } catch (_) {}
            }, { timeout });
            return;
        }
        setTimeout(() => {
            try {
                fn();
            } catch (_) {}
        }, Math.min(timeout, 1200));
    };

    const routeFlags = {
        isHome: pathname === '/',
        isAbout: pathname === '/about',
        isAuth: pathname.startsWith('/auth'),
        isAdmin: pathname.startsWith('/admin'),
        isStudent: pathname.startsWith('/student'),
        isEducation: pathname.startsWith('/education'),
        isMainActivityDetail: /^\/activity\/\d+$/.test(pathname),
        isStudentActivityDetail: /^\/student\/activity\/\d+$/.test(pathname)
    };

    const routeScopes = {
        publicSite: routeFlags.isHome || routeFlags.isAbout || routeFlags.isEducation || routeFlags.isMainActivityDetail,
        auth: routeFlags.isAuth,
        admin: routeFlags.isAdmin,
        student: routeFlags.isStudent,
        activityDetail: routeFlags.isMainActivityDetail || routeFlags.isStudentActivityDetail,
    };

    const pageFlags = {
        hasLoginLink: document.querySelector('a[href="/auth/login"]') !== null,
        hasTooltip: document.querySelector('[data-bs-toggle="tooltip"]') !== null,
        hasChartCanvas: document.querySelector('#registrationChart, #collegeChart, #activityChart') !== null,
        hasAttendanceCheckin: document.getElementById('checkinForm') !== null,
        hasSearchForm: document.querySelector('form[data-search-form]') !== null,
        hasScrollableTable: document.querySelector('table.table-cell-scroll') !== null,
        hasStickyActionTable: document.querySelector('.table-responsive table') !== null,
        hasInlineNotificationBanner: document.querySelector('.notification-banner') !== null,
        hasDeleteConfirm: document.querySelector('.delete-confirm') !== null,
        hasCheckinForm: document.getElementById('checkin-form') !== null,
        hasCountdown: document.querySelector('[data-countdown]') !== null,
        hasLoginFormButton: document.querySelector('form[action*="/auth/login"] .login-btn, .login-btn') !== null
    };

    const scheduleIf = (condition, task, timeout = 900) => {
        if (!condition) {
            return;
        }
        runNonCritical(task, timeout);
    };

    // 非关键：登录态核对延后，优先释放首屏交互。
    runNonCritical(() => syncLoginStateFromServer(), 700);

    // 退出登录：强制带时间戳跳转，避免缓存/下拉交互导致首击未生效
    document.querySelectorAll('a[href*="/auth/logout"]').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            window.location.replace('/auth/logout?t=' + Date.now());
        });
    });

    // 若用户已登录但页面仍显示“登录”入口，点击时兜底跳转到对应面板
    if ((routeScopes.publicSite || routeScopes.auth) && pageFlags.hasLoginLink) {
        setupSmartLoginLink();
    }

    // 初始化Bootstrap提示工具
    if (pageFlags.hasTooltip) {
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // 首屏非关键初始化延后执行，优先让按钮点击与输入可用。
    scheduleIf((routeScopes.admin || routeScopes.student || routeScopes.publicSite) && pageFlags.hasChartCanvas, () => initializeCharts(), 1200);
    scheduleIf((routeScopes.admin || routeScopes.student) && pageFlags.hasAttendanceCheckin, () => setupAttendanceCheckin(), 900);
    scheduleIf((routeScopes.admin || routeScopes.student) && pageFlags.hasSearchForm, () => setupSearchOptimization(), 900);
    scheduleIf((routeScopes.admin || routeScopes.student) && pageFlags.hasScrollableTable, () => enableTableCellScroll(), 1200);
    scheduleIf((routeScopes.admin || routeScopes.student) && pageFlags.hasStickyActionTable, () => initStickyActionColumns(), 1200);

    // 通知系统（学生 + 游客公开通知）
    const isStudent = document.body.dataset.userLoggedIn === 'true' && document.body.dataset.userRole === 'student';

    const headerNoticeClose = document.getElementById('header-notice-close');
    if (headerNoticeClose) {
        headerNoticeClose.addEventListener('click', function() {
            dismissHeaderNotification(isStudent, true);
        });
    }

    if (isStudent) {
        // 学生：首屏先保证交互，未读通知稍后加载。
        runNonCritical(() => fetchUnreadNotifications(true), 1200);

        // 设置定时刷新（每10分钟，减少频率）
        setInterval(fetchUnreadNotifications, 10 * 60 * 1000);
    } else if (routeScopes.publicSite || routeScopes.auth || routeScopes.admin) {
        // 游客/管理员：公开通知延后加载，避免与首屏资源竞争。
        runNonCritical(() => fetchPublicNotifications(), 1200);
        setInterval(fetchPublicNotifications, 10 * 60 * 1000);
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

    // 以下属于增强体验逻辑，延后执行即可。
    scheduleIf((routeScopes.publicSite || routeScopes.auth || routeScopes.admin || routeScopes.student) && pageFlags.hasInlineNotificationBanner, () => displayNotifications(), 900);
    scheduleIf((routeScopes.admin || routeScopes.student) && pageFlags.hasDeleteConfirm, () => setupDeleteConfirmation(), 900);
    scheduleIf(routeScopes.activityDetail && pageFlags.hasCheckinForm, () => setupCheckinForm(), 900);
    scheduleIf((routeScopes.publicSite || routeScopes.student) && pageFlags.hasCountdown, () => setupCountdowns(), 1200);

    // 初始化Toast通知系统
    initToastSystem();
    
    // 初始化统一的加载系统
    initUnifiedLoadingSystem();

    // 重置所有按钮状态（解决浏览器返回问题）
    resetAllButtonStates();
    
    // 监听浏览器前进/后退事件
    window.addEventListener('pageshow', function(event) {
        // BFCache恢复时避免强制刷新，减少白屏与二次加载；只做状态修复。
        resetAllButtonStates();
        if (event.persisted) {
            runNonCritical(() => syncLoginStateFromServer(), 600);
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
    if (routeScopes.auth && pageFlags.hasLoginFormButton) {
        setupLoginButton();
    }

    // 初始化卡片倾斜动画（VanillaTilt）
    (function initCardTilt() {
        if (!routeFlags.isAbout) {
            return;
        }

        function loadVanillaTiltScript() {
            return new Promise((resolve, reject) => {
                if (typeof VanillaTilt !== 'undefined') {
                    resolve();
                    return;
                }

                const existed = document.querySelector('script[data-lib="vanilla-tilt"]');
                if (existed) {
                    existed.addEventListener('load', () => resolve(), { once: true });
                    existed.addEventListener('error', () => reject(new Error('vanilla-tilt load failed')), { once: true });
                    return;
                }

                const sources = [
                    'https://cdn.jsdelivr.net/npm/vanilla-tilt@1.8.0/dist/vanilla-tilt.min.js',
                    'https://unpkg.com/vanilla-tilt@1.8.0/dist/vanilla-tilt.min.js',
                    'https://cdn.bootcdn.net/ajax/libs/vanilla-tilt/1.8.0/vanilla-tilt.min.js'
                ];

                const tryLoad = (idx) => {
                    if (idx >= sources.length) {
                        reject(new Error('vanilla-tilt load failed'));
                        return;
                    }

                    const script = document.createElement('script');
                    let done = false;
                    const timeout = setTimeout(() => {
                        if (done) return;
                        done = true;
                        script.remove();
                        tryLoad(idx + 1);
                    }, 2500);

                    script.src = sources[idx];
                    script.async = true;
                    script.setAttribute('data-lib', 'vanilla-tilt');
                    script.onload = () => {
                        if (done) return;
                        done = true;
                        clearTimeout(timeout);
                        resolve();
                    };
                    script.onerror = () => {
                        if (done) return;
                        done = true;
                        clearTimeout(timeout);
                        script.remove();
                        tryLoad(idx + 1);
                    };
                    document.head.appendChild(script);
                };

                tryLoad(0);
            });
        }

        function applyTilt(tiltCards) {
            if (typeof VanillaTilt === 'undefined' || !tiltCards.length) {
                return;
            }
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

        // 移动端（触控/窄屏）不启用3D倾斜效果
        const isMobile = window.matchMedia('(max-width: 767px)').matches || window.matchMedia('(pointer:coarse)').matches;
        if (isMobile) return;

        const allCards = document.querySelectorAll('.card');
        // 仅对尺寸较小（宽高均 < 600px）的卡片启用倾斜，避免大容器晃动
        const tiltCards = Array.from(allCards).filter(c => {
            const rect = c.getBoundingClientRect();
            return rect.width < 600 && rect.height < 600;
        });
        if (!tiltCards.length) return;

        if (typeof VanillaTilt !== 'undefined') {
            applyTilt(tiltCards);
            return;
        }

        const lazyLoad = () => {
            loadVanillaTiltScript().then(() => applyTilt(tiltCards)).catch(() => {});
        };

        if (window.requestIdleCallback) {
            window.requestIdleCallback(lazyLoad, { timeout: 2500 });
        } else {
            setTimeout(lazyLoad, 1200);
        }
    })();
});

function enableTableCellScroll() {
    const isMobile = window.matchMedia('(max-width: 991.98px)').matches;
    if (!isMobile) {
        return;
    }

    const tables = document.querySelectorAll('table.table-cell-scroll');
    tables.forEach(table => {
        const cells = table.querySelectorAll('th, td');
        cells.forEach(cell => {
            const firstChild = cell.firstElementChild;
            if (
                firstChild &&
                firstChild.classList &&
                firstChild.classList.contains('cell-scroll') &&
                cell.children.length === 1
            ) {
                return;
            }

            const wrapper = document.createElement('div');
            wrapper.className = 'cell-scroll';

            while (cell.firstChild) {
                wrapper.appendChild(cell.firstChild);
            }

            cell.appendChild(wrapper);
        });
    });
}

async function syncLoginStateFromServer() {
    try {
        const body = document.body;
        if (!body) return;

        const pageLoggedIn = body.dataset.userLoggedIn === 'true';
        const response = await fetch('/utils/check_login_status', {
            credentials: 'include',
            cache: 'no-store',
            headers: {
                'Cache-Control': 'no-cache'
            }
        });

        if (!response.ok) return;

        const data = await response.json();
        const serverLoggedIn = !!data.is_logged_in;
        if (pageLoggedIn === serverLoggedIn) {
            sessionStorage.removeItem('login_state_reload_once');
            return;
        }

        // 防止极端情况下重复刷新
        if (sessionStorage.getItem('login_state_reload_once') === '1') return;
        sessionStorage.setItem('login_state_reload_once', '1');
        window.location.reload();
    } catch (e) {
        console.warn('登录态同步检查失败:', e);
    }
}

function setupSmartLoginLink() {
    document.querySelectorAll('a[href="/auth/login"]').forEach(link => {
        link.addEventListener('click', async function(e) {
            try {
                const resp = await fetch('/utils/check_login_status', {
                    credentials: 'include',
                    cache: 'no-store'
                });
                if (!resp.ok) return;
                const data = await resp.json();

                if (data && data.is_logged_in) {
                    e.preventDefault();
                    window.location.href = data.redirect_url || '/';
                }
            } catch (err) {
                console.warn('登录入口状态检查失败:', err);
            }
        });
    });
}

function initStickyActionColumns() {
    const wrappers = document.querySelectorAll('.table-responsive');

    wrappers.forEach(wrapper => {
        const table = wrapper.querySelector('table');
        if (!table) return;

        const headRow = table.querySelector('thead tr');
        if (!headRow) return;

        const headerCells = Array.from(headRow.children).filter(cell =>
            cell.tagName === 'TH' || cell.tagName === 'TD'
        );

        if (!headerCells.length) return;

        const actionIndex = headerCells.findIndex(cell => {
            const text = (cell.textContent || '').trim().toLowerCase();
            return text === '操作' || text === 'actions' || text.includes('操作');
        });

        if (actionIndex === -1) return;

        wrapper.classList.add('has-sticky-action');
        table.classList.add('table-has-sticky-action');

        table.querySelectorAll('tr').forEach(row => {
            const targetCell = row.children[actionIndex];
            if (targetCell) {
                targetCell.classList.add('sticky-action-col');
            }
        });
    });
}

// 统一的加载系统
function initUnifiedLoadingSystem() {
    // 创建全局加载动画
    createGlobalLoading();

    // 初始化请求状态跟踪器（统一管理按钮与全局loading生命周期）
    initRequestStateTracker();

    // 设置按钮加载处理
    setupButtonLoading();

    // 设置表单加载处理
    setupFormLoadingHandlers();

    // 设置AJAX加载处理
    setupAjaxLoadingHandlers();
}

// 统一请求状态跟踪器
function initRequestStateTracker() {
    if (window.RequestStateTracker) {
        return;
    }

    window.RequestStateTracker = {
        requestIdSeed: 0,
        pendingAction: null,
        inflightRequests: new Map(),

        isMobileLike: function() {
            try {
                return window.matchMedia('(max-width: 991.98px), (pointer: coarse)').matches;
            } catch (_) {
                return false;
            }
        },

        markPendingAction: function(button, loadingText = '处理中...') {
            if (!button || !document.body.contains(button)) {
                return;
            }

            this.pendingAction = {
                button,
                loadingText,
                createdAt: Date.now()
            };
        },

        consumePendingAction: function() {
            if (!this.pendingAction) {
                return null;
            }

            const action = this.pendingAction;
            this.pendingAction = null;

            if (!action.button || !document.body.contains(action.button)) {
                return null;
            }

            // 只消费最近的用户触发动作，避免误关联后台轮询请求
            if (Date.now() - action.createdAt > 1800) {
                return null;
            }

            return action;
        },

        beginRequest: function(meta = {}) {
            const id = ++this.requestIdSeed;
            const requestMeta = {
                button: meta.button || null,
                showGlobal: !!meta.showGlobal,
                allowMobileOverlay: !!meta.allowMobileOverlay,
                globalMessage: meta.globalMessage || '处理中...',
                mobileOverlayTimer: null,
                mobileOverlayShown: false
            };

            this.inflightRequests.set(id, requestMeta);

            if (requestMeta.button && window.ButtonLoadingManager) {
                window.ButtonLoadingManager.setLoading(requestMeta.button, meta.loadingText || '处理中...');
            }

            if (requestMeta.showGlobal && window.LoadingManager) {
                window.LoadingManager.show(requestMeta.globalMessage, false);
            } else if (requestMeta.allowMobileOverlay && this.isMobileLike() && window.LoadingManager) {
                // 移动端若请求超过阈值仍未完成，自动显示全屏loading，避免“无反馈”体感
                requestMeta.mobileOverlayTimer = setTimeout(() => {
                    if (!this.inflightRequests.has(id)) {
                        return;
                    }
                    requestMeta.mobileOverlayShown = true;
                    window.LoadingManager.show(requestMeta.globalMessage || '处理中...', false);
                }, 650);
            }

            return id;
        },

        endRequest: function(id) {
            const requestMeta = this.inflightRequests.get(id);
            if (!requestMeta) {
                return;
            }

            this.inflightRequests.delete(id);

            if (requestMeta.mobileOverlayTimer) {
                clearTimeout(requestMeta.mobileOverlayTimer);
                requestMeta.mobileOverlayTimer = null;
            }

            if (requestMeta.button && window.ButtonLoadingManager) {
                window.ButtonLoadingManager.clearLoading(requestMeta.button);
            }

            const hasOverlayInflight = Array.from(this.inflightRequests.values()).some(meta => meta.showGlobal || meta.mobileOverlayShown);
            if (!hasOverlayInflight && window.LoadingManager) {
                window.LoadingManager.hide();
            }
        },

        trackFetch: function(nativeFetch, input, init = {}, meta = {}) {
            const requestId = this.beginRequest({
                button: meta.button || null,
                loadingText: meta.loadingText || '处理中...',
                showGlobal: !!meta.showGlobal,
                allowMobileOverlay: !!meta.allowMobileOverlay,
                globalMessage: meta.globalMessage || '处理中...'
            });

            return nativeFetch(input, init).finally(() => {
                this.endRequest(requestId);
            });
        }
    };
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
    
    // 为链接添加全局加载动画监听（仅慢跳转时显示，避免快速切页闪烁）
    let navigationLoadingTimer = null;

    document.addEventListener('click', function(e) {
        const link = e.target.closest('a');
        if (!link) return;

        // 仅处理主按钮点击；带修饰键/中键通常是新标签打开，不应显示页面加载遮罩
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
            return;
        }

        // AI窗口区域点击不触发全局页面loading
        if (link.closest('.ai-chat-container') || link.closest('.ai-chat-button')) {
            return;
        }
        
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

            // 清理旧定时器，避免短时间多次点击产生叠加
            if (navigationLoadingTimer) {
                clearTimeout(navigationLoadingTimer);
                navigationLoadingTimer = null;
            }

            // 慢跳转才显示全局loading；快速导航直接交给浏览器切页
            navigationLoadingTimer = setTimeout(() => {
                if (window.LoadingManager && document.visibilityState === 'visible') {
                    window.LoadingManager.show('页面加载中...', false);
                }
            }, 320);
        }
    });

    // 页面离开或进入BFCache时清理定时器，避免历史页面残留触发
    window.addEventListener('pagehide', function() {
        if (navigationLoadingTimer) {
            clearTimeout(navigationLoadingTimer);
            navigationLoadingTimer = null;
        }
    });
}

// 统一的按钮加载处理
function setupButtonLoading() {
    // 按钮加载管理器
    window.ButtonLoadingManager = {
        loadingButtons: new Set(),
        loadingTimers: new Map(),

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
            const timeoutId = setTimeout(() => {
                this.clearLoading(button);
            }, 10000); // 10秒超时

            this.loadingTimers.set(button, timeoutId);
        },

        clearLoading: function(button) {
            if (!this.loadingButtons.has(button)) {
                return;
            }

            // 清除超时
            const timeoutId = this.loadingTimers.get(button);
            if (timeoutId) {
                clearTimeout(timeoutId);
                this.loadingTimers.delete(button);
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
            Array.from(this.loadingButtons).forEach(button => {
                this.clearLoading(button);
            });
        }
    };

    // 为按钮添加加载处理 - 更精确的检测
    document.addEventListener('click', function(e) {
        const button = e.target.closest('button, a.btn');
        if (!button) return;

        // 提交按钮交由 setupFormLoadingHandlers 处理，避免在浏览器表单校验前提前锁死按钮
        if (button.tagName === 'BUTTON' && button.type === 'submit' && button.form) {
            return;
        }

        const isAnchorButton = button.tagName === 'A';

        // 普通导航型 a.btn 不应触发“处理中”动画；仅允许显式声明 data-force-loading 的场景
        if (isAnchorButton && !button.hasAttribute('data-force-loading')) {
            return;
        }

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
        if (window.RequestStateTracker) {
            window.RequestStateTracker.markPendingAction(button, loadingText);
        }
    });
}

// 简化的表单加载处理
function setupFormLoadingHandlers() {
    document.addEventListener('submit', function(e) {
        const form = e.target;

        // 跳过特定表单
        if (form.hasAttribute('data-no-loading') ||
            form.hasAttribute('data-no-global-loading') ||
            form.classList.contains('no-loading')) {
            return;
        }

        // 带 confirm 的表单交互在用户确认前不显示加载，避免取消后卡在“提交中...”
        const inlineOnsubmit = form.getAttribute('onsubmit') || '';
        if (inlineOnsubmit.includes('confirm(')) {
            return;
        }

        // 若表单已被其它逻辑阻止提交，不进入加载态
        if (e.defaultPrevented) {
            return;
        }
        
        // 获取表单提交按钮
        const submitBtn = e.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
        if (!submitBtn) return;

        if (submitBtn.hasAttribute('data-no-loading') ||
            submitBtn.hasAttribute('data-no-global-loading') ||
            submitBtn.closest('[data-no-loading]') ||
            submitBtn.closest('[data-no-global-loading]')) {
            return;
        }

        // 下一帧再设置加载，确保浏览器先完成本次提交决策
        requestAnimationFrame(() => {
            if (e.defaultPrevented) {
                return;
            }

            // 确定加载文本
            let loadingText = '提交中...';
            if (form.action?.includes('/login')) loadingText = '登录中...';
            else if (form.action?.includes('/register')) loadingText = '注册中...';

            if (window.RequestStateTracker) {
                window.RequestStateTracker.markPendingAction(submitBtn, loadingText);
            }

            // 使用统一的按钮管理器
            window.ButtonLoadingManager.setLoading(submitBtn, loadingText);
        });
    });
}

// 简化的AJAX加载处理
function setupAjaxLoadingHandlers() {
    // 监听fetch请求
    const originalFetch = window.fetch;

    // 供页面内脚本逐步替换手写fetch，直接获得请求态loading收敛
    window.appFetchWithLoading = function(input, init = {}, meta = {}) {
        if (!window.RequestStateTracker) {
            return originalFetch.call(window, input, init);
        }

        return window.RequestStateTracker.trackFetch(
            originalFetch.bind(window),
            input,
            init,
            {
                button: meta.button || null,
                loadingText: meta.loadingText || '处理中...',
                showGlobal: !!meta.showGlobal,
                allowMobileOverlay: !!meta.allowMobileOverlay,
                globalMessage: meta.globalMessage || '处理中...'
            }
        );
    };

    window.fetch = function(...args) {
        const requestInput = args[0];
        const requestInit = args[1] || {};

        const url = typeof requestInput === 'string'
            ? requestInput
            : (requestInput && requestInput.url) || '';
        const requestMethod = String(
            requestInit.method || (requestInput && requestInput.method) || 'GET'
        ).toUpperCase();

        const lowPriorityPatterns = [
            '/student/api/notifications/unread',
            '/api/public-notifications',
            '/utils/check_login_status',
            '/api/statistics/'
        ];
        const isLowPriorityRequest = lowPriorityPatterns.some(pattern => url.includes(pattern));

        const aiEndpointPatterns = [
            '/activity/ai/',
            '/utils/ai_chat',
            '/api/ai/chat',
            '/api/ai_chat'
        ];
        const isAiEndpointRequest = aiEndpointPatterns.some(pattern => url.includes(pattern));

        const pendingAction = window.RequestStateTracker
            ? window.RequestStateTracker.consumePendingAction()
            : null;

        const isLongOpsRequest = url.includes('/admin/api/') && (url.includes('sync') || url.includes('backup') || url.includes('restore'));

        // 默认不再为普通短请求弹全局遮罩，避免“频繁闪现”；AI请求只保留按钮动画。
        const showGlobalLoading = !isLowPriorityRequest && !isAiEndpointRequest && isLongOpsRequest;
        const allowMobileOverlay = !isAiEndpointRequest && showGlobalLoading;

        const requestId = window.RequestStateTracker
            ? window.RequestStateTracker.beginRequest({
                button: pendingAction ? pendingAction.button : null,
                loadingText: pendingAction ? pendingAction.loadingText : '处理中...',
                showGlobal: showGlobalLoading,
                allowMobileOverlay: allowMobileOverlay,
                globalMessage: requestMethod === 'GET' ? '加载中...' : '处理中...'
            })
            : null;

        return originalFetch.apply(this, args).finally(() => {
            if (window.RequestStateTracker && requestId !== null) {
                window.RequestStateTracker.endRequest(requestId);
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
        toast.className = `toast align-items-center border-0 show app-toast-modern`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.id = toastId;
        
        // 现代极致紧凑图标映射 (Apple/Vercel 风格)
        let iconHtml = '';
        let iconColor = '';
        let iconBg = '';
        switch(type) {
            case 'success':
                iconHtml = `<svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
                iconColor = '#10b981'; // 绿
                iconBg = 'rgba(16, 185, 129, 0.15)';
                break;
            case 'error':
                iconHtml = `<svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
                iconColor = '#ef4444'; // 红
                iconBg = 'rgba(239, 68, 68, 0.15)';
                break;
            case 'warning':
                iconHtml = `<svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
                iconColor = '#f59e0b'; // 橙
                iconBg = 'rgba(245, 158, 11, 0.15)';
                break;
            case 'info':
            default:
                iconHtml = `<svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
                iconColor = '#3b82f6'; // 蓝
                iconBg = 'rgba(59, 130, 246, 0.15)';
                break;
        }
        
        toast.innerHTML = `
            <div class="d-flex align-items-center" style="padding: 6px 12px 6px 8px; cursor: pointer;" title="点击关闭">
                <div style="color: ${iconColor}; background: ${iconBg}; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 8px; flex-shrink: 0;">
                    ${iconHtml}
                </div>
                <div class="toast-body p-0 m-0" style="color: #334155; font-size: 0.82rem; font-weight: 500; text-shadow: none; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    ${message}
                </div>
            </div>
        `;
        
        // 添加到容器
        toastContainer.appendChild(toast);
        
        // 添加动画
        toast.style.transform = 'translateY(100%)';
        toast.style.opacity = '0';
        toast.style.transition = 'all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
        
        // 触发重排，然后应用动画
        setTimeout(() => {
            toast.style.transform = 'translateY(0)';
            toast.style.opacity = '1';
        }, 10);
        
        // 点击整个toast任意位置直接关闭，不仅限于关闭按钮（更适合这种紧凑设计）
        toast.addEventListener('click', () => {
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
            
            fetch('/student/api/attendance/checkin', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
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
const HEADER_NOTICE_DISMISSED_KEY = 'header_notice_dismissed_ids_v1';

function syncNavbarWithHeaderNotice(isVisible) {
    const noticeBar = document.getElementById('header-notice-bar');
    if (!noticeBar) {
        return;
    }

    if (isVisible) {
        const offset = noticeBar.offsetHeight + 10;
        document.documentElement.style.setProperty('--header-notice-offset', `${offset}px`);
        document.body.classList.add('header-notice-open');
    } else {
        document.body.classList.remove('header-notice-open');
        document.documentElement.style.setProperty('--header-notice-offset', '0px');
    }
}

function getDismissedHeaderNoticeIds() {
    try {
        const raw = localStorage.getItem(HEADER_NOTICE_DISMISSED_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        return [];
    }
}

function persistDismissedHeaderNoticeId(notificationId) {
    if (!notificationId) {
        return;
    }

    const ids = getDismissedHeaderNoticeIds();
    const idStr = String(notificationId);
    if (!ids.includes(idStr)) {
        ids.push(idStr);
    }

    const compact = ids.slice(-100);
    localStorage.setItem(HEADER_NOTICE_DISMISSED_KEY, JSON.stringify(compact));
}

function isHeaderNoticeDismissed(notificationId) {
    if (!notificationId) {
        return false;
    }

    const ids = getDismissedHeaderNoticeIds();
    return ids.includes(String(notificationId));
}

// 获取未读通知
function fetchUnreadNotifications(force = false) {
    const now = Date.now();

    // 防止重复请求
    if (isFetchingNotifications) {
        if (force) {
            setTimeout(() => fetchUnreadNotifications(true), 500);
        } else {
            console.log('通知获取正在进行中，跳过此次请求');
        }
        return;
    }

    // 频率限制
    if (!force && now - lastNotificationFetch < NOTIFICATION_FETCH_COOLDOWN) {
        console.log('通知获取频率限制，跳过此次请求');
        return;
    }

    isFetchingNotifications = true;
    lastNotificationFetch = now;

    fetch('/student/api/notifications/unread', {
        cache: 'no-store',
        headers: {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
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
                const visibleNotifications = (data.notifications || []).filter(n => !isHeaderNoticeDismissed(n.id));

                // 更新通知徽章
                updateNotificationBadge(visibleNotifications.length);

                // 显示头部通知条
                if (visibleNotifications.length > 0) {
                    showNotificationBanner(visibleNotifications[0], true);
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

function fetchPublicNotifications() {
    fetch('/api/public-notifications')
        .then(response => {
            if (!response.ok) {
                throw new Error('公开通知请求失败');
            }
            return response.json();
        })
        .then(data => {
            if (!data.success) {
                return;
            }

            const visibleNotifications = (data.notifications || []).filter(n => !isHeaderNoticeDismissed(n.id));
            if (visibleNotifications.length > 0) {
                showNotificationBanner(visibleNotifications[0], false);
            }
        })
        .catch(error => {
            console.error('获取公开通知失败:', error);
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
function showNotificationBanner(notification, allowMarkRead = false) {
    const noticeBar = document.getElementById('header-notice-bar');
    const noticeContent = document.getElementById('header-notice-content');
    const noticeLink = document.getElementById('header-notice-link');

    if (!noticeBar || !noticeContent || !noticeLink) {
        return;
    }

    if (window.currentHeaderNotificationId === notification.id) {
        return;
    }

    window.currentHeaderNotificationId = notification.id;
    window.currentHeaderNotificationAutoTimer && clearTimeout(window.currentHeaderNotificationAutoTimer);

    const titleText = (notification.title || '').toString();
    const contentText = (notification.content || '').toString();
    const fullText = `${titleText}：${contentText.replace(/<[^>]*>/g, '')}`;

    const safeTitle = escapeNoticeText(titleText);
    const safeContent = sanitizeNoticeContentHtml(contentText);
    noticeContent.innerHTML = `<span class="header-notice-title">${safeTitle}：</span>${safeContent}`;
    noticeContent.classList.remove('is-scrolling');
    noticeContent.style.removeProperty('--ticker-duration');

    if (allowMarkRead) {
        noticeLink.style.cursor = 'pointer';
        noticeLink.onclick = function(e) {
            const inlineLink = e.target.closest('.header-notice-inline-link');
            if (inlineLink) {
                markNotificationAsRead(notification.id);
                return;
            }
            markNotificationAsRead(notification.id).then(result => {
                if (!result || result.deleted) {
                    return;
                }
                window.location.href = `/student/notification/${notification.id}`;
            });
        };
        noticeLink.onkeydown = function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                markNotificationAsRead(notification.id).then(result => {
                    if (!result || result.deleted) {
                        return;
                    }
                    window.location.href = `/student/notification/${notification.id}`;
                });
            }
        };
    } else {
        noticeLink.style.cursor = 'default';
        noticeLink.onclick = function(e) {
            const inlineLink = e.target.closest('.header-notice-inline-link');
            if (inlineLink) {
                return;
            }
        };
        noticeLink.onkeydown = null;
    }

    noticeBar.classList.remove('d-none');
    syncNavbarWithHeaderNotice(true);

    const shouldScroll = fullText.length > 46;
    const tickerDuration = Math.min(20, Math.max(10, fullText.length / 7));

    if (shouldScroll) {
        noticeContent.style.setProperty('--ticker-duration', `${tickerDuration}s`);
        requestAnimationFrame(() => {
            noticeContent.classList.add('is-scrolling');
        });
    }

    const autoHideDelay = shouldScroll ? Math.max(30000, tickerDuration * 3000) : 12500;

    window.currentHeaderNotificationAutoTimer = setTimeout(() => {
        dismissHeaderNotification(false, false);
    }, autoHideDelay);
}

function escapeNoticeText(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function sanitizeNoticeHref(href) {
    const value = String(href || '').trim();
    if (/^(https?:\/\/|mailto:|tel:|\/)/i.test(value)) {
        return value;
    }
    return '#';
}

function sanitizeNoticeContentHtml(rawContent) {
    const container = document.createElement('div');
    container.innerHTML = String(rawContent || '');

    function walk(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            return escapeNoticeText(node.textContent || '').replace(/\n/g, '<br>');
        }
        if (node.nodeType !== Node.ELEMENT_NODE) {
            return '';
        }

        const tag = node.tagName.toLowerCase();
        if (tag === 'br') {
            return '<br>';
        }

        const children = Array.from(node.childNodes).map(walk).join('');
        if (tag === 'a') {
            const href = sanitizeNoticeHref(node.getAttribute('href'));
            const target = node.getAttribute('target') === '_blank' ? ' target="_blank" rel="noopener noreferrer"' : '';
            return `<a href="${escapeNoticeText(href)}" class="header-notice-inline-link"${target}>${children || '查看详情'}</a>`;
        }

        return children;
    }

    return Array.from(container.childNodes).map(walk).join('');
}

function dismissHeaderNotification(markAsRead = false, userDismissed = false) {
    const noticeBar = document.getElementById('header-notice-bar');
    const noticeContent = document.getElementById('header-notice-content');
    if (!noticeBar || !noticeContent) {
        return;
    }

    const currentId = window.currentHeaderNotificationId;
    if (markAsRead && currentId) {
        markNotificationAsRead(currentId);
    }

    if (userDismissed && currentId) {
        persistDismissedHeaderNoticeId(currentId);
    }

    noticeBar.classList.add('d-none');
    syncNavbarWithHeaderNotice(false);
    noticeContent.classList.remove('is-scrolling');
    noticeContent.innerHTML = '';
    window.currentHeaderNotificationId = null;

    if (window.currentHeaderNotificationAutoTimer) {
        clearTimeout(window.currentHeaderNotificationAutoTimer);
        window.currentHeaderNotificationAutoTimer = null;
    }
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
    return fetch(`/student/notification/${notificationId}/mark_read`, {
        method: 'POST',
        cache: 'no-store',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken() // 获取CSRF令牌的函数
        }
    })
    .then(response => {
        if (response.status === 410) {
            return response.json().then(data => {
                throw { code: 'deleted', data };
            });
        }

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

            // 以服务端结果为准，避免跨页残留旧通知状态
            fetchUnreadNotifications(true);
        }

        return data;
    })
    .catch(error => {
        if (error && error.code === 'deleted') {
            persistDismissedHeaderNoticeId(notificationId);
            if (window.currentHeaderNotificationId === notificationId) {
                dismissHeaderNotification(false, false);
            }
            fetchUnreadNotifications(true);
            return { success: false, deleted: true };
        }

        console.error('标记通知已读失败:', error);
        return { success: false };
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
            
            fetch('/student/api/attendance/checkin', {
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
    const now = Date.now();
    if (window.__lastButtonResetAt && now - window.__lastButtonResetAt < 250) {
        return;
    }
    window.__lastButtonResetAt = now;

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

