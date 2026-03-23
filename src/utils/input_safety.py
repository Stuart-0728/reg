import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

_TAG_RE = re.compile(r"<[^>]+>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EVENT_JS_RE = re.compile(r"(?i)(javascript:|data:text/html|<\s*script|on\w+\s*=)")
_SAFE_HTML_TAGS = {
    'a', 'p', 'br', 'ul', 'ol', 'li', 'strong', 'em', 'b', 'i', 'u', 'code', 'pre', 'blockquote'
}
_VOID_TAGS = {'br'}
_SAFE_A_TARGETS = {'_blank', '_self'}


def _is_safe_href(href):
    if not href:
        return False
    try:
        candidate = href.strip()
        parsed = urlparse(candidate)
        if parsed.scheme in ('', 'http', 'https', 'mailto', 'tel'):
            return True
        return False
    except Exception:
        return False


class _SafeHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        tag = (tag or '').lower()
        if tag not in _SAFE_HTML_TAGS:
            return

        if tag == 'a':
            attr_map = {k.lower(): (v or '') for k, v in attrs if k}
            href = attr_map.get('href', '').strip()
            if not _is_safe_href(href):
                return

            escaped_href = html.escape(href, quote=True)
            title = html.escape(attr_map.get('title', ''), quote=True)
            target = attr_map.get('target', '').strip().lower()
            if target not in _SAFE_A_TARGETS:
                target = ''

            rendered = f'<a href="{escaped_href}"'
            if title:
                rendered += f' title="{title}"'
            if target:
                rendered += f' target="{target}"'
            # 统一加 rel，降低新窗口与SEO滥用风险
            rendered += ' rel="noopener noreferrer nofollow">'
            self.parts.append(rendered)
            return

        self.parts.append(f'<{tag}>')

    def handle_endtag(self, tag):
        tag = (tag or '').lower()
        if tag in _SAFE_HTML_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(html.escape(data or ''))

    def get_html(self):
        return ''.join(self.parts)


def sanitize_plain_text(value, *, allow_multiline=False, max_length=None):
    """Normalize untrusted user text for storage/display.

    Returns a safe plain-text string by stripping HTML tags, control chars and
    obvious script/event patterns. This function is intentionally conservative.
    """
    text = '' if value is None else str(value)
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    if not allow_multiline:
        text = text.replace('\n', ' ')

    text = _TAG_RE.sub('', text)
    text = _EVENT_JS_RE.sub('', text)
    text = _CONTROL_RE.sub('', text)
    text = text.strip()

    if max_length is not None and max_length > 0:
        text = text[:max_length]

    return text


def sanitize_rich_html(value, *, max_length=None):
    """Sanitize rich-text HTML with a strict allowlist for safe rendering.

    Allowed tags are intentionally small and focused on announcement/notification
    formatting and hyperlinks.
    """
    text = '' if value is None else str(value)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = _CONTROL_RE.sub('', text)

    try:
        parser = _SafeHtmlParser()
        parser.feed(text)
        parser.close()
        sanitized = parser.get_html().strip()
    except Exception:
        sanitized = sanitize_plain_text(text, allow_multiline=True)

    if max_length is not None and max_length > 0:
        sanitized = sanitized[:max_length]

    return sanitized
