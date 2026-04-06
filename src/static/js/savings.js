/**
 * @file savings.js
 * @description Client-side logic for the Savings page.
 *
 * Covers six main areas:
 *   1. Filter panel — toggle visibility, submit with hash preservation, scroll-on-load
 *   2. Transaction ledger — client-side column sorting, inline description editing,
 *      multi-select checkboxes, bulk delete, footer total recalculation
 *   3. Add Transaction modal — form submission, optimistic row injection, orphan cleanup
 *      if the user cancels before allocating
 *   4. Allocation modal — jar selection, amount entry, template pre-fill, validation,
 *      save with optional default-template update, ledger row update without reload
 *   5. Rebalance modal — target amount editing, validation that totals match, submission
 *   6. CSV import offcanvas — file selection/drag-drop, upload, result display, reset
 *
 * Stat tiles and jar tiles are refreshed in-place after any mutation so the page
 * does not need a full reload for most actions.
 *
 * @requires Bootstrap 5 (modal, offcanvas)
 * @requires Chart.js (jar history sparkline)
 */

// ── Filter panel ─────────────────────────────────────────────────────────────

/**
 * Toggles the filter panel open or closed and rotates the chevron icon.
 */
function toggleFilters() {
    const body    = document.getElementById("filter-body");
    const chevron = document.getElementById("filter-chevron");
    const open    = body.style.display !== "none";
    body.style.display = open ? "none" : "";
    chevron.style.transform = open ? "rotate(-90deg)" : "rotate(0deg)";
}

/**
 * Submits the filter form as a GET request, appending #filter-section to the
 * URL so the page scrolls back to the filter panel after reload.
 * @param {Event} event
 */
function submitFilter(event) {
    event.preventDefault();
    const form   = document.getElementById("filter-form");
    const params = new URLSearchParams(new FormData(form));
    window.location.href = "/savings?" + params.toString() + "#filter-section";
    return false;
}

/**
 * Clears all active filters by navigating to the base savings URL.
 * @param {Event} event
 */
function clearFilter(event) {
    event.preventDefault();
    window.location.href = "/savings#filter-section";
}

// On load, scroll to and open the filter panel if #filter-section is in the URL hash.
window.addEventListener("DOMContentLoaded", () => {
    if (window.location.hash === "#filter-section") {
        const el = document.getElementById("filter-section");
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
            const body = document.getElementById("filter-body");
            if (body && body.style.display === "none") {
                body.style.display = "";
                document.getElementById("filter-chevron").style.transform = "rotate(0deg)";
            }
        }
    }
});

// ── Column sorting ────────────────────────────────────────────────────────────

/** @type {number|null} Index of the currently sorted column. */
let sortCol = null;
/** @type {"asc"|"desc"} Current sort direction. */
let sortDir = "asc";

// Attach click handlers to all sortable column headers.
document.querySelectorAll(".sortable").forEach(th => {
    th.addEventListener("click", () => {
        const col  = parseInt(th.dataset.col);
        const type = th.dataset.type;
        if (sortCol === col) { sortDir = sortDir === "asc" ? "desc" : "asc"; }
        else { sortCol = col; sortDir = "asc"; }
        document.querySelectorAll(".sortable").forEach(el => el.classList.remove("asc","desc"));
        th.classList.add(sortDir);
        sortTable(col, type, sortDir);
    });
});

/**
 * Sorts the savings transaction table in place.
 * Reads each cell's data-val attribute (set server-side) for reliable sorting,
 * falling back to textContent if data-val is absent.
 * @param {number} col - Zero-based column index.
 * @param {"date"|"str"|"num"} type - Sort strategy.
 * @param {"asc"|"desc"} dir - Sort direction.
 */
