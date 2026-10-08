from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.async_api import Page

from autositemap.config import FingerprintConfig

_STRUCTURAL_JS = """
(ignoreSelectors) => {
    function walk(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            let t = node.textContent.trim();
            if (!t) return '';
            // Scrub timestamp-like patterns
            t = t.replace(/\\b\\d{1,2}[/.:_-]\\d{1,2}([/.:_-]\\d{2,4})?\\b/g, '');
            t = t.replace(/\\b\\d{4}[/.:_-]\\d{1,2}[/.:_-]\\d{1,2}\\b/g, '');
            t = t.replace(/\\b\\d{1,2}:\\d{2}(:\\d{2})?\\b/g, '');
            t = t.trim();
            return t ? `T[${t}]` : '';
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return '';

        const el = node;
        const tag = el.tagName.toLowerCase();

        // Skip script, style, noscript
        if (tag === 'script' || tag === 'style' || tag === 'noscript') return '';

        // Check if this element should be ignored
        for (const sel of ignoreSelectors) {
            try {
                if (el.matches(sel)) return '';
            } catch (e) {}
        }

        const id = el.id ? '#' + el.id : '';
        const classes = Array.from(el.classList).sort().join('.');
        const cls = classes ? '.' + classes : '';
        const role = el.getAttribute('role') ? `[role=${el.getAttribute('role')}]` : '';
        const expanded = el.getAttribute('aria-expanded');
        const aExp = expanded !== null ? `[expanded=${expanded}]` : '';
        const selected = el.getAttribute('aria-selected');
        const aSel = selected !== null ? `[selected=${selected}]` : '';
        const hidden = el.getAttribute('aria-hidden');
        const aHid = hidden !== null ? `[hidden=${hidden}]` : '';
        const open = el.hasAttribute('open') ? '[open]' : '';
        const htmlHidden = el.hasAttribute('hidden') ? '[html-hidden]' : '';

        let children = '';
        for (const child of el.childNodes) {
            children += walk(child);
        }

        const attrs = `${id}${cls}${role}${aExp}${aSel}${aHid}${open}${htmlHidden}`;
        return `<${tag}${attrs}>${children}</${tag}>`;
    }

    return walk(document.body);
}
"""


@dataclass(frozen=True)
class StateFingerprint:
    url: str
    dom_hash: str

    def matches(self, other: StateFingerprint) -> bool:
        return self.url == other.url and self.dom_hash == other.dom_hash


def normalize_url(url: str, ignore_params: tuple[str, ...] = ()) -> str:
    parsed = urlparse(url)
    if not ignore_params:
        return url

    qs = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {k: v for k, v in qs.items() if k not in ignore_params}
    new_query = urlencode(filtered, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


async def compute_fingerprint(page: Page, config: FingerprintConfig) -> StateFingerprint:
    structural_string = await page.evaluate(_STRUCTURAL_JS, list(config.ignore_selectors))

    dom_hash = hashlib.sha256(structural_string.encode()).hexdigest()[:16]
    normalized = normalize_url(page.url, config.ignore_url_params)

    return StateFingerprint(url=normalized, dom_hash=dom_hash)
