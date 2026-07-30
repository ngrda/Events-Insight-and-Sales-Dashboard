const API = '';

let weeks = [];
let selectedWeekId = null;
let currentView = 'overview';
let firstLoad = true;
let breakdownChart, mixChart, trendChart, ovMixChart, attendanceChart, tpCategoryChart, unitsCategoryChart;
let currentWeekData = null;
let currentOverviewData = null;
let currentProductsData = null;
let currentProductsOverviewData = null;
let productsUnitsChart;
let analyticsAttendanceOrdersChart, analyticsCapitaSpendChart;
let productsOverviewUnitsChart;
let productsOverviewRevenueChart;
let totalProductsChart;
let categoryUnitsChart;
let categoryRevenueByWeekChart;
let productsReturnView = 'overview';
let productsReturnWeekId = null;
let categoryReturnView = 'overview';
let categoryReturnWeekId = null;
let analyticsWeekId = null;
let tableSort = { field: 'units', dir: 'desc' };

const fmt = (n) => Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = (n) => Number(n).toLocaleString('en-US');
const renderChart = (chart) => chart?.update(firstLoad ? undefined : 'none');

function getCumulativeWeeks(ov) {
    if (!ov.scoped_week || !Array.isArray(ov.weekly_detail)) return ov.trend;
    const idx = ov.weekly_detail.findIndex((w) => w.id === ov.scoped_week.id);
    if (idx === -1) return ov.trend;
    return ov.weekly_detail.slice(0, idx + 1);
}

function filterChartData(labels, values) {
    const pairs = (labels || []).map((label, index) => ({
        label,
        value: Number(values?.[index] ?? 0),
    })).filter(({ value }) => Number(value) > 0);

    return {
        labels: pairs.map(({ label }) => label),
        values: pairs.map(({ value }) => value),
    };
}

const MIX_COLORS = ['#f5b942', '#38bdf8', '#a78bfa', '#fb7185', '#52525b'];
const MIX_LABELS = ['Popcorn', 'Snowcones', "Polly's Pop", 'Pioneer', 'Others'];
const CATEGORY_COLORS = ['#f5b942', '#38bdf8', '#a78bfa', '#fb7185', '#34d399', '#facc15', '#60a5fa', '#f472b6', '#c084fc'];

const TOOLTIP_STYLE = {
    backgroundColor: '#18181b',
    borderColor: 'rgba(255,255,255,0.08)',
    borderWidth: 1,
    cornerRadius: 8,
    padding: 10,
    titleColor: '#fafafa',
    bodyColor: '#a1a1aa',
    titleFont: { family: 'Inter', weight: '600', size: 12 },
    bodyFont: { family: 'Inter', size: 12 },
    displayColors: true,
    usePointStyle: false,
    boxWidth: 10,
    boxHeight: 10,
    boxPadding: 4,
};

// ── Tooltip flotante (HTML, no canvas) para los donuts ──
// El tooltip nativo de Chart.js se dibuja DENTRO del propio canvas, así que en
// donuts pequeños (sobre todo en móvil) puede quedar recortado o taparse con
// paneles vecinos. Este handler dibuja un div en document.body con z-index
// alto, así siempre queda por encima de todo, sin importar el tamaño del canvas.
function getFloatingTooltipEl() {
    let el = document.getElementById('floating-chart-tooltip');
    if (!el) {
        el = document.createElement('div');
        el.id = 'floating-chart-tooltip';
        el.className = 'floating-chart-tooltip';
        document.body.appendChild(el);
    }
    return el;
}

function floatingTooltipHandler(context) {
    const { chart, tooltip } = context;
    const el = getFloatingTooltipEl();

    if (!tooltip || tooltip.opacity === 0) {
        el.style.opacity = '0';
        return;
    }

    if (tooltip.body) {
        const titleLines = tooltip.title || [];
        const bodyLines = tooltip.body.map((b) => b.lines);
        const colors = tooltip.labelColors || [];

        let html = '';
        titleLines.forEach((title) => { html += `<div class="ftt-title">${title}</div>`; });
        bodyLines.forEach((lines, i) => {
            const c = colors[i];
            const dot = c ? `<span class="ftt-dot" style="background:${c.backgroundColor}"></span>` : '';
            lines.forEach((line) => { html += `<div class="ftt-row">${dot}<span>${line}</span></div>`; });
        });
        el.innerHTML = html;
    }

    const rect = chart.canvas.getBoundingClientRect();
    el.style.opacity = '1';
    el.style.left = `${rect.left + tooltip.caretX}px`;
    el.style.top = `${rect.top + tooltip.caretY}px`;
}

function productBrandColor(p) {
    const name = p?.name || '';
    if (name.startsWith("Polly's Pop")) return MIX_COLORS[2];
    if (name.startsWith('Pioneer')) return MIX_COLORS[3];
    return 'var(--text-muted)';
}

function productRowHtml(p, i) {
    return `
        <div class="product-row">
            <span class="product-rank">${String(i + 1).padStart(2, '0')}</span>
            <span class="product-dot" style="background:${productBrandColor(p)}"></span>
            <div class="product-info"><h4>${p.name}</h4><p>$${fmt(p.price)} per unit</p></div>
            <div class="product-revenue"><div class="amount">$${fmt(p.revenue)}</div><div class="units">${fmtInt(p.units)} sold</div></div>
        </div>
    `;
}

function bindIfExists(id, eventName, handler) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(eventName, handler);
}

function openModal(title, subtitle, bodyHtml) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-subtitle').textContent = subtitle || '';
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
}

function hideAllDashboards() {
    ['empty-state', 'overview-dashboard', 'dashboard', 'analytics-dashboard', 'products-dashboard', 'products-overview-dashboard', 'total-products-dashboard', 'category-dashboard'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });
}

function getProductsScope() {
    if (productsReturnView === 'week' && productsReturnWeekId) return productsReturnWeekId;
    return null;
}

async function fetchProductsData() {
    const scope = getProductsScope();
    const url = scope ? `${API}/api/products?week=${scope}` : `${API}/api/products`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Products API failed');
    currentProductsData = await res.json();
    return currentProductsData;
}

async function openProductsPage() {
    if (currentView !== 'products') {
        productsReturnView = currentView === 'week' ? 'week' : 'overview';
        productsReturnWeekId = selectedWeekId;
    }
    currentView = 'products';
    hideAllDashboards();
    hideMainHeaderActions();
    document.getElementById('products-dashboard').classList.remove('hidden');
    await renderProductsPage();
}