function sortTable(col, type, dir) {
    const tbody = document.getElementById("savings-tbody");
    if (!tbody) return;
    const rows = [...tbody.querySelectorAll("tr")];
    rows.sort((a, b) => {
        const aCell = a.querySelectorAll("td")[col];
        const bCell = b.querySelectorAll("td")[col];
        let aVal = aCell?.dataset.val ?? aCell?.textContent.trim() ?? "";
        let bVal = bCell?.dataset.val ?? bCell?.textContent.trim() ?? "";
        if (type === "num") {
            aVal = parseFloat(aVal) || 0; bVal = parseFloat(bVal) || 0;
            return dir === "asc" ? aVal - bVal : bVal - aVal;
        }
        return dir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
    rows.forEach(row => tbody.appendChild(row));
}

// ── Add Transaction modal ─────────────────────────────────────────────────────

/**
 * Tracks whether the current allocation modal was opened immediately after
 * adding a new transaction. If the user cancels without saving allocations,
 * the orphaned transaction is deleted server-side.
 * @type {boolean}
 */
let allocFromAdd = false;

/**
 * Opens the Add Transaction modal with today's date pre-filled.
 */
function openAddTransaction() {
    const today = new Date().toISOString().split("T")[0];
    document.getElementById("add-txn-date").value   = today;
    document.getElementById("add-txn-desc").value   = "";
    document.getElementById("add-txn-amount").value = "";
    document.getElementById("add-txn-notes").value  = "";
    document.getElementById("add-txn-error").classList.add("d-none");
    new bootstrap.Modal(document.getElementById("addTransactionModal")).show();
}

/**
 * POSTs the new transaction to the API, injects it into the ledger without
 * reloading, then immediately opens the allocation modal.
 * Sets allocFromAdd = true so that cancelling the allocation modal triggers
 * cleanup of the orphaned transaction.
 */
async function submitAddTransaction() {
    const date   = document.getElementById("add-txn-date").value;
    const desc   = document.getElementById("add-txn-desc").value.trim();
    const amount = parseFloat(document.getElementById("add-txn-amount").value);
    const notes  = document.getElementById("add-txn-notes").value.trim();
    const errEl  = document.getElementById("add-txn-error");

    if (!date || !desc || isNaN(amount)) {
        errEl.textContent = "Please fill in date, description, and amount.";
        errEl.classList.remove("d-none");
        return;
    }

    const resp = await fetch("/api/savings/transactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, description: desc, amount, notes: notes || null })
    });
    if (resp.ok) {
        const newTxn = await resp.json();
        bootstrap.Modal.getInstance(document.getElementById("addTransactionModal")).hide();
        injectNewTransactionRow(newTxn);
        updateFooterTotals();
        allocFromAdd = true;
        setTimeout(() => openAllocateModal(newTxn.id, newTxn.amount, newTxn.description, false), 300);
    } else {
        const data = await resp.json();
        errEl.textContent = data.detail || "Failed to add transaction.";
        errEl.classList.remove("d-none");
    }
}

/**
 * Builds and prepends a new transaction row to the ledger without a page reload.
 * The row is marked unallocated and wired up with the same event handlers as
 * server-rendered rows.
 * @param {Object} txn - Transaction object returned by the API.
 */
function injectNewTransactionRow(txn) {
    const tbody = document.getElementById("savings-tbody");
    if (!tbody) { location.reload(); return; }
    const amtClass = txn.amount >= 0 ? "amount-credit" : "amount-debit";
    const amtSign  = txn.amount >= 0 ? "+" : "−";
    const tr = document.createElement("tr");
    tr.id = `srow-${txn.id}`;
    tr.className = "savings-unallocated-row";
    tr.dataset.desc = txn.description;
    tr.innerHTML = `
        <td class="align-middle">
            <input type="checkbox" class="form-check-input row-checkbox" data-id="${txn.id}"
                   onchange="updateBulkDelete()" onclick="handleCheckboxClick(event, ${txn.id})">
        </td>
        <td class="text-muted small align-middle" data-val="${txn.date}" style="white-space:nowrap;">${txn.date}</td>
        <td class="align-middle" data-val="${txn.description}">
            <span class="desc-text" style="cursor:pointer;" title="Click to edit description"
                  onclick="startInlineEdit(this, ${txn.id})">${txn.description}</span>
            ${txn.notes ? `<small class="text-muted d-block" style="font-size:0.75rem;"><i class="bi bi-chat-left-text me-1"></i>${txn.notes}</small>` : ""}
        </td>
        <td class="text-end align-middle fw-semibold" data-val="${txn.amount}">
            <span class="${amtClass}">${amtSign}$${Math.abs(txn.amount).toFixed(2)}</span>
        </td>
        <td class="align-middle"><span class="badge-unalloc-sav">⚠ Pending</span></td>
        <td class="align-middle"><em class="text-muted small">Not yet allocated to jars</em></td>
        <td class="align-middle">
            <div class="dropdown">
                <button class="btn btn-sm btn-outline-secondary dropdown-toggle"
                        style="padding:0.15rem 0.4rem;font-size:0.75rem;"
                        data-bs-toggle="dropdown">⋯</button>
                <ul class="dropdown-menu dropdown-menu-end" style="font-size:0.85rem;">
                    <li>
                        <a class="dropdown-item" href="javascript:void(0)"
                           onclick="openAllocateModal(${txn.id}, ${txn.amount}, this.closest('tr').dataset.desc, false)">
                            <i class="bi bi-distribute-vertical me-2"></i>Allocate
                        </a>
                    </li>
                    <li><hr class="dropdown-divider"></li>
                    <li>
                        <a class="dropdown-item text-danger" href="javascript:void(0)"
                           onclick="deleteSavingsTransaction(${txn.id}, this.closest('tr').dataset.desc)">
                            <i class="bi bi-trash me-2"></i>Delete
                        </a>
                    </li>
                </ul>
            </div>
        </td>`;
    tbody.insertBefore(tr, tbody.firstChild);
}

// If the allocation modal is dismissed without saving after an Add Transaction flow,
// delete the orphaned transaction so the ledger stays consistent.
document.addEventListener("DOMContentLoaded", () => {
    const allocModal = document.getElementById("allocateModal");
    if (allocModal) {
        allocModal.addEventListener("hidden.bs.modal", async () => {
            if (allocFromAdd && allocTxnId) {
                allocFromAdd = false;
                await fetch(`/api/savings/transactions/${allocTxnId}`, { method: "DELETE" });
                const orphan = document.getElementById(`srow-${allocTxnId}`);
                if (orphan) { orphan.remove(); updateFooterTotals(); }
            }
        });
    }
});

// ── Inline description edit ───────────────────────────────────────────────────

/**
 * Replaces a description span with an input field for inline editing.
 * Saves on blur or Enter, cancels on Escape.
 * @param {HTMLElement} spanEl - The description span element that was clicked.
 * @param {number} txnId - ID of the savings transaction to update.
 */
function startInlineEdit(spanEl, txnId) {
    if (spanEl.querySelector("input")) return;
    const original = spanEl.textContent.trim();
    const input = document.createElement("input");
    input.type  = "text";
    input.value = original;
    input.className = "form-control form-control-sm desc-input";
    input.style.cssText = "display:inline-block;width:auto;min-width:180px;";
    spanEl.textContent = "";
    spanEl.appendChild(input);
    input.focus();
    input.select();

    const finish = async (save) => {
        const newVal = input.value.trim();
        if (save && newVal && newVal !== original) {
            const resp = await fetch(`/api/savings/transactions/${txnId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ description: newVal })
            });
            if (resp.ok) {
                spanEl.textContent = newVal;
                const td = spanEl.closest("td");
                if (td) td.dataset.val = newVal;
            } else {
                spanEl.textContent = original;
            }
        } else {
            spanEl.textContent = original;
        }
    };

    input.addEventListener("blur",    () => finish(true));
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { input.removeEventListener("blur", () => finish(true)); spanEl.textContent = original; }
    });
}

// ── Multi-select checkboxes ───────────────────────────────────────────────────

/** @type {number|null} ID of the last checkbox clicked, used for shift-click range selection. */
let lastCheckedId = null;

/**
 * Handles checkbox clicks with shift-click range selection support.
 * @param {MouseEvent} event
 * @param {number} txnId - Transaction ID of the clicked row's checkbox.
 */
function handleCheckboxClick(event, txnId) {
    const checkboxes = [...document.querySelectorAll(".row-checkbox")];
    const ids = checkboxes.map(cb => parseInt(cb.dataset.id));
    if (event.shiftKey && lastCheckedId !== null) {
        const lastIdx  = ids.indexOf(lastCheckedId);
        const thisIdx  = ids.indexOf(txnId);
        const [lo, hi] = [Math.min(lastIdx, thisIdx), Math.max(lastIdx, thisIdx)];
        const target   = event.target.checked;
        checkboxes.slice(lo, hi + 1).forEach(cb => { cb.checked = target; });
    }
    lastCheckedId = txnId;
    updateBulkDelete();
}

/**
 * Selects or deselects all row checkboxes.
 * @param {HTMLInputElement} master - The select-all checkbox.
 */
function toggleSelectAll(master) {
    document.querySelectorAll(".row-checkbox").forEach(cb => { cb.checked = master.checked; });
    updateBulkDelete();
}

/**
 * Updates bulk-delete button visibility/count and the select-all indeterminate state.
 */
function updateBulkDelete() {
    const checked = document.querySelectorAll(".row-checkbox:checked");
    const btn     = document.getElementById("bulk-delete-btn");
    document.getElementById("bulk-count").textContent = checked.length;
    btn.classList.toggle("d-none", checked.length === 0);
    const all    = document.querySelectorAll(".row-checkbox");
    const master = document.getElementById("select-all-rows");
    if (master) {
        master.indeterminate = checked.length > 0 && checked.length < all.length;
        master.checked       = checked.length === all.length && all.length > 0;
    }
}

/**
 * Deletes all checked transactions sequentially, then refreshes totals and tiles.
 */
async function bulkDelete() {
    const checked = [...document.querySelectorAll(".row-checkbox:checked")];
    if (!checked.length) return;
    if (!confirm(`Delete ${checked.length} transaction${checked.length > 1 ? "s" : ""}?\n\nThis will also remove all jar allocations. This cannot be undone.`)) return;
    for (const cb of checked) {
        const id   = parseInt(cb.dataset.id);
        const resp = await fetch(`/api/savings/transactions/${id}`, { method: "DELETE" });
        if (resp.ok) {
            const row = document.getElementById(`srow-${id}`);
            if (row) row.remove();
        }
    }
    updateBulkDelete();
    updateFooterTotals();
    refreshStatTiles(); refreshJarTiles();
}

// ── Live tile refresh ─────────────────────────────────────────────────────────

/**
 * Fetches current summary stats and updates the four stat tiles in place.
 * Also updates the jar allocation tile color based on whether funds balance.
 */
async function refreshStatTiles() {
    try {
        const resp = await fetch("/api/savings/summary");
        if (!resp.ok) return;
        const d   = await resp.json();
        const fmt = n => "$" + Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

        const tileBalance  = document.getElementById("tile-account-balance");
        const tileJar      = document.getElementById("tile-jar-total");
        const tileJarSub   = document.getElementById("tile-jar-sub");
        const tileJarCard  = document.getElementById("tile-jar-card");
        const tileDeposit  = document.getElementById("tile-deposits-ytd");
        const tileWithdraw = document.getElementById("tile-withdrawals-ytd");

        if (tileBalance)  tileBalance.textContent  = fmt(d.account_balance);
        if (tileJar)      tileJar.textContent      = fmt(d.jar_total);
        if (tileDeposit)  tileDeposit.textContent  = fmt(d.deposits_ytd);
        if (tileWithdraw) tileWithdraw.textContent = fmt(d.withdrawals_ytd);

        if (tileJarSub && tileJarCard) {
            const diff = d.account_balance - d.jar_total;
            if (Math.abs(diff) < 0.01) {
                tileJarSub.textContent = "✓ Fully accounted for";
                tileJarCard.className  = tileJarCard.className.replace(/stat-bg-\w+/g, "stat-bg-green");
            } else if (diff > 0) {
                tileJarSub.textContent = `⚠ $${diff.toFixed(2)} unallocated`;
                tileJarCard.className  = tileJarCard.className.replace(/stat-bg-\w+/g, "stat-bg-red");
            } else {
                tileJarSub.textContent = `⚠ Over by $${Math.abs(diff).toFixed(2)}`;
                tileJarCard.className  = tileJarCard.className.replace(/stat-bg-\w+/g, "stat-bg-red");
            }
        }
    } catch(e) { /* silent — tiles update on next full load */ }
}

/**
 * Fetches current jar balances and re-renders the jar tile grid without reloading.
 */
async function refreshJarTiles() {
    try {
        const resp = await fetch("/api/savings/jars");
        if (!resp.ok) return;
        const { jars } = await resp.json();
        const grid = document.getElementById("jar-tiles-grid");
        if (!grid) return;
        grid.innerHTML = jars.map(jar => {
            const neg      = jar.balance < 0;
            const pct      = Math.min(jar.pct, 100);
            const barFill  = neg
                ? `style="width:100%;background:#e74a3b;"`
                : `style="width:${pct}%;background:${jar.color};"`;
            const amtSign  = neg ? "−" : "";
            const amtVal   = "$" + Math.abs(jar.balance).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});
            const safeName = jar.name.replace(/'/g, "\\'");
            return `
            <div class="col-6 col-md-3 col-lg-2">
                <div class="jar-tile ${neg ? "jar-tile-negative" : ""}"
                     onclick="openJarHistory(${jar.category_id}, '${safeName}')">
                    <div class="jar-tile-name">${jar.name}</div>
                    <div class="jar-tile-amount ${neg ? "amount-debit" : ""}">${amtSign}${amtVal}</div>
                    <div class="jar-bar mt-1">
                        <div class="jar-bar-fill" ${barFill}></div>
                    </div>
                    <small class="text-muted" style="font-size:0.68rem;">
                        ${jar.pct.toFixed(1)}% of savings
                        ${neg ? '<span class="text-danger ms-1">⚠ negative</span>' : ""}
                    </small>
                </div>
            </div>`;
        }).join("");
    } catch(e) { console.warn("refreshJarTiles error:", e); }
}

/**
 * Confirms and deletes a single savings transaction, fades out its row,
 * then refreshes totals and tiles.
 * @param {number} txnId
 * @param {string} description - Used in the confirmation prompt.
 */
async function deleteSavingsTransaction(txnId, description) {
    if (!confirm(`Delete "${description}"?\n\nThis will also remove all jar allocations for this transaction. This cannot be undone.`)) return;
    const resp = await fetch(`/api/savings/transactions/${txnId}`, { method: "DELETE" });
    if (resp.ok) {
        const row = document.getElementById(`srow-${txnId}`);
        row.style.transition = "opacity 0.3s";
        row.style.opacity    = "0";
        setTimeout(() => { row.remove(); updateFooterTotals(); refreshStatTiles(); refreshJarTiles(); }, 300);
    } else {
        alert("Failed to delete transaction. Please try again.");
    }
}

/**
 * Recalculates deposit, withdrawal, and net totals from current DOM rows
 * and updates the table footer without a page reload.
 */
function updateFooterTotals() {
    let deposits = 0, withdrawals = 0;
    document.querySelectorAll("#savings-tbody tr").forEach(row => {
        const amountCell = row.querySelectorAll("td")[3];
        if (!amountCell) return;
        const val = parseFloat(amountCell.dataset.val) || 0;
        if (val > 0) deposits    += val;
        else         withdrawals += Math.abs(val);
    });
    const net = deposits - withdrawals;
    const fmt = n => "$" + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    const tfoot = document.querySelector("#savings-table tfoot");
    if (!tfoot) return;
    const rows = tfoot.querySelectorAll("tr");
    rows[0].querySelector("td:last-child").textContent = "+" + fmt(deposits);
    rows[1].querySelector("td:last-child").textContent = "−" + fmt(withdrawals);
    const netCell = rows[2].querySelector("td.fw-bold");
    if (netCell) {
        netCell.textContent = (net >= 0 ? "+" : "−") + fmt(Math.abs(net));
        netCell.classList.toggle("amount-credit", net >= 0);
        netCell.classList.toggle("amount-debit",  net < 0);
    }
}

// ── Rebalance modal ───────────────────────────────────────────────────────────

/** @type {Array<Object>} Jar data for the rebalance modal, augmented with target amounts. */
let rebalanceJars = [];

/**
 * Opens the Rebalance modal and fetches current jar balances to populate it.
 */
async function openRebalanceModal() {
    rebalanceJars = [];
    document.getElementById("rebalance-tbody").innerHTML =
        '<tr><td colspan="4" class="text-center text-muted py-3">Loading…</td></tr>';
    document.getElementById("rebalance-save-btn").disabled = true;
    new bootstrap.Modal(document.getElementById("rebalanceModal")).show();

    const resp = await fetch("/api/savings/jars");
    if (!resp.ok) {
        document.getElementById("rebalance-tbody").innerHTML =
            '<tr><td colspan="4" class="text-center text-danger py-3">Failed to load jar balances.</td></tr>';
        return;
    }
    const data = await resp.json();
    rebalanceJars = data.jars.map(j => ({ ...j, target: j.balance }));
    renderRebalanceTable();
}

/**
 * Renders the rebalance table rows from current rebalanceJars state.
 */
function renderRebalanceTable() {
    const fmt = n => (n < 0 ? "−" : "") + "$" + Math.abs(n).toFixed(2);
    document.getElementById("rebalance-tbody").innerHTML = rebalanceJars.map((jar, idx) => {
        const change = jar.target - jar.balance;
        const cls    = change > 0.005 ? "amount-credit" : change < -0.005 ? "amount-debit" : "text-muted";
        return `<tr>
            <td style="font-size:0.85rem;">${jar.name}</td>
            <td class="text-end" style="font-size:0.85rem;">${fmt(jar.balance)}</td>
            <td>
                <div class="input-group input-group-sm">
                    <span class="input-group-text">$</span>
                    <input type="number" class="form-control text-end" step="0.01"
                           value="${jar.target.toFixed(2)}"
                           oninput="onRebalanceChange(${idx}, this.value)">
                </div>
            </td>
            <td class="text-end fw-semibold ${cls}" style="font-size:0.85rem;">
                ${Math.abs(change) < 0.005 ? "—" : (change > 0 ? "+" : "−") + "$" + Math.abs(change).toFixed(2)}
            </td>
        </tr>`;
    }).join("");
    updateRebalanceValidation();
}

/**
 * Updates a single jar's target and refreshes validation.
 * @param {number} idx - Index into rebalanceJars.
 * @param {string} val - Raw string value from the input field.
 */
function onRebalanceChange(idx, val) {
    rebalanceJars[idx].target = parseFloat(val) || 0;
    const change = rebalanceJars[idx].target - rebalanceJars[idx].balance;
    const cls    = change > 0.005 ? "amount-credit" : change < -0.005 ? "amount-debit" : "text-muted";
    const tds    = document.querySelectorAll("#rebalance-tbody tr")[idx]?.querySelectorAll("td");
    if (tds) {
        tds[3].className   = `text-end fw-semibold ${cls}`;
        tds[3].textContent = Math.abs(change) < 0.005 ? "—" : (change > 0 ? "+" : "−") + "$" + Math.abs(change).toFixed(2);
    }
    updateRebalanceValidation();
}

/**
 * Checks whether target totals match current totals, updates the validation
 * banner, and enables/disables the save button.
 */
function updateRebalanceValidation() {
    const currentTotal = rebalanceJars.reduce((s, j) => s + j.balance, 0);
    const targetTotal  = rebalanceJars.reduce((s, j) => s + j.target, 0);
    const diff         = Math.abs(targetTotal - currentTotal);
    const balanced     = diff < 0.01;
    const fmt          = n => "$" + Math.abs(n).toFixed(2);

    document.getElementById("rebalance-current-total").textContent = fmt(currentTotal);
    document.getElementById("rebalance-target-total").textContent  = fmt(targetTotal);
    const diffEl = document.getElementById("rebalance-diff-total");
    diffEl.textContent = balanced ? "—" : (targetTotal > currentTotal ? "+" : "−") + fmt(diff);
    diffEl.className   = "text-end " + (balanced ? "text-muted" : targetTotal > currentTotal ? "amount-credit" : "amount-debit");

    const valBox  = document.getElementById("rebalance-validation");
    const valText = document.getElementById("rebalance-validation-text");
    const saveBtn = document.getElementById("rebalance-save-btn");
    if (balanced) {
        valBox.style.cssText  = "background:#d4edda;border:1px solid #c3e6cb;";
        valText.style.color   = "#155724";
        valText.textContent   = "✓ Totals match — ready to apply";
        saveBtn.disabled      = false;
    } else {
        valBox.style.cssText  = "background:#f8d7da;border:1px solid #f5c6cb;";
        valText.style.color   = "#721c24";
        valText.textContent   = `Totals don't match — difference of ${fmt(diff)}`;
        saveBtn.disabled      = true;
    }
}

/**
 * Submits the rebalance, sending only jars whose target differs from current balance.
 * Reloads on success to show the new $0 rebalance transaction in the ledger.
 */
async function submitRebalance() {
    const items = rebalanceJars
        .map(j => ({ category_id: j.category_id, amount: parseFloat((j.target - j.balance).toFixed(2)) }))
        .filter(j => Math.abs(j.amount) > 0.005);

    const resp = await fetch("/api/savings/rebalance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allocations: items })
    });
    if (resp.ok) {
        bootstrap.Modal.getInstance(document.getElementById("rebalanceModal")).hide();
        location.reload();
    } else {
        const err = await resp.json().catch(() => ({}));
        alert(err.detail || "Rebalance failed. Please try again.");
    }
}

// ── Jar history offcanvas ─────────────────────────────────────────────────────

/** @type {Chart|null} The currently rendered jar history chart instance. */
let jarHistoryChartInstance = null;

/**
 * Opens the jar history offcanvas, fetches history for the given jar, and renders
 * a running-balance sparkline and transaction table.
 * @param {number} categoryId - The jar's category ID.
 * @param {string} jarName - Display name shown in the panel header.
 */
async function openJarHistory(categoryId, jarName) {
    document.getElementById("jar-history-title").textContent   = jarName + " — History";
    document.getElementById("jar-history-balance").textContent = "Loading…";
    document.getElementById("jar-history-tbody").innerHTML     =
        '<tr><td colspan="4" class="text-center text-muted py-3">Loading…</td></tr>';
    document.getElementById("jar-stats-strip").innerHTML = "";

    new bootstrap.Offcanvas(document.getElementById("jarHistoryDrawer")).show();

    const resp = await fetch(`/api/savings/jars/${categoryId}/history`);
    if (!resp.ok) {
        document.getElementById("jar-history-tbody").innerHTML =
            '<tr><td colspan="4" class="text-center text-danger py-3">Failed to load history.</td></tr>';
        return;
    }

    const data = await resp.json();
    document.getElementById("jar-history-balance").textContent =
        `Current balance: $${data.balance.toFixed(2)}`;

    const dark = document.body.classList.contains("dark-mode");
    document.getElementById("jar-stats-strip").innerHTML = `
        <div class="text-center flex-fill p-1 rounded" style="background:${dark?'#2a2a45':'#eef0fb'};">
            <div style="color:${dark?'#aaa':'#858796'};">Avg deposit/mo</div>
            <div class="fw-bold text-primary">+$${data.avg_deposit.toFixed(2)}</div>
        </div>
        <div class="text-center flex-fill p-1 rounded" style="background:${dark?'#2a1a1a':'#fff8f8'};">
            <div style="color:${dark?'#aaa':'#858796'};">Withdrawn YTD</div>
            <div class="fw-bold amount-debit">−$${data.withdrawn_ytd.toFixed(2)}</div>
        </div>
        <div class="text-center flex-fill p-1 rounded" style="background:${dark?'#251f35':'#f3f0ff'};">
            <div style="color:${dark?'#aaa':'#858796'};">Net YTD</div>
            <div class="fw-bold" style="color:#6f42c1;">
                ${data.net_ytd >= 0 ? '+' : '−'}$${Math.abs(data.net_ytd).toFixed(2)}
            </div>
        </div>`;

    if (jarHistoryChartInstance) jarHistoryChartInstance.destroy();
    jarHistoryChartInstance = new Chart(document.getElementById("jarHistoryChart"), {
        type: "line",
        data: {
            labels: data.chart_labels,
            datasets: [{
                data: data.chart_balances,
                borderColor: "#6f42c1", backgroundColor: "rgba(111,66,193,0.1)",
                borderWidth: 2, fill: true, tension: 0.3, pointRadius: 2,
            }]
        },
        options: {
            plugins: { legend: { display: false } },
            scales: {
                y: { ticks: { callback: v => "$" + v.toFixed(0), font: { size: 10 } } },
                x: { ticks: { font: { size: 10 } }, grid: { display: false } }
            },
            maintainAspectRatio: false,
        }
    });

    if (!data.entries.length) {
        document.getElementById("jar-history-tbody").innerHTML =
            '<tr><td colspan="4" class="text-center text-muted py-3">No activity for this jar.</td></tr>';
        return;
    }

    document.getElementById("jar-history-tbody").innerHTML = data.entries.map(e => `
        <tr>
            <td style="white-space:nowrap;font-size:0.82rem;">${e.date}</td>
            <td style="font-size:0.82rem;">${e.description}</td>
            <td class="text-end ${e.amount >= 0 ? 'amount-credit' : 'amount-debit'}" style="font-size:0.82rem;">
                ${e.amount >= 0 ? '+' : '−'}$${Math.abs(e.amount).toFixed(2)}
            </td>
            <td class="text-end fw-bold" style="font-size:0.82rem;">
                $${e.running_balance.toFixed(2)}
            </td>
        </tr>`).join("");
}

// ── Allocation modal ──────────────────────────────────────────────────────────

/** @type {number|null} ID of the transaction currently being allocated. */
let allocTxnId     = null;
/** @type {number} Signed amount of the transaction being allocated. */
let allocTxnAmount = 0;
/** @type {Array<Object>} All available jars with current balances, fetched on modal open. */
let allocJars      = [];
/** @type {Array<Object>} Jars currently added to the allocation table with entered amounts. */
let allocRows      = [];

/**
 * Opens the Allocation modal, styles it for deposit vs withdrawal, fetches
 * existing allocations and jar balances, and pre-fills from the default template
 * if this is a new unallocated deposit whose total matches the template.
 * @param {number} txnId
 * @param {number} amount - Signed transaction amount.
 * @param {string} description
 * @param {boolean} isAllocated - Whether the transaction already has allocations.
 */
async function openAllocateModal(txnId, amount, description, isAllocated) {
    allocTxnId     = txnId;
    allocTxnAmount = amount;
    allocRows      = [];

    const isDeposit = amount > 0;

    const header = document.getElementById("alloc-modal-header");
    header.style.background = isDeposit
        ? "linear-gradient(135deg,#6f42c1,#5a32a3)"
        : "linear-gradient(135deg,#e74a3b,#c0392b)";
    header.style.color = "#fff";

    document.getElementById("alloc-modal-title").textContent    = isDeposit ? "Allocate Deposit" : "Allocate Withdrawal";
    document.getElementById("alloc-modal-subtitle").textContent = description;
    document.getElementById("alloc-modal-amount").textContent   = (amount >= 0 ? "+" : "−") + "$" + Math.abs(amount).toFixed(2);

    document.getElementById("alloc-template-save-wrap").style.visibility = isDeposit ? "visible" : "hidden";
    document.getElementById("alloc-save-template").checked = false;

    const saveBtn = document.getElementById("alloc-save-btn");
    saveBtn.style.background  = isDeposit ? "#6f42c1" : "#e74a3b";
    saveBtn.style.borderColor = isDeposit ? "#6f42c1" : "#e74a3b";

    new bootstrap.Modal(document.getElementById("allocateModal")).show();

    const resp = await fetch(`/api/savings/transactions/${txnId}/allocations`);
    if (!resp.ok) { alert("Failed to load allocation data."); return; }
    const data = await resp.json();

    allocJars = data.jars;
    renderJarList();

    // Pre-fill from default template only for new unallocated deposits where
    // the template total exactly matches the transaction amount.
    if (isDeposit && data.allocations.length === 0) {
        const tResp = await fetch("/api/savings/templates/default");
        if (tResp.ok) {
            const tData = await tResp.json();
            const templateTotal = tData.items.reduce((s, i) => s + i.amount, 0);
            const amountMatches = Math.abs(templateTotal - allocTxnAmount) < 0.01;
            if (tData.items.length > 0 && amountMatches) {
                document.getElementById("alloc-template-notice").classList.remove("d-none");
                document.getElementById("alloc-template-name").textContent = tData.name || "Default Template";
                for (const item of tData.items) {
                    const jar = allocJars.find(j => j.category_id === item.category_id);
                    if (jar) addAllocRow(jar, item.amount);
                }
            } else {
                document.getElementById("alloc-template-notice").classList.add("d-none");
            }
        }
    } else {
        document.getElementById("alloc-template-notice").classList.add("d-none");
        for (const item of data.allocations) {
            const jar = allocJars.find(j => j.category_id === item.category_id);
            if (jar) addAllocRow(jar, item.amount);
        }
    }

    renderAllocTable();
    updateValidation();
}

/**
 * Renders the left-panel jar list, highlighting jars already in allocRows.
 */
function renderJarList() {
    const selectedIds = new Set(allocRows.map(r => r.category_id));
    document.getElementById("alloc-jar-list").innerHTML = allocJars.map(jar => {
        const sel      = selectedIds.has(jar.category_id) ? "selected" : "";
        const balClass = jar.balance >= 0 ? "positive" : "negative";
        const balSign  = jar.balance < 0 ? "−" : "";
        return `<div class="jar-ref-item ${sel}" onclick="toggleJar(${jar.category_id})">
            <span class="jar-ref-name">${jar.name}</span>
            <span class="jar-ref-bal ${balClass}">${balSign}$${Math.abs(jar.balance).toFixed(2)}</span>
        </div>`;
    }).join("");
}

/**
 * Adds or removes a jar from the allocation table when clicked in the jar list.
 * @param {number} categoryId
 */
function toggleJar(categoryId) {
    const idx = allocRows.findIndex(r => r.category_id === categoryId);
    if (idx >= 0) { allocRows.splice(idx, 1); }
    else {
        const jar = allocJars.find(j => j.category_id === categoryId);
        if (jar) addAllocRow(jar, 0);
    }
    renderJarList();
    renderAllocTable();
    updateValidation();
}

/**
 * Appends a jar to allocRows if not already present.
 * @param {Object} jar - Jar object from allocJars.
 * @param {number} amount - Initial allocation amount.
 */
function addAllocRow(jar, amount) {
    if (allocRows.find(r => r.category_id === jar.category_id)) return;
    allocRows.push({ category_id: jar.category_id, name: jar.name, balance: jar.balance, amount });
}

/**
 * Removes a jar from the allocation table by category ID.
 * @param {number} categoryId
 */
function removeAllocRow(categoryId) {
    allocRows = allocRows.filter(r => r.category_id !== categoryId);
    renderJarList();
    renderAllocTable();
    updateValidation();
}

/**
 * Renders the right-panel allocation table showing current balance, amount input,
 * and projected post-allocation balance for each jar.
 */
function renderAllocTable() {
    const tbody   = document.getElementById("alloc-tbody");
    const emptyEl = document.getElementById("alloc-empty");

    if (allocRows.length === 0) {
        tbody.innerHTML = "";
        emptyEl.classList.remove("d-none");
        return;
    }
    emptyEl.classList.add("d-none");

    const amtHeader = document.querySelector("#alloc-table thead th:nth-child(3)");
    if (amtHeader) amtHeader.textContent = allocTxnAmount < 0 ? "Withdraw ($)" : "Amount ($)";

    tbody.innerHTML = allocRows.map((row, idx) => {
        const after      = row.balance + row.amount;
        const afterClass = after < 0 ? "proj-negative" : "proj-positive";
        const afterSign  = after < 0 ? "−" : "+";
        const balClass   = row.balance >= 0 ? "bal-pill-pos" : "bal-pill-neg";
        const balSign    = row.balance < 0 ? "−" : "";
        return `<tr>
            <td>${row.name}</td>
            <td class="text-end">
                <span class="bal-pill-sm ${balClass}">${balSign}$${Math.abs(row.balance).toFixed(2)}</span>
            </td>
            <td>
                <input type="number" class="form-control form-control-sm"
                       step="0.01" value="${row.amount !== 0 ? Math.abs(row.amount).toFixed(2) : ''}"
                       placeholder="0.00"
                       oninput="onAmountChange(${idx}, this.value)">
            </td>
            <td class="text-end ${afterClass}">${afterSign}$${Math.abs(after).toFixed(2)}</td>
            <td>
                <button class="btn p-0" style="color:#dc3545;font-size:0.8rem;line-height:1;"
                        onclick="removeAllocRow(${row.category_id})">✕</button>
            </td>
        </tr>`;
    }).join("");
}

/**
 * Handles amount input in the allocation table.
 * For withdrawals, user enters positive numbers stored as negative internally.
 * Updates only the projected balance cell to preserve input focus.
 * @param {number} idx - Index into allocRows.
 * @param {string} val - Raw input value.
 */
function onAmountChange(idx, val) {
    const raw = parseFloat(val) || 0;
    allocRows[idx].amount = (allocTxnAmount < 0) ? -Math.abs(raw) : raw;
    const trs = document.querySelectorAll("#alloc-tbody tr");
    if (trs[idx]) {
        const row       = allocRows[idx];
        const after     = row.balance + row.amount;
        const afterCell = trs[idx].querySelectorAll("td")[3];
        afterCell.className   = after < 0 ? "text-end proj-negative" : "text-end proj-positive";
        afterCell.textContent = (after < 0 ? "−" : "+") + "$" + Math.abs(after).toFixed(2);
    }
    updateValidation();
}

/**
 * Validates that allocation sum matches the transaction amount, updates the
 * balance bar, warns if any jar goes negative, and gates the save button.
 */
function updateValidation() {
    const target     = Math.abs(allocTxnAmount);
    const totalAlloc = Math.abs(allocRows.reduce((sum, r) => sum + r.amount, 0));
    const diff       = totalAlloc - target;
    const balanced   = Math.abs(diff) < 0.01;
    const fmt        = n => "$" + Math.abs(n).toFixed(2);

    document.getElementById("alloc-total-display").textContent  = fmt(totalAlloc);
    document.getElementById("alloc-target-display").textContent = fmt(target);

    const bar    = document.getElementById("alloc-balance-bar");
    const status = document.getElementById("alloc-balance-status");

    if (balanced) {
        bar.style.background  = "#d4edda";
        bar.style.borderColor = "#c3e6cb";
        status.textContent    = "✓ Balanced";
        status.style.color    = "#155724";
    } else if (diff < 0) {
        bar.style.background  = "#f8f9fc";
        bar.style.borderColor = "#e3e6f0";
        status.textContent    = `${fmt(Math.abs(diff))} remaining`;
        status.style.color    = "#856404";
    } else {
        bar.style.background  = "#f8d7da";
        bar.style.borderColor = "#f5c6cb";
        status.textContent    = `${fmt(diff)} over`;
        status.style.color    = "#721c24";
    }

    const negJars = allocRows.filter(r => (r.balance + r.amount) < 0);
    const warnEl  = document.getElementById("alloc-negative-warn");
    if (negJars.length > 0) {
        const names = negJars.map(r => {
            const after = r.balance + r.amount;
            return `${r.name} (${after < 0 ? "−" : ""}$${Math.abs(after).toFixed(2)})`;
        }).join(", ");
        document.getElementById("alloc-negative-warn-text").textContent =
            `Jar${negJars.length > 1 ? "s" : ""} will go negative: ${names}`;
        warnEl.classList.remove("d-none");
    } else {
        warnEl.classList.add("d-none");
    }

    document.getElementById("alloc-save-btn").disabled = !balanced;
}

/**
 * Saves allocations via the API, optionally saves the current split as the
 * default deposit template, then updates the ledger row in place.
 */
async function submitAllocations() {
    const items = allocRows
        .filter(r => r.amount !== 0)
        .map(r => ({ category_id: r.category_id, amount: r.amount }));

    const resp = await fetch(`/api/savings/transactions/${allocTxnId}/allocations`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allocations: items }),
    });

    if (!resp.ok) {
        const err = await resp.json();
        alert(err.detail || "Failed to save allocations.");
        return;
    }

    const result = await resp.json();

    if (document.getElementById("alloc-save-template").checked && allocTxnAmount > 0) {
        await fetch("/api/savings/templates/default", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: "Default Template", items }),
        });
    }

    allocFromAdd = false;
    bootstrap.Modal.getInstance(document.getElementById("allocateModal")).hide();
    updateLedgerRow(allocTxnId, result.is_allocated, items);
    refreshStatTiles(); refreshJarTiles();
}

