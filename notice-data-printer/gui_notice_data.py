#!/usr/bin/env python3
"""Tkinter GUI for rendering Lilly notice data before extension autofill.

Run:
  python gui_notice_data.py
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:  # pragma: no cover
    print("Tkinter is not available in this Python installation.", file=sys.stderr)
    raise

try:  # Pillow is used only for the optional image preview tab.
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - GUI still works without Pillow
    Image = None
    ImageTk = None

try:
    import print_notice_data as engine
except BaseException as exc:  # catches SystemExit from missing tldextract too
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Cannot start GUI",
        "Could not load print_notice_data.py.\n\n"
        "Most common fix:\n"
        "  pip install -r requirements.txt\n\n"
        f"Details:\n{exc}",
    )
    raise SystemExit(1)

try:
    import bridge_server
except Exception:
    bridge_server = None

APP_TITLE = "Notice Data Printer GUI"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
PLACEHOLDER_TAG = "placeholder"


def split_lines(text: str) -> List[str]:
    """Return non-empty, non-comment lines from a textarea."""
    items: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


DEFAULT_VALUE_KEYS = [
    "domain",
    "hostname",
    "host",
    "seller_hostname",
    "url",
    "urls",
    "first_url",
    "action_urls",
    "homepage_url",
    "url_list",
    "action_url_list",
    "user",
    "claims_text",
    "name_on_product_label",
    "domain_label",
    "recipient_type",
    "platform",
]

DEFAULT_PLACEHOLDERS = [
    "[DOMAIN]",
    "DOMAIN",
    "[USER]",
    "[the seller]",
    "[NAME ON PRODUCT LABEL]",
    "[CLAIM OR CLAIMS MADE IN POST IN BULLETED LIST]",
    "[CLAIM OR CLAIMS MADE IN POST IN BULLETED LIST, INCLUDING PICTURE OF VIAL WITH TELEHEALTH NAME]",
    "[LIST URL FOR SPECIFIC ACTION]",
    "[LIST URLs FOR SPECIFIC ACTION]",
]


def split_csv(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"[,\n]", text or "") if part.strip()]


def normalize_mapping_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a placeholder-map rule.

    Supported shapes:
      {"[DOMAIN]": "hehe.com"}
      {"placeholder": "[DOMAIN]", "value_template": "hehe.com", "enabled": true}
    """
    if not isinstance(rule, dict):
        return {"enabled": True, "placeholder": "", "value_template": "", "note": ""}
    if "placeholder" in rule or "key" in rule:
        placeholder = str(rule.get("placeholder") or rule.get("key") or "").strip()
        value = rule.get("value_template", rule.get("value", rule.get("replacement", "")))
        enabled = bool(rule.get("enabled", True))
        note = str(rule.get("note", ""))
    else:
        pairs = [(k, v) for k, v in rule.items() if k not in {"enabled", "note"}]
        if pairs:
            placeholder, value = pairs[0]
            placeholder = str(placeholder).strip()
        else:
            placeholder, value = "", ""
        enabled = bool(rule.get("enabled", True))
        note = str(rule.get("note", ""))
    return {
        "enabled": enabled,
        "placeholder": placeholder,
        "value_template": "" if value is None else str(value),
        "note": note,
    }


def compact_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Save enabled placeholder rules close to the user's requested JSON shape."""
    output: List[Dict[str, str]] = []
    for raw in rules:
        rule = normalize_mapping_rule(raw)
        if not rule.get("enabled", True):
            continue
        placeholder = rule.get("placeholder", "").strip()
        if placeholder:
            output.append({placeholder: rule.get("value_template", "")})
    return output


