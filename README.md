# Notice Python + Extension Bridge - Auto Fill On Page Load

This package contains:

- `notice-data-printer/` - Python GUI that generates notice data and queues it to the local bridge.
- `abuse-form-autofill-extension/` - Chrome extension that can auto-fill the current abuse form.

## New behavior

After you save a profile once, the extension can automatically fill the page when the abuse form loads:

1. Python GUI renders the notice.
2. Click **Queue mapped** in the Python GUI.
3. Open/reload the abuse form page.
4. The extension content script notifies the background worker.
5. Background worker loads the latest queue item from `http://127.0.0.1:8765`.
6. Background worker chooses the last used profile if it matches the current URL; otherwise it falls back to a profile whose URL pattern matches the current page.
7. It fills fixed, generated, and template/mixed rules automatically.

No popup button is required for normal use.

## Safety rule

Auto-fill only runs when a saved profile matches the current page URL. This avoids filling random pages with the previously used profile.

## Disable auto-fill

Open the extension popup and uncheck:

`Auto-fill on page load using latest queue + last used profile`

## Manual fallback

The popup still has a manual button:

`Manual: latest queue + last profile + fill`

Use it when a form renders late or if you want to test a profile manually.