/**
 * Updates a ledger row's status badge, allocation pills, and dropdown label
 * after a successful save, without reloading the page.
 * @param {number} txnId
 * @param {boolean} isAllocated
 * @param {Array<Object>} items - The saved allocation items.
 */
function updateLedgerRow(txnId, isAllocated, items) {
    const row = document.getElementById(`srow-${txnId}`);
    if (!row) { location.reload(); return; }

    row.classList.toggle("savings-unallocated-row", !isAllocated);

    const statusCell = row.querySelectorAll("td")[4];
    if (statusCell) {
        statusCell.innerHTML = isAllocated
            ? '<span class="badge-alloc-sav">✓ Allocated</span>'
            : '<span class="badge-unalloc-sav">⚠ Pending</span>';
    }

    const allocCell = row.querySelectorAll("td")[5];
    if (allocCell) {
        if (items.length === 0) {
            allocCell.innerHTML = '<em class="text-muted small">Not yet allocated to jars</em>';
        } else {
            allocCell.innerHTML = items.map(item => {
                const jar  = allocJars.find(j => j.category_id === item.category_id);
                const name = jar ? jar.name : `Jar ${item.category_id}`;
                const cls  = item.amount >= 0 ? "alloc-deposit" : "alloc-withdraw";
                const sign = item.amount >= 0 ? "+" : "−";
                return `<span class="alloc-pill ${cls}">${name} ${sign}$${Math.abs(item.amount).toFixed(2)}</span>`;
            }).join("");
        }
    }

    const allocLink = row.querySelector(".dropdown-item");
    if (allocLink) {
        allocLink.innerHTML = `<i class="bi bi-distribute-vertical me-2"></i>${isAllocated ? "Edit Allocations" : "Allocate"}`;
    }
}

