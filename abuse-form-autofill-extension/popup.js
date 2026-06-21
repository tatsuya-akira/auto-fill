const STORAGE_KEYS = {
  profiles: "abuseAutofillProfiles",
  lastData: "abuseAutofillLastGeneratedData",
  lastProfileId: "abuseAutofillLastProfileId",
  bridgeUrl: "abuseAutofillBridgeUrl",
  useLatestQueueOnFill: "abuseAutofillUseLatestQueueOnFill",
  autoFillOnPageLoad: "abuseAutofillAutoFillOnPageLoad"
};

const MSG = {
  SCAN_FIELDS: "ABUSE_AUTOFILL_SCAN_FIELDS",
  FILL_FIELDS: "ABUSE_AUTOFILL_FILL_FIELDS"
};

let state = {
  tabId: null,
  currentUrl: "",
  fields: [],
  generatedData: {},
  profiles: [],
  activeProfile: makeEmptyProfile(),
  selectedRuleIndex: -1,
  bridgeUrl: "http://127.0.0.1:8765",
  bridgeItems: [],
  selectedQueueIndex: -1,
  useLatestQueueOnFill: true,
  autoFillOnPageLoad: true
};

function makeEmptyProfile() {
  return {
    id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    profile_name: "Untitled abuse form profile",
    url_match: "",
    rules: []
  };
}

function $(id) { return document.getElementById(id); }

