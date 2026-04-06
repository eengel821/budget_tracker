/**
 * @file budget_manage.js
 * @description Client-side logic for the Manage Budgets page.
 *
 * Provides inline budget amount editing, category name editing, income/savings
 * toggle switches, and a new category form — all saving immediately via the API
 * without a full page reload. A toast notification confirms each save.
 *
 * Features:
 *   - Per-row Save button that activates when the budget input changes
 *   - Save All button that iterates all rows and saves in sequence
 *   - Inline category rename with click-to-edit (Enter to save, Escape to cancel)
 *   - Income and savings toggle switches with immediate API calls and revert on failure
 *   - Add category form with inline row injection on success
 *   - Footer totals that update live as budgets are saved
 */

/**
 * Saves the budget amount for a single category and flashes the row green on success.
 * @param {number} categoryId
 * @param {string} categoryName - Used in the toast confirmation message.
 */
async function saveBudget(categoryId, categoryName) {
    const input  = document.getElementById("budget-" + categoryId);
    const amount = parseFloat(input.value) || 0;

    const response = await fetch(`/api/categories/${categoryId}/budget`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monthly_budget: amount })
    });

    if (response.ok) {
        const row = document.getElementById("row-" + categoryId);
        row.style.transition = "background-color 0.3s";
        row.style.backgroundColor = "#d1fae5";
        setTimeout(() => { row.style.backgroundColor = ""; }, 1500);
        const btn = document.getElementById("save-btn-" + categoryId);
        if (btn) { btn.disabled = true; btn.className = "btn btn-sm btn-outline-secondary w-100"; }
        showToast(`Saved budget for <strong>${categoryName}</strong>`);
        updateTotal();
    } else {
        alert(`Failed to save budget for '${categoryName}'. Please try again.`);
    }
}

/**
 * Saves budget amounts for all categories in sequence. Flashes all rows and
 * resets save buttons on full success, or shows an error summary on partial failure.
 */
async function saveAll() {
    const inputs = document.querySelectorAll("input[id^='budget-']");
    let success = 0, failed = 0;

    for (const input of inputs) {
        const categoryId = input.id.replace("budget-", "");
        const amount     = parseFloat(input.value) || 0;
        const response   = await fetch(`/api/categories/${categoryId}/budget`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ monthly_budget: amount })
        });
        if (response.ok) { success++; } else { failed++; }
    }

    if (failed === 0) {
        document.querySelectorAll("tbody tr").forEach(row => {
            row.style.transition = "background-color 0.3s";
            row.style.backgroundColor = "#d1fae5";
            setTimeout(() => { row.style.backgroundColor = ""; }, 1200);
        });
        document.querySelectorAll("button[id^='save-btn-']").forEach(btn => {
            btn.disabled = true;
            btn.className = "btn btn-sm btn-outline-secondary w-100";
        });
        showToast(`<strong>${success} budgets saved</strong> successfully`);
        updateTotal();
    } else {
        alert(`${success} budgets saved, ${failed} failed. Please try again.`);
    }
}

/**
 * Activates a row's Save button (turns it green) when its budget input changes.
 * @param {number} categoryId
 */
function enableSaveBtn(categoryId) {
    const btn = document.getElementById("save-btn-" + categoryId);
    if (btn) { btn.disabled = false; btn.className = "btn btn-sm btn-success w-100"; }
}

/**
 * Shows a Bootstrap toast with the given HTML message.
 * @param {string} msg - HTML string for the toast body.
 */
function showToast(msg) {
    document.getElementById("save-toast-msg").innerHTML = msg;
    const toastEl = document.getElementById("save-toast");
    bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 4000 }).show();
}

/**
 * Submits the Add Category form, then injects the new row into the table
 * on success without a page reload.
 */
async function addCategory() {
    const nameInput   = document.getElementById('new-category-name');
    const budgetInput = document.getElementById('new-category-budget');
    const messageDiv  = document.getElementById('add-category-message');
    const name        = nameInput.value.trim();
    const budget      = parseFloat(budgetInput.value) || 0;

    if (!name) {
        messageDiv.style.display = 'block';
        messageDiv.className     = 'mt-2 alert alert-warning py-2';
        messageDiv.textContent   = 'Please enter a category name.';
        return;
    }

    const response = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, monthly_budget: budget })
    });

    const data = await response.json();
    messageDiv.style.display = 'block';

    if (response.ok) {
        messageDiv.className   = 'mt-2 alert alert-success py-2';
        messageDiv.textContent = `Category '${name}' added successfully!`;
        nameInput.value        = '';
        budgetInput.value      = '';

        const tbody  = document.querySelector('tbody');
        const newRow = document.createElement('tr');
        newRow.id    = 'row-' + data.id;
        newRow.innerHTML = `
            <td class="align-middle">
                <span id="name-text-${data.id}" class="editable-field fw-semibold"
                      title="Click to rename category" onclick="editName(${data.id}, this)">
                    ${data.name}
                </span>
                <input id="name-input-${data.id}" type="text" class="form-control form-control-sm d-none"
                       value="${data.name}" maxlength="100"
                       onblur="saveName(${data.id})" onkeydown="handleNameKey(event, ${data.id})">
            </td>
            <td>
                <div class="input-group input-group-sm">
                    <span class="input-group-text">$</span>
                    <input type="number" class="form-control" id="budget-${data.id}"
                           value="${data.monthly_budget.toFixed(2)}" min="0" step="0.01" placeholder="0.00"
                           oninput="enableSaveBtn(${data.id})">
                </div>
            </td>
            <td class="text-center align-middle">
                <div class="form-check form-switch d-flex justify-content-center">
                    <input class="form-check-input" type="checkbox" id="income-${data.id}"
                           onchange="toggleIncome(${data.id}, this)">
                </div>
            </td>
            <td class="text-center align-middle">
                <div class="form-check form-switch d-flex justify-content-center">
                    <input class="form-check-input" type="checkbox" id="savings-${data.id}"
                           onchange="toggleSavings(${data.id}, this)">
                </div>
            </td>
            <td>
                <button id="save-btn-${data.id}" class="btn btn-sm btn-outline-secondary w-100"
                        onclick="saveBudget(${data.id}, '${data.name}')" disabled>
                    <i class="bi bi-check-lg me-1"></i>Save
                </button>
            </td>`;
        tbody.appendChild(newRow);
        updateTotal();
    } else if (response.status === 409) {
        messageDiv.className   = 'mt-2 alert alert-warning py-2';
        messageDiv.textContent = `Category '${name}' already exists.`;
    } else {
        messageDiv.className   = 'mt-2 alert alert-danger py-2';
        messageDiv.textContent = 'Failed to add category. Please try again.';
    }
}