// ── CSV import ────────────────────────────────────────────────────────────────

/** @type {File|null} The currently selected CSV file for savings import. */
let savingsSelectedFile = null;

/**
 * Handles file selection from the file input, updating the drop zone label.
 * @param {File} file
 */
function handleSavingsFileSelect(file) {
    if (!file) return;
    savingsSelectedFile = file;
    document.getElementById("savings-drop-label").innerHTML =
        `<i class="bi bi-file-earmark-check text-success me-1"></i><strong>${file.name}</strong>`;
    document.getElementById("savings-drop-zone").style.borderColor = "#198754";
    updateSavingsImportBtn();
}

/**
 * Handles drag-and-drop onto the drop zone.
 * @param {DragEvent} e
 */
function handleSavingsDrop(e) {
    e.preventDefault();
    document.getElementById("savings-drop-zone").style.borderColor = "#dee2e6";
    const file = e.dataTransfer.files[0];
    if (file) {
        document.getElementById("savings-import-file").files = e.dataTransfer.files;
        handleSavingsFileSelect(file);
    }
}

/**
 * Enables the import button only when both a bank and a file are selected.
 */
function updateSavingsImportBtn() {
    const bank = document.getElementById("savings-import-bank").value;
    document.getElementById("savings-import-btn").disabled = !(bank && savingsSelectedFile);
}

