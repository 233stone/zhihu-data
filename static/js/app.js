// ---------------- 基础导航逻辑 ----------------
function switchTab(tabId, navElem = null) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    document.getElementById(`tab-${tabId}`).classList.add('active');
    const activeNav = navElem || document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    if (activeNav) activeNav.classList.add('active');

    // 控制二级侧边栏显隐：仅在"dashboard"时显示
    const secondarySidebar = document.getElementById('secondarySidebar');
    if (tabId === 'dashboard') {
        secondarySidebar.classList.remove('hidden');
    } else {
        secondarySidebar.classList.add('hidden');
    }

    if (tabId === 'dashboard') loadDashboard();
    if (tabId === 'articles') loadArticlesTable();
    if (tabId === 'settings') loadConfig();
}

function setSidebarCollapsed(collapsed) {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    const toggleBtn = document.getElementById('sidebarToggleBtn');
    toggleBtn.innerText = collapsed ? '»' : '«';
    toggleBtn.title = collapsed ? '展开导航' : '折叠导航';
    localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
}

function toggleSidebar() {
    const collapsed = document.body.classList.contains('sidebar-collapsed');
    setSidebarCollapsed(!collapsed);
}

// ---------------- 全局变量 ----------------
let currentDays = 1;
let currentTimeFilter = 'today';
let currentMetric = 'pv';
let currentArticleToken = '';  // 空字符串 = 总览
let chartInstance = null;
let tableData = [];
let currentSortCol = '';
let sortAsc = false;
let allArticles = [];  // 缓存文章列表用于搜索过滤

// ---------------- 初始化 ----------------
window.onload = () => {
    setSidebarCollapsed(localStorage.getItem('sidebarCollapsed') === '1');
    loadArticleSubNav();
    loadDashboard();
};

// ---------------- 格式化辅助 ----------------
function parsePercent(str) {
    if (!str) return 0;
    return parseFloat(str.replace('%', ''));
}

function getLocalDateStr(dateObj = new Date()) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function shiftDate(baseDate, deltaDays) {
    const shifted = new Date(baseDate);
    shifted.setDate(shifted.getDate() + deltaDays);
    return shifted;
}

function getSelectedSingleDayDate() {
    if (currentTimeFilter === 'yesterday') {
        return getLocalDateStr(shiftDate(new Date(), -1));
    }
    return getLocalDateStr();
}

function getTrendRequestDays() {
    if (currentTimeFilter === 'yesterday') return 2;
    if (currentTimeFilter === 'today') return 1;
    return currentDays;
}

function getSummaryDate() {
    return currentTimeFilter === 'yesterday' ? getSelectedSingleDayDate() : getLocalDateStr();
}

function setTimeFilterState(filterKey, days) {
    const targetBtn = Array.from(document.querySelectorAll('.time-filter-btn'))
        .find(btn =>
            btn.getAttribute('data-filter') === filterKey &&
            Number(btn.getAttribute('data-days')) === Number(days)
        );
    if (!targetBtn) return;
    document.querySelectorAll('.time-filter-btn').forEach(btn => btn.classList.remove('active'));
    targetBtn.classList.add('active');
    currentTimeFilter = filterKey;
    currentDays = Number(days);
    document.getElementById('chart-title-days').innerText = targetBtn.getAttribute('data-label') || '';
}

async function loadArticleSubNav() {
    try {
        const res = await fetch('/api/articles');
        allArticles = await res.json();
        renderArticleList(allArticles);
    } catch (e) {
        console.error('加载文章导航失败', e);
    }
}

function renderArticleList(articles) {
    const container = document.getElementById('articleSubMenu');
    // 保留第一个"总览"项
    const firstChild = container.firstElementChild;
    container.innerHTML = '';
    firstChild.dataset.token = '';
    firstChild.classList.toggle('active', !currentArticleToken);
    container.appendChild(firstChild);
    articles.forEach(article => {
        const item = document.createElement('li');
        item.className = 'secondary-sidebar-item';
        if (article.token === currentArticleToken) {
            item.className += ' active';
        }
        item.dataset.token = article.token;
        item.title = article.title;
        item.innerText = article.title;
        item.onclick = function () { switchArticle(article.token, this); };
        container.appendChild(item);
    });
}

