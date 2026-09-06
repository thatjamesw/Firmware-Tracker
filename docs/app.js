const SEEN_VERSIONS_KEY = "firmware_tracker_seen_versions_v1";
const SEEN_SOURCE_ISSUES_KEY = "firmware_tracker_seen_source_issues_v1";

function loadSeenVersions() {
  try {
    const raw = localStorage.getItem(SEEN_VERSIONS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_err) {
    return {};
  }
}

function saveSeenVersions(versionsByDevice) {
  try {
    localStorage.setItem(SEEN_VERSIONS_KEY, JSON.stringify(versionsByDevice));
  } catch (_err) {
    // Ignore localStorage errors.
  }
}

function loadSeenSourceIssuesSignature() {
  try {
    return localStorage.getItem(SEEN_SOURCE_ISSUES_KEY) || "";
  } catch (_err) {
    return "";
  }
}

function saveSeenSourceIssuesSignature(signature) {
  try {
    localStorage.setItem(SEEN_SOURCE_ISSUES_KEY, signature);
  } catch (_err) {
    // Ignore localStorage errors.
  }
}

function ageInDays(dateText) {
  if (!dateText) return null;
  const parsed = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(dateText) ? dateText + "T00:00:00Z" : dateText);
  if (Number.isNaN(parsed)) return null;
  const ms = Date.now() - parsed;
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

function formatAge(days) {
  if (days === null || Number.isNaN(days)) return "unknown";
  if (days <= 0) return "today";
  if (days === 1) return "1 day";
  if (days < 30) return `${days} days`;
  const months = Math.floor(days / 30);
  if (days < 365) return `${months} month${months === 1 ? "" : "s"}`;
  const years = Math.floor(days / 365);
  return `${years} year${years === 1 ? "" : "s"}`;
}

const UTC_TO_LOCAL_FORMATTER = (() => {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZoneName: "short"
    });
  } catch (_err) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }
})();

