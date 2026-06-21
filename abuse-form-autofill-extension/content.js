(function () {
  if (window.__ABUSE_AUTOFILL_CONTENT_LOADED__) return;
  window.__ABUSE_AUTOFILL_CONTENT_LOADED__ = true;
  const MESSAGE_TYPES = {
    SCAN_FIELDS: "ABUSE_AUTOFILL_SCAN_FIELDS",
    FILL_FIELDS: "ABUSE_AUTOFILL_FILL_FIELDS",
    PAGE_READY: "ABUSE_AUTOFILL_PAGE_READY"
  };

  function visibleText(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function getLabelFor(el) {
    if (!el) return "";
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor) return visibleText(byFor.textContent);
    }
    const parentLabel = el.closest("label");
    if (parentLabel) return visibleText(parentLabel.textContent);
    const ariaLabelledBy = el.getAttribute("aria-labelledby");
    if (ariaLabelledBy) {
      return ariaLabelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((node) => visibleText(node.textContent))
        .join(" ")
        .trim();
    }
    return "";
  }

  function scanFields() {
    const nodes = Array.from(document.querySelectorAll("input, textarea, select"));
    return nodes.map((el, index) => {
      const tag = el.tagName.toLowerCase();
      const type = tag === "input" ? (el.getAttribute("type") || "text").toLowerCase() : tag;
      return {
        index,
        id: el.id || "",
        name: el.getAttribute("name") || "",
        tag,
        type,
        label: getLabelFor(el),
        placeholder: el.getAttribute("placeholder") || "",
        ariaLabel: el.getAttribute("aria-label") || "",
        disabled: Boolean(el.disabled),
        readOnly: Boolean(el.readOnly),
        valuePreview: String(el.value || "").slice(0, 120)
      };
    });
  }

  function setNativeValue(el, value) {
    const tag = el.tagName.toLowerCase();
    const proto = tag === "textarea"
      ? window.HTMLTextAreaElement.prototype
      : tag === "select"
        ? window.HTMLSelectElement.prototype
        : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }
  }

  function dispatchInputEvents(el) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function fillElementById(rule) {
    const id = rule.field_id || rule.input_id || rule.id;
    if (!id) return { ok: false, id: "", error: "Missing field_id" };

    const el = document.getElementById(id);
    if (!el) return { ok: false, id, error: "Element id not found" };
    if (el.disabled) return { ok: false, id, error: "Element is disabled" };
    if (el.readOnly) return { ok: false, id, error: "Element is read-only" };

    const action = rule.action || "fill";
    const value = rule.value == null ? "" : String(rule.value);
    const tag = el.tagName.toLowerCase();
    const type = tag === "input" ? (el.getAttribute("type") || "text").toLowerCase() : tag;

    try {
      if (action === "check" || type === "checkbox" || type === "radio") {
        const shouldCheck = ["1", "true", "yes", "on", "checked", value].includes(value.toLowerCase()) || Boolean(value);
        el.checked = shouldCheck;
        dispatchInputEvents(el);
        return { ok: true, id, action: "check", value: String(shouldCheck) };
      }

      if (tag === "select" || action === "select") {
        const options = Array.from(el.options || []);
        const exact = options.find((opt) => opt.value === value || opt.text.trim() === value.trim());
        const loose = exact || options.find((opt) => opt.text.toLowerCase().includes(value.toLowerCase()));
        if (loose) {
          setNativeValue(el, loose.value);
        } else {
          setNativeValue(el, value);
        }
        dispatchInputEvents(el);
        return { ok: true, id, action: "select", value };
      }

      setNativeValue(el, value);
      dispatchInputEvents(el);
      return { ok: true, id, action: "fill", valuePreview: value.slice(0, 120) };
    } catch (err) {
      return { ok: false, id, error: err && err.message ? err.message : String(err) };
    }
  }


  function notifyPageReady() {
    try {
      chrome.runtime.sendMessage({
        type: MESSAGE_TYPES.PAGE_READY,
        url: location.href,
        title: document.title || ""
      });
    } catch (_) {
      // Background may not be ready on restricted pages. Ignore.
    }
  }

  // Ask the background worker to auto-load the latest Python queue item and
  // fill this page using the last saved profile. Use two delayed pings to help
  // React/SPA forms that render fields shortly after document_idle.
  setTimeout(notifyPageReady, 700);
  setTimeout(notifyPageReady, 2500);

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || !message.type) return false;

    if (message.type === MESSAGE_TYPES.SCAN_FIELDS) {
      sendResponse({ ok: true, url: location.href, fields: scanFields() });
      return true;
    }

    if (message.type === MESSAGE_TYPES.FILL_FIELDS) {
      const rules = Array.isArray(message.rules) ? message.rules : [];
      const results = rules.map(fillElementById);
      const okCount = results.filter((r) => r.ok).length;
      sendResponse({ ok: true, url: location.href, okCount, total: results.length, results });
      return true;
    }

    return false;
  });
})();