function filterArticleList() {
    const keyword = document.getElementById('articleSearchInput').value.trim().toLowerCase();
    if (!keyword) {
        renderArticleList(allArticles);
        return;
    }
    const filtered = allArticles.filter(a => a.title.toLowerCase().includes(keyword));
    renderArticleList(filtered);
}

function switchArticle(token, elem) {
    document.querySelectorAll('.secondary-sidebar-item').forEach(el => el.classList.remove('active'));
    elem.classList.add('active');
    currentArticleToken = token;
    // 更新标题
    const titleEl = document.querySelector('.page-title');
    if (token) {
        titleEl.innerText = elem.title || elem.innerText;
        // 切换到单篇时，默认展示今天
        setTimeFilterState('today', 1);
    } else {
        titleEl.innerText = '整体数据总览';
    }
    loadDashboard();
}

async function goToArticleData(token) {
    switchTab('dashboard');
    if (!allArticles.length) {
        await loadArticleSubNav();
    }

    let targetItem = Array.from(document.querySelectorAll('.secondary-sidebar-item'))
        .find(item => item.dataset.token === token);
    if (!targetItem) {
        await loadArticleSubNav();
        targetItem = Array.from(document.querySelectorAll('.secondary-sidebar-item'))
            .find(item => item.dataset.token === token);
    }

    if (!targetItem) {
        alert('未找到对应文章，可能已被删除。');
        return;
    }

    switchArticle(token, targetItem);
    targetItem.scrollIntoView({ block: 'nearest' });
}

// ---------------- [模块1] 数据看板 ----------------
function filterTime(btnElem, filterKey, days) {
    setTimeFilterState(filterKey, days);
    loadDashboard();
}

function switchChartMetric(metric, btnElem) {
    document.querySelectorAll('.chart-actions button').forEach(b => b.classList.remove('active'));
    btnElem.classList.add('active');
    currentMetric = metric;
    renderChart();
}

async function loadDashboard() {
    try {
        const dateStr = getSummaryDate();
        const tokenParam = currentArticleToken ? `&token=${currentArticleToken}` : '';

        // 获取总览/单篇文章的汇总数据
        const sumRes = await fetch(`/api/stats/summary?date=${dateStr}${tokenParam}`);
        const sumData = await sumRes.json();

        document.getElementById('card-pv').innerText = (sumData.total_pv || 0).toLocaleString();
        document.getElementById('card-upvote').innerText = (sumData.total_upvote || 0).toLocaleString();
        document.getElementById('card-comment').innerText = (sumData.total_comment || 0).toLocaleString();
        document.getElementById('card-collect').innerText = (sumData.total_collect || 0).toLocaleString();
        document.getElementById('card-share').innerText = (sumData.total_share || 0).toLocaleString();

        document.getElementById('card-finish').innerText = sumData.avg_finish_rate;
        document.getElementById('card-clickrate').innerText = sumData.click_rate;

        // 获取趋势数据（带 token 筛选）
        const trendTokenParam = currentArticleToken ? `&token=${currentArticleToken}` : '';
        const trendRes = await fetch(`/api/stats/trend?days=${getTrendRequestDays()}${trendTokenParam}`);
        window.trendDataRaw = await trendRes.json();

        renderChart();
    } catch (e) {
        console.error('加载面板失败', e);
    }
}