function formatUtcAsLocalDateTime(utcIsoText) {
  if (!utcIsoText) return "";
  const parsed = new Date(utcIsoText);
  if (Number.isNaN(parsed.getTime())) return "";
  return UTC_TO_LOCAL_FORMATTER.format(parsed);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function versionSortKey(version) {
  const clean = String(version || "").trim().replace(/^v/i, "");
  const parts = clean.match(/\d+|[A-Za-z]+/g) || [];
  return parts.map((part) => /^\d+$/.test(part) ? [1, Number(part)] : [0, part.toLowerCase()]);
}

function compareVersionKeys(left, right) {
  const length = Math.max(left.length, right.length);
  for (let idx = 0; idx < length; idx += 1) {
    const a = left[idx] || [0, ""];
    const b = right[idx] || [0, ""];
    if (a[0] !== b[0]) return a[0] - b[0];
    if (a[1] < b[1]) return -1;
    if (a[1] > b[1]) return 1;
  }
  return 0;
}

function getLatestActiveRelease(releases) {
  const active = releases.filter((r) => r.active === true);
  if (!active.length) return null;
  return [...active].sort(compareReleasesDesc)[0];
}

function compareReleasesDesc(a, b) {
  const versionCompare = compareVersionKeys(versionSortKey(a.version), versionSortKey(b.version));
  if (versionCompare !== 0) return -versionCompare;
  const at = a.released_time ? new Date(a.released_time).getTime() : -1;
  const bt = b.released_time ? new Date(b.released_time).getTime() : -1;
  return bt - at;
}

function getAllRows() {
  const rows = [];
  for (const [categoryId, category] of Object.entries(CATEGORIES)) {
    for (const [deviceId, deviceName] of Object.entries(category.devices)) {
      const sourceType =
        (TRACKER_CONFIG &&
          TRACKER_CONFIG.device_source_types &&
          TRACKER_CONFIG.device_source_types[deviceId]) ||
        "";
      if (sourceType === "static") continue;
      const data = FIRMWARE_INDEX[deviceId];
      const releases = data && Array.isArray(data.releases) ? data.releases : [];
      const latest = releases.length ? getLatestActiveRelease(releases) : null;
      rows.push({
        categoryId,
        category: category.title,
        deviceId,
        deviceName,
        releases,
        latest,
        age: latest ? ageInDays(latest.released_time) : null
      });
    }
  }
  return rows;
}

function buildVersionSnapshot(rows) {
  const snapshot = {};
  for (const row of rows) {
    if (!row.latest) continue;
    snapshot[row.deviceId] = row.latest.version;
  }
  return snapshot;
}

function detectNewFirmware(rows) {
  const current = buildVersionSnapshot(rows);
  const seen = loadSeenVersions();
  const seenKeys = Object.keys(seen);

  if (!seenKeys.length) {
    saveSeenVersions(current);
    return { newDeviceIds: new Set(), current, hasBaseline: false };
  }

  const newDeviceIds = new Set();
  for (const row of rows) {
    if (!row.latest) continue;
    if (seen[row.deviceId] !== row.latest.version) {
      newDeviceIds.add(row.deviceId);
    }
  }

  return { newDeviceIds, current, hasBaseline: true };
}

function getDeviceNameById(deviceId) {
  for (const category of Object.values(CATEGORIES || {})) {
    if (category && category.devices && category.devices[deviceId]) {
      return category.devices[deviceId];
    }
  }
  return deviceId;
}

function getSourceIssueSignature(issues) {
  if (!Array.isArray(issues) || !issues.length) return "";
  const normalized = issues
    .map((item) => ({
      vendor: String(item.vendor || "").toLowerCase(),
      device_id: String(item.device_id || "").toLowerCase(),
      status: String(item.status || "").toLowerCase(),
      reason: String(item.reason || "").toLowerCase()
    }))
    .sort((a, b) => {
      const ak = `${a.vendor}|${a.device_id}|${a.status}|${a.reason}`;
      const bk = `${b.vendor}|${b.device_id}|${b.status}|${b.reason}`;
      return ak < bk ? -1 : ak > bk ? 1 : 0;
    });
  return JSON.stringify(normalized);
}

function initSourceBanner() {
  const banner = document.getElementById("source-banner");
  const text = document.getElementById("source-banner-text");
  const hideBtn = document.getElementById("hide-source-banner");
  const status = (TRACKER_CONFIG && TRACKER_CONFIG.source_sync_status) || {};
  const issues = Array.isArray(status.issues) ? status.issues : [];

  if (!issues.length) {
    banner.classList.remove("active");
    return;
  }
  const issueSignature = getSourceIssueSignature(issues);
  const seenSignature = loadSeenSourceIssuesSignature();
  if (issueSignature && seenSignature === issueSignature) {
    banner.classList.remove("active");
    return;
  }

  const previewItems = issues.slice(0, 3).map((item) => {
    const vendor = (item.vendor || "source").toUpperCase();
    const deviceName = getDeviceNameById(item.device_id || "");
    const reason = item.reason || item.status || "issue detected";
    const streak = Number(item.streak_days || 0);
    const streakText = streak > 1 ? ` (${streak} runs)` : "";
    return `${vendor} / ${deviceName}: ${reason}${streakText}`;
  });
  const previewText = previewItems.join(" | ");
  const moreCount = issues.length - previewItems.length;
  const runText = status.last_run_utc ? ` Last check: ${status.last_run_utc}.` : "";
  const moreText = moreCount > 0 ? ` +${moreCount} more.` : "";
  const maxStreak = Number(status.max_issue_streak_days || 0);
  const prefix = maxStreak >= 3
    ? "Persistent source issues detected (3+ runs)"
    : "Source issues detected";
  text.textContent = `${prefix}: ${previewText}.${moreText}${runText} Existing data is still shown.`;
  banner.classList.add("active");

  hideBtn.addEventListener("click", () => {
    if (issueSignature) saveSeenSourceIssuesSignature(issueSignature);
    banner.classList.remove("active");
  });
}


const uiState = {rows: [], unseen: new Set(), query: "", category: "", unseenOnly: false, sortKey: "category", sortDir: "asc"};
let returnFocusId = "";
const STALE_AFTER_MS = 3 * 24 * 60 * 60 * 1000;

function sourceFreshness(deviceId, now = Date.now()) {
  const health = TRACKER_CONFIG.source_sync_status?.device_health?.[deviceId];
  const lastSuccess = health?.last_success_utc || "";
  const timestamp = Date.parse(lastSuccess);
  const stale = !Number.isFinite(timestamp) || now - timestamp > STALE_AFTER_MS;
  const issue = health && !["ok", "ok_empty", "transient_error"].includes(health.status);
  const checked = formatUtcAsLocalDateTime(lastSuccess);
  return {
    warning: stale || Boolean(issue),
    label: !Number.isFinite(timestamp) ? "Not checked yet" : stale ? "Check overdue" : issue ? "Source issue" : "",
    detail: checked ? `Last successful check: ${checked}${issue ? ". Latest check failed; stored data is shown." : ""}` : "No successful source check has been recorded."
  };
}

function filteredRows(rows, state) {
  const query = state.query.trim().toLowerCase();
  return rows.filter(row =>
    (!query || `${row.deviceName} ${row.category}`.toLowerCase().includes(query)) &&
    (!state.category || row.categoryId === state.category) &&
    (!state.unseenOnly || state.unseen.has(row.deviceId))
  );
}

function compareRows(a, b, key, direction) {
  let av, bv;
  if (key === "version") {
    av = a.latest?.version || null;
    bv = b.latest?.version || null;
  } else if (key === "date") {
    av = Date.parse(a.latest?.released_time);
    bv = Date.parse(b.latest?.released_time);
    av = Number.isFinite(av) ? av : null;
    bv = Number.isFinite(bv) ? bv : null;
  } else if (key === "age") {
    av = a.age;
    bv = b.age;
  } else {
    av = key === "category" ? a.category : a.deviceName;
    bv = key === "category" ? b.category : b.deviceName;
  }
  // Unknown dates and versions always stay last, in either direction.
  if (av == null && bv != null) return 1;
  if (bv == null && av != null) return -1;
  let result = 0;
  if (av != null && bv != null) {
    if (key === "version") result = compareVersionKeys(versionSortKey(av), versionSortKey(bv));
    else if (typeof av === "string") result = av.localeCompare(bv, undefined, {sensitivity: "base"});
    else result = av - bv;
  }
  return result ? (direction === "asc" ? result : -result) : a.deviceName.localeCompare(b.deviceName);
}

function updateFirmwareStatus() {
  const count = uiState.unseen.size;
  document.getElementById("firmware-status").classList.toggle("has-updates", count > 0);
  document.getElementById("firmware-status-title").textContent = count ? `${count} unseen release${count === 1 ? "" : "s"}` : "No unseen releases";
  document.getElementById("firmware-status-actions").hidden = !count;
}

function markDeviceSeen(deviceId) {
  const row = uiState.rows.find(row => row.deviceId === deviceId);
  if (!row?.latest) return;
  const seen = loadSeenVersions();
  seen[deviceId] = row.latest.version;
  saveSeenVersions(seen);
  uiState.unseen.delete(deviceId);
  updateFirmwareStatus();
  renderTable();
}

function getDeviceDownloadPage(deviceId) {
  const url = TRACKER_CONFIG.device_download_pages?.[deviceId] || "";
  return /^https?:\/\//i.test(url) ? url : "";
}

function releaseMarkup(rel, latest = false) {
  const lines = String(rel.release_note?.en || "").split("\n").map(line => line.trim()).filter(Boolean);
  const note = lines.length && lines.every(line => /^[•-]\s/.test(line))
    ? `<ul class="release-notes">${lines.map(line => `<li>${escapeHtml(line.replace(/^[•-]\s*/, ""))}</li>`).join("")}</ul>`
    : `<p class="release-notes">${escapeHtml(lines.join("\n") || "No release notes available.")}</p>`;
  return `<section class="release-item${latest ? " latest-release" : ""}" aria-label="${latest ? "Latest release" : "Release"} ${escapeHtml(rel.version)}">
    ${latest ? '<span class="section-label">Latest release</span>' : ""}
    <h3 class="release-title">${escapeHtml(rel.version)}${!rel.active ? ' <span class="badge old">Inactive</span>' : ""}</h3>
    <p class="release-date">${rel.released_time ? `Released ${escapeHtml(rel.released_time)}` : "Release date unknown"}</p>
    ${rel.arb != null && rel.arb !== "" ? `<p>Anti-rollback: ${escapeHtml(rel.arb)}</p>` : ""}
    ${note}
  </section>`;
}

function renderModal(deviceId, deviceName, releases) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");
  const pageUrl = getDeviceDownloadPage(deviceId);
  const latest = getLatestActiveRelease(releases);
  const older = [...releases].filter(rel => rel !== latest).sort(compareReleasesDesc);
  const freshness = sourceFreshness(deviceId);
  document.getElementById("modal-title").textContent = deviceName;
  content.innerHTML = `<div class="device-actions">
      ${pageUrl ? `<a class="release-link" href="${escapeHtml(pageUrl)}" target="_blank" rel="noopener noreferrer">Open official download page <span aria-hidden="true">↗</span></a>` : ""}
      ${uiState.unseen.has(deviceId) ? '<button class="primary" id="mark-device-seen">Mark as seen</button>' : ""}
    </div>
    <p class="source-detail${freshness.warning ? " source-warning" : ""}">${escapeHtml(freshness.detail)}</p>
    ${latest ? releaseMarkup(latest, true) : '<p>No published firmware yet. This device is being tracked.</p>'}
    ${older.length ? `<details class="older-releases"><summary>Older releases (${older.length})</summary>${older.map(rel => releaseMarkup(rel)).join("")}</details>` : ""}
    <p class="device-id">Device ID: <code>${escapeHtml(deviceId)}</code></p>`;
  document.getElementById("mark-device-seen")?.addEventListener("click", event => {
    markDeviceSeen(deviceId);
    event.currentTarget.textContent = "Marked as seen";
    event.currentTarget.disabled = true;
    document.getElementById("close-modal").focus();
  });
  returnFocusId = `history-${deviceId}`;
  modal.showModal();
  document.body.classList.add("dialog-open");
}

