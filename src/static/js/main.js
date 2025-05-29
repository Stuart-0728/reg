// 主要JavaScript功能
document.addEventListener('DOMContentLoaded', function() {
    // 初始化工具提示
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });

    // 活动提醒功能
    if (document.querySelector('.notification-container')) {
        fetchNotifications();
    }

    // 图表初始化
    initializeCharts();

    // 自动隐藏提示消息
    setTimeout(function() {
        var alerts = document.querySelectorAll('.alert');
        alerts.forEach(function(alert) {
            var bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);
});

// 获取通知
function fetchNotifications() {
    fetch('/utils/notifications')
        .then(response => response.json())
        .then(data => {
            const container = document.querySelector('.notification-container');
            if (!container) return;
            
            if (data.deadline_soon && data.deadline_soon.length > 0) {
                let html = '<div class="list-group">';
                data.deadline_soon.forEach(item => {
                    html += `
                        <a href="/student/activity/${item.id}" class="list-group-item list-group-item-action">
                            <div class="d-flex w-100 justify-content-between">
                                <h6 class="mb-1">${item.title}</h6>
                                <small class="text-danger"><i class="fas fa-clock"></i> ${item.type}</small>
                            </div>
                            <small>${item.time}</small>
                        </a>
                    `;
                });
                html += '</div>';
                container.innerHTML = html;
                
                // 更新通知徽章
                const badge = document.querySelector('.notification-badge .badge');
                if (badge) {
                    badge.textContent = data.deadline_soon.length;
                    badge.style.display = 'block';
                }
            } else {
                container.innerHTML = '<p class="text-muted">暂无通知</p>';
                
                // 隐藏通知徽章
                const badge = document.querySelector('.notification-badge .badge');
                if (badge) {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(error => console.error('获取通知失败:', error));
}

// 初始化图表
function initializeCharts() {
    // 注册人数统计图表
    const registrationChart = document.getElementById('registrationChart');
    if (registrationChart) {
        fetch('/utils/api/statistics?type=registrations_by_date')
            .then(response => response.json())
            .then(data => {
                new Chart(registrationChart, {
                    type: 'line',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            label: '每日报名人数',
                            data: data.data,
                            backgroundColor: 'rgba(30, 136, 229, 0.2)',
                            borderColor: 'rgba(30, 136, 229, 1)',
                            borderWidth: 2,
                            tension: 0.3,
                            pointRadius: 3
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
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
            .catch(error => console.error('获取报名统计数据失败:', error));
    }

    // 学院分布图表
    const collegeChart = document.getElementById('collegeChart');
    if (collegeChart) {
        fetch('/utils/api/statistics?type=registrations_by_college')
            .then(response => response.json())
            .then(data => {
                new Chart(collegeChart, {
                    type: 'doughnut',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            data: data.data,
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
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'right'
                            }
                        }
                    }
                });
            })
            .catch(error => console.error('获取学院分布数据失败:', error));
    }

    // 活动状态图表
    const activityStatusChart = document.getElementById('activityStatusChart');
    if (activityStatusChart) {
        fetch('/utils/api/statistics?type=activities_by_status')
            .then(response => response.json())
            .then(data => {
                new Chart(activityStatusChart, {
                    type: 'pie',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            data: data.data,
                            backgroundColor: [
                                'rgba(76, 175, 80, 0.7)',
                                'rgba(33, 150, 243, 0.7)',
                                'rgba(244, 67, 54, 0.7)'
                            ],
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false
                    }
                });
            })
            .catch(error => console.error('获取活动状态数据失败:', error));
    }
}

// 活动签到功能
function checkInStudent(activityId) {
    const studentId = document.getElementById('studentIdInput').value;
    if (!studentId) {
        alert('请输入学号');
        return;
    }
    
    document.getElementById('checkInForm').submit();
}

// 导出报名信息
function exportRegistrations(activityId) {
    window.location.href = `/admin/activity/${activityId}/export`;
}

// 确认删除活动
function confirmDeleteActivity(activityId, activityTitle) {
    if (confirm(`确定要删除活动"${activityTitle}"吗？此操作不可撤销。`)) {
        document.getElementById(`deleteActivityForm-${activityId}`).submit();
    }
}

// 确认取消报名
function confirmCancelRegistration(activityId, activityTitle) {
    if (confirm(`确定要取消报名活动"${activityTitle}"吗？`)) {
        document.getElementById(`cancelRegistrationForm-${activityId}`).submit();
    }
}

// 倒计时功能
function startCountdown(elementId, targetDate) {
    const countdownElement = document.getElementById(elementId);
    if (!countdownElement) return;
    
    const targetTime = new Date(targetDate).getTime();
    
    const updateCountdown = function() {
        const now = new Date().getTime();
        const distance = targetTime - now;
        
        if (distance < 0) {
            countdownElement.innerHTML = '已截止';
            return;
        }
        
        const days = Math.floor(distance / (1000 * 60 * 60 * 24));
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((distance % (1000 * 60)) / 1000);
        
        countdownElement.innerHTML = `${days}天 ${hours}小时 ${minutes}分 ${seconds}秒`;
    };
    
    updateCountdown();
    setInterval(updateCountdown, 1000);
}