async function renderProductsOverviewPage() {
    try {
        const res = await fetch(`${API}/api/overview`);
        if (!res.ok) throw new Error("Overview API failed");
        const data = await res.json();
        currentProductsOverviewData = data;
        const products = data.top_products || [];

        const totalRevenue = data.metrics.total_revenue;
        const totalUnits = data.metrics.total_units;
        const stats = data.seller_stats?.products || {};
        const bestUnits = stats.best_by_units;
        const bestRevenue = stats.best_by_revenue;

        document.getElementById("po-kpi-revenue").textContent = "$" + fmt(totalRevenue);
        document.getElementById("po-kpi-units").textContent = fmtInt(totalUnits);
        document.getElementById("po-kpi-best-units").textContent = bestUnits ? `${bestUnits.name} (${fmtInt(bestUnits.units)})` : "—";
        document.getElementById("po-kpi-best-revenue").textContent = bestRevenue ? `${bestRevenue.name} ($${fmt(bestRevenue.revenue)})` : "—";

        renderProductsOverviewCharts(products);
    } catch(err){
        console.error(err);
    }
}

async function openTotalProductsPage() {
    currentView = 'totalProducts';
    hideAllDashboards();
    hideMainHeaderActions();
    document.getElementById('total-products-dashboard').classList.remove('hidden');
    await renderTotalProductsPage();
}