document.getElementById("savings-import-bank").addEventListener("change", updateSavingsImportBtn);

/**
 * Uploads the selected CSV to the savings import API, shows a spinner during
 * the request, then displays the result summary or an error message.
 */
async function runSavingsImport() {
    const bank = document.getElementById("savings-import-bank").value;
    if (!bank || !savingsSelectedFile) return;

    document.getElementById("savings-import-form-section").classList.add("d-none");
    document.getElementById("savings-import-loading").classList.remove("d-none");
    document.getElementById("savings-import-loading").classList.add("d-flex");
    document.getElementById("savings-import-error").classList.add("d-none");

    const formData = new FormData();
    formData.append("file", savingsSelectedFile);
    formData.append("bank", bank);

    try {
        const resp = await fetch("/api/savings/import", { method: "POST", body: formData });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Import failed");

        document.getElementById("sav-res-imported").textContent = data.imported;
        document.getElementById("sav-res-dupes").textContent    = data.duplicates_skipped;
        document.getElementById("sav-res-skipped").textContent  = data.skipped;

        document.getElementById("savings-import-loading").classList.add("d-none");
        document.getElementById("savings-import-loading").classList.remove("d-flex");
        document.getElementById("savings-import-result").classList.remove("d-none");
        document.getElementById("savings-import-result").classList.add("d-flex");
        refreshStatTiles(); refreshJarTiles();

    } catch (err) {
        document.getElementById("savings-import-loading").classList.add("d-none");
        document.getElementById("savings-import-loading").classList.remove("d-flex");
        document.getElementById("savings-import-form-section").classList.remove("d-none");
        document.getElementById("savings-import-error").classList.remove("d-none");
        document.getElementById("savings-import-error-msg").textContent = err.message;
    }
}

/**
 * Resets the import offcanvas to its initial state for another import.
 */
function resetSavingsImport() {
    savingsSelectedFile = null;
    document.getElementById("savings-import-file").value = "";
    document.getElementById("savings-import-bank").value = "";
    document.getElementById("savings-drop-label").innerHTML = 'Drag &amp; drop or <span class="text-primary">browse</span>';
    document.getElementById("savings-drop-zone").style.borderColor = "#dee2e6";
    document.getElementById("savings-import-btn").disabled = true;
    document.getElementById("savings-import-form-section").classList.remove("d-none");
    document.getElementById("savings-import-result").classList.add("d-none");
    document.getElementById("savings-import-result").classList.remove("d-flex");
    document.getElementById("savings-import-error").classList.add("d-none");
}
