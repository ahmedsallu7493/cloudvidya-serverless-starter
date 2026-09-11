const API_BASE = window.API_BASE;

const studentView = document.getElementById("studentView");
const adminView = document.getElementById("adminView");

const studentModeBtn = document.getElementById("studentModeBtn");
const adminModeBtn = document.getElementById("adminModeBtn");

const statusEl = document.getElementById("status");
const listEl = document.getElementById("list");
const adminListEl = document.getElementById("adminList");

const submitBtn = document.getElementById("submitBtn");
const refreshBtn = document.getElementById("refreshBtn");

const statusFilter = document.getElementById("statusFilter");
const priorityFilter = document.getElementById("priorityFilter");
const searchInput = document.getElementById("searchInput");

document.getElementById("appTitle").textContent =
  window.APP_NAME || "CampusFix";

document.documentElement.style.setProperty(
  "--accent",
  window.APP_THEME_COLOR || "#38bdf8"
);


/* =========================
   BASIC HELPERS
========================= */

function setStatus(text, kind = "") {
  statusEl.textContent = text;
  statusEl.className = kind;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function formatDate(value) {
  if (!value) return "Unknown date";

  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function priorityClass(priority) {
  return `priority-${String(priority || "medium").toLowerCase()}`;
}


/* =========================
   ROLE SWITCHING
========================= */

studentModeBtn.addEventListener("click", () => {
  studentView.classList.remove("hidden");
  adminView.classList.add("hidden");

  studentModeBtn.classList.add("active");
  adminModeBtn.classList.remove("active");

  loadItems();
});

adminModeBtn.addEventListener("click", () => {
  studentView.classList.add("hidden");
  adminView.classList.remove("hidden");

  adminModeBtn.classList.add("active");
  studentModeBtn.classList.remove("active");

  loadAdminDashboard();
});


/* =========================
   STUDENT: LOAD ISSUES
========================= */

async function loadItems() {
  listEl.innerHTML = "<p>Loading campus issues...</p>";

  try {
    const response = await fetch(`${API_BASE}/items`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not load issues.");
    }

    const items = data.items || [];

    if (items.length === 0) {
      listEl.innerHTML = `
        <p style="color: var(--muted);">
          No issues reported yet.
        </p>
      `;
      return;
    }

    listEl.innerHTML = items
      .map((item) => {
        const priority = String(item.priority || "MEDIUM").toUpperCase();

        return `
          <div class="item">

            <div class="title">
              ${escapeHtml(item.title)}
            </div>

            <div class="desc">
              ${escapeHtml(item.description)}
            </div>

            <div class="meta">

              <span class="badge">
                ${escapeHtml(item.category || "General")}
              </span>

              ${
                item.subcategory
                  ? `<span class="badge">${escapeHtml(item.subcategory)}</span>`
                  : ""
              }

              <span class="badge ${priorityClass(priority)}">
                ${escapeHtml(priority)}
              </span>

              <span class="badge">
                ${escapeHtml(item.status || "OPEN")}
              </span>

              ${
                item.location
                  ? `<span class="badge">📍 ${escapeHtml(item.location)}</span>`
                  : ""
              }

              ${
                item.severity
                  ? `<span class="badge">Severity ${escapeHtml(item.severity)}/5</span>`
                  : ""
              }

              <span>
                ${formatDate(item.createdAt)}
              </span>

            </div>

            ${
              item.aiSummary
                ? `
                  <div style="
                    margin-top: 10px;
                    color: var(--muted);
                    font-size: 12px;
                  ">
                    <strong style="color: var(--accent);">
                      AI Summary:
                    </strong>
                    ${escapeHtml(item.aiSummary)}
                  </div>
                `
                : ""
            }

          </div>
        `;
      })
      .join("");

  } catch (error) {
    console.error(error);

    listEl.innerHTML = `
      <p style="color: var(--danger);">
        Couldn't load issues. Check the API connection.
      </p>
    `;
  }
}


/* =========================
   STUDENT: SUBMIT ISSUE
========================= */

submitBtn.addEventListener("click", async () => {

  const title = document.getElementById("title").value.trim();
  const description = document.getElementById("description").value.trim();
  const category = document.getElementById("category").value;
  const location = document.getElementById("location").value.trim();
  const participantName =
    document.getElementById("participantName").value.trim();

  if (!title || !description || !location) {
    setStatus(
      "Please fill in the title, location and description.",
      "err"
    );
    return;
  }

  submitBtn.disabled = true;
  setStatus("Analyzing and submitting your issue...");

  try {

    const response = await fetch(`${API_BASE}/items`, {
      method: "POST",

      headers: {
        "Content-Type": "application/json"
      },

      body: JSON.stringify({
        title,
        description,
        category,
        location,
        participantName
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error || "Issue submission failed."
      );
    }

    const item = data.item;

    setStatus(
      `Issue submitted successfully. Priority: ${
        item.priority || "MEDIUM"
      }`,
      "ok"
    );

    document.getElementById("title").value = "";
    document.getElementById("description").value = "";
    document.getElementById("location").value = "";
    document.getElementById("participantName").value = "";

    await loadItems();

  } catch (error) {

    console.error(error);

    setStatus(
      error.message || "Something went wrong.",
      "err"
    );

  } finally {

    submitBtn.disabled = false;

  }
});


/* =========================
   REFRESH
========================= */

refreshBtn.addEventListener("click", loadItems);


/* =========================
   ADMIN DASHBOARD
========================= */

async function loadAdminDashboard() {

  adminListEl.innerHTML = "<p>Loading dashboard...</p>";

  try {

    const response = await fetch(`${API_BASE}/items`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not load dashboard.");
    }

    const items = data.items || [];

    updateStats(items);

    renderAdminItems(items);

  } catch (error) {

    console.error(error);

    adminListEl.innerHTML = `
      <p style="color: var(--danger);">
        Couldn't load admin dashboard.
      </p>
    `;
  }
}


/* =========================
   ADMIN: STATISTICS
========================= */

function updateStats(items) {

  const total = items.length;

  const open = items.filter(
    item =>
      String(item.status || "").toUpperCase() === "OPEN"
  ).length;

  const critical = items.filter(
    item =>
      String(item.priority || "").toUpperCase() === "CRITICAL"
  ).length;

  const resolved = items.filter(
    item =>
      ["RESOLVED", "CLOSED"].includes(
        String(item.status || "").toUpperCase()
      )
  ).length;

  document.getElementById("totalCount").textContent = total;
  document.getElementById("openCount").textContent = open;
  document.getElementById("criticalCount").textContent = critical;
  document.getElementById("resolvedCount").textContent = resolved;
}


/* =========================
   ADMIN: FILTERING
========================= */

statusFilter.addEventListener(
  "change",
  loadAdminDashboard
);

priorityFilter.addEventListener(
  "change",
  loadAdminDashboard
);

searchInput.addEventListener(
  "input",
  loadAdminDashboard
);


/* =========================
   ADMIN: RENDER ISSUES
========================= */

function renderAdminItems(items) {

  const selectedStatus =
    statusFilter.value.toUpperCase();

  const selectedPriority =
    priorityFilter.value.toUpperCase();

  const search =
    searchInput.value.trim().toLowerCase();

  let filteredItems = items.filter((item) => {

    const status =
      String(item.status || "").toUpperCase();

    const priority =
      String(item.priority || "").toUpperCase();

    const searchableText = [
      item.title,
      item.description,
      item.category,
      item.location,
      item.department,
      item.subcategory
    ]
      .join(" ")
      .toLowerCase();

    if (selectedStatus && status !== selectedStatus) {
      return false;
    }

    if (
      selectedPriority &&
      priority !== selectedPriority
    ) {
      return false;
    }

    if (
      search &&
      !searchableText.includes(search)
    ) {
      return false;
    }

    return true;
  });

  if (filteredItems.length === 0) {

    adminListEl.innerHTML = `
      <p style="color: var(--muted);">
        No issues match the selected filters.
      </p>
    `;

    return;
  }

  adminListEl.innerHTML = filteredItems
    .map((item) => {

      const priority =
        String(item.priority || "MEDIUM").toUpperCase();

      const currentStatus =
        String(item.status || "OPEN").toUpperCase();

      return `
        <div class="admin-item">

          <div class="admin-item-top">

            <div>

              <div class="admin-item-title">
                ${escapeHtml(item.title)}
              </div>

              <div class="admin-item-description">
                ${escapeHtml(item.description)}
              </div>

            </div>

            <span class="badge ${priorityClass(priority)}">
              ${escapeHtml(priority)}
            </span>

          </div>

          <div class="issue-details">

            <span class="badge">
              ${escapeHtml(item.category || "General")}
            </span>

            ${
              item.subcategory
                ? `<span class="badge">${escapeHtml(item.subcategory)}</span>`
                : ""
            }

            ${
              item.department
                ? `<span class="badge">Dept: ${escapeHtml(item.department)}</span>`
                : ""
            }

            ${
              item.location
                ? `<span class="badge">📍 ${escapeHtml(item.location)}</span>`
                : ""
            }

            ${
              item.severity
                ? `<span class="badge">Severity ${escapeHtml(item.severity)}/5</span>`
                : ""
            }

            <span class="badge">
              ${escapeHtml(currentStatus)}
            </span>

            ${
              item.aiProcessed
                ? `<span class="badge">🤖 AI analyzed</span>`
                : `<span class="badge">Manual classification</span>`
            }

          </div>

          ${
            item.aiSummary
              ? `
                <div style="
                  margin-top: 10px;
                  color: var(--muted);
                  font-size: 12px;
                ">
                  <strong style="color: var(--accent);">
                    Intelligence:
                  </strong>
                  ${escapeHtml(item.aiSummary)}
                </div>
              `
              : ""
          }

          <div class="status-control">

            <select id="status-${escapeHtml(item.id)}">

              ${statusOption("OPEN", currentStatus)}
              ${statusOption("ACKNOWLEDGED", currentStatus)}
              ${statusOption("IN_PROGRESS", currentStatus)}
              ${statusOption("RESOLVED", currentStatus)}
              ${statusOption("CLOSED", currentStatus)}

            </select>

            <button
              class="update-btn"
              onclick="updateIssueStatus('${escapeHtml(item.id)}')"
            >
              Update Status
            </button>

          </div>

          <div style="
            margin-top: 8px;
            color: var(--muted);
            font-size: 11px;
          ">
            Reported ${formatDate(item.createdAt)}
          </div>

        </div>
      `;
    })
    .join("");
}


function statusOption(value, current) {

  return `
    <option
      value="${value}"
      ${value === current ? "selected" : ""}
    >
      ${value.replace("_", " ")}
    </option>
  `;
}


/* =========================
   ADMIN: UPDATE STATUS
========================= */

async function updateIssueStatus(itemId) {

  const select =
    document.getElementById(`status-${itemId}`);

  const newStatus =
    select.value;

  try {

    const response = await fetch(
      `${API_BASE}/items/${itemId}`,
      {
        method: "PATCH",

        headers: {
          "Content-Type": "application/json"
        },

        body: JSON.stringify({
          status: newStatus,
          adminNote: `Status updated to ${newStatus}`
        })
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error || "Status update failed."
      );
    }

    await loadAdminDashboard();

  } catch (error) {

    console.error(error);

    alert(
      error.message ||
      "Could not update issue status."
    );
  }
}


/* =========================
   START APPLICATION
========================= */

loadItems();