function setStatus(text, type = "") {
  const el = $("status");
  if (!el) return;
  el.textContent = text;
  el.className = `status ${type}`.trim();
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function truncate(value, n = 100) {
  const text = String(value == null ? "" : value);
  return text.length > n ? text.slice(0, n - 1) + "..." : text;
}

function wildcardToRegExp(pattern) {
  const escaped = pattern
    .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`, "i");
}

function matchesUrl(pattern, url) {
  if (!pattern) return false;
  try {
    return wildcardToRegExp(pattern).test(url);
  } catch (_) {
    return pattern === url;
  }
}

function getOriginWildcard(url) {
  try {
    const u = new URL(url);
    return `${u.origin}/*`;
  } catch (_) {
    return url || "";
  }
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(obj) {
  return new Promise((resolve) => chrome.storage.local.set(obj, resolve));
}

async function ensureContentScript() {
  if (!state.tabId) throw new Error("No active tab");
  try {
    await chrome.scripting.executeScript({
      target: { tabId: state.tabId, allFrames: false },
      files: ["content.js"]
    });
  } catch (err) {
    throw new Error(`Cannot inject content script: ${err && err.message ? err.message : err}`);
  }
}

function sendRawMessageToTab(type, payload = {}) {
  return new Promise((resolve, reject) => {
    if (!state.tabId) {
      reject(new Error("No active tab"));
      return;
    }
    chrome.tabs.sendMessage(state.tabId, { type, ...payload }, (response) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(response);
    });
  });
}

async function sendToTab(type, payload = {}) {
  try {
    return await sendRawMessageToTab(type, payload);
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    if (msg.includes("Receiving end does not exist") || msg.includes("Could not establish connection")) {
      await ensureContentScript();
      return await sendRawMessageToTab(type, payload);
    }
    throw err;
  }
}

function extractFillValues(jsonText) {
  if (!jsonText.trim()) return {};
  const parsed = JSON.parse(jsonText);

  if (parsed && parsed.extension_payload && parsed.extension_payload.fill_values) {
    return parsed.extension_payload.fill_values;
  }
  if (parsed && parsed.fill_values) {
    return parsed.fill_values;
  }
  if (parsed && parsed.case_data && parsed.rendered) {
    return {
      ...(parsed.case_data || {}),
      ...(parsed.rendered || {}),
      ...((parsed.extension_payload && parsed.extension_payload.fill_values) || {})
    };
  }
  if (parsed && parsed.rendered) {
    return {
      ...(parsed.rendered || {}),
      ...((parsed.extension_payload && parsed.extension_payload.fill_values) || {})
    };
  }
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
}

function renderTemplate(template, data) {
  return String(template || "").replace(/{{\s*([\w.-]+)\s*}}/g, (_, key) => {
    const value = data[key];
    return value == null ? "" : String(value);
  });
}

function normalizeRule(rule) {
  const out = { ...(rule || {}) };
  if (!out.source) {
    if (out.fixed_value != null && String(out.fixed_value).length) out.source = "fixed";
    else if (out.value_template && !out.value_key) out.source = "template";
    else out.source = "generated";
  }
  if (out.source === "static") out.source = "fixed";
  out.action = out.action || "fill";
  return out;
}

function buildTemplateData() {
  return {
    ...(state.generatedData || {}),
    current_page_url: state.currentUrl || "",
    profile_name: state.activeProfile.profile_name || "",
    url_match: state.activeProfile.url_match || ""
  };
}

function getRuleValue(rule) {
  const r = normalizeRule(rule);
  const data = buildTemplateData();
  if (r.source === "fixed") {
    return r.fixed_value == null ? "" : String(r.fixed_value);
  }
  if (r.source === "template") {
    return renderTemplate(r.value_template || "", data);
  }
  const key = r.value_key || "";
  if (r.value_template && r.value_template.trim()) {
    return renderTemplate(r.value_template, data);
  }
  const value = data[key];
  return value == null ? "" : String(value);
}

function getRuleSourceLabel(rule) {
  const r = normalizeRule(rule);
  if (r.source === "fixed") return "fixed";
  if (r.source === "template") return "template";
  return "generated";
}

function getRuleValueLabel(rule) {
  const r = normalizeRule(rule);
  if (r.source === "fixed") return truncate(r.fixed_value || "", 60);
  if (r.source === "template") return truncate(r.value_template || "", 60);
  return r.value_key || "";
}

function ruleToFill(rule) {
  const r = normalizeRule(rule);
  return {
    field_id: r.field_id,
    action: r.action || "fill",
    value: getRuleValue(r),
    source: r.source,
    value_key: r.value_key || "",
    fixed_value: r.fixed_value || "",
    value_template: r.value_template || ""
  };
}

function getEnabledMappedRules(profile = state.activeProfile) {
  return (profile.rules || [])
    .filter((rule) => rule.enabled !== false)
    .map(ruleToFill);
}

function syncProfileFromInputs() {
  state.activeProfile.profile_name = $("profileName").value.trim() || "Untitled abuse form profile";
  state.activeProfile.url_match = $("profilePattern").value.trim();
}

function syncInputsFromProfile() {
  $("profileName").value = state.activeProfile.profile_name || "";
  $("profilePattern").value = state.activeProfile.url_match || "";
}

function findMatchingProfile() {
  const exact = state.profiles.find((profile) => matchesUrl(profile.url_match, state.currentUrl));
  return exact || null;
}

function findLastUsedProfile(lastProfileId) {
  return state.profiles.find((p) => p.id === lastProfileId) || null;
}

function setActiveProfile(profile, options = {}) {
  state.activeProfile = JSON.parse(JSON.stringify(profile || makeEmptyProfile()));
  state.selectedRuleIndex = -1;
  syncInputsFromProfile();
  if (!options.skipStore && state.activeProfile && state.activeProfile.id) {
    storageSet({ [STORAGE_KEYS.lastProfileId]: state.activeProfile.id });
  }
  renderAll();
  if (saved.abuseAutofillLastAutoFillStatus) {
    setStatus(saved.abuseAutofillLastAutoFillStatus, saved.abuseAutofillLastAutoFillStatus.includes("failed") || saved.abuseAutofillLastAutoFillStatus.includes("Skipped") ? "warn" : "ok");
  }
}

function newProfileForCurrentUrl() {
  const profile = makeEmptyProfile();
  profile.url_match = getOriginWildcard(state.currentUrl);
  setActiveProfile(profile);
  setStatus("New unsaved profile created. Add rules, then Save profile.", "warn");
}

function getActiveProfileId() {
  return state.activeProfile && state.activeProfile.id ? state.activeProfile.id : "";
}

function selectProfileById(profileId) {
  if (!profileId || profileId === "__new__") {
    newProfileForCurrentUrl();
    return;
  }
  const profile = state.profiles.find((p) => p.id === profileId);
  if (profile) {
    setActiveProfile(profile);
    setStatus(`Selected profile: ${profile.profile_name || "Untitled"}`, "ok");
  }
}

function updateDataKeysUI() {
  const keys = Object.keys(state.generatedData || {}).sort();
  const chips = $("dataKeys");
  const select = $("ruleValueKey");
  chips.innerHTML = "";
  select.innerHTML = "";

  if (!keys.length) {
    chips.textContent = "No data parsed yet.";
    chips.className = "chips empty";
    select.innerHTML = '<option value="">No generated keys</option>';
    return;
  }

  chips.className = "chips";
  keys.forEach((key) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = key;
    chips.appendChild(chip);

    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = key;
    select.appendChild(opt);
  });
}

function updateFieldSelects() {
  const select = $("ruleFieldId");
  select.innerHTML = "";
  const fieldsWithId = state.fields.filter((field) => field.id);

  if (!fieldsWithId.length) {
    select.innerHTML = '<option value="">No id fields detected</option>';
    return;
  }

  fieldsWithId.forEach((field) => {
    const opt = document.createElement("option");
    opt.value = field.id;
    opt.textContent = `${field.id} (${field.tag}/${field.type})`;
    select.appendChild(opt);
  });
}

function renderFieldsTable() {
  const tbody = $("fieldsTable").querySelector("tbody");
  tbody.innerHTML = "";
  state.fields.forEach((field) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td title="${escapeHtml(field.id || "")}">${escapeHtml(field.id || "(no id)")}</td>
      <td>${escapeHtml(field.tag)}/${escapeHtml(field.type)}</td>
      <td title="${escapeHtml(field.name || "")}">${escapeHtml(field.name || "")}</td>
      <td title="${escapeHtml([field.label, field.placeholder, field.ariaLabel].filter(Boolean).join(" / "))}">${escapeHtml([field.label, field.placeholder, field.ariaLabel].filter(Boolean).join(" / "))}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderRulesTable() {
  const tbody = $("rulesTable").querySelector("tbody");
  tbody.innerHTML = "";
  const rules = state.activeProfile.rules || [];

  rules.forEach((rule, index) => {
    const mapped = ruleToFill(rule);
    const tr = document.createElement("tr");
    if (index === state.selectedRuleIndex) tr.classList.add("selected");
    tr.dataset.index = String(index);
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td>${rule.enabled === false ? "No" : "Yes"}</td>
      <td title="${escapeHtml(rule.field_id || "")}">${escapeHtml(rule.field_id || "")}</td>
      <td>${escapeHtml(getRuleSourceLabel(rule))}</td>
      <td title="${escapeHtml(getRuleValueLabel(rule))}">${escapeHtml(getRuleValueLabel(rule))}</td>
      <td>${escapeHtml(rule.action || "fill")}</td>
      <td title="${escapeHtml(mapped.value || "")}">${escapeHtml(truncate(mapped.value || "", 140))}</td>
    `;
    tr.addEventListener("click", () => {
      state.selectedRuleIndex = index;
      loadSelectedRuleToEditor();
      renderRulesTable();
    });
    tbody.appendChild(tr);
  });
}

function renderProfileJson() {
  syncProfileFromInputs();
  const el = $("profileJson");
  if (el) el.value = JSON.stringify(state.activeProfile, null, 2);
}


function getBridgeUrl() {
  const input = $("bridgeUrl");
  const raw = input ? input.value.trim() : state.bridgeUrl;
  return (raw || "http://127.0.0.1:8765").replace(/\/+$/, "");
}

async function bridgeRequest(path, options = {}) {
  const url = getBridgeUrl() + path;
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Bridge request failed: ${response.status}`);
  }
  return data;
}

function renderQueueSelect() {
  const select = $("queueSelect");
  if (!select) return;
  select.innerHTML = "";
  const items = state.bridgeItems || [];
  if (!items.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No queued payload";
    select.appendChild(opt);
    return;
  }
  items.forEach((item, index) => {
    const opt = document.createElement("option");
    opt.value = String(index);
    opt.textContent = `${index === 0 ? "Latest: " : ""}${item.domain || "case"} | ${item.title || item.template_id || "queued payload"}`;
    select.appendChild(opt);
  });
  select.value = state.selectedQueueIndex >= 0 ? String(state.selectedQueueIndex) : "0";
}

function renderBridgeQueue() {
  renderQueueSelect();
  const tbody = $("queueTable") ? $("queueTable").querySelector("tbody") : null;
  if (!tbody) return;
  tbody.innerHTML = "";
  const items = state.bridgeItems || [];
  items.forEach((item, index) => {
    const tr = document.createElement("tr");
    if (index === state.selectedQueueIndex) tr.classList.add("selected");
    tr.dataset.index = String(index);
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td title="${escapeHtml(item.domain || "")}">${escapeHtml(item.domain || "")}</td>
      <td title="${escapeHtml(item.template_id || "")}">${escapeHtml(item.template_id || "")}</td>
      <td title="${escapeHtml(item.title || "")}">${escapeHtml(truncate(item.title || "", 120))}</td>
      <td title="${escapeHtml(item.updated_at || item.created_at || "")}">${escapeHtml(item.updated_at || item.created_at || "")}</td>
    `;
    tr.addEventListener("click", () => {
      state.selectedQueueIndex = index;
      const selected = state.bridgeItems[index];
      $("selectedQueueTitle").value = selected ? `${selected.domain || ""} | ${selected.title || ""}` : "";
      renderBridgeQueue();
    });
    tbody.appendChild(tr);
  });
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="5" class="empty">No queued payloads. Queue one from the Python GUI.</td>';
    tbody.appendChild(tr);
  }
}

async function refreshBridgeQueue(options = {}) {
  try {
    state.bridgeUrl = getBridgeUrl();
    await storageSet({ [STORAGE_KEYS.bridgeUrl]: state.bridgeUrl });
    const data = await bridgeRequest("/queue");
    state.bridgeItems = Array.isArray(data.items) ? data.items : [];
    if (options.selectLatest || state.selectedQueueIndex < 0 || state.selectedQueueIndex >= state.bridgeItems.length) {
      state.selectedQueueIndex = state.bridgeItems.length ? 0 : -1;
    }
    const selected = state.bridgeItems[state.selectedQueueIndex];
    const titleEl = $("selectedQueueTitle");
    if (titleEl) titleEl.value = selected ? `${selected.domain || ""} | ${selected.title || ""}` : "";
    renderBridgeQueue();
    if (!options.silent) setStatus(`Bridge queue: ${state.bridgeItems.length} item(s).`, "ok");
    return true;
  } catch (err) {
    if (!options.silent) setStatus(`Bridge not connected: ${err.message}. Start the Python GUI bridge first.`, "warn");
    return false;
  }
}

async function loadQueueItem(item, options = {}) {
  if (!item) {
    if (!options.silent) setStatus("Select a queue item first.", "warn");
    return false;
  }
  const payload = item.payload || item;
  const text = JSON.stringify(payload, null, 2);
  $("generatedJson").value = text;
  state.generatedData = extractFillValues(text);
  await storageSet({ [STORAGE_KEYS.lastData]: text });
  renderAll();
  if (!options.silent) setStatus(`Loaded queue item for ${item.domain || "case"}.`, "ok");
  if (options.openDataTab) {
    const dataTabButton = document.querySelector('.tab[data-tab="dataTab"]');
    if (dataTabButton) dataTabButton.click();
  }
  return true;
}

async function useSelectedQueueItem(options = {}) {
  const item = state.bridgeItems[state.selectedQueueIndex];
  return loadQueueItem(item, options);
}

async function useLatestQueueItem(options = {}) {
  const ok = await refreshBridgeQueue({ selectLatest: true, silent: options.silent });
  if (!ok) return false;
  state.selectedQueueIndex = state.bridgeItems.length ? 0 : -1;
  return useSelectedQueueItem(options);
}

async function deleteSelectedQueueItem() {
  const item = state.bridgeItems[state.selectedQueueIndex];
  if (!item) {
    setStatus("Select a queue item first.", "warn");
    return;
  }
  try {
    await bridgeRequest("/delete", { method: "POST", body: JSON.stringify({ id: item.id }) });
    state.selectedQueueIndex = -1;
    $("selectedQueueTitle").value = "";
    await refreshBridgeQueue();
    setStatus("Deleted selected queue item.", "ok");
  } catch (err) {
    setStatus(`Delete failed: ${err.message}`, "error");
  }
}

async function clearBridgeQueue() {
  try {
    await bridgeRequest("/clear", { method: "POST", body: "{}" });
    state.selectedQueueIndex = -1;
    $("selectedQueueTitle").value = "";
    await refreshBridgeQueue();
    setStatus("Cleared bridge queue.", "ok");
  } catch (err) {
    setStatus(`Clear failed: ${err.message}`, "error");
  }
}

function renderProfileSelectors() {
  const ids = ["profileSelect", "profileSelectProfileTab"];
  ids.forEach((id) => {
    const select = $(id);
    if (!select) return;
    select.innerHTML = "";
    const newOpt = document.createElement("option");
    newOpt.value = "__new__";
    newOpt.textContent = "New unsaved profile";
    select.appendChild(newOpt);

    const matchingIds = new Set(state.profiles.filter((p) => matchesUrl(p.url_match, state.currentUrl)).map((p) => p.id));
    state.profiles.forEach((profile) => {
      const opt = document.createElement("option");
      opt.value = profile.id;
      opt.textContent = `${matchingIds.has(profile.id) ? "✓ " : ""}${profile.profile_name || "Untitled"} — ${profile.url_match || "no pattern"}`;
      select.appendChild(opt);
    });
    select.value = state.profiles.some((p) => p.id === getActiveProfileId()) ? getActiveProfileId() : "__new__";
  });
}

function renderProfilesList() {
  const box = $("profilesList");
  box.innerHTML = "";
  if (!state.profiles.length) {
    box.textContent = "No saved profiles yet.";
    box.className = "profilesList empty";
    return;
  }
  box.className = "profilesList";
  state.profiles.forEach((profile) => {
    const div = document.createElement("div");
    div.className = "profileItem";
    div.innerHTML = `<strong>${escapeHtml(profile.profile_name || "Untitled")}</strong><span>${escapeHtml(profile.url_match || "")}</span>`;
    div.addEventListener("click", () => setActiveProfile(profile));
    box.appendChild(div);
  });
}

function renderAll() {
  updateDataKeysUI();
  updateFieldSelects();
  renderFieldsTable();
  renderRulesTable();
  renderProfileJson();
  renderProfileSelectors();
  renderProfilesList();
  renderBridgeQueue();
  const chk = $("useLatestQueueOnFill");
  if (chk) chk.checked = Boolean(state.useLatestQueueOnFill);
  const autoChk = $("autoFillOnPageLoad");
  if (autoChk) autoChk.checked = Boolean(state.autoFillOnPageLoad);
}

function loadSelectedRuleToEditor() {
  const rule = normalizeRule(state.activeProfile.rules[state.selectedRuleIndex]);
  if (!rule) return;
  $("ruleFieldId").value = rule.field_id || "";
  $("ruleSource").value = rule.source || "generated";
  $("ruleValueKey").value = rule.value_key || "";
  $("ruleAction").value = rule.action || "fill";
  $("ruleFixedValue").value = rule.fixed_value || "";
  $("ruleTemplate").value = rule.value_template || "";
}

function makeRuleFromEditor() {
  return {
    enabled: true,
    field_id: $("ruleFieldId").value.trim(),
    source: $("ruleSource").value || "generated",
    value_key: $("ruleValueKey").value.trim(),
    fixed_value: $("ruleFixedValue").value,
    value_template: $("ruleTemplate").value,
    action: $("ruleAction").value || "fill"
  };
}

function validateRule(rule) {
  const r = normalizeRule(rule);
  if (!r.field_id) return "Rule needs an input id.";
  if (r.source === "generated" && !r.value_key && !(r.value_template || "").trim()) {
    return "Generated rule needs a generated key or a value template.";
  }
  if (r.source === "template" && !(r.value_template || "").trim()) {
    return "Template rule needs a value template.";
  }
  return "";
}

async function scanFields() {
  try {
    const response = await sendToTab(MSG.SCAN_FIELDS);
    state.fields = response && response.fields ? response.fields : [];
    renderAll();
    setStatus(`Scanned ${state.fields.length} field(s).`, "ok");
  } catch (err) {
    setStatus(`Scan failed: ${err.message}. Reload the page and try again.`, "error");
  }
}

function parseGeneratedDataFromBox() {
  try {
    const data = extractFillValues($("generatedJson").value);
    state.generatedData = data || {};
    storageSet({ [STORAGE_KEYS.lastData]: $("generatedJson").value });
    renderAll();
    setStatus(`Parsed ${Object.keys(state.generatedData).length} generated key(s).`, "ok");
  } catch (err) {
    setStatus(`Invalid generated JSON: ${err.message}`, "error");
  }
}

async function saveActiveProfile() {
  syncProfileFromInputs();
  if (!state.activeProfile.url_match) {
    setStatus("Profile needs a URL match pattern.", "warn");
    return;
  }

  const index = state.profiles.findIndex((p) => p.id === state.activeProfile.id);
  if (index >= 0) state.profiles[index] = JSON.parse(JSON.stringify(state.activeProfile));
  else state.profiles.push(JSON.parse(JSON.stringify(state.activeProfile)));

  await storageSet({
    [STORAGE_KEYS.profiles]: state.profiles,
    [STORAGE_KEYS.lastProfileId]: state.activeProfile.id
  });
  renderAll();
  setStatus(`Saved profile: ${state.activeProfile.profile_name}`, "ok");
}

async function deleteActiveProfile() {
  const id = state.activeProfile.id;
  state.profiles = state.profiles.filter((p) => p.id !== id);
  await storageSet({ [STORAGE_KEYS.profiles]: state.profiles });
  setActiveProfile(makeEmptyProfile());
  setStatus("Deleted profile.", "ok");
}

async function fillCurrentPage(options = {}) {
  if (options.useLatestQueue || (options.useLatestQueue !== false && state.useLatestQueueOnFill)) {
    await useLatestQueueItem({ silent: true });
  }
  if (options.matchProfile) {
    const found = findMatchingProfile();
    if (found) setActiveProfile(found);
  }
  syncProfileFromInputs();
  if (state.activeProfile && state.activeProfile.id) {
    await storageSet({ [STORAGE_KEYS.lastProfileId]: state.activeProfile.id });
  }
  const rules = getEnabledMappedRules();
  if (!rules.length) {
    setStatus("No enabled mapping rules to fill. Select or create a saved profile for this form.", "warn");
    return;
  }
  try {
    const response = await sendToTab(MSG.FILL_FIELDS, { rules });
    const failed = (response.results || []).filter((r) => !r.ok);
    if (failed.length) {
      setStatus(`Filled ${response.okCount}/${response.total}. Failed: ${failed.map((r) => r.id + " " + r.error).join("; ")}`, "warn");
    } else {
      setStatus(`Filled ${response.okCount}/${response.total} field(s). Review before submitting.`, "ok");
    }
  } catch (err) {
    setStatus(`Fill failed: ${err.message}`, "error");
  }
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(btn.dataset.tab).classList.add("active");
    });
  });
}

function on(id, event, handler) {
  const el = $(id);
  if (!el) return false;
  el.addEventListener(event, handler);
  return true;
}

function setupEvents() {
  on("scanBtn", "click", scanFields);
  on("refreshProfileBtn", "click", () => {
    const found = findMatchingProfile();
    if (found) {
      setActiveProfile(found);
      setStatus(`Matched profile: ${found.profile_name}`, "ok");
    } else {
      setStatus("No matching profile for this URL.", "warn");
    }
  });
  on("fillBtn", "click", () => fillCurrentPage({ matchProfile: false }));
  on("oneClickFillBtn", "click", () => fillCurrentPage({ useLatestQueue: true, matchProfile: false }));
  on("newProfileBtn", "click", newProfileForCurrentUrl);
  on("profileSelect", "change", (event) => selectProfileById(event.target.value));
  on("profileSelectProfileTab", "change", (event) => selectProfileById(event.target.value));
  on("queueSelect", "change", (event) => {
    state.selectedQueueIndex = Number(event.target.value);
    const selected = state.bridgeItems[state.selectedQueueIndex];
    const titleEl = $("selectedQueueTitle");
    if (titleEl) titleEl.value = selected ? `${selected.domain || ""} | ${selected.title || ""}` : "";
    renderBridgeQueue();
  });
  on("useLatestQueueOnFill", "change", async (event) => {
    state.useLatestQueueOnFill = Boolean(event.target.checked);
    await storageSet({ [STORAGE_KEYS.useLatestQueueOnFill]: state.useLatestQueueOnFill });
  });
  on("autoFillOnPageLoad", "change", async (event) => {
    state.autoFillOnPageLoad = Boolean(event.target.checked);
    await storageSet({ [STORAGE_KEYS.autoFillOnPageLoad]: state.autoFillOnPageLoad });
    setStatus(state.autoFillOnPageLoad ? "Auto-fill on page load enabled." : "Auto-fill on page load disabled.", state.autoFillOnPageLoad ? "ok" : "warn");
  });

  on("parseDataBtn", "click", parseGeneratedDataFromBox);
  on("clearDataBtn", "click", () => {
    $("generatedJson").value = "";
    state.generatedData = {};
    storageSet({ [STORAGE_KEYS.lastData]: "" });
    renderAll();
  });

  on("refreshQueueBtn", "click", () => refreshBridgeQueue({ selectLatest: false }));
  on("useQueueBtn", "click", () => useSelectedQueueItem({ openDataTab: true }));
  on("deleteQueueBtn", "click", deleteSelectedQueueItem);
  on("clearQueueBtn", "click", clearBridgeQueue);
  on("bridgeUrl", "input", () => {
    state.bridgeUrl = getBridgeUrl();
    storageSet({ [STORAGE_KEYS.bridgeUrl]: state.bridgeUrl });
  });

  on("useCurrentUrlBtn", "click", () => {
    $("profilePattern").value = state.currentUrl;
    renderProfileJson();
  });
  on("useCurrentOriginBtn", "click", () => {
    $("profilePattern").value = getOriginWildcard(state.currentUrl);
    renderProfileJson();
  });
  on("saveProfileBtn", "click", saveActiveProfile);
  on("deleteProfileBtn", "click", deleteActiveProfile);

  on("profileName", "input", renderProfileJson);
  on("profilePattern", "input", renderProfileJson);
  ["ruleSource", "ruleValueKey", "ruleFieldId", "ruleAction", "ruleFixedValue", "ruleTemplate"].forEach((id) => {
    on(id, "input", () => {
      if (state.selectedRuleIndex >= 0) {
        // Live-preview edits in the editor without mutating the selected rule until Update is clicked.
        renderRulesTable();
      }
    });
  });

  on("addRuleBtn", "click", () => {
    const rule = makeRuleFromEditor();
    const validation = validateRule(rule);
    if (validation) {
      setStatus(validation, "warn");
      return;
    }
    state.activeProfile.rules.push(rule);
    state.selectedRuleIndex = state.activeProfile.rules.length - 1;
    renderAll();
  });

  on("updateRuleBtn", "click", () => {
    if (state.selectedRuleIndex < 0) {
      setStatus("Select a rule first.", "warn");
      return;
    }
    const updated = {
      ...state.activeProfile.rules[state.selectedRuleIndex],
      ...makeRuleFromEditor()
    };
    const validation = validateRule(updated);
    if (validation) {
      setStatus(validation, "warn");
      return;
    }
    state.activeProfile.rules[state.selectedRuleIndex] = updated;
    renderAll();
  });

  on("duplicateRuleBtn", "click", () => {
    const rule = state.activeProfile.rules[state.selectedRuleIndex];
    if (!rule) return;
    state.activeProfile.rules.splice(state.selectedRuleIndex + 1, 0, JSON.parse(JSON.stringify(rule)));
    state.selectedRuleIndex += 1;
    renderAll();
  });

  on("deleteRuleBtn", "click", () => {
    if (state.selectedRuleIndex < 0) return;
    state.activeProfile.rules.splice(state.selectedRuleIndex, 1);
    state.selectedRuleIndex = -1;
    renderAll();
  });

  on("moveUpBtn", "click", () => {
    const i = state.selectedRuleIndex;
    if (i <= 0) return;
    const rules = state.activeProfile.rules;
    [rules[i - 1], rules[i]] = [rules[i], rules[i - 1]];
    state.selectedRuleIndex = i - 1;
    renderAll();
  });

  on("moveDownBtn", "click", () => {
    const i = state.selectedRuleIndex;
    const rules = state.activeProfile.rules;
    if (i < 0 || i >= rules.length - 1) return;
    [rules[i + 1], rules[i]] = [rules[i], rules[i + 1]];
    state.selectedRuleIndex = i + 1;
    renderAll();
  });

  on("toggleRuleBtn", "click", () => {
    const rule = state.activeProfile.rules[state.selectedRuleIndex];
    if (!rule) return;
    rule.enabled = rule.enabled === false;
    renderAll();
  });

  on("applyProfileJsonBtn", "click", () => {
    try {
      const profile = JSON.parse($("profileJson").value);
      if (!profile.id) profile.id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
      if (!Array.isArray(profile.rules)) profile.rules = [];
      setActiveProfile(profile);
      setStatus("Applied profile JSON.", "ok");
    } catch (err) {
      setStatus(`Invalid profile JSON: ${err.message}`, "error");
    }
  });

  on("copyProfileJsonBtn", "click", async () => {
    await navigator.clipboard.writeText($("profileJson").value);
    setStatus("Copied profile JSON.", "ok");
  });

  on("exportProfileBtn", "click", () => {
    syncProfileFromInputs();
    const blob = new Blob([JSON.stringify(state.activeProfile, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(state.activeProfile.profile_name || "abuse-form-profile").replace(/[^a-z0-9_-]+/gi, "_")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });

  on("importProfileFile", "change", async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const text = await file.text();
    try {
      const profile = JSON.parse(text);
      if (!profile.id) profile.id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
      if (!Array.isArray(profile.rules)) profile.rules = [];
      setActiveProfile(profile);
      setStatus("Imported profile JSON. Click Save profile to store it.", "ok");
    } catch (err) {
      setStatus(`Import failed: ${err.message}`, "error");
    }
  });
}

async function init() {
  setupTabs();
  setupEvents();

  const tab = await getActiveTab();
  state.tabId = tab && tab.id;
  state.currentUrl = tab && tab.url ? tab.url : "";
  $("currentUrl").value = state.currentUrl;

  const saved = await storageGet([STORAGE_KEYS.profiles, STORAGE_KEYS.lastData, STORAGE_KEYS.lastProfileId, STORAGE_KEYS.bridgeUrl, STORAGE_KEYS.useLatestQueueOnFill, STORAGE_KEYS.autoFillOnPageLoad, "abuseAutofillLastAutoFillStatus", "abuseAutofillLastAutoFillAt"]);
  state.profiles = Array.isArray(saved[STORAGE_KEYS.profiles]) ? saved[STORAGE_KEYS.profiles] : [];
  state.bridgeUrl = saved[STORAGE_KEYS.bridgeUrl] || state.bridgeUrl;
  state.useLatestQueueOnFill = saved[STORAGE_KEYS.useLatestQueueOnFill] == null ? true : Boolean(saved[STORAGE_KEYS.useLatestQueueOnFill]);
  state.autoFillOnPageLoad = saved[STORAGE_KEYS.autoFillOnPageLoad] == null ? true : Boolean(saved[STORAGE_KEYS.autoFillOnPageLoad]);
  if ($("bridgeUrl")) $("bridgeUrl").value = state.bridgeUrl;
  if ($("useLatestQueueOnFill")) $("useLatestQueueOnFill").checked = state.useLatestQueueOnFill;
  if ($("autoFillOnPageLoad")) $("autoFillOnPageLoad").checked = state.autoFillOnPageLoad;
  $("generatedJson").value = saved[STORAGE_KEYS.lastData] || "";
  if ($("generatedJson").value.trim()) {
    try { state.generatedData = extractFillValues($("generatedJson").value); } catch (_) { state.generatedData = {}; }
  }

  const lastProfile = findLastUsedProfile(saved[STORAGE_KEYS.lastProfileId]);
  const matched = findMatchingProfile();
  if (lastProfile) {
    setActiveProfile(lastProfile, { skipStore: true });
    setStatus(`Loaded last used profile: ${lastProfile.profile_name}`, "ok");
  } else if (matched) {
    setActiveProfile(matched, { skipStore: true });
    setStatus(`Matched URL profile: ${matched.profile_name}`, "ok");
  } else {
    const empty = makeEmptyProfile();
    empty.url_match = getOriginWildcard(state.currentUrl);
    setActiveProfile(empty, { skipStore: true });
    setStatus("No saved profile yet. Create one for this URL.", "warn");
  }

  await scanFields();
  await refreshBridgeQueue({ selectLatest: true, silent: true });
  if (state.bridgeItems.length) {
    await useSelectedQueueItem({ silent: true });
  }
  renderAll();
  if (saved.abuseAutofillLastAutoFillStatus) {
    setStatus(saved.abuseAutofillLastAutoFillStatus, saved.abuseAutofillLastAutoFillStatus.includes("failed") || saved.abuseAutofillLastAutoFillStatus.includes("Skipped") ? "warn" : "ok");
  }
}

init().catch((err) => setStatus(`Init failed: ${err.message}`, "error"));