function renderChart() {
    if (!window.trendDataRaw) return;

    let labels = [];
    let dataPoints = [];

    if (currentTimeFilter === 'today' || currentTimeFilter === 'yesterday') {
        // Single-day mode: show intraday points with HH:mm on the X axis.
        const targetDate = getSelectedSingleDayDate();
        const singleDayData = window.trendDataRaw.filter(item => {
            // fetch_time format: "YYYY-MM-DD HH:MM:SS"
            return item.fetch_time && item.fetch_time.startsWith(targetDate);
        });

        labels = singleDayData.map(item => {
            // Extract HH:mm.
            const timePart = item.fetch_time.split(' ')[1] || '';
            return timePart.substring(0, 5);
        });
        dataPoints = singleDayData.map(item => {
            if (currentMetric === 'pv') return item.today_pv;
            if (currentMetric === 'upvote') return item.today_upvote;
            if (currentMetric === 'collect') return item.today_collect;
            return 0;
        });
    } else {
        // 多天模式：按天去重，取每天最后一条
        const dailyMap = {};
        window.trendDataRaw.forEach(item => {
            const date = item.today_date;
            if (!date) return;
            dailyMap[date] = item;
        });

        labels = Object.keys(dailyMap).sort();
        dataPoints = labels.map(date => {
            const row = dailyMap[date];
            if (currentMetric === 'pv') return row.today_pv;
            if (currentMetric === 'upvote') return row.today_upvote;
            if (currentMetric === 'collect') return row.today_collect;
            return 0;
        });
    }

    const ctx = document.getElementById('trendChart').getContext('2d');

    if (chartInstance) {
        chartInstance.destroy();
    }

    const labelName = currentMetric === 'pv' ? '阅读量' : (currentMetric === 'upvote' ? '点赞数' : '收藏数');

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: labelName,
                data: dataPoints,
                borderColor: '#0084ff',
                backgroundColor: 'rgba(0,132,255,0.1)',
                borderWidth: 2,
                pointBackgroundColor: '#fff',
                pointBorderColor: '#0084ff',
                pointBorderWidth: 2,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { beginAtZero: true, grid: { color: '#f0f0f0' } },
                x: { grid: { display: false } }
            }
        }
    });
}

// ---------------- [模块2] 文章与表格排序 ----------------
async function loadArticlesTable() {
    try {
        const res = await fetch('/api/articles/table');
        tableData = await res.json();
        renderTable();
    } catch (e) {
        console.error(e);
    }
}

