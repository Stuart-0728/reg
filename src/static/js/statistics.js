document.addEventListener('DOMContentLoaded', function() {
    initializeCharts();
});

function initializeCharts() {
    // 设置全局Chart.js配置
    Chart.defaults.font.family = "'Segoe UI', 'Microsoft YaHei', sans-serif";
    Chart.defaults.color = '#6c757d';
    Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(0, 0, 0, 0.7)';
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 6;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    
    // 首先尝试带前缀的API路径
    tryFetchStats();
    tryFetchExtStats();
}

// 尝试获取基本统计数据
function tryFetchStats() {
    fetch('/admin/api/statistics')
        .then(response => {
            if (!response.ok) {
                // 如果带前缀的路径失败，尝试不带前缀的路径
                return fetch('/api/statistics');
            }
            return response;
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            renderBasicCharts(data);
        })
        .catch(error => {
            console.error('加载统计数据失败:', error);
            showChartError('registrationChart');
            showChartError('participationChart');
            showChartError('monthlyChart');
        });
}

// 尝试获取扩展统计数据
function tryFetchExtStats() {
    fetch('/admin/api/statistics_ext')
        .then(response => {
            if (!response.ok) {
                // 如果带前缀的路径失败，尝试不带前缀的路径
                return fetch('/api/statistics_ext');
            }
            return response;
        })
        .then(response => response.json())
        .then(ext => {
            if (ext.error) {
                throw new Error(ext.error);
            }
            renderExtCharts(ext);
        })
        .catch(error => {
            console.error('加载扩展统计数据失败:', error);
            showChartError('tagHeatChart');
            showChartError('pointsDistChart');
            showChartError('registrationTrendChart');
        });
}

// 显示图表加载错误
function showChartError(chartId) {
    const canvas = document.getElementById(chartId);
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = '14px "Microsoft YaHei", sans-serif';
        ctx.fillStyle = '#dc3545';
        ctx.textAlign = 'center';
        ctx.fillText('加载数据失败，请刷新页面重试', canvas.width/2, canvas.height/2);
    }
}