async function renderTotalProductsPage() {
    try {
        const res = await fetch(`${API}/api/overview`);
        if (!res.ok) throw new Error('Overview API failed');
        const data = await res.json();
        const weeks = data.weekly_detail || [];
        const filteredWeeks = weeks.filter((w) => Number(w.product_units || 0) > 0);

        if (totalProductsChart) {
            totalProductsChart.data.labels = filteredWeeks.map((w) => w.label);
            totalProductsChart.data.datasets[0].data = filteredWeeks.map((w) => Number(w.product_units || 0));
            renderChart(totalProductsChart);
        }

        const stats = data.seller_stats?.products || {};
        const bestByRevenue = stats.best_by_revenue;
        const worstByRevenue = stats.worst_by_revenue;

        const revenueEl = document.getElementById('tp-kpi-revenue');
        const unitsEl = document.getElementById('tp-kpi-units');
        const bestRevenueEl = document.getElementById('tp-kpi-best-revenue');
        const worstRevenueEl = document.getElementById('tp-kpi-worst-revenue');
        const countEl = document.getElementById('tp-product-count');

        if (revenueEl) revenueEl.textContent = `$${fmt(data.metrics.total_revenue)}`;
        if (unitsEl) unitsEl.textContent = fmtInt(data.metrics.total_units);
        if (bestRevenueEl) bestRevenueEl.textContent = bestByRevenue ? `${bestByRevenue.name} ($${fmt(bestByRevenue.revenue)})` : '—';
        if (worstRevenueEl) worstRevenueEl.textContent = worstByRevenue ? `${worstByRevenue.name} ($${fmt(worstByRevenue.revenue)})` : '—';
        if (countEl) countEl.textContent = `${filteredWeeks.length} weeks`;

        const body = document.getElementById('total-products-body');
        if (body) {
            body.innerHTML = filteredWeeks.map((w, i) => `
                <tr>
                    <td>${i + 1}</td>
                    <td>${w.label}</td>
                    <td>${fmtInt(w.product_units || 0)}</td>
                    <td>$${fmt(w.revenue || 0)}</td>
                </tr>
            `).join('');
        }

        const catLabels = data.charts.combined_labels;
        const catValues = data.charts.combined_values;
        const catUnits = data.charts.combined_units || [];
        const catTotal = catValues.reduce((a, b) => a + b, 0);

        if (tpCategoryChart) {
            tpCategoryChart.data.labels = catLabels;
            tpCategoryChart.data.datasets[0].data = catValues;
            tpCategoryChart.data.datasets[0].unitsData = catUnits;
            renderChart(tpCategoryChart);
        }

        const centerEl = document.getElementById('tp-category-center');
        if (centerEl) centerEl.textContent = `$${fmtInt(catTotal)}`;

        const legendEl = document.getElementById('tp-category-legend');
        if (legendEl) {
            legendEl.innerHTML = catLabels.map((label, i) => `
                <div class="legend-item">
                    <div class="legend-header"><span class="legend-dot" style="background:${CATEGORY_COLORS[i]}"></span><span class="legend-name">${label}</span></div>
                    <div class="legend-stats">
                        <span class="legend-pct">${catTotal ? Math.round((catValues[i] / catTotal) * 100) : 0}%</span>
                        <span class="legend-units">${fmtInt(catUnits[i] || 0)} units</span>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error(e);
    }
}

function renderProductsOverviewCharts(products){
    const filteredProducts = products.filter((p) => Number(p.units || 0) > 0);
    const labels = filteredProducts.map(p => p.name);
    const units = filteredProducts.map(p => p.units);
    const revenue = filteredProducts.map(p => p.revenue);

    if (productsOverviewUnitsChart) {
        productsOverviewUnitsChart.data.labels = labels;
        productsOverviewUnitsChart.data.datasets[0].data = units;
        renderChart(productsOverviewUnitsChart);
    }

    if (productsOverviewRevenueChart) {
        productsOverviewRevenueChart.data.labels = labels;
        productsOverviewRevenueChart.data.datasets[0].data = revenue;
        renderChart(productsOverviewRevenueChart);
    }
}

async function openCategoryPage() {
    if (currentView !== 'category') {
        categoryReturnView = currentView === 'week' ? 'week' : 'overview';
        categoryReturnWeekId = selectedWeekId;
    }
    currentView = 'category';
    hideAllDashboards();
    hideMainHeaderActions();
    document.getElementById('category-dashboard').classList.remove('hidden');
    await renderCategoryPage();
}

function getCategoryScope() {
    if (categoryReturnView === 'week' && categoryReturnWeekId) return categoryReturnWeekId;
    return null;
}

async function renderCategoryPage() {
    try {
        const scope = getCategoryScope();
        const url = scope ? `${API}/api/categories?week=${scope}` : `${API}/api/categories`;
        const res = await fetch(url);
        if (!res.ok) throw new Error('Categories API failed');
        const data = await res.json();

        const eyebrowEl = document.getElementById('category-eyebrow');
        if (eyebrowEl) eyebrowEl.textContent = data.scoped_week ? data.scoped_week.label : 'All Weeks';

        document.getElementById('cat-kpi-revenue').textContent = `$${fmt(data.metrics.total_revenue)}`;
        document.getElementById('cat-kpi-units').textContent = fmtInt(data.metrics.total_units);
        document.getElementById('cat-kpi-best').textContent = data.best_seller ? `${data.best_seller.name} ($${fmt(data.best_seller.revenue)} · ${fmtInt(data.best_seller.units)} units)` : '—';
        document.getElementById('cat-kpi-worst').textContent = data.worst_seller ? `${data.worst_seller.name} ($${fmt(data.worst_seller.revenue)} · ${fmtInt(data.worst_seller.units)} units)` : '—';
        document.getElementById('cat-kpi-spend').textContent = `$${fmt(data.metrics.avg_spend_per_customer)}`;

        const unitsChartData = data.charts.units_by_category;
        const filteredUnits = filterChartData(unitsChartData.labels, unitsChartData.values);
        if (categoryUnitsChart) {
            const revenueByLabel = {};
            (data.categories || []).forEach((c) => { revenueByLabel[c.name] = Number(c.revenue || 0); });
            categoryUnitsChart.data.labels = filteredUnits.labels;
            categoryUnitsChart.data.datasets[0].data = filteredUnits.values;
            categoryUnitsChart.data.datasets[0].revenueData = filteredUnits.labels.map((label) => revenueByLabel[label] || 0);
            renderChart(categoryUnitsChart);
        }

        const unitsTotal = filteredUnits.values.reduce((a, b) => a + b, 0);
        document.getElementById('category-units-center').textContent = fmtInt(unitsTotal);
        document.getElementById('category-units-legend').innerHTML = filteredUnits.labels.map((label, i) => `
            <div class="legend-item">
                <div class="legend-header"><span class="legend-dot" style="background:${CATEGORY_COLORS[i]}"></span><span class="legend-name">${label}</span></div>
                <div class="legend-stats">
                    <span class="legend-pct">${unitsTotal ? Math.round((filteredUnits.values[i] / unitsTotal) * 100) : 0}%</span>
                </div>
            </div>
        `).join('');

        const isWeekScoped = !!data.scoped_week;
        const revenueTitleEl = document.getElementById('category-revenue-chart-title');
        const revenueSubEl = document.getElementById('category-revenue-chart-sub');
        if (revenueTitleEl) revenueTitleEl.textContent = isWeekScoped ? 'Revenue per Category' : 'Revenue by Week';
        if (revenueSubEl) revenueSubEl.textContent = isWeekScoped ? 'Revenue by category for this week only' : 'Product revenue across every reporting week';

        const revenueChartItems = isWeekScoped
            ? (data.categories || []).filter((c) => Number(c.revenue || 0) > 0)
            : (data.charts?.revenue_by_week?.labels || []).map((label, index) => ({
                label,
                value: Number((data.charts?.revenue_by_week?.values || [])[index] || 0),
            })).filter((item) => item.value > 0);

        const revenueChartLabels = isWeekScoped
            ? revenueChartItems.map((c) => c.name)
            : revenueChartItems.map((item) => item.label);
        const revenueChartValues = isWeekScoped
            ? revenueChartItems.map((c) => Number(c.revenue || 0))
            : revenueChartItems.map((item) => item.value);

        if (categoryRevenueByWeekChart) {
            categoryRevenueByWeekChart.data.labels = revenueChartLabels;
            categoryRevenueByWeekChart.data.datasets[0].data = revenueChartValues;
            categoryRevenueByWeekChart.data.datasets[0].backgroundColor = isWeekScoped
                ? CATEGORY_COLORS.slice(0, revenueChartLabels.length)
                : '#34d399';
            renderChart(categoryRevenueByWeekChart);
        }

        const countEl = document.getElementById('category-product-count');
        const visibleCategories = [...data.categories].filter((c) => Number(c.units || 0) > 0);
        if (countEl) countEl.textContent = `${visibleCategories.length} categories`;

        const body = document.getElementById('category-products-body');
        if (body) {
            const categories = [...data.categories]
                .filter((c) => Number(c.units || 0) > 0)
                .sort((a, b) => b.revenue - a.revenue);
            body.innerHTML = categories.map((c, i) => `
                <tr>
                    <td>${String(i + 1).padStart(2, '0')}</td>
                    <td>${c.name}</td>
                    <td class="num">${fmtInt(c.units)}</td>
                    <td class="num">$${fmt(c.revenue)}</td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error(e);
    }
}

function closeCategoryPage() {
    if (categoryReturnView === 'week' && categoryReturnWeekId) { selectWeek(categoryReturnWeekId); } 
    else { selectOverview(); }
}

function closeProductsOverviewPage() { selectOverview(); }
function closeTotalProductsPage() { selectOverview(); }
function closeProductsPage() {
    if (productsReturnView === 'week' && productsReturnWeekId) { selectWeek(productsReturnWeekId); } 
    else { selectOverview(); }
}

function openAnalyticsPage() {
    analyticsWeekId = currentView === 'week' ? selectedWeekId : null;
    currentView = 'analytics';
    hideAllDashboards();
    hideMainHeaderActions();
    document.getElementById('analytics-dashboard').classList.remove('hidden');
    renderAnalyticsPage();
}

async function refreshAnalyticsData() {
    const url = analyticsWeekId ? `${API}/api/overview?week=${analyticsWeekId}` : `${API}/api/overview`;
    const res = await fetch(url);
    if (!res.ok) return;
    updateOverviewDataOnly(await res.json());
    renderAnalyticsPage();
}

function closeAnalyticsPage() {
    if (analyticsWeekId) selectWeek(analyticsWeekId);
    else selectOverview();
}

function sortProducts(products) {
    const sorted = [...products];
    sorted.sort((a, b) => {
        const av = a[tableSort.field];
        const bv = b[tableSort.field];
        if (typeof av === 'string') return tableSort.dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
        return tableSort.dir === 'asc' ? av - bv : bv - av;
    });
    return sorted;
}

function renderProductsTable(products) {
    const sorted = sortProducts(products);
    document.getElementById('products-table-body').innerHTML = sorted.map((p, i) => {
        const noSales = Number(p.units || 0) === 0;
        return `
        <tr${noSales ? ' class="no-sales-row"' : ''}>
            <td>${String(i + 1).padStart(2, '0')}</td>
            <td>${p.name}</td>
            <td class="num">$${fmt(p.price)}</td>
            <td class="num">${noSales ? '<span class="no-sales-label">No Sales</span>' : fmtInt(p.units)}</td>
            <td class="num">${noSales ? '<span class="no-sales-label">No Sales</span>' : `$${fmt(p.revenue)}`}</td>
        </tr>
    `;
    }).join('');
}

async function renderProductsPage() {
    try {
        const data = await fetchProductsData();
        const scopeLabel = data.scope === 'all' ? 'All Weeks' : (currentOverviewData?.scoped_week?.label?.split(' · ')[0] || 'Selected Week');
        document.getElementById('products-scope-label').textContent = scopeLabel;

        const products = data.products.filter((p) => p.units > 0);
        const best = products[0];

        document.getElementById('pp-kpi-revenue').textContent = `$${fmt(data.summary.total_revenue)}`;
        document.getElementById('pp-kpi-units').textContent = fmtInt(data.summary.soda_total);
        document.getElementById('pp-kpi-best').textContent = best ? best.name : '—';
        document.getElementById('pp-kpi-active').textContent = fmtInt(data.summary.active_products);

        const scopeParam = data.scope === 'all' ? '' : `?week=${data.scope}`;
        document.getElementById('pp-dl-csv').href = `${API}/api/export/products/csv${scopeParam}`;
        document.getElementById('pp-dl-json').href = `${API}/api/export/products/json${scopeParam}`;
       
        if (productsUnitsChart) {
            const filteredProducts = filterChartData(data.charts.top_units_labels.slice(0, 7), data.charts.top_units_values.slice(0, 7));
            productsUnitsChart.data.labels = filteredProducts.labels;
            productsUnitsChart.data.datasets[0].data = filteredProducts.values;
            const colors = ['#f5b942', '#38bdf8', '#a78bfa', '#fb7185', '#34d399', '#f97316', '#06b6d4'];
            productsUnitsChart.data.datasets[0].backgroundColor = colors.slice(0, filteredProducts.labels.length);
            renderChart(productsUnitsChart);
        }

        document.getElementById('pp-product-count').textContent = `${products.length} active · ${data.summary.total_products} total`;
        renderProductsTable(data.products);
    } catch (e) {
        console.error(e);
    }
}

function renderAnalyticsPage() {
    if (!currentOverviewData) return;
    const ov = currentOverviewData;
    const detail = getCumulativeWeeks(ov);
    const labels = detail.map((w) => w.label);

    document.getElementById('an-kpi-attendance').textContent = fmtInt(ov.metrics.total_customers);
    document.getElementById('an-kpi-avgspend').textContent = `$${fmt(ov.metrics.avg_spend_per_attendee)}`;
    document.getElementById('an-kpi-orders').textContent = fmtInt(ov.metrics.total_orders);
    document.getElementById('an-kpi-units').textContent = fmtInt(ov.metrics.total_units);
    document.getElementById('analytics-export-csv').href = `${API}/api/export/all/csv`;

    const scopedLabel = ov.scoped_week ? ov.scoped_week.label.split(' · ')[0] : null;
    const eyebrowEl = document.getElementById('analytics-eyebrow');
    const attOrdSubEl = document.getElementById('an-attendance-orders-sub');
    const capitaSubEl = document.getElementById('an-capita-spend-sub');
    if (eyebrowEl) eyebrowEl.textContent = scopedLabel ? `Through ${scopedLabel} · Deep Analytics` : 'All Weeks · Deep Analytics';
    if (attOrdSubEl) attOrdSubEl.textContent = scopedLabel ? `Weekly comparison through ${scopedLabel}` : 'Weekly comparison across all periods';
    if (capitaSubEl) capitaSubEl.textContent = scopedLabel ? `Average financial matrix through ${scopedLabel}` : 'Average financial matrix week-by-week';

    const filteredAttendance = filterChartData(labels, detail.map((w) => w.customers));
    const filteredOrders = filterChartData(labels, detail.map((w) => w.orders));
    const filteredSpend = filterChartData(labels, detail.map((w) => w.avg_spend));

    if (analyticsAttendanceOrdersChart) {
        analyticsAttendanceOrdersChart.data.labels = filteredAttendance.labels;
        analyticsAttendanceOrdersChart.data.datasets[0].data = filteredAttendance.values;
        analyticsAttendanceOrdersChart.data.datasets[1].data = filteredOrders.values;
        renderChart(analyticsAttendanceOrdersChart);
    }

    if (analyticsCapitaSpendChart) {
        analyticsCapitaSpendChart.data.labels = filteredSpend.labels;
        analyticsCapitaSpendChart.data.datasets[0].data = filteredSpend.values;
        renderChart(analyticsCapitaSpendChart);
    }

    document.querySelector('#weekly-summary-table tbody').innerHTML = detail
        .filter((w) => Number(w.revenue || 0) > 0 || Number(w.orders || 0) > 0 || Number(w.customers || 0) > 0)
        .map((w) => `
        <tr>
            <td>${w.label}</td>
            <td>${w.date}</td>
            <td class="num">$${fmt(w.revenue)}</td>
            <td class="num">${fmtInt(w.orders)}</td>
            <td class="num">${fmtInt(w.customers)}</td>
            <td class="num">$${fmt(w.avg_spend)}</td>
        </tr>
    `).join('');
}

async function openProductsOverviewPage() {
    currentView = 'productsOverview';
    hideAllDashboards();
    hideMainHeaderActions();
    document.getElementById('products-overview-dashboard').classList.remove('hidden');
    await renderProductsOverviewPage();
}

function openWeeksModal() {
    if (!weeks.length) return;
    const rows = weeks.map((w) => `
        <div class="week-row">
            <div class="week-row-main">
                <span class="week-row-label">${w.label.split(' · ')[0]}</span>
                <span class="week-row-date">${w.date}</span>
            </div>
            <div class="week-row-stats">
                <span>$${fmt(w.revenue)}</span>
                <span>${fmtInt(w.orders)} orders</span>
                <span>${fmtInt(w.units)} units</span>
                <span>${fmtInt(w.customers)} attendees</span>
            </div>
        </div>
    `).join('');
    openModal('All Weeks', `${weeks.length} reporting periods`, `<div class="weeks-modal-list">${rows}</div>`);
}

function initCharts() {
    const poUnitsEl = document.getElementById("productsOverviewUnitsChart");
    if (poUnitsEl) {
        productsOverviewUnitsChart = new Chart(poUnitsEl, {
            type: "bar", data: { labels: [], datasets: [{ data: [], backgroundColor: "#38bdf8", borderRadius: 5 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` ${fmtInt(c.parsed.y)} units` } } } }
        });
    }

    const poRevEl = document.getElementById("productsOverviewRevenueChart");
    if (poRevEl) {
        productsOverviewRevenueChart = new Chart(poRevEl, {
            type: "bar", data: { labels: [], datasets: [{ data: [], backgroundColor: "#34d399", borderRadius: 5 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` $${fmt(c.parsed.y)}` } } } }
        });
    }

    const totProdEl = document.getElementById("totalProductsChart");
    if (totProdEl) {
        totalProductsChart = new Chart(totProdEl, {
            type: "bar", data: { labels: [], datasets: [{ data: [], backgroundColor: "#f5b942", borderRadius: 5 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` ${fmtInt(c.parsed.y)} units` } } } }
        });
    }
    
    const barOpts = {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (ctx) => `$${fmt(ctx.parsed.y)}` } } },
        scales: {
            x: { grid: { display: false }, ticks: { color: '#71717a', font: { family: 'Inter' } } },
            y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', callback: (v) => `$${fmtInt(v)}` } },
        },
    };

    const breakdownEl = document.getElementById('breakdownChart');
    if (breakdownEl) {
        breakdownChart = new Chart(breakdownEl, {
            type: 'bar', data: { labels: [], datasets: [] }, options: { ...barOpts, onClick: () => openProductsPage() },
        });
    }

    const mixEl = document.getElementById('mixChart');
    if (mixEl) {
        mixChart = new Chart(mixEl, {
            type: 'doughnut', data: { labels: MIX_LABELS, datasets: [{ data: [], backgroundColor: MIX_COLORS, borderWidth: 2, borderColor: '#111113', hoverOffset: 6 }] },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: '74%',
                plugins: { 
                    legend: { display: false }, 
                    tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` ${c.label}: ${fmtInt(c.parsed)} units` } } 
                },
                onClick: () => openProductsPage(),
            },
        });
    }

    const trendEl = document.getElementById('trendChart');
    if (trendEl) {
        const trendCtx = trendEl.getContext('2d');
        const trendGradient = trendCtx.createLinearGradient(0, 0, 0, 260);
        trendGradient.addColorStop(0, 'rgba(52,211,153,0.28)');
        trendGradient.addColorStop(1, 'rgba(52,211,153,0.01)');
        trendChart = new Chart(trendCtx, {
            type: 'line',
            data: { labels: [], datasets: [{ data: [], borderColor: '#34d399', backgroundColor: trendGradient, fill: true, tension: 0.35, borderWidth: 2.5, pointRadius: 4, pointBackgroundColor: '#0b120e', pointBorderColor: '#34d399', pointBorderWidth: 2 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` $${fmt(c.parsed.y)} / attendee` } } },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#71717a' } },
                    y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', callback: (v) => `$${fmt(v)}` } },
                },
                onClick: () => openAnalyticsPage(),
            },
        });
    }

    const unitsCatEl = document.getElementById('unitsCategoryChart');
    if (unitsCatEl) {
        unitsCategoryChart = new Chart(unitsCatEl, {
            type: 'bar',
            data: { labels: MIX_LABELS, datasets: [{ data: [], backgroundColor: MIX_COLORS, borderRadius: 4, maxBarThickness: 46 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` ${fmtInt(c.parsed.y)} units` } }
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#71717a', autoSkip: false, maxRotation: 45, minRotation: 0 } },
                    y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', callback: (v) => fmtInt(v) } },
                },
                onClick: () => openCategoryPage(),
            }
        });
    }

    const ovMixEl = document.getElementById('ovMixChart');
    if (ovMixEl) {
        ovMixChart = new Chart(ovMixEl, {
            type: 'doughnut', data: { labels: MIX_LABELS, datasets: [{ data: [], backgroundColor: MIX_COLORS, borderWidth: 2, borderColor: '#111113', hoverOffset: 6 }] },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: '62%',
                plugins: { legend: { display: false }, tooltip: {
                    ...TOOLTIP_STYLE,
                    enabled: false,
                    external: floatingTooltipHandler,
                    callbacks: {
                        label: (c) => {
                            const revenue = c.dataset.revenueData?.[c.dataIndex];
                            return ` ${c.label}: $${fmt(revenue ?? 0)}`;
                        },
                        labelColor: (c) => ({ backgroundColor: MIX_COLORS[c.dataIndex], borderColor: '#111113', borderWidth: 1 }),
                    },
                } }
            }
        });
    }

    const tpCatEl = document.getElementById('tpCategoryChart');
    if (tpCatEl) {
        tpCategoryChart = new Chart(tpCatEl, {
            type: 'doughnut', data: { labels: [], datasets: [{ data: [], backgroundColor: CATEGORY_COLORS, borderWidth: 2, borderColor: '#111113', hoverOffset: 6 }] },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: '74%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        ...TOOLTIP_STYLE,
                        enabled: false,
                        external: floatingTooltipHandler,
                        callbacks: {
                            label: (c) => ` ${c.label}: $${fmt(c.parsed)}`,
                            labelColor: (c) => ({ backgroundColor: CATEGORY_COLORS[c.dataIndex], borderColor: '#111113', borderWidth: 1 }),
                        },
                    },
                },
                onClick: () => openProductsPage(),
            }
        });
    }

    const attEl = document.getElementById('attendanceChart');
    if (attEl) {
        const attCtx = attEl.getContext('2d');
        const attGradient = attCtx.createLinearGradient(0, 0, 0, 220);
        attGradient.addColorStop(0, '#60a5fa');
        attGradient.addColorStop(1, '#3b82f6');
        attendanceChart = new Chart(attCtx, {
    type: 'bar',
    data: {
        labels: [],
        datasets: [
            // 1. Añade maxBarThickness para que no se deformen si hay pocas semanas
            { label: 'Attendance', data: [], backgroundColor: attGradient, borderRadius: 6, maxBarThickness: 40 },
            { label: 'Orders', data: [], backgroundColor: '#a78bfa', borderRadius: 6, maxBarThickness: 40 },
        ],
    },
    options: {
        responsive: true, 
        maintainAspectRatio: false,
        barPercentage: 0.9,      // Aumenta el ancho de las barras individuales (reduce espacio entre ellas)
        categoryPercentage: 0.4,
        plugins: {
            legend: { display: true, labels: { color: '#a1a1aa', font: { family: 'Inter', size: 13 }, boxWidth: 10, boxHeight: 10 } },
            tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` ${c.dataset.label}: ${fmtInt(c.parsed.y)}` } },
        },
        scales: { 
            x: { 
                grid: { display: false }, 
                ticks: { color: '#71717a', font: { size: 13 } },
                // 2. Esto obliga a Chart.js a centrar y distribuir correctamente 
                // el espacio cuando cambias dinámicamente el número de elementos.
                offset: true 
            }, 
            y: { 
                grid: { color: 'rgba(255,255,255,0.04)' }, 
                ticks: { color: '#71717a', font: { size: 13 } } 
            } 
        },
        onClick: () => openAnalyticsPage(),
    },
});
    }

    const hBarOpts = {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE } },
        scales: {
            x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a' } },
            y: { grid: { display: false }, ticks: { color: '#71717a', font: { size: 13 } } },
        },
    };

    const prodUnitsEl = document.getElementById('productsUnitsChart');
    if (prodUnitsEl) {
        productsUnitsChart = new Chart(prodUnitsEl, {
            type: 'bar', data: { labels: [], datasets: [{ data: [], borderRadius: 4, barThickness: 14 }] },
            options: { ...hBarOpts, indexAxis: 'x', plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` ${fmtInt(c.parsed.y)} units` } } }, scales: { x: { ...hBarOpts.scales.x }, y: { ...hBarOpts.scales.y, ticks: { ...hBarOpts.scales.y.ticks, callback: (v) => fmtInt(v) } } } }
        });
    }

    const analyticsBarOpts = {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: '#fafafa', font: { family: 'Inter', size: 13 } } }, tooltip: TOOLTIP_STYLE },
        scales: { x: { grid: { display: false }, ticks: { color: '#71717a', font: { size: 13 } } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', font: { size: 13 } } } },
    };

    const anAttEl = document.getElementById('analyticsAttendanceOrdersChart');
    if (anAttEl) {
        analyticsAttendanceOrdersChart = new Chart(anAttEl, {
            type: 'bar', data: { labels: [], datasets: [{ label: 'Attendance', data: [], backgroundColor: '#3b82f6', borderRadius: 4 }, { label: 'Orders', data: [], backgroundColor: '#a78bfa', borderRadius: 4 }] }, options: analyticsBarOpts,
        });
    }

    const anCapEl = document.getElementById('analyticsCapitaSpendChart');
    if (anCapEl) {
        analyticsCapitaSpendChart = new Chart(anCapEl, {
            type: 'line', data: { labels: [], datasets: [{ label: 'Avg Spend / Person', data: [], borderColor: '#f5b942', backgroundColor: 'rgba(245,185,66,0.06)', fill: true, borderWidth: 2, pointRadius: 4, tension: 0.25 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` $${fmt(c.parsed.y)} / person` } } },
                scales: { x: { grid: { display: false }, ticks: { color: '#71717a' } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', callback: (v) => `$${v}` } } },
            },
        });
    }

    const catUnitsEl = document.getElementById('categoryUnitsChart');
    if (catUnitsEl) {
        categoryUnitsChart = new Chart(catUnitsEl, {
            type: 'doughnut', data: { labels: [], datasets: [{ data: [], backgroundColor: CATEGORY_COLORS, borderWidth: 2, borderColor: '#111113', hoverOffset: 6 }] },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: '74%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        ...TOOLTIP_STYLE,
                        enabled: false,
                        external: floatingTooltipHandler,
                        callbacks: {
                            label: (c) => ` ${c.label}: ${fmtInt(c.parsed)} units`,
                            labelColor: (c) => ({ backgroundColor: CATEGORY_COLORS[c.dataIndex], borderColor: '#111113', borderWidth: 1 }),
                        },
                    },
                },
            }
        });
    }

    const catRevEl = document.getElementById('categoryRevenueByWeekChart');
    if (catRevEl) {
        categoryRevenueByWeekChart = new Chart(catRevEl, {
            type: 'bar', data: { labels: [], datasets: [{ data: [], backgroundColor: '#34d399', borderRadius: 4 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_STYLE, callbacks: { label: (c) => ` $${fmt(c.parsed.y)}` } } },
                scales: { x: { grid: { display: false }, ticks: { color: '#71717a' } }, y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', callback: (v) => `$${fmtInt(v)}` } } },
            },
        });
    }

    ['trendChart', 'attendanceChart', 'ovMixChart', 'breakdownChart', 'mixChart', 'unitsCategoryChart'].forEach((id) => {
        document.getElementById(id)?.closest('.chart-wrap')?.classList.add('clickable');
    });
}

