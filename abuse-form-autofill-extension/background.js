const STORAGE_KEYS = {
  profiles: "abuseAutofillProfiles",
  lastData: "abuseAutofillLastGeneratedData",
  lastProfileId: "abuseAutofillLastProfileId",
  bridgeUrl: "abuseAutofillBridgeUrl",
  autoFillOnPageLoad: "abuseAutofillAutoFillOnPageLoad"
};

const MSG = {
  PAGE_READY: "ABUSE_AUTOFILL_PAGE_READY",
  FILL_FIELDS: "ABUSE_AUTOFILL_FILL_FIELDS"
};

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(obj) {
  return new Promise((resolve) => chrome.storage.local.set(obj, resolve));
}

function wildcardToRegExp(pattern) {
  const escaped = String(pattern || "")
    .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`, "i");
}

function matchesUrl(pattern, url) {
  if (!pattern) return false;
  try {
    return wildcardToRegExp(pattern).test(url || "");
  } catch (_) {
    return pattern === url;
  }
}

function extractFillValuesFromPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return {};

  if (payload.extension_payload && payload.extension_payload.fill_values) {
    return payload.extension_payload.fill_values;
  }
  if (payload.fill_values) {
    return payload.fill_values;
  }
  if (payload.case_data && payload.rendered) {
    return {
      ...(payload.case_data || {}),
      ...(payload.rendered || {}),
      ...((payload.extension_payload && payload.extension_payload.fill_values) || {})
    };
  }
  if (payload.rendered) {
    return {
      ...(payload.rendered || {}),
      ...((payload.extension_payload && payload.extension_payload.fill_values) || {})
    };
  }
  return payload;
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

function ruleNeedsGeneratedData(rule) {
  const r = normalizeRule(rule);
  if (r.source === "generated") return true;
  if (r.source === "template") return /{{\s*[\w.-]+\s*}}/.test(r.value_template || "");
  return false;
}

function buildTemplateData(generatedData, currentUrl, profile) {
  return {
    ...(generatedData || {}),
    current_page_url: currentUrl || "",
    profile_name: profile.profile_name || "",
    url_match: profile.url_match || ""
  };
}

function getRuleValue(rule, generatedData, currentUrl, profile) {
  const r = normalizeRule(rule);
  const data = buildTemplateData(generatedData, currentUrl, profile);
  if (r.source === "fixed") {
    return r.fixed_value == null ? "" : String(r.fixed_value);
  }
  if (r.source === "template") {
    return renderTemplate(r.value_template || "", data);
  }
  if (r.value_template && String(r.value_template).trim()) {
    return renderTemplate(r.value_template, data);
  }
  const key = r.value_key || "";
  const value = data[key];
  return value == null ? "" : String(value);
}

function buildFillRules(profile, generatedData, currentUrl, hasQueuePayload) {
  const rules = Array.isArray(profile.rules) ? profile.rules : [];
  return rules
    .filter((rule) => rule.enabled !== false)
    .filter((rule) => hasQueuePayload || !ruleNeedsGeneratedData(rule))
    .map((rule) => {
      const r = normalizeRule(rule);
      return {
        field_id: r.field_id,
        action: r.action || "fill",
        value: getRuleValue(r, generatedData, currentUrl, profile),
        source: r.source || "generated",
        value_key: r.value_key || "",
        fixed_value: r.fixed_value || "",
        value_template: r.value_template || ""
      };
    })
    .filter((rule) => rule.field_id);
}

async function fetchLatestQueue(bridgeUrl) {
  const base = (bridgeUrl || "http://127.0.0.1:8765").replace(/\/+$/, "");
  const response = await fetch(base + "/queue", { cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Bridge request failed: ${response.status}`);
  }
  const items = Array.isArray(data.items) ? data.items : [];
  return items.length ? items[0] : null;
}

