/**
 * @file review.js
 * @description Client-side logic for the Review Queue page.
 *
 * Provides bulk and single-row actions for categorizing or excluding uncategorized
 * transactions. Rows fade out as they are processed so the queue shrinks live
 * without a full page reload. A floating bulk action bar appears when one or more
 * rows are selected.
 *
 * Checkbox states:
 *   - disabled (grey)  — no category selected for this row
 *   - enabled + green  — category selected, ready to confirm
 *   - checked + green  — pre-selected by the suggestion engine, ready to confirm
 *
 * Bulk bar actions:
 *   - "Confirm Selected" — confirms each checked row using its own dropdown value
 *   - "Override Category" + "Apply Override" — sets all checked rows to one category
 *   - "Exclude Selected" — excludes all checked rows
 */

/** @type {HTMLInputElement|null} Last clicked checkbox, for shift-range selection. */
let lastChecked = null;
let bulkActionRunning = false;

// ── Initialization ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    updateSelection();
    document.querySelectorAll(".sortable").forEach(header => {
        const sort = () => {
            const column = parseInt(header.dataset.col, 10);
            const direction = header.classList.contains("asc") ? "desc" : "asc";
            document.querySelectorAll(".sortable").forEach(item => {
                item.classList.remove("asc", "desc");
                item.setAttribute("aria-sort", "none");
            });
            header.classList.add(direction);
            header.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
            sortReviewRows(column, header.dataset.type, direction);
        };
        header.addEventListener("click", sort);
        header.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                sort();
            }
        });
    });
});

function sortReviewRows(column, type, direction) {
    const tbody = document.querySelector(".review-row")?.parentElement;
    if (!tbody) return;

    const rows = [...tbody.querySelectorAll(".review-row")];
    rows.sort((left, right) => {
        const value = row => {
            const cell = row.querySelectorAll("td")[column];
            if (column === 6) return cell.querySelector("select")?.selectedOptions[0]?.textContent.trim() ?? "";
            return cell.dataset.sortValue ?? cell.textContent.trim();
        };
        const leftValue = value(left);
        const rightValue = value(right);
        const comparison = type === "num"
            ? Number(leftValue) - Number(rightValue)
            : leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
        return direction === "asc" ? comparison : -comparison;
    });
    rows.forEach(row => tbody.appendChild(row));
}

// ── Checkbox handling ─────────────────────────────────────────────────────────

/**
 * Handles checkbox clicks with shift-click range selection support.
 * Only enabled (non-disabled) checkboxes participate in range selection.
 * @param {MouseEvent} e
 * @param {HTMLInputElement} cb - The checkbox that was clicked.
 */
function handleCheckboxClick(e, cb) {
    if (e.shiftKey && lastChecked && lastChecked !== cb) {
        const checkboxes = [...document.querySelectorAll(".row-check")];
        const from = checkboxes.indexOf(lastChecked);
        const to   = checkboxes.indexOf(cb);
        const [start, end] = from < to ? [from, to] : [to, from];
        checkboxes.slice(start, end + 1).forEach(el => { el.checked = cb.checked; });
    }
    lastChecked = cb;
    updateSelection();
}

/**
 * Selects or deselects all enabled row checkboxes via the header checkbox.
 * @param {HTMLInputElement} cb - The select-all checkbox.
 */
function toggleAll(cb) {
    document.querySelectorAll(".row-check").forEach(el => {
        el.checked = cb.checked;
    });
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
    bar.classList.toggle("d-none", ids.length === 0);

    document.querySelectorAll(".row-check").forEach(cb => {
        const row = document.getElementById("row-" + cb.dataset.id);
        if (row) row.classList.toggle("selected-row", cb.checked);
    });

    const all     = [...document.querySelectorAll(".row-check")];
    const checked = all.filter(cb => cb.checked);
    const selectAll = document.getElementById("select-all");
    selectAll.indeterminate = checked.length > 0 && checked.length < all.length;
    selectAll.checked       = all.length > 0 && checked.length === all.length;
}

// ── Category dropdown change ───────────────────────────────────────────────────

/**
 * Called when the user changes a row's category dropdown.
 * Enables the confirm button (green) when a category is selected, disables when not.
 * @param {number} transactionId
 * @param {HTMLSelectElement} selectEl
 */
function onCategoryChange(transactionId, selectEl) {
    const btn = document.getElementById(`confirm-btn-${transactionId}`);
    if (!btn) return;

    if (selectEl.value) {
        btn.disabled = false;
        btn.className = "btn btn-sm btn-success";
    } else {
        btn.disabled = true;
        btn.className = "btn btn-sm btn-outline-secondary";
    }
}

// ── Row removal ───────────────────────────────────────────────────────────────

/**
 * Fades out and removes rows for the given transaction IDs, then updates count.
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
 * Updates the queue subtitle and navbar badge.
 * Reloads the page when the queue reaches zero.
 */
function updateCount() {
    const remaining = document.querySelectorAll("tbody tr").length;

    const subtitle = document.getElementById("queue-count");
    if (subtitle) {
        subtitle.textContent = remaining + " transaction" + (remaining !== 1 ? "s" : "") + " need review";
    }

    const badge = document.querySelector(".nav-link .badge");
    if (badge) {
        if (remaining > 0) { badge.textContent = remaining; }
        else { badge.remove(); }
    }

    if (remaining === 0) location.reload();
}