// 渲染基础图表
function renderBasicCharts(data) {
    // 活动报名统计图表
    const registrationCtx = document.getElementById('registrationChart').getContext('2d');
    new Chart(registrationCtx, {
        type: 'doughnut',
        data: {
            labels: data.registration_stats.labels,
            datasets: [{
                data: data.registration_stats.data,
                backgroundColor: [
                    'rgba(54, 162, 235, 0.8)',
                    'rgba(75, 192, 192, 0.8)',
                    'rgba(255, 99, 132, 0.8)'
                ],
                borderColor: [
                    'rgba(54, 162, 235, 1)',
                    'rgba(75, 192, 192, 1)',
                    'rgba(255, 99, 132, 1)'
                ],
                borderWidth: 2,
                hoverOffset: 15
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: '65%',
            layout: {
                padding: 20
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 15,
                        boxWidth: 12,
                        boxHeight: 12
                    }
                },
                title: {
                    display: true,
                    text: '活动状态分布',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: {
                        top: 10,
                        bottom: 20
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.raw || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            },
            animation: {
                animateScale: true,
                animateRotate: true,
                duration: 1000
            }
        }
    });

    // 学生参与度图表
    const participationCtx = document.getElementById('participationChart').getContext('2d');
    new Chart(participationCtx, {
        type: 'pie',
        data: {
            labels: data.participation_stats.labels,
            datasets: [{
                data: data.participation_stats.data,
                backgroundColor: [
                    'rgba(75, 192, 192, 0.8)',
                    'rgba(255, 99, 132, 0.8)'
                ],
                borderColor: [
                    'rgba(75, 192, 192, 1)',
                    'rgba(255, 99, 132, 1)'
                ],
                borderWidth: 2,
                hoverOffset: 15
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            layout: {
                padding: 20
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 15,
                        boxWidth: 12,
                        boxHeight: 12
                    }
                },
                title: {
                    display: true,
                    text: '学生参与情况',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: {
                        top: 10,
                        bottom: 20
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.raw || 0;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            },
            animation: {
                animateScale: true,
                animateRotate: true,
                duration: 1000
            }
        }
    });

    // 月度统计图表 - 使用双Y轴解决数量级不同的问题
    const monthlyCtx = document.getElementById('monthlyChart').getContext('2d');
    new Chart(monthlyCtx, {
        type: 'bar',
        data: {
            labels: data.monthly_stats.labels,
            datasets: [
                {
                    label: '活动数量',
                    data: data.monthly_stats.activities,
                    backgroundColor: 'rgba(54, 162, 235, 0.7)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1,
                    borderRadius: 4,
                    yAxisID: 'y-activities'
                },
                {
                    label: '报名人数',
                    data: data.monthly_stats.registrations,
                    backgroundColor: 'rgba(255, 99, 132, 0.7)',
                    borderColor: 'rgba(255, 99, 132, 1)',
                    borderWidth: 1,
                    borderRadius: 4,
                    yAxisID: 'y-registrations'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            layout: {
                padding: {
                    top: 10,
                    right: 25,
                    bottom: 10,
                    left: 10
                }
            },
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        padding: 15,
                        boxWidth: 12,
                        boxHeight: 12
                    }
                },
                title: {
                    display: true,
                    text: '月度统计',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: {
                        top: 10,
                        bottom: 20
                    }
                }
            },
            scales: {
                'y-activities': {
                    beginAtZero: true,
                    type: 'linear',
                    position: 'left',
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        precision: 0
                    },
                    title: {
                        display: true,
                        text: '活动数量'
                    }
                },
                'y-registrations': {
                    beginAtZero: true,
                    type: 'linear',
                    position: 'right',
                    grid: {
                        display: false
                    },
                    ticks: {
                        precision: 0
                    },
                    title: {
                        display: true,
                        text: '报名人数'
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    title: {
                        display: true,
                        text: '月份'
                    }
                }
            }
        }
    });
}

// 渲染扩展图表
function renderExtCharts(ext) {
    // 标签热度图表
    const tagHeatCtx = document.getElementById('tagHeatChart').getContext('2d');
    new Chart(tagHeatCtx, {
        type: 'bar',
        data: {
            labels: ext.tag_heat.labels,
            datasets: [{
                label: '选择次数',
                data: ext.tag_heat.data,
                backgroundColor: 'rgba(255, 206, 86, 0.7)',
                borderColor: 'rgba(255, 206, 86, 1)',
                borderWidth: 1,
                borderRadius: 4,
                hoverBackgroundColor: 'rgba(255, 206, 86, 0.9)'
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: true,
            layout: {
                padding: 10
            },
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: '标签热度（按学生选择次数）',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: {
                        top: 10,
                        bottom: 20
                    }
                }
            },
            scales: {
                y: {
                    grid: {
                        display: false
                    }
                },
                x: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        precision: 0
                    },
                    title: {
                        display: true,
                        text: '选择次数'
                    }
                }
            }
        }
    });

    // 积分分布图表
    const pointsDistCtx = document.getElementById('pointsDistChart').getContext('2d');
    
    // 计算百分比数据用于标签显示
    const total = ext.points_dist.data.reduce((acc, curr) => acc + curr, 0);
    const percentages = ext.points_dist.data.map(value => total > 0 ? Math.round((value / total) * 100) : 0);
    
    new Chart(pointsDistCtx, {
        type: 'bar',
        data: {
            labels: ext.points_dist.labels,
            datasets: [{
                label: '学生数',
                data: ext.points_dist.data,
                backgroundColor: 'rgba(153, 102, 255, 0.7)',
                borderColor: 'rgba(153, 102, 255, 1)',
                borderWidth: 1,
                borderRadius: 4,
                hoverBackgroundColor: 'rgba(153, 102, 255, 0.9)'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            layout: {
                padding: 10
            },
            plugins: {
                legend: { display: false },
                title: { 
                    display: true, 
                    text: '学生积分分布',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: {
                        top: 10,
                        bottom: 20
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.raw || 0;
                            const percentage = percentages[context.dataIndex];
                            return `学生数: ${value} (${percentage}%)`;
                        }
                    }
                }
            },
            scales: { 
                y: { 
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        precision: 0
                    },
                    title: {
                        display: true,
                        text: '学生数量'
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    title: {
                        display: true,
                        text: '积分区间'
                    }
                }
            }
        }
    });

    // 学生注册趋势图表
    if (ext.registration_trend && ext.registration_trend.labels) {
        const trendCtx = document.getElementById('registrationTrendChart').getContext('2d');
        new Chart(trendCtx, {
            type: 'line',
            data: {
                labels: ext.registration_trend.labels,
                datasets: [{
                    label: '注册人数',
                    data: ext.registration_trend.data,
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                layout: {
                    padding: 10
                },
                plugins: {
                    legend: { display: false },
                    title: { 
                        display: true, 
                        text: '30天内新注册学生趋势',
                        font: {
                            size: 16,
                            weight: 'bold'
                        },
                        padding: {
                            top: 10,
                            bottom: 20
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        },
                        ticks: {
                            precision: 0
                        },
                        title: {
                            display: true,
                            text: '注册人数'
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        },
                        title: {
                            display: true,
                            text: '日期'
                        },
                        ticks: {
                            maxTicksLimit: 7
                        }
                    }
                }
            }
        });
    }
}