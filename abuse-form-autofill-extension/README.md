# Abuse Form Autofill Extension

This extension reads notice payloads from the Python GUI queue and fills abuse forms using saved profiles.

## Auto-fill on page load

When an abuse form page loads, the extension will automatically:

1. Load the latest Python queue item from the bridge.
2. Select the last used profile if its `url_match` matches the current page.
3. If the last profile does not match, select a saved profile that matches the current URL.
4. Fill the form using the profile rules.

The profile can contain:

- `source: "fixed"` for values saved in the profile, such as name, email, company, category.
- `source: "generated"` for values from Python queue, such as `notice_text`, `domain`, `action_url_list`.
- `source: "template"` for mixed values, such as `IP rights infringement - {{domain}}`.

## First-time setup

1. Open the abuse form page.
2. Open the extension popup.
3. Scan fields.
4. Create or select a profile.
5. Add rules for each input id.
6. Save the profile.

After that, queue a new case from Python and open/reload the abuse form page. The extension fills automatically.

## Manual mode

Open the popup and click `Manual: latest queue + last profile + fill` if needed.