// ── Single row actions ────────────────────────────────────────────────────────

/**
 * Confirms the category shown in a single row's dropdown and removes the row.
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

// ── Bulk actions ──────────────────────────────────────────────────────────────

/**
 * Confirms all checked rows using each row's own dropdown value.
 * Rows without a category selected are skipped with a warning.
 * This is also called by "Confirm All Pre-selected" in the page header.
 */
async function confirmChecked() {
    const checked = [...document.querySelectorAll(".row-check:checked")];
    if (!checked.length) {
        alert("No rows are selected.");
        return;
    }

    const updates = [];
    let skipped = 0;

    for (const cb of checked) {
        const id         = parseInt(cb.dataset.id);
        const select     = document.getElementById("category-" + id);
        const categoryId = select?.value;

        if (!categoryId) { skipped++; continue; }

        updates.push({ id, categoryId: parseInt(categoryId, 10) });
    }

    const result = await processBulkUpdates(updates, "Confirming");
    if (result?.succeeded.length) removeRows(result.succeeded);
    if (skipped > 0) {
        alert(`${skipped} row${skipped !== 1 ? "s" : ""} skipped — no category selected.`);
    }
    if (result?.failed.length) alert(`${result.failed.length} transaction(s) failed to confirm.`);
}

/**
 * Applies a single override category to all checked rows.
 * Uses the bulk-category dropdown in the floating bar.
 * Only fires if the user has explicitly chosen an override category.
 */
async function applyBulk() {
    const ids        = getSelectedIds();
    const select     = document.getElementById("bulk-category");
    const categoryId = select.value;
    if (!categoryId) {
        alert("Choose an override category from the dropdown first, or use \"Confirm Selected\" to confirm each row's existing category.");
        return;
    }

    const result = await processBulkUpdates(
        ids.map(id => ({ id, categoryId: parseInt(categoryId, 10) })),
        "Updating"
    );

    if (result?.succeeded.length) removeRows(result.succeeded);
    if (result?.failed.length) alert(`${result.failed.length} transaction(s) failed to update. Please try again.`);

    select.value = "";
}

/**
 * Excludes all checked transactions sequentially to avoid exhausting DB connections.
 */
async function excludeBulk() {
    const ids = getSelectedIds();
    if (!ids.length) return;
    if (!confirm(`Exclude ${ids.length} transaction${ids.length !== 1 ? "s" : ""} from reports?\n\nYou can restore them using "Show Excluded" on the transactions page.`)) return;

    const result = await processBulkUpdates(ids.map(id => ({ id })), "Excluding", true);
    if (result?.succeeded.length) removeRows(result.succeeded);
    if (result?.failed.length) alert(`${result.failed.length} transaction(s) failed to exclude. Please try again.`);
}

async function processBulkUpdates(updates, label, exclude = false) {
    if (bulkActionRunning || !updates.length) return null;

    bulkActionRunning = true;
    const controls = [...document.querySelectorAll("#bulk-bar button, #bulk-category, #confirm-preselected, .row-check, #select-all")];
    controls.forEach(control => { control.disabled = true; });
    const status = document.getElementById("review-progress");
    const bar = document.getElementById("review-progress-bar");
    const progress = status.querySelector(".progress");
    status.className = "alert alert-info py-2 mb-2";
    bar.className = "progress-bar progress-bar-striped progress-bar-animated";
    document.getElementById("review-progress-label").textContent = `${label} transactions...`;
    document.getElementById("review-progress-count").textContent = `0 of ${updates.length}`;
    bar.style.width = "0%";
    progress.setAttribute("aria-valuenow", "0");

    const succeeded = [];
    const failed = [];
    try {
        for (let index = 0; index < updates.length; index++) {
            const update = updates[index];
            const url = exclude
                ? `/api/transactions/${update.id}/exclude`
                : `/transactions/${update.id}/category`;
            const options = exclude
                ? { method: "PUT" }
                : {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ category_id: update.categoryId })
                };

            try {
                const response = await fetch(url, options);
                (response.ok ? succeeded : failed).push(update.id);
            } catch {
                failed.push(update.id);
            }

            const completed = index + 1;
            const percent = Math.round(completed / updates.length * 100);
            document.getElementById("review-progress-label").textContent = `${label} transactions...`;
            document.getElementById("review-progress-count").textContent = `${completed} of ${updates.length}`;
            bar.style.width = `${percent}%`;
            progress.setAttribute("aria-valuenow", String(percent));
        }

        status.className = `alert ${failed.length ? "alert-warning" : "alert-success"} py-2 mb-2`;
        document.getElementById("review-progress-label").textContent = failed.length
            ? `Finished with ${failed.length} failure${failed.length === 1 ? "" : "s"}.`
            : `Finished: ${succeeded.length} transaction${succeeded.length === 1 ? "" : "s"} processed.`;
        bar.className = "progress-bar";
    } finally {
        bulkActionRunning = false;
        controls.forEach(control => { control.disabled = false; });
    }

    return { succeeded, failed };
}

/**
 * Confirms all currently checked rows using their individual dropdown values.
 * Called by the "Confirm All Pre-selected" button in the page header.
 */
async function confirmAllPreselected() {
    await confirmChecked();
}
