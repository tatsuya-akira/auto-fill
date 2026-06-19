#!/usr/bin/env python3
"""
Print rendered notice data before using the Chrome extension autofill step.

This script converts a raw URL + template choice into:
  - case_data: normalized fields derived from the input
  - rendered: subject + notice_text after placeholder replacement
  - extension_payload: values that the extension can later map into form fields

Requires tldextract for reliable registrable-domain parsing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

try:
    import tldextract
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: tldextract. Install it with: pip install -r requirements.txt"
    ) from exc

# Do not fetch the Public Suffix List at runtime. tldextract ships with a snapshot,
# which is enough for offline notice generation and avoids surprise network calls.
TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


TEMPLATE_ALIASES = {
    "sponsor": "sponsor",
    "zpb_sponsor": "sponsor",
    "unapprove": "unapproved_retatrutide",
    "unapproved": "unapproved_retatrutide",
    "unapproved_retatrutide": "unapproved_retatrutide",
    "retatrutide": "unapproved_retatrutide",
    "newtag": "newtag",
    "new_tag": "newtag",
    "us_newtag": "us_newtag",
    "us_new_tag": "us_newtag",
    "uslabel": "us_label",
    "us_label": "us_label",
    "usonly": "us_label",
}

SMART_CHAR_MAP = str.maketrans({
    "“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...",
})


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    parsed = urlparse(value)
    if not parsed.scheme and "." in value.split("/")[0]:
        value = "https://" + value
    return value


def read_lines_file(path: str | Path) -> List[str]:
    """Read one item per line from a UTF-8 text file.

    Blank lines are ignored. Lines starting with # are treated as comments so
    a URL list can contain notes without becoming part of the notice.
    """
    text = Path(path).read_text(encoding="utf-8")
    items: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


def unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def get_hostname(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    host = parsed.netloc or parsed.path.split("/")[0]
    host = host.split("@")[ -1].split(":")[0].strip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def homepage_url(url: str) -> str:
    url = normalize_url(url)
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or parsed.path.split("/")[0]
    if not host:
        return url
    return f"{scheme}://{host}".rstrip("/")


def registrable_domain(url_or_host: str) -> str:
    """Return the registrable/root domain using the Public Suffix List.

    Examples:
      - shop.slimvials.com -> slimvials.com
      - mounjarosa.co.za -> mounjarosa.co.za
      - a.b.example.com.au -> example.com.au
    """
    host = get_hostname(url_or_host)
    extracted = TLD_EXTRACTOR(host)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return host


def domain_label(domain_or_url: str) -> str:
    """Return the main label/domain stem using tldextract.

    Examples:
      - slimvials.com -> slimvials
      - mounjarosa.co.za -> mounjarosa
    """
    extracted = TLD_EXTRACTOR(get_hostname(domain_or_url))
    if extracted.domain:
        return extracted.domain
    return get_hostname(domain_or_url) or domain_or_url


def bulletize(values: List[str]) -> str:
    clean = [v.strip() for v in values if v.strip()]
    if not clean:
        return "[CLAIM OR CLAIMS MADE IN POST IN BULLETED LIST]"
    return "\n".join(f"•\t{v}" for v in clean)


def load_template(template_id: str) -> str:
    template_id = TEMPLATE_ALIASES.get(template_id, template_id)
    path = TEMPLATE_DIR / f"{template_id}.txt"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in TEMPLATE_DIR.glob("*.txt")))
        raise SystemExit(f"Unknown template '{template_id}'. Available templates: {available}")
    return path.read_text(encoding="utf-8")


def choose_url_line(text: str, url_count: int) -> str:
    """Normalize singular/plural URL wording before placeholder replacement.

    The source templates are intentionally close to the originals, so some of
    them use only [LIST URL FOR SPECIFIC ACTION] even when the data contains
    multiple URLs. This helper keeps the template readable while making the
    rendered notice grammatically correct.
    """
    # Handles blocks like:
    # Lilly requests that you remove the following URL [LIST URL...].
    # OR
    # Lilly requests that you remove the following URLs [LIST URLs...].
    pattern = re.compile(
        r"(?P<single>^[ \t]*Lilly requests that you remove\s+the following URL\s+\[LIST URL FOR SPECIFIC ACTION\]\.\s*$)"
        r"\s*^\s*OR\s*$\s*"
        r"(?P<plural>^[ \t]*Lilly requests that you remove\s+the following URLs\s+\[LIST URLs FOR SPECIFIC ACTION\]\.\s*$)",
        flags=re.IGNORECASE | re.MULTILINE,
    )

    def repl(match: re.Match[str]) -> str:
        return match.group("single") if url_count == 1 else match.group("plural")

    text = pattern.sub(repl, text)

    if url_count == 1:
        text = re.sub(r"the following URLs\b", "the following URL", text)
        text = re.sub(r"following URLs\b", "following URL", text)
    else:
        text = re.sub(r"the following URL\b", "the following URLs", text)
        text = re.sub(r"following URL\b", "following URLs", text)

    return text




def apply_url_placeholders(text: str, action_url_list: str) -> str:
    """Replace URL-list placeholders with one URL per line.

    Handles both inline placeholders, e.g.
    "following URLs: [LIST URL FOR SPECIFIC ACTION].", and standalone
    placeholders on their own line.
    """
    placeholder = r"\[(?:LIST URL FOR SPECIFIC ACTION|LIST URLs FOR SPECIFIC ACTION)\]"

    inline_pattern = re.compile(
        r"(?P<prefix>following URLs?)(?:[ \t]*:)?[ \t]*" + placeholder + r"[ \t]*[\.,]?",
        flags=re.IGNORECASE,
    )

    def inline_repl(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}:\n\n{action_url_list}"

    text = inline_pattern.sub(inline_repl, text)
    text = re.sub(placeholder, action_url_list, text)
    return text

def replace_placeholders(template: str, data: Dict[str, Any]) -> str:
    text = choose_url_line(template, data["url_count"])
    claims_text = bulletize(data.get("claims", []))
    text = apply_url_placeholders(text, data["action_url_list"])

    replacements = {
        "[DOMAIN]": data["domain"],
        "[USER]": data.get("user") or data["domain"],
        "[CLAIM OR CLAIMS MADE IN POST IN BULLETED LIST]": claims_text,
        "[CLAIM OR CLAIMS MADE IN POST IN BULLETED LIST, INCLUDING PICTURE OF VIAL WITH TELEHEALTH NAME]": claims_text,
        "[NAME ON PRODUCT LABEL]": data.get("name_on_product_label") or data["domain_label"],
    }
    # Replace longer placeholders first so the claim-with-vial placeholder is not partially matched.
    for key in sorted(replacements, key=len, reverse=True):
        text = text.replace(key, str(replacements[key]))

    # Replace standalone capital DOMAIN only. This keeps normal words like "Domain" intact.
    text = re.sub(r"\bDOMAIN\b", data["domain"], text)

    if data.get("ascii"):
        text = text.translate(SMART_CHAR_MAP)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip() + "\n"


def derive_subject(rendered_text: str, domain: str, template_id: str) -> str:
    lines = [line.strip() for line in rendered_text.splitlines() if line.strip()]
    if not lines:
        return f"Notice re {domain}"
    first = lines[0]
    if first.lower().startswith(("notification", "misleading")):
        return first
    subjects = {
        "sponsor": f"Notification of IP rights infringement - {domain}",
        "unapproved_retatrutide": f"Unapproved Retatrutide products - {domain}",
        "newtag": f"Misleading compounded tirzepatide advertising - {domain}",
        "us_newtag": f"Misleading compounded tirzepatide/orforglipron advertising - {domain}",
        "us_label": f"Misleading compounded tirzepatide labeling - {domain}",
    }
    return subjects.get(template_id, f"Notice re {domain}")


def unresolved_placeholders(text: str) -> List[str]:
    found = set()
    placeholder_markers = (
        "DOMAIN", "LIST URL", "LIST URLs", "CLAIM OR CLAIMS", "USER", "NAME ON PRODUCT LABEL"
    )
    for match in re.findall(r"\[[^\]]+\]", text):
        # Ignore ordinary editorial brackets like [C]ompanies and [the seller].
        if any(marker in match for marker in placeholder_markers):
            found.add(match)
    # Remaining all-caps DOMAIN should be considered unresolved.
    if re.search(r"\bDOMAIN\b", text):
        found.add("DOMAIN")
    return sorted(found)


def build_case_data(args: argparse.Namespace, case_obj: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    case_obj = case_obj or {}
    template_id = args.template or case_obj.get("template") or case_obj.get("template_id") or "unapproved_retatrutide"
    template_id = TEMPLATE_ALIASES.get(template_id, template_id)

    urls: List[str] = []
    urls.extend(case_obj.get("urls") or [])
    if case_obj.get("url"):
        urls.append(case_obj["url"])
    urls.extend(args.url or [])
    if args.urls_file:
        urls.extend(read_lines_file(args.urls_file))
    if case_obj.get("urls_file"):
        urls.extend(read_lines_file(case_obj["urls_file"]))
    urls = unique_keep_order(normalize_url(u) for u in urls)
    if not urls:
        raise SystemExit("Missing URL. Use --url, --urls-file, or --case with url/urls.")

    first_url = urls[0]
    home = homepage_url(first_url)
    domain = case_obj.get("domain") or args.domain or registrable_domain(first_url)
    label = domain_label(domain)

    # For multiple URLs, put homepage/root first as default for registrar notices.
    # Keep both the raw input URLs and the action URL list. The action list is
    # what replaces [LIST URL FOR SPECIFIC ACTION] in the rendered notice.
    if len(urls) > 1:
        action_urls = unique_keep_order([home] + urls)
    else:
        action_urls = urls[:]
    action_url_list = "\n".join(action_urls)

    claims: List[str] = []
    claims.extend(case_obj.get("claims") or [])
    if case_obj.get("claim"):
        claims.append(case_obj["claim"])
    claims.extend(args.claim or [])
    if args.claims_file:
        claims.extend(read_lines_file(args.claims_file))
    if case_obj.get("claims_file"):
        claims.extend(read_lines_file(case_obj["claims_file"]))
    claims = unique_keep_order(claims)

    data = {
        "template_id": template_id,
        "source_template_file": str(TEMPLATE_DIR / f"{template_id}.txt"),
        "urls": urls,
        "first_url": first_url,
        "homepage_url": home,
        "domain": domain,
        "domain_label": label,
        "url_count": len(urls),
        "action_url_count": len(action_urls),
        "action_urls": action_urls,
        "action_url_list": action_url_list,
        # Backward-compatible aliases for earlier extension mapping drafts.
        "url_list_items": action_urls,
        "url_list": action_url_list,
        "url_word": "URL" if len(urls) == 1 else "URLs",
        "user": args.user or case_obj.get("user") or case_obj.get("seller") or case_obj.get("account") or domain,
        "claims": claims,
        "claims_text": bulletize(claims),
        "name_on_product_label": args.name_on_label or case_obj.get("name_on_product_label") or case_obj.get("name_on_label") or label,
        "recipient_type": args.recipient_type or case_obj.get("recipient_type") or "registrar",
        "platform": args.platform or case_obj.get("platform") or "",
        "ascii": bool(args.ascii or case_obj.get("ascii")),
    }
    # Preserve custom case fields too.
    for k, v in case_obj.items():
        if k not in data and k not in {"url", "urls", "template", "template_id"}:
            data[k] = v
    return data


def render_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    template = load_template(data["template_id"])
    notice_text = replace_placeholders(template, data)
    subject = derive_subject(notice_text, data["domain"], data["template_id"])
    data["subject"] = subject

    fill_values = {
        "domain": data["domain"],
        "url": data["first_url"],
        "urls": data["urls"],
        "action_urls": data["action_urls"],
        "homepage_url": data["homepage_url"],
        "url_list": data["url_list"],
        "action_url_list": data["action_url_list"],
        "url_count": data["url_count"],
        "action_url_count": data["action_url_count"],
        "subject": subject,
        "notice_text": notice_text,
        "user": data.get("user", ""),
        "claims_text": data.get("claims_text", ""),
        "name_on_product_label": data.get("name_on_product_label", ""),
        "recipient_type": data.get("recipient_type", ""),
    }
    payload = {
        "case_data": data,
        "rendered": {
            "subject": subject,
            "notice_text": notice_text,
        },
        "extension_payload": {
            "fill_values": fill_values,
            "mapping_ready": True,
        },
        "unresolved_placeholders": unresolved_placeholders(notice_text),
    }
    return payload


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print notice data before extension autofill.")
    parser.add_argument("--template", help="Template id: sponsor, unapproved, newtag, us_newtag, us_label")
    parser.add_argument("--case", help="JSON file with template/url/urls/user/claims/etc.")
    parser.add_argument("--url", action="append", help="URL to include. Can be repeated.")
    parser.add_argument("--urls-file", help="Text file with one URL per line.")
    parser.add_argument("--domain", help="Override derived domain.")
    parser.add_argument("--user", help="Platform user/account/seller name for [USER].")
    parser.add_argument("--claim", action="append", help="Claim/evidence line. Can be repeated.")
    parser.add_argument("--claims-file", help="Text file with one claim per line.")
    parser.add_argument("--name-on-label", help="Value for [NAME ON PRODUCT LABEL]. Defaults to domain label.")
    parser.add_argument("--recipient-type", choices=["registrar", "hosting", "platform", "other"], help="Stored in case_data for later mapping.")
    parser.add_argument("--platform", help="Platform/provider name for later mapping.")
    parser.add_argument("--ascii", action="store_true", help="Convert smart quotes/dashes to ASCII in notice_text.")
    parser.add_argument("--format", choices=["json", "text", "both"], default="json", help="What to print to stdout.")
    parser.add_argument("--save-json", help="Write full payload JSON to this path.")
    parser.add_argument("--save-text", help="Write rendered notice_text to this path.")
    parser.add_argument("--list-templates", action="store_true", help="List available templates and exit.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.list_templates:
        for path in sorted(TEMPLATE_DIR.glob("*.txt")):
            print(path.stem)
        return 0

    case_obj = None
    if args.case:
        case_obj = json.loads(Path(args.case).read_text(encoding="utf-8"))

    data = build_case_data(args, case_obj)
    payload = render_payload(data)

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.save_text:
        Path(args.save_text).write_text(payload["rendered"]["notice_text"], encoding="utf-8")

    if args.format in {"json", "both"}:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.format in {"text", "both"}:
        if args.format == "both":
            print("\n--- rendered.notice_text ---\n")
        print(payload["rendered"]["notice_text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