function chooseProfile(profiles, lastProfileId, currentUrl) {
  const last = (profiles || []).find((p) => p.id === lastProfileId) || null;
  if (last && matchesUrl(last.url_match, currentUrl)) {
    return { profile: last, source: "last-used" };
  }
  const matched = (profiles || []).find((p) => matchesUrl(p.url_match, currentUrl)) || null;
  if (matched) {
    return { profile: matched, source: "url-match" };
  }
  return { profile: null, source: "none" };
}

async function sendFill(tabId, rules) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, { type: MSG.FILL_FIELDS, rules }, (response) => {
      const err = chrome.runtime.lastError;
      if (err) resolve({ ok: false, error: err.message });
      else resolve(response || { ok: false, error: "No response" });
    });
  });
}

async function autoFillTab(tabId, currentUrl, reason = "page-ready") {
  const saved = await storageGet([
    STORAGE_KEYS.profiles,
    STORAGE_KEYS.lastProfileId,
    STORAGE_KEYS.bridgeUrl,
    STORAGE_KEYS.autoFillOnPageLoad
  ]);

  const enabled = saved[STORAGE_KEYS.autoFillOnPageLoad] == null
    ? true
    : Boolean(saved[STORAGE_KEYS.autoFillOnPageLoad]);
  if (!enabled) return { ok: false, skipped: true, reason: "auto-fill disabled" };

  const profiles = Array.isArray(saved[STORAGE_KEYS.profiles]) ? saved[STORAGE_KEYS.profiles] : [];
  const { profile, source } = chooseProfile(profiles, saved[STORAGE_KEYS.lastProfileId], currentUrl);
  if (!profile) {
    await storageSet({ abuseAutofillLastAutoFillStatus: `Skipped: no saved profile matched ${currentUrl}` });
    return { ok: false, skipped: true, reason: "no matching profile" };
  }

  let latestItem = null;
  let generatedData = {};
  let queueError = "";
  try {
    latestItem = await fetchLatestQueue(saved[STORAGE_KEYS.bridgeUrl]);
    if (latestItem) {
      const payload = latestItem.payload || latestItem;
      generatedData = extractFillValuesFromPayload(payload);
      await storageSet({ [STORAGE_KEYS.lastData]: JSON.stringify(payload, null, 2) });
    }
  } catch (err) {
    queueError = err && err.message ? err.message : String(err);
  }

  const rules = buildFillRules(profile, generatedData, currentUrl, Boolean(latestItem));
  if (!rules.length) {
    const msg = queueError
      ? `Skipped auto-fill: bridge unavailable (${queueError}) and no fixed-only rules.`
      : "Skipped auto-fill: no rules to fill.";
    await storageSet({ abuseAutofillLastAutoFillStatus: msg });
    return { ok: false, skipped: true, reason: msg };
  }

  const response = await sendFill(tabId, rules);
  const okCount = response && typeof response.okCount === "number" ? response.okCount : 0;
  const total = response && typeof response.total === "number" ? response.total : rules.length;
  const status = response && response.ok
    ? `Auto-filled ${okCount}/${total} field(s) using ${source} profile "${profile.profile_name || "Untitled"}"${latestItem ? ` and latest queue "${latestItem.domain || "case"}"` : " with fixed-only rules"}.`
    : `Auto-fill failed using profile "${profile.profile_name || "Untitled"}": ${(response && response.error) || "unknown error"}`;

  await storageSet({
    abuseAutofillLastAutoFillStatus: status,
    abuseAutofillLastAutoFillAt: new Date().toISOString()
  });
  return { ok: Boolean(response && response.ok), response, status, reason };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== MSG.PAGE_READY) return false;
  const tabId = sender && sender.tab && sender.tab.id;
  const url = (message && message.url) || (sender && sender.url) || "";
  if (!tabId || !url) return false;

  autoFillTab(tabId, url, "page-ready")
    .then((result) => sendResponse(result))
    .catch((err) => sendResponse({ ok: false, error: err && err.message ? err.message : String(err) }));
  return true;
});