async function fetchWeeks() {
    const res = await fetch(`${API}/api/weeks`);
    if (!res.ok) throw new Error('API server down');
    const data = await res.json();
    weeks = data.weeks || [];
    if (!weeks.length) { showEmpty(); return; }
    renderSidebar();
    if (selectedWeekId === null) selectedWeekId = weeks[weeks.length - 1].id;

    if (currentView === 'overview') await loadOverview();
    else if (currentView === 'analytics') { await refreshAnalyticsData(); }
    else if (currentView === 'products') await renderProductsPage();
    else if (currentView === 'productsOverview') await renderProductsOverviewPage();
    else if (currentView === 'totalProducts') await renderTotalProductsPage();
    else if (currentView === 'category') await renderCategoryPage();
    else await loadWeek(selectedWeekId);
}

function renderSidebar() {
    document.getElementById('week-list').innerHTML = weeks.map((w) => `
        <button class="week-item ${currentView === 'week' && w.id === selectedWeekId ? 'active' : ''}" onclick="selectWeek('${w.id}')">
            <div class="week-item-top">
                <span class="week-item-label">${w.label.split(' · ')[0]}</span>
                <span class="week-tag" data-cat="${(w.category || '').toLowerCase()}">${w.category || '—'}</span>
            </div>
            <span class="week-item-date">${w.date}</span>
            <div class="week-item-meta">
                <span class="week-item-revenue">$${fmt(w.revenue)}</span>
                <span class="week-item-orders">${fmtInt(w.units)} units sold</span>
            </div>
        </button>
    `).join('');

    const ovBtn = document.getElementById('btn-overview');
    if (ovBtn) ovBtn.classList.toggle('active', currentView === 'overview' || currentView === 'analytics');
}