function renderTable() {
    const tbody = document.getElementById('articleTableBody');
    tbody.innerHTML = '';
    tableData.forEach(row => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
                <td>
                    <div class="article-title-cell" title="${row.title}"><a href="https://www.zhihu.com/answer/${row.token}" target="_blank" style="color:inherit;text-decoration:none;" onmouseover="this.style.color='var(--primary-color)'" onmouseout="this.style.color='inherit'">${row.title}</a></div>
                    <div style="font-size:12px;color:var(--text-muted);margin-top:4px;display:flex;align-items:center;">
                        ID: ${row.token}
                        <button class="btn btn-secondary" style="padding: 4px; border: 1px solid transparent; background: transparent; color: var(--text-muted); margin-left: 6px; border-radius: 4px; display: flex; align-items: center; justify-content: center; cursor: pointer;" onmouseover="this.style.color='var(--primary-color)';" onmouseout="this.style.color='var(--text-muted)';" onclick="copyArticleLinkToClipboard('https://www.zhihu.com/answer/${row.token}', this)" title="复制链接">
                            <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        </button>
                    </div>
                </td>
                <td>${(row.total_show || 0).toLocaleString()}</td>
                <td>${(row.total_pv || 0).toLocaleString()}</td>
                <td><span style="color:var(--primary-color)">${row.click_rate}</span></td>
                <td>${row.finish_read_percent || '0%'}</td>
                <td>${row.positive_interact_percent || '0%'}</td>
                <td><span style="color:var(--success-color); font-weight:500;">${row.exposure_interact_rate || '0.000%'}</span></td>
                <td>${(row.total_upvote || 0).toLocaleString()}</td>
                <td>${(row.total_collect || 0).toLocaleString()}</td>
                <td>
                    <div class="row-actions">
                        <button class="btn btn-secondary" onclick="goToArticleData('${row.token}')">数据</button>
                        <button class="btn btn-danger" onclick="deleteArticle('${row.token}')">删除</button>
                    </div>
                </td>
            `;
        tbody.appendChild(tr);
    });
}

function sortTable(col) {
    if (currentSortCol === col) {
        sortAsc = !sortAsc;
    } else {
        currentSortCol = col;
        sortAsc = false; // 默认降序
    }

    // 更新表头箭头样式
    document.querySelectorAll('th[data-sort]').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.getAttribute('data-sort') === col) {
            th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
        }
    });

    tableData.sort((a, b) => {
        let valA = a[col] || 0;
        let valB = b[col] || 0;

        // 特殊处理带%的百分比
        if (col === 'click_rate' || col === 'finish_read_percent' || col === 'positive_interact_percent' || col === 'exposure_interact_rate') {
            valA = parsePercent(valA);
            valB = parsePercent(valB);
        }

        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
    });

    renderTable();
}

async function addArticle() {
    const url = document.getElementById('add-url').value.trim();
    const title = document.getElementById('add-title').value.trim();
    if (!url) {
        alert('请粘贴知乎回答链接');
        return;
    }
    try {
        const res = await fetch('/api/articles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, title })
        });
        if (res.ok) {
            document.getElementById('add-url').value = '';
            document.getElementById('add-title').value = '';
            loadArticlesTable();
            loadArticleSubNav(); // 同步刷新侧边栏
        } else {
            const data = await res.json();
            alert(data.error || '添加失败');
        }
    } catch (e) {
        console.error(e);
    }
}

async function deleteArticle(token) {
    if (!confirm('确定要删除此文章的监控吗？')) return;
    try {
        await fetch(`/api/articles/${token}`, { method: 'DELETE' });
        if (currentArticleToken === token) {
            currentArticleToken = '';
        }
        loadArticlesTable();
        loadArticleSubNav();
    } catch (e) {
        console.error(e);
    }
}

// ---------------- [模块3] 系统配置 ----------------
async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        const conf = await res.json();
        document.getElementById('conf-interval').value = conf.interval_minutes || 10;
        document.getElementById('conf-delay').value = conf.request_delay_seconds || 5;
        document.getElementById('conf-cookie').value = conf.cookie || '';
        document.getElementById('conf-zse96').value = conf.x_zse_96 || '';
        document.getElementById('config-validate-result').innerText = '';
    } catch (e) {
        console.error(e);
    }
}

async function saveConfig() {
    const resultEl = document.getElementById('config-validate-result');
    const payload = {
        interval_minutes: document.getElementById('conf-interval').value,
        request_delay_seconds: document.getElementById('conf-delay').value,
        cookie: document.getElementById('conf-cookie').value,
        x_zse_96: document.getElementById('conf-zse96').value
    };
    try {
        resultEl.style.color = 'var(--text-muted)';
        resultEl.innerText = '正在校验 Cookie 和 x-zse-96...';
        const res = await fetch('/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            const validation = data.validation || {};
            resultEl.innerText = validation.message || '配置已保存成功。';
            const warnCodes = ['skipped_no_article', 'network_error', 'request_failed'];
            resultEl.style.color = warnCodes.includes(validation.code) ? '#d48806' : 'var(--success-color)';
            alert(`配置已保存成功！${validation.message ? `\n${validation.message}` : ''}`);
        } else {
            resultEl.innerText = data.error || '配置保存失败';
            resultEl.style.color = '#f1403c';
            alert(data.error || '配置保存失败');
        }
    } catch (e) {
        console.error(e);
        resultEl.innerText = '配置保存失败，请检查网络后重试。';
        resultEl.style.color = '#f1403c';
    }
}

// ---------------- [模块4] 辅助功能 ----------------
function copyArticleLinkToClipboard(url, btnElem) {
    const copyIcon = `<svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>`;
    const checkIcon = `<svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    
    const setCopied = () => {
        btnElem.innerHTML = checkIcon;
        btnElem.style.color = 'var(--success-color)';
        setTimeout(() => {
            btnElem.innerHTML = copyIcon;
            btnElem.style.color = 'var(--text-muted)';
        }, 2000);
    };

    if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(setCopied).catch(err => console.error('复制失败', err));
    } else {
        // Fallback
        const input = document.createElement('input');
        input.value = url;
        document.body.appendChild(input);
        input.select();
        try {
            document.execCommand('copy');
            setCopied();
        } catch (err) {
            console.error('复制失败', err);
        }
        document.body.removeChild(input);
    }
}
