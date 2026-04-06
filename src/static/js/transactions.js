/**
 * @file transactions.js
 * @description Client-side logic for the Transactions page.
 *
 * Covers five main areas:
 *   1. Filter panel — toggle visibility, live badge update as filters change
 *   2. Column sorting — client-side sort on date, string, or numeric columns
 *   3. Inline field editing — description, notes, and category edited in place
 *      via click-to-edit with save on blur/Enter and cancel on Escape
 *   4. Transaction actions — exclude, un-exclude, delete with fade animation
 *   5. Split transactions — modal for splitting a transaction across multiple
 *      categories, toggling split child row visibility, and removing splits
 *   6. CSV import offcanvas — file selection/drag-drop, upload, result display, reset
 *
 * @requires Bootstrap 5 (modal, offcanvas)
 * @requires SPLIT_CATEGORIES - Array of {id, name} objects injected inline by
 *           the Jinja template before this script loads.
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
        document.querySelectorAll(".sortable").forEach(el => el.classList.remove("asc", "desc"));
        th.classList.add(sortDir);
        sortTable(col, type, sortDir);
    });
});

/**
 * Sorts the transactions table in place.
 * Reads each cell's data-val attribute for reliable sorting (set server-side),
 * falling back to textContent if absent.
 * @param {number} col - Zero-based column index.
 * @param {"date"|"str"|"num"} type - Sort strategy.
 * @param {"asc"|"desc"} dir - Sort direction.
 */
function sortTable(col, type, dir) {
    const tbody = document.getElementById("tbody");
    const rows  = [...tbody.querySelectorAll("tr")];
    rows.sort((a, b) => {
        const aCell = a.querySelectorAll("td")[col];
        const bCell = b.querySelectorAll("td")[col];
        let aVal = aCell?.dataset.val ?? aCell?.textContent.trim() ?? "";
        let bVal = bCell?.dataset.val ?? bCell?.textContent.trim() ?? "";
        if (type === "num") {
            aVal = parseFloat(aVal) || 0;
            bVal = parseFloat(bVal) || 0;
            return dir === "asc" ? aVal - bVal : bVal - aVal;
        }
        return dir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });
    rows.forEach(row => tbody.appendChild(row));
}

// ── Filter badge ──────────────────────────────────────────────────────────────

// Show/hide the "Active" badge as filter inputs change without submitting the form.
document.querySelectorAll("#filter-form input, #filter-form select").forEach(el => {
    el.addEventListener("change", updateFilterBadge);
    el.addEventListener("input",  updateFilterBadge);
});

/**
 * Updates the filter badge visibility based on whether any filter has a value.
 */
function updateFilterBadge() {
    const inputs   = [...document.querySelectorAll("#filter-form input")];
    const selects  = [...document.querySelectorAll("#filter-form select")];
    const hasValue = [...inputs, ...selects].some(el => el.value.trim() !== "");
    const badge    = document.getElementById("filter-badge");
    badge.classList.toggle("d-none", !hasValue);
    badge.classList.toggle("bg-primary", hasValue);
    badge.classList.toggle("bg-secondary", !hasValue);
}

// ── Inline field editing ──────────────────────────────────────────────────────

/**
 * Shows the input field for a given field type (desc, notes, cat) and hides
 * the display element.
 * @param {"desc"|"notes"|"cat"} field - The field identifier.
 * @param {number} transactionId
 * @param {HTMLElement} displayEl - The currently visible display element.
 */
function editField(field, transactionId, displayEl) {
    const input = document.getElementById(`${field}-input-${transactionId}`);
    displayEl.classList.add("d-none");
    input.classList.remove("d-none");
    input.focus();
    if (input.select) input.select();
}

/**
 * Cancels an inline edit, restoring the display element.
 * @param {"desc"|"notes"|"cat"} field
 * @param {number} transactionId
 */
function cancelField(field, transactionId) {
    const input   = document.getElementById(`${field}-input-${transactionId}`);
    const display = document.getElementById(`${field === "cat" ? "cat-badge" : field + "-text"}-${transactionId}`);
    input.classList.add("d-none");
    display.classList.remove("d-none");
}

/**
 * Keyboard handler for inline text fields — saves on Enter, cancels on Escape.
 * @param {KeyboardEvent} event
 * @param {"desc"|"notes"} field
 * @param {number} transactionId
 */
function handleFieldKey(event, field, transactionId) {
    if (event.key === "Enter")  saveField(field, transactionId);
    if (event.key === "Escape") cancelField(field, transactionId);
}