async function selectWeek(id) {
    showMainHeaderActions();
    currentView = 'week';
    selectedWeekId = id;
    renderSidebar();
    await loadWeek(id);
}

function selectOverview() {
    showMainHeaderActions();
    currentView = 'overview';
    selectedWeekId = null;
    renderSidebar();
    loadOverview();
}

async function loadOverview() {
    const res = await fetch(`${API}/api/overview`);
    if (!res.ok) return;
    hideAllDashboards();
    document.getElementById('overview-dashboard').classList.remove('hidden');
    updateOverviewDataOnly(await res.json());
}

function updateOverviewDataOnly(ov) {
    currentOverviewData = ov;
    const scoped = ov.scoped_week;
    const ovBadge = document.getElementById('week-badge');
    const tempEl = document.getElementById('temp-badge');

    if (scoped) {
        if (document.getElementById('week-eyebrow')) document.getElementById('week-eyebrow').textContent = scoped.label;
        if (ovBadge) {
            ovBadge.textContent = scoped.category || 'Uncategorized';
            ovBadge.className = `chip ${scoped.category ? 'chip-cat' : 'chip-muted'}`;
            ovBadge.dataset.cat = (scoped.category || '').toLowerCase();
        }
        if (tempEl) {
            if (scoped.temperature) { tempEl.textContent = scoped.temperature; tempEl.classList.remove('hidden'); }
            else tempEl.classList.add('hidden');
        }
        if (document.getElementById('dl-csv')) document.getElementById('dl-csv').href = `${API}/api/export/${scoped.id}/csv`;
        if (document.getElementById('dl-json')) document.getElementById('dl-json').href = `${API}/api/export/${scoped.id}/json`;
    } else {
        if (document.getElementById('week-eyebrow')) document.getElementById('week-eyebrow').textContent = `${ov.weeks_count} weeks tracked`;
        if (ovBadge) {
            ovBadge.textContent = 'All Weeks';
            ovBadge.className = 'chip chip-muted';
        }
        if (tempEl) tempEl.classList.add('hidden');
        if (document.getElementById('dl-csv')) document.getElementById('dl-csv').href = `${API}/api/export/all/csv`;
        if (document.getElementById('dl-json')) document.getElementById('dl-json').href = '#';
    }

    const m = ov.metrics;
    const pct = ov.breakdown_pct;

    if (document.getElementById('ov-kpi-revenue')) document.getElementById('ov-kpi-revenue').textContent = `$${fmt(m.total_revenue)}`;
    if (document.getElementById('ov-kpi-avg')) document.getElementById('ov-kpi-avg').textContent = `$${fmt(m.avg_revenue_per_week)} avg / week`;
    if (document.getElementById('ov-kpi-orders')) document.getElementById('ov-kpi-orders').textContent = fmtInt(m.total_orders);
    if (document.getElementById('ov-kpi-customers')) document.getElementById('ov-kpi-customers').textContent = fmtInt(m.total_customers);
    if (document.getElementById('ov-kpi-avgspend')) document.getElementById('ov-kpi-avgspend').textContent = `$${fmt(m.avg_spend_per_attendee)}`;

    const bestCard = document.getElementById('ov-card-bestweek');
    const lowestCard = document.getElementById('ov-card-lowestweek');
    const bestLabel = document.getElementById('ov-card-bestweek-label');
    const lowestLabel = document.getElementById('ov-card-lowestweek-label');
    const bestValue = document.getElementById('ov-kpi-best-week');
    const lowestValue = document.getElementById('ov-kpi-lowest-week');
    const bestSub = document.getElementById('ov-kpi-best-week-revenue');
    const lowestSub = document.getElementById('ov-kpi-lowest-week-revenue');

    if (scoped) {
        // Viewing a single week: Best/Weakest Week don't mean anything here,
        // show that week's real Temperature and Status (Inside/Outside) instead.
        if (bestCard) bestCard.className = 'kpi-card border border-[rgba(96,165,250,0.15)]';
        if (bestLabel) {
            bestLabel.textContent = 'Temperature';
            bestLabel.className = 'kpi-label text-[#60a5fa] font-medium uppercase tracking-wider';
        }
        if (bestValue) bestValue.textContent = scoped.temperature || '—';
        if (bestSub) bestSub.textContent = 'recorded on site';

        if (lowestCard) lowestCard.className = 'kpi-card border border-[rgba(251,191,36,0.15)]';
        if (lowestLabel) {
            lowestLabel.textContent = 'Status';
            lowestLabel.className = 'kpi-label text-[#fbbf24] font-medium uppercase tracking-wider';
        }
        if (lowestValue) lowestValue.textContent = scoped.category || '—';
        if (lowestSub) lowestSub.textContent = 'venue setting';
    } else {
        if (bestCard) bestCard.className = 'kpi-card border border-[rgba(52,211,153,0.15)]';
        if (bestLabel) {
            bestLabel.textContent = 'Best Week';
            bestLabel.className = 'kpi-label text-[#34d399] font-medium uppercase tracking-wider';
        }
        if (lowestCard) lowestCard.className = 'kpi-card border border-[rgba(248,113,113,0.15)]';
        if (lowestLabel) {
            lowestLabel.textContent = 'Weakest Week';
            lowestLabel.className = 'kpi-label text-[#f87171] font-medium uppercase tracking-wider';
        }

        if (ov.best_week) {
            if (bestValue) bestValue.textContent = ov.best_week.label.split(' · ')[0];
            if (bestSub) bestSub.textContent = `$${fmt(ov.best_week.revenue)} peak`;
        }
        if (ov.worst_week) {
            if (lowestValue) lowestValue.textContent = ov.worst_week.label.split(' · ')[0];
            if (lowestSub) lowestSub.textContent = `$${fmt(ov.worst_week.revenue)} valley`;
        }
    }

    const cumulativeWeeks = getCumulativeWeeks(ov);
    const scopedLabel = scoped ? scoped.label.split(' · ')[0] : null;

    const activeWeeks = cumulativeWeeks.filter((w) => Number(w.customers || 0) > 0 || Number(w.orders || 0) > 0);
    if (attendanceChart) {
        attendanceChart.data.labels = activeWeeks.map((w) => w.label);
        attendanceChart.data.datasets[0].data = activeWeeks.map((w) => Number(w.customers || 0));
        attendanceChart.data.datasets[1].data = activeWeeks.map((w) => Number(w.orders || 0));
        renderChart(attendanceChart);
    }

    const attTitleEl = document.getElementById('attendance-chart-title');
    if (attTitleEl) attTitleEl.textContent = scopedLabel ? 'Attendees\u00A0\u00A0&\u00A0\u00A0Orders' : 'Attendees';

    const attSubEl = document.getElementById('attendance-chart-sub');
    if (attSubEl) attSubEl.textContent = scopedLabel ? `Attendance & orders through ${scopedLabel}` : 'Attendance & orders across every reporting week';

    const spendTitleEl = document.getElementById('spend-chart-title');
    const spendSubEl = document.getElementById('spend-chart-sub');
    const trendWrapEl = document.getElementById('spend-trend-wrap');
    const unitsCatWrapEl = document.getElementById('units-category-wrap');

    if (scoped) {
        if (trendWrapEl) trendWrapEl.classList.add('hidden');
        if (unitsCatWrapEl) unitsCatWrapEl.classList.remove('hidden');
        if (spendTitleEl) spendTitleEl.textContent = 'Units per Category';
        if (spendSubEl) spendSubEl.textContent = `Units sold by category — ${scopedLabel}`;

        const weekMixValues = [ov.breakdown.popcorn, ov.breakdown.snowcones, ov.breakdown.polly, ov.breakdown.pioneer, ov.breakdown.others];
        const filteredWeekMix = filterChartData(MIX_LABELS, weekMixValues);
        const weekUnitsTotal = filteredWeekMix.values.reduce((a, b) => a + b, 0);

        if (unitsCategoryChart) {
            unitsCategoryChart.data.labels = filteredWeekMix.labels;
            unitsCategoryChart.data.datasets[0].data = filteredWeekMix.values;
            renderChart(unitsCategoryChart);
        }
        if (document.getElementById('units-category-center')) document.getElementById('units-category-center').textContent = fmtInt(weekUnitsTotal);
        const unitsCatLegendEl = document.getElementById('units-category-legend');
        if (unitsCatLegendEl) {
            unitsCatLegendEl.innerHTML = filteredWeekMix.labels.map((label, i) => `
                <div class="legend-item">
                    <div class="legend-header"><span class="legend-dot" style="background:${MIX_COLORS[i]}"></span><span class="legend-name">${label}</span></div>
                    <div class="legend-stats">
                        <span class="legend-pct">${weekUnitsTotal ? Math.round((filteredWeekMix.values[i] / weekUnitsTotal) * 100) : 0}%</span>
                        <span class="legend-units">${fmtInt(filteredWeekMix.values[i] || 0)} units</span>
                    </div>
                </div>
            `).join('');
        }
    } else {
        if (unitsCatWrapEl) unitsCatWrapEl.classList.add('hidden');
        if (trendWrapEl) trendWrapEl.classList.remove('hidden');
        if (spendTitleEl) spendTitleEl.textContent = 'Spend per Attendee';
        if (spendSubEl) spendSubEl.textContent = 'Average spend per attendee across every reporting week';

        const spendSeries = filterChartData(cumulativeWeeks.map((t) => t.label), cumulativeWeeks.map((t) => t.avg_spend));
        if (trendChart) {
            trendChart.data.labels = spendSeries.labels;
            trendChart.data.datasets[0].data = spendSeries.values;
            renderChart(trendChart);
        }
    }

    const keys = ['popcorn', 'snowcones', 'polly', 'pioneer', 'others'];
    const mixValues = [ov.breakdown.popcorn, ov.breakdown.snowcones, ov.breakdown.polly, ov.breakdown.pioneer, ov.breakdown.others];
    const filteredMix = filterChartData(MIX_LABELS, mixValues);
    if (ovMixChart) {
        ovMixChart.data.labels = filteredMix.labels;
        ovMixChart.data.datasets[0].data = filteredMix.values;
        ovMixChart.data.datasets[0].revenueData = filteredMix.labels.map((label) => {
            const idx = MIX_LABELS.indexOf(label);
            return ov.breakdown_revenue[keys[idx]] || 0;
        });
        renderChart(ovMixChart);
    }
    if (document.getElementById('ov-mix-center')) document.getElementById('ov-mix-center').textContent = fmtInt(filteredMix.values.reduce((a, b) => a + b, 0));

    const mixLegendEl = document.getElementById('ov-mix-legend');
    if (mixLegendEl) {
        mixLegendEl.innerHTML = MIX_LABELS.map((label, i) => `
            <div class="legend-item">
                <div class="legend-header"><span class="legend-dot" style="background:${MIX_COLORS[i]}"></span><span class="legend-name">${label}</span></div>
                <div class="legend-stats">
                    <span class="legend-pct">${pct[keys[i]]}%</span>
                    <span class="legend-units">${fmtInt(ov.breakdown[keys[i]] || 0)} units</span>
                </div>
            </div>
        `).join('') + '<div class="legend-item hidden-placeholder"></div>';
    }

    const catLabels = ov.charts.combined_labels;
    const catValues = ov.charts.combined_values;
    const catUnitsRaw = ov.charts.combined_units || [];
    const catUnitsByLabel = Object.fromEntries(catLabels.map((label, i) => [label, catUnitsRaw[i] || 0]));
    const filteredCat = filterChartData(catLabels, catValues);
    const filteredCatUnits = filteredCat.labels.map((label) => catUnitsByLabel[label] || 0);
    const catTotal = catValues.reduce((a, b) => a + Number(b || 0), 0);

    if (tpCategoryChart) {
        tpCategoryChart.data.labels = filteredCat.labels;
        tpCategoryChart.data.datasets[0].data = filteredCat.values;
        tpCategoryChart.data.datasets[0].unitsData = filteredCatUnits;
        renderChart(tpCategoryChart);
    }
    if (document.getElementById('tp-category-center')) document.getElementById('tp-category-center').textContent = `$${fmtInt(catTotal)}`;
    
    const catLegendEl = document.getElementById('tp-category-legend');
    if (catLegendEl) {
        catLegendEl.innerHTML = filteredCat.labels.map((label, i) => `
            <div class="legend-item">
                <div class="legend-header"><span class="legend-dot" style="background:${CATEGORY_COLORS[i]}"></span><span class="legend-name">${label}</span></div>
                <div class="legend-stats">
                    <span class="legend-pct">${catTotal ? Math.round((filteredCat.values[i] / catTotal) * 100) : 0}%</span>
                </div>
            </div>
        `).join('');
    }

    const topThree = (ov.soda_products || ov.top_products || []).filter((p) => Number(p.units || 0) > 0).slice(0, 3);
    const noBeverageSales = topThree.length === 0;
    const ovProductCountEl = document.getElementById('ov-product-count');
    const ovProductsListEl = document.getElementById('ov-products-list');

    if (ovProductCountEl) {
        if (noBeverageSales) {
            ovProductCountEl.textContent = 'No sales';
            ovProductCountEl.classList.add('is-disabled');
            ovProductCountEl.setAttribute('aria-disabled', 'true');
        } else {
            ovProductCountEl.textContent = `Top ${topThree.length} of ${ov.summary.total_sodas} · view all`;
            ovProductCountEl.classList.remove('is-disabled');
            ovProductCountEl.removeAttribute('aria-disabled');
        }
    }

    if (ovProductsListEl) {
        ovProductsListEl.innerHTML = noBeverageSales
            ? `
                <div class="no-sales-message">
                    <div class="no-sales-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="9"></circle>
                            <line x1="6.3" y1="6.3" x2="17.7" y2="17.7"></line>
                        </svg>
                    </div>
                    <div class="no-sales-title">No Sales</div>
                    <div class="no-sales-sub">No beverages were sold this week</div>
                </div>
            `
            : topThree.map((p, i) => productRowHtml(p, i)).join('');
    }
}