class RuleEditorDialog(tk.Toplevel):
    """Small modal editor for one placeholder-map rule."""

    def __init__(self, parent: tk.Tk, title: str, rule: Optional[Dict[str, Any]], value_keys: List[str]) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("680x360")
        self.minsize(620, 320)
        self.transient(parent)
        self.grab_set()
        self.result: Optional[Dict[str, Any]] = None

        rule = normalize_mapping_rule(rule or {})
        self.enabled_var = tk.BooleanVar(value=bool(rule.get("enabled", True)))
        self.placeholder_var = tk.StringVar(value=rule.get("placeholder", "[DOMAIN]"))
        self.insert_key_var = tk.StringVar(value=value_keys[0] if value_keys else "domain")
        self.note_var = tk.StringVar(value=rule.get("note", ""))
        self.value_keys = value_keys or DEFAULT_VALUE_KEYS

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        ttk.Checkbutton(outer, text="Enabled", variable=self.enabled_var).grid(row=0, column=0, sticky="w", pady=(0, 8))

        ttk.Label(outer, text="Placeholder").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        placeholder_box = ttk.Combobox(outer, textvariable=self.placeholder_var, values=DEFAULT_PLACEHOLDERS, width=42)
        placeholder_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Label(outer, text="Example: [DOMAIN], [USER], [NAME ON PRODUCT LABEL], or any exact text in the template.").grid(
            row=2, column=1, columnspan=3, sticky="w", pady=(0, 8)
        )

        ttk.Label(outer, text="Value").grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=4)
        value_frame = ttk.Frame(outer)
        value_frame.grid(row=3, column=1, columnspan=3, sticky="nsew", pady=4)
        value_frame.columnconfigure(0, weight=1)
        self.value_text = tk.Text(value_frame, height=5, wrap="word", font=("Consolas", 10), padx=6, pady=6)
        self.value_text.grid(row=0, column=0, columnspan=3, sticky="nsew")
        self.value_text.insert("1.0", str(rule.get("value_template", "")))
        ttk.Label(value_frame, text="Insert auto value:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(value_frame, textvariable=self.insert_key_var, values=self.value_keys, state="readonly", width=28).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Button(value_frame, text="Insert {{value}}", command=self.insert_value_key).grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(6, 0))

        ttk.Label(outer, text="Note").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(outer, textvariable=self.note_var).grid(row=4, column=1, columnspan=3, sticky="ew", pady=4)

        button_row = ttk.Frame(outer)
        button_row.grid(row=5, column=0, columnspan=4, sticky="e", pady=(14, 0))
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(button_row, text="Save rule", command=self.save_rule).pack(side="right", padx=(0, 8))

        outer.rowconfigure(3, weight=1)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-Return>", lambda _event: self.save_rule())
        self.wait_visibility()
        self.focus_set()

    def insert_value_key(self) -> None:
        key = self.insert_key_var.get().strip()
        if key:
            self.value_text.insert("insert", "{{" + key + "}}")
            self.value_text.focus_set()

    def save_rule(self) -> None:
        placeholder = self.placeholder_var.get().strip()
        value_template = self.value_text.get("1.0", "end").strip()
        if not placeholder:
            messagebox.showwarning("Missing placeholder", "Placeholder is required.", parent=self)
            return
        if not value_template:
            messagebox.showwarning("Missing value", "Value is required. Empty values are skipped so placeholders stay visible.", parent=self)
            return
        self.result = {
            "enabled": bool(self.enabled_var.get()),
            "placeholder": placeholder,
            "value_template": value_template,
            "note": self.note_var.get().strip(),
        }
        self.destroy()


class NoticeGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.last_payload: Optional[Dict[str, Any]] = None
        self.last_builtin_payload: Optional[Dict[str, Any]] = None
        self.last_raw_payload: Optional[Dict[str, Any]] = None
        self.case_path: Optional[Path] = None
        self._render_after_id: Optional[str] = None
        self._image_after_id: Optional[str] = None

        self.template_var = tk.StringVar(value="unapproved_retatrutide")
        self.domain_var = tk.StringVar()
        self.user_var = tk.StringVar()
        self.name_on_label_var = tk.StringVar()
        self.ascii_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        self.image_folder_var = tk.StringVar()
        self.image_code_var = tk.StringVar()
        self.image_recursive_var = tk.BooleanVar(value=False)
        self.image_status_var = tk.StringVar(value="No image check yet")
        self.image_results: List[Path] = []
        self.image_preview_ref: Any = None

        self.mapping_name_var = tk.StringVar(value="Untitled placeholder map")
        self.mapping_match_var = tk.StringVar()
        self.mapping_status_var = tk.StringVar(value="No mapping profile loaded")
        self.mapping_rules: List[Dict[str, Any]] = []
        self.mapping_path: Optional[Path] = None

        # Separate module: Raw rules JSON is edited directly and does not sync
        # with the Add/Edit UI in the Placeholder map tab.
        self.raw_json_rules: List[Dict[str, Any]] = []
        self.raw_json_error_var = tk.StringVar(value="Raw rules JSON: ready")

        # Extension bridge state. These must be created before _build_ui(),
        # because the bridge panel binds Entry/Checkbutton/Label widgets to them.
        self.bridge_port_var = tk.StringVar(value="8765")
        self.bridge_auto_var = tk.BooleanVar(value=False)
        self.bridge_status_var = tk.StringVar(value="Bridge not started")
        self._last_bridge_signature = ""

        self._build_ui()
        self._load_templates()
        self._refresh_mapping_tree()
        self._bind_realtime_rendering()
        self._schedule_render()
        self._schedule_image_check()
        self.start_bridge_server(silent=True)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        paned = ttk.PanedWindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 10, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=2)

        # Template row
        template_frame = ttk.LabelFrame(left, text="1) Template")
        template_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(template_frame, text="Template:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.template_combo = ttk.Combobox(
            template_frame,
            textvariable=self.template_var,
            state="readonly",
            values=[],
            width=28,
        )
        self.template_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(template_frame, text="Open template", command=self.open_template_file).grid(
            row=0, column=2, sticky="e", padx=8, pady=8
        )
        template_frame.columnconfigure(1, weight=1)

        # URLs input
        urls_frame = ttk.LabelFrame(left, text="2) URLs")
        urls_frame.pack(fill="both", expand=True, pady=(0, 8))

        url_btns = ttk.Frame(urls_frame)
        url_btns.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(url_btns, text="Load urls.txt", command=self.load_urls_file).pack(side="left")
        ttk.Button(url_btns, text="Clear URLs", command=lambda: self._replace_text(self.urls_text, "")).pack(side="left", padx=6)
        ttk.Label(url_btns, text="Realtime preview. One URL per line. Blank lines and # comments are ignored.").pack(side="left", padx=8)

        self.urls_text = tk.Text(urls_frame, height=9, wrap="none", undo=True)
        self.urls_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.urls_text.insert("1.0", "https://mounjarosa.co.za\n")

        # Claims input
        claims_frame = ttk.LabelFrame(left, text="3) Claims / evidence lines")
        claims_frame.pack(fill="both", expand=True, pady=(0, 8))

        claim_btns = ttk.Frame(claims_frame)
        claim_btns.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(claim_btns, text="Load claims.txt", command=self.load_claims_file).pack(side="left")
        ttk.Button(claim_btns, text="Clear claims", command=lambda: self._replace_text(self.claims_text, "")).pack(side="left", padx=6)
        ttk.Label(claim_btns, text="Optional. Blank keeps [CLAIM...] visible.").pack(side="left", padx=8)

        self.claims_text = tk.Text(claims_frame, height=7, wrap="word", undo=True)
        self.claims_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Extra fields
        fields_frame = ttk.LabelFrame(left, text="4) Optional fields")
        fields_frame.pack(fill="x", pady=(0, 8))

        self._field(fields_frame, 0, "Domain override", self.domain_var)

        ttk.Label(fields_frame, text="User / seller override").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(fields_frame, textvariable=self.user_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(fields_frame, text="Blank = hostname from first URL; no URL = [USER]").grid(
            row=2, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )

        self._field(fields_frame, 3, "Name on label", self.name_on_label_var)
        ttk.Label(fields_frame, text="Blank keeps [NAME ON PRODUCT LABEL] visible").grid(
            row=4, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4)
        )
        ttk.Checkbutton(fields_frame, text="Convert smart quotes/dashes to ASCII", variable=self.ascii_var).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 8)
        )
        fields_frame.columnconfigure(1, weight=1)

        # Image file checker
        image_frame = ttk.LabelFrame(left, text="5) Image file check")
        image_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(image_frame, text="Folder prefix").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(image_frame, textvariable=self.image_folder_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(image_frame, text="Browse", command=self.browse_image_folder).grid(row=0, column=2, sticky="e", padx=8, pady=4)

        ttk.Label(image_frame, text="File code / suffix").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(image_frame, textvariable=self.image_code_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(image_frame, text="Realtime: <folder>/<code>.*").grid(row=1, column=2, sticky="e", padx=8, pady=4)

        ttk.Checkbutton(image_frame, text="Search subfolders", variable=self.image_recursive_var).grid(
            row=2, column=0, sticky="w", padx=8, pady=(4, 8)
        )
        ttk.Label(image_frame, textvariable=self.image_status_var).grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        image_frame.columnconfigure(1, weight=1)

        # Extension bridge: Python queues generated payloads; Chrome extension pulls them.
        bridge_frame = ttk.LabelFrame(left, text="6) Extension bridge queue")
        bridge_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(bridge_frame, text="Local bridge URL").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(bridge_frame, textvariable=self.bridge_port_var, width=8).grid(row=0, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(bridge_frame, text="port on 127.0.0.1").grid(row=0, column=2, sticky="w", padx=0, pady=4)
        ttk.Button(bridge_frame, text="Start bridge", command=lambda: self.start_bridge_server(silent=False)).grid(row=0, column=3, sticky="e", padx=8, pady=4)
        ttk.Button(bridge_frame, text="Queue mapped", command=self.queue_mapped_to_extension).grid(row=1, column=0, sticky="w", padx=8, pady=(4, 8))
        ttk.Checkbutton(bridge_frame, text="Auto queue on preview update", variable=self.bridge_auto_var).grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        ttk.Label(bridge_frame, textvariable=self.bridge_status_var).grid(row=1, column=3, sticky="e", padx=8, pady=(4, 8))
        bridge_frame.columnconfigure(3, weight=1)

        # Action buttons. Render is automatic; these buttons are for I/O only.
        actions = ttk.Frame(left)
        actions.pack(fill="x")
        ttk.Button(actions, text="Load case JSON", command=self.load_case_json).pack(side="left")
        ttk.Button(actions, text="Save JSON", command=self.save_json).pack(side="left", padx=6)
        ttk.Button(actions, text="Save mapped TXT", command=self.save_text).pack(side="left")

        copy_actions = ttk.Frame(left)
        copy_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(copy_actions, text="Copy mapped", command=self.copy_notice).pack(side="left")
        ttk.Button(copy_actions, text="Copy built-in", command=self.copy_builtin_notice).pack(side="left", padx=6)
        ttk.Button(copy_actions, text="Copy JSON", command=self.copy_json).pack(side="left")
        ttk.Button(copy_actions, text="Clear all", command=self.clear_all).pack(side="left")

        # Output tabs
        output_frame = ttk.LabelFrame(right, text="Preview")
        output_frame.pack(fill="both", expand=True)

        self.tabs = ttk.Notebook(output_frame)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)

        # Use modern, Unicode-capable fonts and add padding so the preview is readable.
        self.notice_text = tk.Text(self.tabs, wrap="word", undo=True, font=("Segoe UI", 10), padx=8, pady=8)
        self.json_text = tk.Text(self.tabs, wrap="none", undo=True, font=("Consolas", 10), padx=8, pady=8)
        self.values_text = tk.Text(self.tabs, wrap="none", undo=True, font=("Consolas", 10), padx=8, pady=8)
        self.notice_text.tag_configure(PLACEHOLDER_TAG, background="#fff3a3")

        self.image_tab = ttk.Frame(self.tabs, padding=8)
        self.image_paths_text = tk.Text(self.image_tab, height=8, wrap="none", undo=True, font=("Consolas", 10), padx=8, pady=8)
        self.image_paths_text.pack(fill="x", expand=False)

        image_actions = ttk.Frame(self.image_tab)
        image_actions.pack(fill="x", pady=(6, 6))
        ttk.Button(image_actions, text="Copy found paths", command=self.copy_image_paths).pack(side="left")
        ttk.Button(image_actions, text="Open first file", command=self.open_first_image_file).pack(side="left", padx=6)

        self.image_preview_label = ttk.Label(self.image_tab, text="Image preview will appear here when the first matched file is an image.", anchor="center")
        self.image_preview_label.pack(fill="both", expand=True)

        # User-defined placeholder-map rules. These rules replace exact
        # template placeholders such as [DOMAIN] or [USER]. Non-empty JSON rules
        # have priority; built-in domain/hostname/name-on-label rules are fallback.
        self.mapping_tab = ttk.Frame(self.tabs, padding=8)
        profile_frame = ttk.LabelFrame(self.mapping_tab, text="Placeholder rules")
        profile_frame.pack(fill="x", pady=(0, 8))
        profile_frame.columnconfigure(0, weight=1)
        ttk.Label(
            profile_frame,
            text="This module uses Add/Edit rule buttons. It is separate from the Raw rules JSON tab. Notice text tab stays built-in; the result below applies these UI rules.",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Button(profile_frame, text="Clear rules", command=self.clear_mapping_rules).grid(row=0, column=1, sticky="e", padx=8, pady=6)

        builtin_frame = ttk.LabelFrame(self.mapping_tab, text="Built-in auto values")
        builtin_frame.pack(fill="x", pady=(0, 8))
        self.builtin_values_text = tk.Text(builtin_frame, height=5, wrap="none", undo=True, font=("Consolas", 10), padx=8, pady=8)
        self.builtin_values_text.pack(fill="x", expand=False)

        rules_frame = ttk.LabelFrame(self.mapping_tab, text="User rules: exact placeholder → value")
        rules_frame.pack(fill="both", expand=True, pady=(0, 8))
        columns = ("enabled", "placeholder", "value")
        self.mapping_tree = ttk.Treeview(rules_frame, columns=columns, show="headings", selectmode="browse", height=8)
        headers = {"enabled": "On", "placeholder": "Placeholder", "value": "Value"}
        widths = {"enabled": 42, "placeholder": 230, "value": 520}
        for col in columns:
            self.mapping_tree.heading(col, text=headers[col])
            self.mapping_tree.column(col, width=widths[col], anchor="w", stretch=True)
        self.mapping_tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(rules_frame, orient="vertical", command=self.mapping_tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.mapping_tree.configure(yscrollcommand=tree_scroll.set)
        self.mapping_tree.bind("<Double-1>", lambda _event: self.edit_selected_rule())

        rule_buttons = ttk.Frame(self.mapping_tab)
        rule_buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(rule_buttons, text="Add rule", command=self.add_mapping_rule).pack(side="left")
        ttk.Button(rule_buttons, text="Edit", command=self.edit_selected_rule).pack(side="left", padx=4)
        ttk.Button(rule_buttons, text="Duplicate", command=self.duplicate_selected_rule).pack(side="left")
        ttk.Button(rule_buttons, text="Delete", command=self.delete_selected_rule).pack(side="left", padx=4)
        ttk.Button(rule_buttons, text="Move up", command=lambda: self.move_selected_rule(-1)).pack(side="left")
        ttk.Button(rule_buttons, text="Move down", command=lambda: self.move_selected_rule(1)).pack(side="left", padx=4)
        ttk.Label(rule_buttons, textvariable=self.mapping_status_var).pack(side="right")

        bottom_pane = ttk.PanedWindow(self.mapping_tab, orient="vertical")
        bottom_pane.pack(fill="both", expand=True)

        preview_frame = ttk.LabelFrame(bottom_pane, text="Resolved rule preview")
        self.mapping_preview_text = tk.Text(preview_frame, height=6, wrap="none", undo=True, font=("Consolas", 10), padx=8, pady=8)
        self.mapping_preview_text.pack(fill="both", expand=True)
        bottom_pane.add(preview_frame, weight=1)

        result_frame = ttk.LabelFrame(bottom_pane, text="Notice result after applying placeholder map")
        result_header = ttk.Frame(result_frame)
        result_header.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(result_header, text="This result uses only the Placeholder map rules from this tab plus built-in fallback.").pack(side="left")
        ttk.Button(result_header, text="Copy mapped notice", command=self.copy_mapped_notice).pack(side="right")
        self.mapping_result_text = tk.Text(result_frame, height=12, wrap="word", undo=True, font=("Segoe UI", 10), padx=8, pady=8)
        self.mapping_result_text.tag_configure(PLACEHOLDER_TAG, background="#fff3a3")
        self.mapping_result_text.pack(fill="both", expand=True, padx=4, pady=4)
        bottom_pane.add(result_frame, weight=3)

        self.mapping_json_tab = ttk.Frame(self.tabs, padding=8)
        json_help = ttk.Frame(self.mapping_json_tab)
        json_help.pack(fill="x", pady=(0, 6))
        ttk.Label(
            json_help,
            text="Raw rules JSON module. Edit JSON here; this module has its own result preview below and does not sync with Placeholder map.",
        ).pack(side="left")
        ttk.Label(json_help, textvariable=self.raw_json_error_var).pack(side="right")

        raw_json_pane = ttk.PanedWindow(self.mapping_json_tab, orient="vertical")
        raw_json_pane.pack(fill="both", expand=True)

        raw_editor_frame = ttk.LabelFrame(raw_json_pane, text="Raw rules JSON only")
        self.mapping_json_text = tk.Text(raw_editor_frame, wrap="none", undo=True, font=("Consolas", 10), padx=8, pady=8)
        self.mapping_json_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.mapping_json_text.insert("1.0", "{}")
        self.mapping_json_text.edit_modified(False)
        raw_json_pane.add(raw_editor_frame, weight=1)

        raw_result_frame = ttk.LabelFrame(raw_json_pane, text="Notice result after applying Raw rules JSON")
        raw_result_header = ttk.Frame(raw_result_frame)
        raw_result_header.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(raw_result_header, text="This preview uses only the JSON rules above plus built-in fallback.").pack(side="left")
        ttk.Button(raw_result_header, text="Copy raw JSON result", command=self.copy_raw_json_notice).pack(side="right")
        self.raw_json_result_text = tk.Text(raw_result_frame, height=12, wrap="word", undo=True, font=("Segoe UI", 10), padx=8, pady=8)
        self.raw_json_result_text.tag_configure(PLACEHOLDER_TAG, background="#fff3a3")
        self.raw_json_result_text.pack(fill="both", expand=True, padx=4, pady=4)
        raw_json_pane.add(raw_result_frame, weight=2)

        self.tabs.add(self.notice_text, text="Notice text (built-in)")
        self.tabs.add(self.json_text, text="Full JSON payload")
        self.tabs.add(self.values_text, text="Fill values only")
        self.tabs.add(self.mapping_tab, text="Placeholder map")
        self.tabs.add(self.mapping_json_tab, text="Raw rules JSON")
        self.tabs.add(self.image_tab, text="Image check")

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(8, 0))
        ttk.Label(status, textvariable=self.status_var).pack(side="left")

    def _field(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8, pady=4)

    def _bind_realtime_rendering(self) -> None:
        for var in (
            self.template_var,
            self.domain_var,
            self.user_var,
            self.name_on_label_var,
            self.ascii_var,
            self.mapping_name_var,
            self.mapping_match_var,
        ):
            var.trace_add("write", lambda *_: self._schedule_render())

        for var in (self.image_folder_var, self.image_code_var, self.image_recursive_var):
            var.trace_add("write", lambda *_: self._schedule_image_check())

        self.urls_text.bind("<<Modified>>", self._on_input_text_modified)
        self.claims_text.bind("<<Modified>>", self._on_input_text_modified)
        self.mapping_json_text.bind("<<Modified>>", self._on_mapping_json_modified)
        self.urls_text.edit_modified(False)
        self.claims_text.edit_modified(False)
        self.mapping_json_text.edit_modified(False)

    def _on_input_text_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if isinstance(widget, tk.Text) and widget.edit_modified():
            widget.edit_modified(False)
            self._schedule_render()

    def _on_mapping_json_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Text) or not widget.edit_modified():
            return
        widget.edit_modified(False)
        raw = widget.get("1.0", "end").strip()
        if not raw:
            self.raw_json_rules = []
            self.raw_json_error_var.set("Raw rules JSON: empty = no raw rules")
            self._schedule_render()
            return
        try:
            obj = json.loads(raw)
            rules_source = self._raw_json_to_rules_source(obj)
            self.raw_json_rules = [normalize_mapping_rule(rule) for rule in engine.normalize_placeholder_rules(rules_source)]
            self.raw_json_error_var.set(f"Raw rules JSON: {len(self.raw_json_rules)} valid rule(s)")
            self._schedule_render()
        except Exception as exc:
            # Keep the last valid raw rule set while the user is midway through typing.
            self.raw_json_error_var.set("Raw rules JSON error: " + str(exc))
            self.status_var.set("Raw rules JSON error: " + str(exc))

    def _raw_json_to_rules_source(self, obj: Any) -> Any:
        # Preferred raw shape is just the rules object:
        #   {"[DOMAIN]": "hehe.com", "[USER]": "hehe"}
        # Also accept list style and old wrapper profiles for compatibility.
        if isinstance(obj, dict) and any(key in obj for key in ("rules", "placeholder_rules", "placeholder_map")):
            return obj.get("rules") or obj.get("placeholder_rules") or obj.get("placeholder_map") or []
        return obj

    def _sync_mapping_json_from_rules(self) -> None:
        """Deprecated: Placeholder map and Raw rules JSON are separate modules."""
        return

    def _schedule_render(self) -> None:
        if self._render_after_id:
            self.after_cancel(self._render_after_id)
        self._render_after_id = self.after(350, self.render)

    def _schedule_image_check(self) -> None:
        if self._image_after_id:
            self.after_cancel(self._image_after_id)
        self._image_after_id = self.after(350, self.check_image_files_silent)

    def _replace_text(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.edit_modified(False)
        self._schedule_render()

    def _load_templates(self) -> None:
        templates = sorted(p.stem for p in engine.TEMPLATE_DIR.glob("*.txt"))
        self.template_combo.configure(values=templates)
        if self.template_var.get() not in templates and templates:
            self.template_var.set(templates[0])

    def _args_namespace(self) -> SimpleNamespace:
        urls = split_lines(self.urls_text.get("1.0", "end"))
        claims = split_lines(self.claims_text.get("1.0", "end"))
        return SimpleNamespace(
            template=self.template_var.get(),
            case=None,
            url=urls,
            urls_file=None,
            domain=self.domain_var.get().strip() or None,
            user=self.user_var.get().strip() or None,
            claim=claims,
            claims_file=None,
            name_on_label=self.name_on_label_var.get().strip() or None,
            recipient_type=None,
            platform=None,
            ascii=self.ascii_var.get(),
            format="json",
            save_json=None,
            save_text=None,
            list_templates=False,
        )

    def render(self) -> None:
        self._render_after_id = None
        try:
            args = self._args_namespace()
            base_data = engine.build_case_data(args, None, allow_missing_url=True)

            # Built-in preview: this is the stable/original template result.
            # User JSON rules are intentionally ignored here so the Notice text tab
            # always shows the hard-template fallback output.
            builtin_data = copy.deepcopy(base_data)
            builtin_data["placeholder_rules"] = []
            builtin_data["placeholder_profile_name"] = "Built-in only"
            builtin_data["template_match"] = builtin_data.get("source_template_file", "")
            builtin_payload = engine.render_payload(builtin_data)

            # Placeholder-map preview: rules from the Add/Edit UI only.
            mapped_data = copy.deepcopy(base_data)
            mapped_data["placeholder_rules"] = [normalize_mapping_rule(rule) for rule in self.mapping_rules]
            mapped_data["placeholder_profile_name"] = self.mapping_name_var.get().strip() or "Untitled placeholder map"
            mapped_data["template_match"] = self.mapping_match_var.get().strip() or mapped_data.get("source_template_file", "")
            payload = engine.render_payload(mapped_data)
            payload["rendered"]["builtin_notice_text"] = builtin_payload["rendered"]["notice_text"]
            payload["rendered"]["placeholder_map_notice_text"] = payload["rendered"]["notice_text"]
            payload["builtin_unresolved_placeholders"] = builtin_payload.get("unresolved_placeholders", [])
            self._attach_mapping_to_payload(payload)

            # Raw JSON preview: rules typed directly in the Raw rules JSON tab only.
            raw_data = copy.deepcopy(base_data)
            raw_data["placeholder_rules"] = [normalize_mapping_rule(rule) for rule in self.raw_json_rules]
            raw_data["placeholder_profile_name"] = "Raw rules JSON"
            raw_data["template_match"] = raw_data.get("source_template_file", "")
            raw_payload = engine.render_payload(raw_data)
            raw_payload["rendered"]["builtin_notice_text"] = builtin_payload["rendered"]["notice_text"]
            raw_payload["rendered"]["raw_rules_notice_text"] = raw_payload["rendered"]["notice_text"]
            self._attach_raw_json_to_payload(payload, raw_payload)

            self.last_builtin_payload = builtin_payload
            self.last_payload = payload
            self.last_raw_payload = raw_payload
            self._set_output(payload)
            self._maybe_auto_queue(payload)
            unresolved = payload.get("unresolved_placeholders") or []
            if unresolved:
                self.status_var.set("Mapped preview updated. Missing fields: " + ", ".join(unresolved))
            else:
                self.status_var.set(
                    f"Preview updated: {payload['case_data']['action_url_count']} action URL(s) for {payload['case_data']['domain']}"
                )
        except BaseException as exc:
            self.last_payload = None
            self.last_builtin_payload = None
            self.status_var.set("Preview error: " + str(exc))
            self._set_error_output(exc)

    def _set_error_output(self, exc: BaseException) -> None:
        text = f"Render failed:\n{exc}\n\n{traceback.format_exc(limit=2)}"
        widgets = [self.notice_text, self.json_text, self.values_text]
        if hasattr(self, "mapping_result_text"):
            widgets.append(self.mapping_result_text)
        if hasattr(self, "raw_json_result_text"):
            widgets.append(self.raw_json_result_text)
        for widget in widgets:
            widget.delete("1.0", "end")
            widget.insert("1.0", text)

    def _clean_display_text(self, value: str) -> str:
        # Extra guard for cases/templates that already contain visible \u2019-style escapes.
        cleaner = getattr(engine, "decode_unicode_escape_sequences", None)
        return cleaner(value) if cleaner else value

    def _set_output(self, payload: Dict[str, Any]) -> None:
        # Notice tab intentionally shows built-in/hard-template output only.
        notice = self._clean_display_text(payload["rendered"].get("builtin_notice_text") or payload["rendered"]["notice_text"])
        full_json = self._clean_display_text(json.dumps(payload, ensure_ascii=False, indent=2))
        fill_values = self._clean_display_text(json.dumps(payload["extension_payload"]["fill_values"], ensure_ascii=False, indent=2))

        for widget, value in (
            (self.notice_text, notice),
            (self.json_text, full_json),
            (self.values_text, fill_values),
        ):
            widget.delete("1.0", "end")
            widget.insert("1.0", value)

        self._set_mapping_preview(payload)
        if self.last_raw_payload is not None:
            self._set_raw_json_preview(self.last_raw_payload)
        self._highlight_notice_placeholders()

    def _highlight_notice_placeholders(self) -> None:
        """Highlight only unresolved workflow placeholders, not quote brackets.

        Templates contain legal/editorial brackets such as [C]ompanies and th[e].
        Those should not look like missing fields. The engine reports the real
        unresolved placeholders, e.g. [DOMAIN], [USER], [the seller], or [CLAIM...].
        """
        self.notice_text.tag_remove(PLACEHOLDER_TAG, "1.0", "end")
        unresolved = []
        if self.last_builtin_payload:
            unresolved = self.last_builtin_payload.get("unresolved_placeholders") or []
        for placeholder in unresolved:
            if not placeholder.startswith("["):
                continue
            start = "1.0"
            while True:
                pos = self.notice_text.search(placeholder, start, "end")
                if not pos:
                    break
                close_end = self.notice_text.index(f"{pos}+{len(placeholder)}c")
                self.notice_text.tag_add(PLACEHOLDER_TAG, pos, close_end)
                start = close_end

    def _mapping_value_keys(self) -> List[str]:
        keys = list(DEFAULT_VALUE_KEYS)
        if self.last_payload:
            fill_values = self.last_payload.get("extension_payload", {}).get("fill_values", {})
            for key in fill_values:
                if key not in keys:
                    keys.append(key)
        return keys

    def _template_match_value(self) -> str:
        explicit = self.mapping_match_var.get().strip()
        if explicit:
            return explicit
        template_id = self.template_var.get().strip()
        if template_id:
            return str(engine.TEMPLATE_DIR / f"{template_id}.txt")
        return ""

    def _mapping_profile(self) -> Dict[str, Any]:
        return {
            "profile_name": self.mapping_name_var.get().strip() or "Untitled placeholder map",
            "template_match": self._template_match_value(),
            "rules": compact_rules(self.mapping_rules),
        }

    def _verbose_mapping_profile(self) -> Dict[str, Any]:
        return {
            "profile_name": self.mapping_name_var.get().strip() or "Untitled placeholder map",
            "template_match": self._template_match_value(),
            "rules": [normalize_mapping_rule(rule) for rule in self.mapping_rules],
        }

    def _render_template_value(self, template: str, fill_values: Dict[str, Any]) -> str:
        """Render {{key}} placeholders for placeholder-map values.

        Missing keys are kept as {{key}} so a broken rule is easy to spot.
        Lists are joined one item per line because URLs usually need multiline output.
        """
        def stringify(value: Any) -> str:
            if isinstance(value, list):
                return "\n".join(str(item) for item in value)
            if value is None:
                return ""
            return str(value)

        def repl(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key not in fill_values:
                return "{{" + key + "}}"
            return stringify(fill_values[key])

        return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", repl, template or "")

    def _resolved_mapping_rules(self, fill_values: Dict[str, Any]) -> List[Dict[str, Any]]:
        resolved: List[Dict[str, Any]] = []
        for idx, raw_rule in enumerate(self.mapping_rules, start=1):
            rule = normalize_mapping_rule(raw_rule)
            value = self._render_template_value(rule.get("value_template", ""), fill_values)
            resolved.append({
                "order": idx,
                "enabled": rule.get("enabled", True),
                "placeholder": rule.get("placeholder", ""),
                "value_template": rule.get("value_template", ""),
                "value": value,
                "note": rule.get("note", ""),
            })
        return resolved

    def _attach_mapping_to_payload(self, payload: Dict[str, Any]) -> None:
        fill_values = payload.get("extension_payload", {}).get("fill_values", {})
        mapped_rules = self._resolved_mapping_rules(fill_values)
        payload["extension_payload"]["placeholder_profile"] = self._mapping_profile()
        payload["extension_payload"]["placeholder_profile_verbose"] = self._verbose_mapping_profile()
        payload["extension_payload"]["resolved_placeholder_rules"] = mapped_rules
        payload["extension_payload"]["enabled_placeholder_rules"] = [rule for rule in mapped_rules if rule.get("enabled")]

    def _attach_raw_json_to_payload(self, payload: Dict[str, Any], raw_payload: Dict[str, Any]) -> None:
        raw_fill_values = raw_payload.get("extension_payload", {}).get("fill_values", {})
        raw_rules = []
        for idx, raw_rule in enumerate(self.raw_json_rules, start=1):
            rule = normalize_mapping_rule(raw_rule)
            value = self._render_template_value(rule.get("value_template", ""), raw_fill_values)
            raw_rules.append({
                "order": idx,
                "enabled": rule.get("enabled", True),
                "placeholder": rule.get("placeholder", ""),
                "value_template": rule.get("value_template", ""),
                "value": value,
                "note": rule.get("note", ""),
            })
        payload["extension_payload"]["raw_rules_json"] = {
            "rules": compact_rules(self.raw_json_rules),
            "resolved_rules": raw_rules,
            "enabled_rules": [rule for rule in raw_rules if rule.get("enabled")],
            "notice_text": raw_payload.get("rendered", {}).get("notice_text", ""),
            "unresolved_placeholders": raw_payload.get("unresolved_placeholders", []),
        }
        payload["rendered"]["raw_rules_notice_text"] = raw_payload.get("rendered", {}).get("notice_text", "")

    def _refresh_mapping_tree(self, sync_json: bool = False) -> None:
        if not hasattr(self, "mapping_tree"):
            return
        selected_index = self._selected_rule_index()
        self.mapping_tree.delete(*self.mapping_tree.get_children())
        for idx, raw_rule in enumerate(self.mapping_rules):
            rule = normalize_mapping_rule(raw_rule)
            enabled = "yes" if rule.get("enabled") else "no"
            value_preview = str(rule.get("value_template", "")).replace("\n", " ")
            if len(value_preview) > 120:
                value_preview = value_preview[:117] + "..."
            self.mapping_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(enabled, rule.get("placeholder", ""), value_preview),
            )
        if selected_index is not None and 0 <= selected_index < len(self.mapping_rules):
            self.mapping_tree.selection_set(str(selected_index))
        self.mapping_status_var.set(f"{len(self.mapping_rules)} placeholder rule(s)")
        # Placeholder-map UI no longer syncs into Raw rules JSON.

    def _set_mapping_preview(self, payload: Dict[str, Any]) -> None:
        profile = payload.get("extension_payload", {}).get("placeholder_profile", self._mapping_profile())
        mapped_rules = payload.get("extension_payload", {}).get("resolved_placeholder_rules", [])
        enabled_count = sum(1 for rule in mapped_rules if rule.get("enabled"))
        fill_values = payload.get("extension_payload", {}).get("fill_values", {})

        builtins = {
            "[DOMAIN]": fill_values.get("domain"),
            "DOMAIN": fill_values.get("domain"),
            "[USER]": fill_values.get("user"),
            "[the seller]": fill_values.get("hostname") or fill_values.get("seller_hostname"),
            "[NAME ON PRODUCT LABEL]": fill_values.get("name_on_product_label"),
            "[LIST URL FOR SPECIFIC ACTION]": fill_values.get("action_url_list"),
        }
        builtin_lines = ["Built-in fallback values available to both rule modules:"]
        for key, value in builtins.items():
            builtin_lines.append(f"{key} => {value}")
        self.builtin_values_text.delete("1.0", "end")
        self.builtin_values_text.insert("1.0", self._clean_display_text("\n".join(builtin_lines)))

        lines = [
            "Placeholder map module: rules added with Add/Edit here only.",
            "Priority in this preview: non-empty Placeholder map rule value first, then built-in fallback.",
            f"Rules: {len(mapped_rules)} total / {enabled_count} enabled",
            "",
        ]
        if not mapped_rules:
            lines.extend([
                "No user placeholder rules yet.",
                "Built-in fallback still handles [DOMAIN], DOMAIN, [USER], [the seller], [NAME ON PRODUCT LABEL], and URL-list placeholders when no JSON value is provided.",
                "Use Add rule only when you want to override or add an exact replacement.",
            ])
        else:
            for rule in mapped_rules:
                status = "ON" if rule.get("enabled") else "OFF"
                value = str(rule.get("value", ""))
                if len(value) > 500:
                    value = value[:500] + "..."
                lines.extend([
                    f"#{rule.get('order')} [{status}] {rule.get('placeholder')}",
                    "  value:",
                    "  " + value.replace("\n", "\n  "),
                    "",
                ])
        self.mapping_preview_text.delete("1.0", "end")
        self.mapping_preview_text.insert("1.0", self._clean_display_text("\n".join(lines)))

        if hasattr(self, "mapping_result_text"):
            mapped_notice = self._clean_display_text(payload.get("rendered", {}).get("notice_text", ""))
            self.mapping_result_text.delete("1.0", "end")
            self.mapping_result_text.insert("1.0", mapped_notice)
            self.mapping_result_text.tag_remove(PLACEHOLDER_TAG, "1.0", "end")
            for placeholder in payload.get("unresolved_placeholders", []) or []:
                if not isinstance(placeholder, str) or not placeholder.startswith("["):
                    continue
                start = "1.0"
                while True:
                    pos = self.mapping_result_text.search(placeholder, start, "end")
                    if not pos:
                        break
                    end = self.mapping_result_text.index(f"{pos}+{len(placeholder)}c")
                    self.mapping_result_text.tag_add(PLACEHOLDER_TAG, pos, end)
                    start = end

    def _set_raw_json_preview(self, raw_payload: Dict[str, Any]) -> None:
        if not hasattr(self, "raw_json_result_text"):
            return
        raw_notice = self._clean_display_text(raw_payload.get("rendered", {}).get("notice_text", ""))
        self.raw_json_result_text.delete("1.0", "end")
        self.raw_json_result_text.insert("1.0", raw_notice)
        self.raw_json_result_text.tag_remove(PLACEHOLDER_TAG, "1.0", "end")
        for placeholder in raw_payload.get("unresolved_placeholders", []) or []:
            if not isinstance(placeholder, str) or not placeholder.startswith("["):
                continue
            start = "1.0"
            while True:
                pos = self.raw_json_result_text.search(placeholder, start, "end")
                if not pos:
                    break
                end = self.raw_json_result_text.index(f"{pos}+{len(placeholder)}c")
                self.raw_json_result_text.tag_add(PLACEHOLDER_TAG, pos, end)
                start = end

    def _selected_rule_index(self) -> Optional[int]:
        if not hasattr(self, "mapping_tree"):
            return None
        selection = self.mapping_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def add_mapping_rule(self) -> None:
        default_rule = {
            "enabled": True,
            "placeholder": "[DOMAIN]",
            "value_template": "{{domain}}",
            "note": "",
        }
        dialog = RuleEditorDialog(self, "Add mapping rule", default_rule, self._mapping_value_keys())
        self.wait_window(dialog)
        if dialog.result:
            self.mapping_rules.append(dialog.result)
            self._refresh_mapping_tree()
            self._schedule_render()
            self.tabs.select(self.mapping_tab)

    def edit_selected_rule(self) -> None:
        idx = self._selected_rule_index()
        if idx is None or not (0 <= idx < len(self.mapping_rules)):
            messagebox.showinfo("No rule selected", "Select a mapping rule to edit.")
            return
        dialog = RuleEditorDialog(self, "Edit mapping rule", self.mapping_rules[idx], self._mapping_value_keys())
        self.wait_window(dialog)
        if dialog.result:
            self.mapping_rules[idx] = dialog.result
            self._refresh_mapping_tree()
            self.mapping_tree.selection_set(str(idx))
            self._schedule_render()

    def duplicate_selected_rule(self) -> None:
        idx = self._selected_rule_index()
        if idx is None or not (0 <= idx < len(self.mapping_rules)):
            messagebox.showinfo("No rule selected", "Select a mapping rule to duplicate.")
            return
        duplicated = dict(normalize_mapping_rule(self.mapping_rules[idx]))
        duplicated["note"] = str(duplicated.get("note") or "") + " copy"
        self.mapping_rules.insert(idx + 1, duplicated)
        self._refresh_mapping_tree()
        self.mapping_tree.selection_set(str(idx + 1))
        self._schedule_render()

    def delete_selected_rule(self) -> None:
        idx = self._selected_rule_index()
        if idx is None or not (0 <= idx < len(self.mapping_rules)):
            messagebox.showinfo("No rule selected", "Select a mapping rule to delete.")
            return
        del self.mapping_rules[idx]
        self._refresh_mapping_tree()
        self._schedule_render()

    def move_selected_rule(self, direction: int) -> None:
        idx = self._selected_rule_index()
        if idx is None:
            return
        new_idx = idx + direction
        if not (0 <= idx < len(self.mapping_rules)) or not (0 <= new_idx < len(self.mapping_rules)):
            return
        self.mapping_rules[idx], self.mapping_rules[new_idx] = self.mapping_rules[new_idx], self.mapping_rules[idx]
        self._refresh_mapping_tree()
        self.mapping_tree.selection_set(str(new_idx))
        self._schedule_render()

    def clear_mapping_rules(self) -> None:
        if self.mapping_rules and not messagebox.askyesno("Clear mapping", "Remove all mapping rules from the current profile?"):
            return
        self.mapping_rules = []
        self.mapping_path = None
        self.mapping_name_var.set("Untitled placeholder map")
        self.mapping_match_var.set("")
        self._refresh_mapping_tree()
        self._schedule_render()

    def load_mapping_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Open placeholder map JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
            # Accept full payloads as well as saved placeholder-map profiles.
            if "extension_payload" in obj and "placeholder_profile" in obj.get("extension_payload", {}):
                obj = obj["extension_payload"]["placeholder_profile"]
            self.mapping_name_var.set(obj.get("profile_name") or obj.get("name") or Path(path).stem)
            self.mapping_match_var.set(obj.get("template_match") or obj.get("template") or "")
            rules_source = obj.get("rules") or obj.get("placeholder_rules") or obj.get("placeholder_map") or []
            self.mapping_rules = [normalize_mapping_rule(rule) for rule in engine.normalize_placeholder_rules(rules_source)]
            self.mapping_path = Path(path)
            self._refresh_mapping_tree()
            self._schedule_render()
            self.tabs.select(self.mapping_tab)
            self.status_var.set(f"Loaded placeholder map JSON: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Could not load placeholder map JSON", str(exc))

    def save_mapping_json(self) -> None:
        profile = self._mapping_profile()
        default_name = (profile.get("profile_name") or "placeholder-map").lower().replace(" ", "-") + ".json"
        path = filedialog.asksaveasfilename(
            title="Save placeholder map JSON",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        self.mapping_path = Path(path)
        self.status_var.set(f"Saved placeholder map JSON: {path}")
        self._schedule_render()

    def browse_image_folder(self) -> None:
        path = filedialog.askdirectory(title="Select image folder prefix")
        if path:
            self.image_folder_var.set(path)
            self.image_status_var.set("Folder selected")

    def _image_search_pattern(self, code: str) -> str:
        # Main workflow: folder prefix + file code/suffix + .*
        # Example: /evidence/screenshots + ABC123 -> /evidence/screenshots/ABC123.*
        return code if any(char in code for char in "*?[]") else f"{code}.*"

    def check_image_files_silent(self) -> None:
        self._image_after_id = None
        folder_raw = self.image_folder_var.get().strip().strip('"')
        code = self.image_code_var.get().strip()
        if not folder_raw or not code:
            self.image_results = []
            self.image_status_var.set("Waiting for folder + file code")
            self._set_image_results_text("Enter Folder prefix and File code / suffix to check:\n\n<folder>/<code>.*")
            self._clear_image_preview("Image preview will appear here when the first matched file is an image.")
            return

        folder = Path(folder_raw).expanduser()
        pattern = self._image_search_pattern(code)
        if not folder.exists() or not folder.is_dir():
            self.image_results = []
            self.image_status_var.set("Folder not found")
            self._set_image_results_text("FOLDER NOT FOUND\n\n" + str(folder))
            self._clear_image_preview("Folder not found.")
            return

        try:
            iterator = folder.rglob(pattern) if self.image_recursive_var.get() else folder.glob(pattern)
            results = sorted(path for path in iterator if path.is_file())
        except Exception as exc:
            self.image_results = []
            self.image_status_var.set("Image check failed")
            self._set_image_results_text("IMAGE CHECK FAILED\n\n" + str(exc))
            self._clear_image_preview("Image check failed.")
            return

        self.image_results = results
        if results:
            result_lines = [str(path.resolve()) for path in results]
            text = "FOUND " + str(len(results)) + " file(s) for pattern: " + pattern + "\n\n" + "\n".join(result_lines)
            self.image_status_var.set(f"Found {len(results)} file(s)")
            self._set_image_results_text(text)
            self._render_first_image_preview(results)
        else:
            text = "NOT FOUND\n\nFolder:\n" + str(folder.resolve()) + "\n\nPattern:\n" + pattern
            self.image_status_var.set("No matching file")
            self._set_image_results_text(text)
            self._clear_image_preview("No matched file to preview.")

    def _set_image_results_text(self, text: str) -> None:
        self.image_paths_text.delete("1.0", "end")
        self.image_paths_text.insert("1.0", text)

    def _clear_image_preview(self, message: str) -> None:
        self.image_preview_ref = None
        self.image_preview_label.configure(image="", text=message)

    def _render_first_image_preview(self, paths: List[Path]) -> None:
        image_path = next((path for path in paths if path.suffix.lower() in IMAGE_EXTENSIONS), None)
        if not image_path:
            self._clear_image_preview("Matched file(s) found, but none look like an image file.")
            return
        if Image is None or ImageTk is None:
            self._clear_image_preview(
                "Matched image found, but Pillow is not installed.\nRun: pip install -r requirements.txt\n\n" + str(image_path.resolve())
            )
            return
        try:
            img = Image.open(image_path)
            img.thumbnail((720, 420))
            photo = ImageTk.PhotoImage(img)
            self.image_preview_ref = photo
            self.image_preview_label.configure(image=photo, text="")
        except Exception as exc:
            self._clear_image_preview(f"Could not render image preview:\n{image_path}\n\n{exc}")

    def copy_image_paths(self) -> None:
        if not self.image_results:
            messagebox.showinfo("No paths", "No matched paths to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(str(path.resolve()) for path in self.image_results))
        self.status_var.set("Copied image path(s) to clipboard")

    def open_first_image_file(self) -> None:
        if not self.image_results:
            messagebox.showinfo("No file", "No matched file to open yet.")
            return
        path = self.image_results[0].resolve()
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(path)])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
            self.status_var.set(f"Opened first matched file: {path}")
        except Exception as exc:
            messagebox.showerror("Could not open file", str(exc))

    def load_urls_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open URL list",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            urls = engine.read_lines_file(path)
            self._replace_text(self.urls_text, "\n".join(urls) + ("\n" if urls else ""))
            self.status_var.set(f"Loaded {len(urls)} URL(s) from {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Could not load URL file", str(exc))

    def load_claims_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open claims/evidence list",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            claims = engine.read_lines_file(path)
            self._replace_text(self.claims_text, "\n".join(claims) + ("\n" if claims else ""))
            self.status_var.set(f"Loaded {len(claims)} claim line(s) from {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Could not load claims file", str(exc))

    def load_case_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Open case JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
            self.template_var.set(engine.TEMPLATE_ALIASES.get(obj.get("template") or obj.get("template_id") or self.template_var.get(), obj.get("template") or obj.get("template_id") or self.template_var.get()))
            urls = obj.get("urls") or ([obj["url"]] if obj.get("url") else [])
            self._replace_text(self.urls_text, "\n".join(urls) + ("\n" if urls else ""))

            claims = obj.get("claims") or ([obj["claim"]] if obj.get("claim") else [])
            self._replace_text(self.claims_text, "\n".join(claims) + ("\n" if claims else ""))

            self.domain_var.set(obj.get("domain", ""))
            self.user_var.set(obj.get("user") or obj.get("seller") or obj.get("account") or "")
            self.name_on_label_var.set(obj.get("name_on_product_label") or obj.get("name_on_label") or "")
            self.ascii_var.set(bool(obj.get("ascii", False)))
            if obj.get("rules") or obj.get("placeholder_rules") or obj.get("placeholder_map"):
                self.mapping_name_var.set(obj.get("profile_name") or obj.get("placeholder_profile_name") or self.mapping_name_var.get())
                self.mapping_match_var.set(obj.get("template_match") or self.mapping_match_var.get())
                raw_rules = obj.get("rules") or obj.get("placeholder_rules") or obj.get("placeholder_map") or []
                self.mapping_rules = [normalize_mapping_rule(rule) for rule in engine.normalize_placeholder_rules(raw_rules)]
                self._refresh_mapping_tree()
            self.case_path = Path(path)
            self.status_var.set(f"Loaded case JSON: {Path(path).name}")
            self._schedule_render()
        except Exception as exc:
            messagebox.showerror("Could not load case JSON", str(exc))

    def open_template_file(self) -> None:
        template_id = self.template_var.get()
        path = engine.TEMPLATE_DIR / f"{template_id}.txt"
        if not path.exists():
            messagebox.showerror("Template not found", str(path))
            return
        try:
            text = self._clean_display_text(path.read_text(encoding="utf-8"))
            win = tk.Toplevel(self)
            win.title(f"Template: {template_id}")
            win.geometry("900x600")
            box = tk.Text(win, wrap="word", font=("Segoe UI", 10), padx=8, pady=8)
            box.pack(fill="both", expand=True, padx=8, pady=8)
            box.insert("1.0", text)
        except Exception as exc:
            messagebox.showerror("Could not open template", str(exc))

    def start_bridge_server(self, silent: bool = False) -> None:
        if bridge_server is None:
            self.bridge_status_var.set("Bridge unavailable: bridge_server.py not loaded")
            if not silent:
                messagebox.showerror("Bridge unavailable", "bridge_server.py could not be loaded.")
            return
        try:
            port_text = self.bridge_port_var.get().strip() or "8765"
            port = int(port_text)
            actual_port = bridge_server.start_server(port=port)
            self.bridge_port_var.set(str(actual_port))
            self.bridge_status_var.set(f"Bridge: http://127.0.0.1:{actual_port} queue={len(bridge_server.list_items())}")
            if not silent:
                self.status_var.set(f"Extension bridge running at http://127.0.0.1:{actual_port}")
        except OSError as exc:
            self.bridge_status_var.set("Bridge start failed")
            if not silent:
                messagebox.showerror(
                    "Bridge start failed",
                    f"Could not start localhost bridge on port {self.bridge_port_var.get()}.\n\n{exc}\n\n"
                    "Try another port, then update the same Bridge URL in the Chrome extension.",
                )
        except Exception as exc:
            self.bridge_status_var.set("Bridge start failed")
            if not silent:
                messagebox.showerror("Bridge start failed", str(exc))

    def _payload_signature_for_bridge(self, payload: Dict[str, Any]) -> str:
        if bridge_server is not None:
            try:
                return bridge_server.payload_signature(payload)
            except Exception:
                pass
        seed = json.dumps(payload.get("rendered", {}).get("notice_text", ""), ensure_ascii=False)
        return str(hash(seed))

    def _queue_payload_to_bridge(self, payload: Dict[str, Any], manual: bool = False) -> None:
        if bridge_server is None:
            self.bridge_status_var.set("Bridge unavailable")
            return
        if not bridge_server.is_running():
            self.start_bridge_server(silent=True)
        try:
            rendered = payload.get("rendered", {})
            case_data = payload.get("case_data", {})
            title = rendered.get("subject") or f"{case_data.get('domain', 'unknown-domain')} - {case_data.get('template_id', 'notice')}"
            item = bridge_server.enqueue(payload, title=title, source="python-gui")
            count = len(bridge_server.list_items())
            self.bridge_status_var.set(f"Queued: {item.get('domain')} | queue={count}")
            if manual:
                self.status_var.set("Queued mapped payload for Chrome extension. Open extension > Bridge queue > Use selected.")
        except Exception as exc:
            self.bridge_status_var.set("Queue failed")
            if manual:
                messagebox.showerror("Queue failed", str(exc))

    def _maybe_auto_queue(self, payload: Dict[str, Any]) -> None:
        if not self.bridge_auto_var.get():
            return
        signature = self._payload_signature_for_bridge(payload)
        if signature == self._last_bridge_signature:
            return
        self._last_bridge_signature = signature
        self._queue_payload_to_bridge(payload, manual=False)

    def queue_mapped_to_extension(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        self._last_bridge_signature = self._payload_signature_for_bridge(payload)
        self._queue_payload_to_bridge(payload, manual=True)

    def _ensure_payload(self) -> Optional[Dict[str, Any]]:
        if not self.last_payload:
            self.render()
        return self.last_payload

    def save_json(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        default_name = f"{payload['case_data']['domain']}-{payload['case_data']['template_id']}.json".replace("[", "").replace("]", "")
        path = filedialog.asksaveasfilename(
            title="Save full payload JSON",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status_var.set(f"Saved JSON: {path}")

    def save_text(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        default_name = f"{payload['case_data']['domain']}-{payload['case_data']['template_id']}.txt".replace("[", "").replace("]", "")
        path = filedialog.asksaveasfilename(
            title="Save notice TXT",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        Path(path).write_text(payload["rendered"]["notice_text"], encoding="utf-8")
        self.status_var.set(f"Saved notice text: {path}")

    def copy_notice(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        # Main copy/save uses the final mapped notice because that is what will
        # be sent downstream. The Notice tab itself remains a built-in preview.
        self.clipboard_clear()
        self.clipboard_append(payload["rendered"]["notice_text"])
        self.status_var.set("Copied final mapped notice text to clipboard")

    def copy_builtin_notice(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        builtin = payload["rendered"].get("builtin_notice_text") or payload["rendered"]["notice_text"]
        self.clipboard_clear()
        self.clipboard_append(builtin)
        self.status_var.set("Copied built-in notice text to clipboard")

    def copy_mapped_notice(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        self.clipboard_clear()
        self.clipboard_append(payload["rendered"]["notice_text"])
        self.status_var.set("Copied mapped notice text to clipboard")

    def copy_raw_json_notice(self) -> None:
        if not self.last_raw_payload:
            self.render()
        if not self.last_raw_payload:
            return
        self.clipboard_clear()
        self.clipboard_append(self.last_raw_payload["rendered"]["notice_text"])
        self.status_var.set("Copied Raw rules JSON result to clipboard")

    def copy_json(self) -> None:
        payload = self._ensure_payload()
        if not payload:
            return
        self.clipboard_clear()
        self.clipboard_append(json.dumps(payload, ensure_ascii=False, indent=2))
        self.status_var.set("Copied full JSON payload to clipboard")

    def clear_all(self) -> None:
        self._replace_text(self.urls_text, "")
        self._replace_text(self.claims_text, "")
        self.domain_var.set("")
        self.user_var.set("")
        self.name_on_label_var.set("")
        self.ascii_var.set(False)
        self.image_folder_var.set("")
        self.image_code_var.set("")
        self.image_recursive_var.set(False)
        self.image_status_var.set("No image check yet")
        self.image_results = []
        self._clear_image_preview("Image preview will appear here when the first matched file is an image.")
        self.raw_json_rules = []
        if hasattr(self, "mapping_json_text"):
            self.mapping_json_text.delete("1.0", "end")
            self.mapping_json_text.insert("1.0", "{}")
            self.mapping_json_text.edit_modified(False)
        self.raw_json_error_var.set("Raw rules JSON: ready")
        self.last_payload = None
        self.last_builtin_payload = None
        self.last_raw_payload = None
        self.status_var.set("Cleared; realtime preview will update")
        self._schedule_render()
        self._schedule_image_check()
        self.start_bridge_server(silent=True)


def main() -> int:
    app = NoticeGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