// ── Category name editing ─────────────────────────────────────────────────────

/**
 * Switches a category name cell from display to edit mode.
 * @param {number} categoryId
 * @param {HTMLElement} spanEl - The name span that was clicked.
 */
function editName(categoryId, spanEl) {
    const input = document.getElementById("name-input-" + categoryId);
    spanEl.classList.add("d-none");
    input.classList.remove("d-none");
    input.focus();
    input.select();
}

/**
 * Keyboard handler for the name input — saves on Enter, cancels on Escape.
 * @param {KeyboardEvent} event
 * @param {number} categoryId
 */
function handleNameKey(event, categoryId) {
    if (event.key === "Enter")  saveName(categoryId);
    if (event.key === "Escape") cancelName(categoryId);
}

/**
 * Cancels a name edit, restoring the input to the current saved value.
 * @param {number} categoryId
 */
function cancelName(categoryId) {
    const input = document.getElementById("name-input-" + categoryId);
    const span  = document.getElementById("name-text-" + categoryId);
    input.value = span.textContent.trim();
    input.classList.add("d-none");
    span.classList.remove("d-none");
}

/**
 * Saves a renamed category via the API and flashes the row green on success.
 * Reverts on 409 conflict (duplicate name) or other errors.
 * @param {number} categoryId
 */
async function saveName(categoryId) {
    const input   = document.getElementById("name-input-" + categoryId);
    const span    = document.getElementById("name-text-" + categoryId);
    const newName = input.value.trim();

    if (!newName) { cancelName(categoryId); return; }
    if (newName === span.textContent.trim()) {
        // No change — just close
        input.classList.add("d-none");
        span.classList.remove("d-none");
        return;
    }

    const response = await fetch(`/api/categories/${categoryId}/name`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName })
    });

    if (response.ok) {
        span.textContent = newName;
        const row = document.getElementById("row-" + categoryId);
        row.style.transition = "background-color 0.2s";
        row.style.backgroundColor = "#d1fae5";
        setTimeout(() => row.style.backgroundColor = "", 1000);
    } else if (response.status === 409) {
        alert(`A category named "${newName}" already exists.`);
        cancelName(categoryId);
    } else {
        alert("Failed to rename category. Please try again.");
        cancelName(categoryId);
    }

    input.classList.add("d-none");
    span.classList.remove("d-none");
}

/**
 * Toggles the is_income flag for a category. Reverts the checkbox on failure.
 * @param {number} categoryId
 * @param {HTMLInputElement} checkbox
 */
async function toggleIncome(categoryId, checkbox) {
    const response = await fetch(`/api/categories/${categoryId}/is_income`, { method: "PUT" });
    if (!response.ok) {
        alert("Failed to update income flag. Please try again.");
        checkbox.checked = !checkbox.checked;
    }
}

/**
 * Toggles the is_savings flag for a category. Reverts the checkbox on failure,
 * including the 409 case where the jar has a non-zero balance and cannot be removed.
 * @param {number} categoryId
 * @param {HTMLInputElement} checkbox
 */
async function toggleSavings(categoryId, checkbox) {
    const response = await fetch(`/api/categories/${categoryId}/is_savings`, { method: "PUT" });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        alert(data.detail || "Failed to update savings flag. Please try again.");
        checkbox.checked = !checkbox.checked;
    }
}

/**
 * Recalculates and updates the footer expense and income totals based on
 * current input values and income toggle states.
 */
function updateTotal() {
    let expenseTotal = 0, incomeTotal = 0;
    document.querySelectorAll("input[id^='budget-']").forEach(input => {
        const rowId       = input.id.replace("budget-", "");
        const incomeToggle = document.getElementById("income-" + rowId);
        const amount      = parseFloat(input.value) || 0;
        if (incomeToggle && incomeToggle.checked) { incomeTotal  += amount; }
        else                                       { expenseTotal += amount; }
    });
    const fmt     = n => "$" + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    const strongs = document.querySelectorAll(".card-footer strong");
    if (strongs[0]) strongs[0].textContent = fmt(expenseTotal);
    if (strongs[1]) strongs[1].textContent = fmt(incomeTotal);
}
