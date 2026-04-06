/**
 * @file categories.js
 * @description Client-side logic for the Category Analysis page.
 *
 * Renders sparkline bar charts for each category row and a detailed bar/line
 * combo chart in the expandable detail panel. Only one detail panel is open
 * at a time; clicking an open row closes it.
 *
 * @requires Chart.js
 * @requires MONTH_LABELS - string[] injected inline by the Jinja template.
 * @requires CAT_DATA - Array of category objects injected inline by the Jinja template.
 *           Each object includes: name, budget, monthly_spent[], over_under[], avg_spent,
 *           avg_diff, max_spent, max_month, active_months.
 */

/** @type {Object.<number, Chart>} Sparkline chart instances keyed by row index. */
const sparkCharts  = {};
/** @type {Object.<number, Chart>} Detail chart instances keyed by row index. */
const detailCharts = {};
/** @type {number|null} Index of the currently open detail panel, or null if all closed. */
let openIndex = null;

// ── Sparklines ────────────────────────────────────────────────────────────────

// Render a small bar chart in each category row's Trend column.
// If the category has a budget, an additional dashed budget line is overlaid.
// Bars are colored green (under budget), red (over budget), or orange (no budget).
CAT_DATA.forEach((cat, i) => {
    const el = document.getElementById(`spark-${i}`);
    if (!el) return;
    sparkCharts[i] = new Chart(el, {
        type: "bar",
        data: {
            labels: MONTH_LABELS,
            datasets: [
                cat.budget > 0 ? {
                    type: "line",
                    data: Array(cat.monthly_spent.length).fill(cat.budget),
                    borderColor: "rgba(99,102,241,0.5)",
                    borderWidth: 1.5,
                    borderDash: [3,3],
                    pointRadius: 0,
                    fill: false,
                } : null,
                {
                    data: cat.monthly_spent,
                    backgroundColor: cat.monthly_spent.map(v =>
                        cat.budget === 0 ? "rgba(234,130,50,0.75)" :
                        v > cat.budget   ? "rgba(231,74,59,0.75)" : "rgba(28,200,138,0.7)"
                    ),
                    borderRadius: 2,
                }
            ].filter(Boolean)
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false, beginAtZero: true } }
        }
    });
});

// ── Detail chart ──────────────────────────────────────────────────────────────

/**
 * Renders the full detail chart for a category in its expanded panel.
 * Destroys any existing chart instance for that index before creating a new one.
 * The chart shows budgeted vs actual bars, with an Over/Under line on a secondary
 * Y axis for categories that have a budget set.
 * @param {number} i - Row index into CAT_DATA.
 */
function openDetail(i) {
    const cat = CAT_DATA[i];
    if (detailCharts[i]) { detailCharts[i].destroy(); }

    const datasets = [
        cat.budget > 0 ? {
            label: "Budgeted",
            data: Array(cat.monthly_spent.length).fill(cat.budget),
            backgroundColor: "rgba(99,102,241,0.2)",
            borderColor: "rgba(99,102,241,0.6)",
            borderWidth: 1.5,
            borderRadius: 4,
            order: 3,
        } : null,
        {
            label: "Actual Spent",
            data: cat.monthly_spent,
            backgroundColor: cat.monthly_spent.map(v =>
                cat.budget === 0 ? "rgba(234,130,50,0.8)" :
                v > cat.budget   ? "rgba(231,74,59,0.75)" : "rgba(28,200,138,0.75)"
            ),
            borderRadius: 4,
            order: 2,
        },
        cat.budget > 0 ? {
            label: "Over / Under",
            data: cat.over_under,
            type: "line",
            borderColor: "#6366f1",
            backgroundColor: "rgba(99,102,241,0.07)",
            pointBackgroundColor: cat.over_under.map(v =>
                v === null ? "transparent" : v >= 0 ? "#1cc88a" : "#e74a3b"
            ),
            pointRadius: 5,
            pointHoverRadius: 7,
            borderWidth: 2,
            tension: 0.3,
            fill: true,
            yAxisID: "y2",
            order: 1,
        } : null,
    ].filter(Boolean);

    detailCharts[i] = new Chart(document.getElementById(`detail-${i}`), {
        type: "bar",
        data: { labels: MONTH_LABELS, datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { position: "top" } },
            scales: {
                y: {
                    beginAtZero: true, position: "left",
                    ticks: { callback: v => "$" + v.toLocaleString() }
                },
                ...(cat.budget > 0 ? {
                    y2: {
                        position: "right",
                        title: { display: true, text: "Over / Under ($)", color: "#6366f1" },
                        ticks: { callback: v => (v >= 0 ? "+" : "") + v.toLocaleString(), color: "#6366f1" },
                        grid: { drawOnChartArea: false },
                    }
                } : {})
            }
        }
    });
}

// ── Row click expand/collapse ─────────────────────────────────────────────────

// Clicking a category row opens its detail panel and closes any other open panel.
// The detail chart is rendered after the panel becomes visible so Chart.js can
// measure its container dimensions correctly (requestAnimationFrame).
document.querySelectorAll(".cat-expand-row").forEach(row => {
    row.addEventListener("click", () => {
        const i      = parseInt(row.dataset.index);
        const panel  = document.getElementById(`panel-${i}`);
        const icon   = row.querySelector(".cat-expand-icon");
        const isOpen = !panel.classList.contains("d-none");

        // Close the previously open panel if different from the clicked one.
        if (openIndex !== null && openIndex !== i) {
            document.getElementById(`panel-${openIndex}`).classList.add("d-none");
            document.querySelector(`[data-index="${openIndex}"] .cat-expand-icon`).classList.remove("open");
        }

        if (isOpen) {
            panel.classList.add("d-none");
            icon.classList.remove("open");
            openIndex = null;
        } else {
            panel.classList.remove("d-none");
            icon.classList.add("open");
            openIndex = i;
            // Defer chart creation until after the panel is visible in the DOM.
            requestAnimationFrame(() => openDetail(i));
        }
    });
});