/**
 * PATCHes the transaction with the new field value and updates the display element.
 * @param {"desc"|"notes"} field
 * @param {number} transactionId
 */
async function saveField(field, transactionId) {
    const input     = document.getElementById(`${field}-input-${transactionId}`);
    const displayId = field === "notes" ? `notes-text-${transactionId}` : `desc-text-${transactionId}`;
    const display   = document.getElementById(displayId);
    const value     = input.value.trim();

    const response = await fetch(`/api/transactions/${transactionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value })
    });

    if (response.ok) {
        display.textContent = value || (field === "notes" ? "Add note..." : "");
        if (field === "notes" && !value) display.classList.add("text-muted", "small");
    } else {
        alert("Failed to save. Please try again.");
    }

    input.classList.add("d-none");
    display.classList.remove("d-none");
}

/**
 * Handles category select change — PUTs the new category and updates the badge.
 * @param {number} transactionId
 * @param {HTMLSelectElement} selectEl
 */
async function saveCategoryField(transactionId, selectEl) {
    const categoryId = selectEl.value;
    const badge      = document.getElementById(`cat-badge-${transactionId}`);

    if (!categoryId) { cancelField("cat", transactionId); return; }

    const response = await fetch(`/transactions/${transactionId}/category`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: parseInt(categoryId) })
    });

    if (response.ok) {
        const data = await response.json();
        badge.textContent = data.category_name;
        badge.className   = "badge bg-light text-dark border category-badge";
        badge.style.cursor = "pointer";
        badge.closest("td").dataset.val = data.category_name;
    } else {
        alert("Failed to update category. Please try again.");
    }

    selectEl.classList.add("d-none");
    badge.classList.remove("d-none");
}

// ── Exclude / un-exclude ──────────────────────────────────────────────────────

/**
 * Excludes a transaction from reports and removes it from the current view.
 * @param {number} transactionId
 * @param {string} description - Used in the confirmation prompt.
 */
async function excludeTransaction(transactionId, description) {
    if (!confirm(`Exclude "${description}" from reports and budget calculations?\n\nIt will be hidden from this page but can be restored using "Show Excluded".`)) return;
    const response = await fetch(`/api/transactions/${transactionId}/exclude`, { method: "PUT" });
    if (response.ok) { fadeRemove(transactionId); }
    else { alert("Failed to exclude transaction. Please try again."); }
}

/**
 * Un-excludes a transaction and removes it from the current view (which shows excluded items).
 * @param {number} transactionId
 */
async function unexcludeTransaction(transactionId) {
    const response = await fetch(`/api/transactions/${transactionId}/unexclude`, { method: "PUT" });
    if (response.ok) { fadeRemove(transactionId); }
    else { alert("Failed to un-exclude transaction. Please try again."); }
}

// ── Delete ────────────────────────────────────────────────────────────────────

/**
 * Deletes a transaction permanently and fades out its row.
 * @param {number} transactionId
 * @param {string} description - Used in the confirmation prompt.
 */
async function deleteTransaction(transactionId, description) {
    if (!confirm(`Delete transaction "${description}"?\n\nThis cannot be undone.`)) return;
    const response = await fetch(`/api/transactions/${transactionId}`, { method: "DELETE" });
    if (response.ok) { fadeRemove(transactionId); }
    else { alert("Failed to delete transaction. Please try again."); }
}

/**
 * Fades out and removes a transaction row from the DOM.
 * @param {number} transactionId
 */
function fadeRemove(transactionId) {
    const row = document.getElementById(`row-${transactionId}`);
    row.style.transition = "opacity 0.3s";
    row.style.opacity    = "0";
    setTimeout(() => row.remove(), 300);
}

// ── Split transactions ────────────────────────────────────────────────────────

/** @type {number|null} ID of the transaction being split. */
let splitTxnId     = null;
/** @type {number} Absolute amount of the transaction being split. */
let splitTxnAmount = 0;
/** @type {1|-1} Sign of the original transaction, applied to split amounts on save. */
let splitTxnSign   = 1;
/** @type {number} Counter for generating unique split row IDs. */
let splitRowCount  = 0;

/**
 * Opens the Split Transaction modal, pre-populating two empty rows.
 * @param {number} txnId
 * @param {number} amount - Signed transaction amount.
 * @param {string} description
 */
function openSplitModal(txnId, amount, description) {
    splitTxnId     = txnId;
    splitTxnAmount = Math.abs(amount);
    splitTxnSign   = amount < 0 ? -1 : 1;
    splitRowCount  = 0;

    document.getElementById("split-modal-desc").textContent    = description;
    document.getElementById("split-total-display").textContent = "$" + splitTxnAmount.toFixed(2);

    const tbody = document.getElementById("split-rows-body");
    tbody.innerHTML = "";
    addSplitRow();
    addSplitRow();
    updateSplitValidation();

    bootstrap.Modal.getOrCreateInstance(document.getElementById("splitModal")).show();
}

/**
 * Builds an HTML option string for the category select in each split row.
 * @param {number|null} selectedId - Pre-selected category ID.
 * @returns {string} HTML option elements.
 */
function categoryOptions(selectedId) {
    let opts = `<option value="">— Uncategorized —</option>`;
    for (const c of SPLIT_CATEGORIES) {
        const sel = c.id === selectedId ? "selected" : "";
        opts += `<option value="${c.id}" ${sel}>${c.name}</option>`;
    }
    return opts;
}

/**
 * Appends a new split row to the modal table.
 * @param {number|null} [categoryId=null] - Pre-selected category ID.
 * @param {string|number} [amount=""] - Pre-filled amount.
 */
function addSplitRow(categoryId = null, amount = "") {
    const id    = ++splitRowCount;
    const tbody = document.getElementById("split-rows-body");
    const tr    = document.createElement("tr");
    tr.id       = `split-row-${id}`;
    tr.innerHTML = `
        <td>
            <select class="form-select form-select-sm split-cat" data-row="${id}">
                ${categoryOptions(categoryId)}
            </select>
        </td>
        <td>
            <input type="number" step="0.01" min="0.01"
                   class="form-control form-control-sm text-end split-amt"
                   data-row="${id}" value="${amount}"
                   oninput="if(this.value.startsWith('-')) this.value = this.value.slice(1); updateSplitValidation()"
                   placeholder="0.00">
        </td>
        <td class="text-center">
            <button class="btn btn-sm btn-link text-danger p-0"
                    onclick="removeSplitRow(${id})" title="Remove">
                <i class="bi bi-x-lg"></i>
            </button>
        </td>`;
    tbody.appendChild(tr);
    updateSplitValidation();
}

/**
 * Removes a split row. A minimum of two rows is enforced.
 * @param {number} id - The split row's local ID.
 */
function removeSplitRow(id) {
    const rows = document.querySelectorAll("#split-rows-body tr");
    if (rows.length <= 2) return;
    document.getElementById(`split-row-${id}`)?.remove();
    updateSplitValidation();
}

/**
 * Validates that split amounts sum to the transaction total and updates the
 * remainder bar and save button state.
 */
function updateSplitValidation() {
    const amts     = [...document.querySelectorAll(".split-amt")].map(i => parseFloat(i.value) || 0);
    const total    = amts.reduce((s, v) => s + v, 0);
    const remain   = splitTxnAmount - total;
    const balanced = Math.abs(remain) < 0.01;
    const rowCount = document.querySelectorAll("#split-rows-body tr").length;

    const remEl  = document.getElementById("split-remainder");
    const barEl  = document.getElementById("split-remainder-bar");
    remEl.textContent = (remain >= 0 ? "$" : "-$") + Math.abs(remain).toFixed(2);
    remEl.className   = balanced ? "fw-bold text-success" : (remain < 0 ? "fw-bold text-danger" : "fw-bold text-warning");
    barEl.style.background = balanced ? "#d1fae5" : (remain < 0 ? "#fde8e8" : "#f8f9fa");

    document.getElementById("split-save-btn").disabled = !(balanced && rowCount >= 2);
}

/**
 * Submits the split to the API, applying the original transaction's sign to
 * each split amount, then reloads to show the updated split rows.
 */
async function submitSplit() {
    const rows   = [...document.querySelectorAll("#split-rows-body tr")];
    const splits = rows.map(row => ({
        amount:      splitTxnSign * (parseFloat(row.querySelector(".split-amt").value) || 0),
        category_id: parseInt(row.querySelector(".split-cat").value) || null,
    }));

    const resp = await fetch(`/api/transactions/${splitTxnId}/split`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ splits }),
    });

    if (!resp.ok) {
        const err = await resp.json();
        alert(err.detail || "Failed to save split.");
        return;
    }

    bootstrap.Modal.getInstance(document.getElementById("splitModal")).hide();
    location.reload();
}

/**
 * Toggles visibility of child rows for a split transaction.
 * @param {number} parentId - The parent transaction's ID.
 */
function toggleSplitRows(parentId) {
    const children = document.querySelectorAll(`.split-child-row[data-parent="${parentId}"]`);
    const chevron  = document.getElementById(`split-chevron-${parentId}`);
    const hidden   = children[0]?.classList.contains("d-none");
    children.forEach(r => r.classList.toggle("d-none", !hidden));
    if (chevron) chevron.style.transform = hidden ? "rotate(180deg)" : "";
}

/**
 * Removes a split from a transaction, reverting it to a single entry.
 * @param {number} parentId - The parent transaction's ID.
 * @param {string} description - Used in the confirmation prompt.
 */
async function removeSplit(parentId, description) {
    if (!confirm(`Remove split from "${description}"?\n\nThe transaction will revert to a single entry. This cannot be undone.`)) return;
    const resp = await fetch(`/api/transactions/${parentId}/split`, { method: "DELETE" });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert(err.detail || "Failed to remove split.");
        return;
    }
    location.reload();
}

// ── CSV import ────────────────────────────────────────────────────────────────

/** @type {File|null} The currently selected CSV file for import. */
let selectedFile = null;

/**
 * Handles file selection from the file input, updating the drop zone label.
 * @param {File} file
 */
function handleFileSelect(file) {
    if (!file) return;
    selectedFile = file;
    document.getElementById('drop-label').innerHTML =
        `<i class="bi bi-file-earmark-check text-success me-1"></i><strong>${file.name}</strong>`;
    document.getElementById('drop-zone').style.borderColor = '#198754';
    updateImportBtn();
}

/**
 * Handles drag-and-drop onto the import drop zone.
 * @param {DragEvent} e
 */
function handleDrop(e) {
    e.preventDefault();
    document.getElementById('drop-zone').style.borderColor = '#dee2e6';
    const file = e.dataTransfer.files[0];
    if (file) {
        document.getElementById('import-file').files = e.dataTransfer.files;
        handleFileSelect(file);
    }
}

/**
 * Enables the import button only when both a bank and a file are selected.
 */
function updateImportBtn() {
    const bank = document.getElementById('import-bank').value;
    document.getElementById('import-btn').disabled = !(bank && selectedFile);
}

document.getElementById('import-bank').addEventListener('change', updateImportBtn);

/**
 * Uploads the selected CSV to the import API, shows a spinner during the request,
 * then displays the result summary (imported, excluded, duplicates, skipped) or
 * an error message.
 */
async function runImport() {
    const bank = document.getElementById('import-bank').value;
    if (!bank || !selectedFile) return;

    document.getElementById('import-form-section').classList.add('d-none');
    document.getElementById('import-loading').classList.remove('d-none');
    document.getElementById('import-loading').classList.add('d-flex');
    document.getElementById('import-error').classList.add('d-none');

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('bank', bank);

    try {
        const resp = await fetch('/api/import', { method: 'POST', body: formData });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Import failed');

        document.getElementById('res-imported').textContent = data.imported;
        document.getElementById('res-excluded').textContent = data.auto_excluded;
        document.getElementById('res-dupes').textContent    = data.duplicates_skipped;
        document.getElementById('res-skipped').textContent  = data.skipped;

        const count = data.uncategorized_count;
        document.getElementById('res-review-count').textContent = count > 0 ? count + ' to review' : '';

        document.getElementById('import-loading').classList.add('d-none');
        document.getElementById('import-loading').classList.remove('d-flex');
        document.getElementById('import-result').classList.remove('d-none');
        document.getElementById('import-result').classList.add('d-flex');

    } catch (err) {
        document.getElementById('import-loading').classList.add('d-none');
        document.getElementById('import-loading').classList.remove('d-flex');
        document.getElementById('import-form-section').classList.remove('d-none');
        document.getElementById('import-error').classList.remove('d-none');
        document.getElementById('import-error-msg').textContent = err.message;
    }
}

/**
 * Resets the import offcanvas to its initial state for another import.
 */
function resetImport() {
    selectedFile = null;
    document.getElementById('import-file').value = '';
    document.getElementById('import-bank').value = '';
    document.getElementById('drop-label').innerHTML = 'Drag &amp; drop or <span class="text-primary">browse</span>';
    document.getElementById('drop-zone').style.borderColor = '#dee2e6';
    document.getElementById('import-btn').disabled = true;
    document.getElementById('import-form-section').classList.remove('d-none');
    document.getElementById('import-result').classList.add('d-none');
    document.getElementById('import-result').classList.remove('d-flex');
    document.getElementById('import-error').classList.add('d-none');
}
