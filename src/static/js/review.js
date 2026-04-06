/**
 * @file review.js
 * @description Client-side logic for the Review Queue page.
 *
 * Provides bulk and single-row actions for categorizing or excluding uncategorized
 * transactions. Rows fade out as they are processed so the queue shrinks live
 * without a full page reload. A floating bulk action bar appears when one or more
 * rows are selected.
 *
 * Features:
 *   - Shift-click range selection across checkboxes
 *   - Single-row assign and exclude actions
 *   - Bulk assign and bulk exclude with parallel API calls
 *   - Live queue count and navbar badge updates
 *   - Auto-reload when the queue is empty
 */

/** @type {HTMLInputElement|null} The last checkbox that was clicked, for shift-range selection. */
let lastChecked = null;

/**
 * Handles checkbox clicks with shift-click range selection support.
 * @param {MouseEvent} e
 * @param {HTMLInputElement} cb - The checkbox that was clicked.
 */
function handleCheckboxClick(e, cb) {
    if (e.shiftKey && lastChecked && lastChecked !== cb) {
        const checkboxes = [...document.querySelectorAll(".row-check")];
        const from = checkboxes.indexOf(lastChecked);
        const to   = checkboxes.indexOf(cb);
        const [start, end] = from < to ? [from, to] : [to, from];
        checkboxes.slice(start, end + 1).forEach(el => el.checked = cb.checked);
    }
    lastChecked = cb;
    updateSelection();
}

/**
 * Selects or deselects all row checkboxes via the header checkbox.
 * @param {HTMLInputElement} cb - The select-all checkbox.
 */
function toggleAll(cb) {
    document.querySelectorAll(".row-check").forEach(el => el.checked = cb.checked);
    updateSelection();
}

/**
 * Deselects all rows and hides the bulk action bar.
 */
function clearSelection() {
    document.querySelectorAll(".row-check").forEach(el => el.checked = false);
    document.getElementById("select-all").checked = false;
    updateSelection();
}

/**
 * Returns the IDs of all currently checked rows.
 * @returns {number[]}
 */
function getSelectedIds() {
    return [...document.querySelectorAll(".row-check:checked")]
        .map(cb => parseInt(cb.dataset.id));
}

/**
 * Updates the bulk bar visibility, selected count, row highlight classes,
 * and the select-all checkbox indeterminate state.
 */
function updateSelection() {
    const ids = getSelectedIds();
    document.getElementById("selected-count").textContent = ids.length;
    const bar = document.getElementById("bulk-bar");
    bar.classList.toggle("hidden", ids.length === 0);

    document.querySelectorAll(".row-check").forEach(cb => {
        document.getElementById("row-" + cb.dataset.id)
            .classList.toggle("selected-row", cb.checked);
    });

    const all = document.querySelectorAll(".row-check");
    document.getElementById("select-all").indeterminate =
        ids.length > 0 && ids.length < all.length;
    document.getElementById("select-all").checked =
        ids.length > 0 && ids.length === all.length;
}

/**
 * Fades out and removes rows for the given transaction IDs, then updates the queue count.
 * @param {number[]} ids
 */
function removeRows(ids) {
    ids.forEach(id => {
        const row = document.getElementById("row-" + id);
        if (!row) return;
        row.style.transition = "opacity 0.3s";
        row.style.opacity = "0";
        setTimeout(() => { row.remove(); updateCount(); }, 300);
    });
    setTimeout(updateSelection, 350);
}

/**
 * Updates the queue subtitle and navbar badge to reflect the current remaining count.
 * Reloads the page if the queue reaches zero (to show the "All caught up" state).
 */
function updateCount() {
    const remaining = document.querySelectorAll("tbody tr").length;

    const subtitle = document.getElementById("queue-count");
    if (subtitle) {
        subtitle.textContent = remaining + " transaction" + (remaining !== 1 ? "s" : "") + " need categorizing";
    }

    const badge = document.querySelector(".nav-link .badge");
    if (badge) {
        if (remaining > 0) { badge.textContent = remaining; }
        else { badge.remove(); }
    }

    if (remaining === 0) location.reload();
}

/**
 * Assigns the selected category to a single transaction and removes its row.
 * @param {number} transactionId
 */
async function assignSingle(transactionId) {
    const select     = document.getElementById("category-" + transactionId);
    const categoryId = select.value;
    if (!categoryId) { alert("Please select a category first."); return; }

    const response = await fetch(`/transactions/${transactionId}/category`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: parseInt(categoryId) })
    });

    if (response.ok) { removeRows([transactionId]); }
    else { alert("Failed to assign category. Please try again."); }
}

/**
 * Excludes a single transaction from reports and removes its row.
 * @param {number} transactionId
 */
async function excludeSingle(transactionId) {
    const row         = document.getElementById("row-" + transactionId);
    const description = row.querySelector("td:nth-child(3)").textContent.trim();
    if (!confirm(`Exclude "${description}" from reports?\n\nYou can restore it using "Show Excluded" on the transactions page.`)) return;

    const response = await fetch(`/api/transactions/${transactionId}/exclude`, { method: "PUT" });
    if (response.ok) { removeRows([transactionId]); }
    else { alert("Failed to exclude transaction. Please try again."); }
}

/**
 * Assigns the selected bulk category to all checked transactions in parallel.
 * Successfully updated rows are removed; failures are reported in aggregate.
 */
async function applyBulk() {
    const ids        = getSelectedIds();
    const select     = document.getElementById("bulk-category");
    const categoryId = select.value;
    if (!categoryId) { alert("Please select a category first."); return; }

    const results = await Promise.all(
        ids.map(id => fetch(`/transactions/${id}/category`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category_id: parseInt(categoryId) })
        }))
    );

    const succeeded = results.filter(r => r.ok).length;
    const failed    = results.length - succeeded;

    if (succeeded > 0) removeRows(ids.slice(0, succeeded));
    if (failed > 0) alert(`${failed} transaction(s) failed to update. Please try again.`);

    select.value = "";
}

/**
 * Excludes all checked transactions in parallel.
 * Successfully excluded rows are removed; failures are reported in aggregate.
 */
async function excludeBulk() {
    const ids = getSelectedIds();
    if (!confirm(`Exclude ${ids.length} transaction${ids.length !== 1 ? "s" : ""} from reports?\n\nYou can restore them using "Show Excluded" on the transactions page.`)) return;

    const results = await Promise.all(
        ids.map(id => fetch(`/api/transactions/${id}/exclude`, { method: "PUT" }))
    );

    const succeeded = results.filter(r => r.ok).length;
    const failed    = results.length - succeeded;

    if (succeeded > 0) removeRows(ids.slice(0, succeeded));
    if (failed > 0) alert(`${failed} transaction(s) failed to exclude. Please try again.`);
}