async function loadWeek(weekId) {
    const res = await fetch(`${API}/api/overview?week=${weekId}`);
    if (!res.ok) return;
    hideAllDashboards();
    document.getElementById('overview-dashboard').classList.remove('hidden');
    updateOverviewDataOnly(await res.json());
}

function showEmpty() {
    hideAllDashboards();
    document.getElementById('empty-state').classList.remove('hidden');
}

function hideMainHeaderActions() {
    const actions = document.querySelector(".header-actions");
    if (actions) actions.style.display = "none";
}

function showMainHeaderActions() {
    const actions = document.querySelector(".header-actions");
    if (actions) actions.style.display = "flex";
}

async function refresh() {
    try {
        const res = await fetch(`${API}/api/weeks`);
        if (!res.ok) throw new Error('API server down');
        const data = await res.json();
        weeks = data.weeks || [];
        if (!weeks.length) { showEmpty(); return; }
        renderSidebar();
        if (selectedWeekId === null) selectedWeekId = weeks[weeks.length - 1].id;

        if (currentView === 'overview') await loadOverview();
        else if (currentView === 'analytics') { await refreshAnalyticsData(); }
        else if (currentView === 'products') await renderProductsPage();
        else if (currentView === 'productsOverview') await renderProductsOverviewPage();
        else if (currentView === 'totalProducts') await renderTotalProductsPage();
        else if (currentView === 'category') await renderCategoryPage();
        else await loadWeek(selectedWeekId);
        
        if (document.getElementById('sync-status')) document.getElementById('sync-status').textContent = `Synced · ${weeks.length} weeks`;
    } catch (e) {
        if (document.getElementById('sync-status')) document.getElementById('sync-status').textContent = 'Backend offline';
    } finally {
        firstLoad = false;
    }
}