function renderTable() {
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.className = "sr-only";
  caption.textContent = "Tracked firmware. Use the column buttons or Sort by to change the order.";
  table.appendChild(caption);
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  const headers = [["Category", "category"], ["Device", "name"], ["Latest", "version"], ["Released", "date"], ["Age", "age"], ["History", null]];
  for (const [title, key] of headers) {
    const th = document.createElement("th");
    th.scope = "col";
    if (key) {
      const active = uiState.sortKey === key;
      if (active) th.setAttribute("aria-sort", uiState.sortDir === "asc" ? "ascending" : "descending");
      const button = document.createElement("button");
      button.className = "sort-button";
      button.id = `sort-${key}`;
      button.innerHTML = `${title} <span aria-hidden="true">${active ? (uiState.sortDir === "asc" ? "↑" : "↓") : "↕"}</span>`;
      button.setAttribute("aria-label", `Sort by ${title.toLowerCase()}`);
      button.addEventListener("click", () => {
        uiState.sortDir = uiState.sortKey === key && uiState.sortDir === "asc" ? "desc" : "asc";
        uiState.sortKey = key;
        renderTable();
        document.getElementById(`sort-${key}`).focus();
      });
      th.appendChild(button);
    } else th.textContent = title;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  const rows = filteredRows(uiState.rows, uiState).sort((a,b) => compareRows(a,b,uiState.sortKey,uiState.sortDir));
  for (const row of rows) {
    const tr = document.createElement("tr");
    const unseen = uiState.unseen.has(row.deviceId);
    const freshness = sourceFreshness(row.deviceId);
    tr.classList.toggle("row-new", unseen);
    tr.innerHTML = `<td data-label="Category">${escapeHtml(row.category)}</td>
      <td data-label="Device"><span class="device-name">${escapeHtml(row.deviceName)}</span>${freshness.warning ? `<span class="source-warning" title="${escapeHtml(freshness.detail)}">${escapeHtml(freshness.label)}</span>` : ""}</td>
      <td data-label="Latest"><span class="latest-version">${escapeHtml(row.latest?.version || "—")}</span>${unseen ? ' <span class="badge new">Unseen</span>' : ""}</td>
      <td data-label="Released">${escapeHtml(row.latest?.released_time || "Unknown")}</td>
      <td data-label="Age">${escapeHtml(row.age == null ? "—" : formatAge(row.age))}</td>
      <td data-label="History"><button class="ghost" id="history-${escapeHtml(row.deviceId)}" aria-label="Release history for ${escapeHtml(row.deviceName)}">Release history</button></td>`;
    tr.querySelector("button").addEventListener("click", () => renderModal(row.deviceId, row.deviceName, row.releases));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  const container = document.getElementById("table-container");
  container.replaceChildren(table);
  container.hidden = rows.length === 0;
  document.getElementById("empty-results").hidden = rows.length !== 0;
  document.getElementById("result-count").textContent = `${rows.length} of ${uiState.rows.length} devices`;
  document.getElementById("clear-filters").hidden = !uiState.query && !uiState.category && !uiState.unseenOnly;
  document.getElementById("sort-order").value = `${uiState.sortKey}:${uiState.sortDir}`;
}

function initSourceFreshness() {
  const meta = document.getElementById("firmware-status-meta");
  const checked = TRACKER_CONFIG.source_sync_status?.last_run_utc;
  const local = formatUtcAsLocalDateTime(checked);
  const overdue = !local || Date.now() - Date.parse(checked) > STALE_AFTER_MS;
  meta.textContent = local ? `Sources checked ${local}${overdue ? " · Check overdue" : ""}` : "Sources have not been checked yet";
  meta.classList.toggle("source-warning", overdue);
  meta.title = "The time vendor sources were scanned. Individual devices show their last successful check in release history.";
}

function initApp() {
  const manageUrl = TRACKER_CONFIG.manage_devices_url;
  if (manageUrl?.startsWith("https://github.com/")) {
    const link = document.getElementById("manage-devices");
    link.href = manageUrl;
    link.hidden = false;
  }
  uiState.rows = getAllRows();
  uiState.unseen = detectNewFirmware(uiState.rows).newDeviceIds;
  const categorySelect = document.getElementById("category-filter");
  const categories = [...new Map(uiState.rows.map(row => [row.categoryId, row.category])).entries()].sort((a,b) => a[1].localeCompare(b[1]));
  for (const [id, title] of categories) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = title;
    categorySelect.appendChild(option);
  }
  document.getElementById("device-search").addEventListener("input", event => {uiState.query = event.target.value; renderTable();});
  categorySelect.addEventListener("change", event => {uiState.category = event.target.value; renderTable();});
  document.getElementById("unseen-filter").addEventListener("change", event => {uiState.unseenOnly = event.target.checked; renderTable();});
  document.getElementById("sort-order").addEventListener("change", event => {
    [uiState.sortKey, uiState.sortDir] = event.target.value.split(":");
    renderTable();
  });
  document.getElementById("clear-filters").addEventListener("click", () => {
    uiState.query = uiState.category = "";
    uiState.unseenOnly = false;
    document.getElementById("device-search").value = "";
    categorySelect.value = "";
    document.getElementById("unseen-filter").checked = false;
    renderTable();
    document.getElementById("device-search").focus();
  });
  document.getElementById("mark-updates-seen").addEventListener("click", () => {
    saveSeenVersions(buildVersionSnapshot(uiState.rows));
    uiState.unseen.clear();
    updateFirmwareStatus();
    renderTable();
    document.getElementById("device-search").focus();
  });
  const modal = document.getElementById("modal");
  document.getElementById("close-modal").addEventListener("click", () => modal.close());
  modal.addEventListener("click", event => {
    const rect = modal.getBoundingClientRect();
    if (event.target === modal && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) modal.close();
  });
  modal.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const controls = [...modal.querySelectorAll('button:not([disabled]), a[href], summary, [tabindex="0"]')]
      .filter(element => element.getClientRects().length > 0);
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
  modal.addEventListener("close", () => {
    document.body.classList.remove("dialog-open");
    (document.getElementById(returnFocusId) || document.getElementById("device-search")).focus();
  });
  updateFirmwareStatus();
  initSourceBanner();
  initSourceFreshness();
  renderTable();
}

if (typeof document !== "undefined") initApp();