bindIfExists('btn-refresh', 'click', refresh);
bindIfExists('btn-overview', 'click', selectOverview);
bindIfExists('ov-product-count', 'click', (e) => {
    if (e.currentTarget.classList.contains('is-disabled')) return;
    openProductsPage();
});
bindIfExists('product-count', 'click', openProductsPage);
bindIfExists('btn-products-back', 'click', closeProductsPage);
bindIfExists('btn-products-overview-back', 'click', closeProductsOverviewPage);
bindIfExists('btn-total-products-back', 'click', closeTotalProductsPage);
bindIfExists('btn-products-overview', 'click', openProductsOverviewPage);
bindIfExists('btn-total-products', 'click', openTotalProductsPage);
bindIfExists('btn-analytics-back', 'click', closeAnalyticsPage);
bindIfExists('btn-category-back', 'click', closeCategoryPage);
bindIfExists('btn-revenue-category', 'click', openCategoryPage);
bindIfExists('btn-view-analytics', 'click', openAnalyticsPage);

bindIfExists('modal-close', 'click', closeModal);
bindIfExists('modal-overlay', 'click', (e) => { if (e.target.id === 'modal-overlay') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

document.querySelectorAll('#products-table th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
        const field = th.dataset.sort;
        if (tableSort.field === field) tableSort.dir = tableSort.dir === 'asc' ? 'desc' : 'asc';
        else { tableSort.field = field; tableSort.dir = 'desc'; }
        if (currentProductsData) renderProductsTable(currentProductsData.products);
    });
});

window.selectWeek = selectWeek;

initCharts();
refresh();