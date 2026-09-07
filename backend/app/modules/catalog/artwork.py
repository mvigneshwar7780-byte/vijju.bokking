"""Generated placeholder artwork.

Real film posters are copyrighted, so the demo needs stand-in images. It used an
external placeholder service, which meant every poster in the app depended on a
third-party host being reachable -- and on a filtered network, or behind an
extension that blocks unknown image hosts, the entire grid rendered blank while
the API happily reported valid URLs.

Serving the SVG ourselves removes that variable: same origin, no third party, no
rate limit, and it works with the network cable pulled out. The image is drawn
from the title alone, so any film an operator adds without a poster still gets
one.
"""

from __future__ import annotations

from hashlib import blake2b
from xml.sax.saxutils import escape

# (background, foreground) pairs, all comfortably above 4.5:1 contrast so the
# title stays readable at thumbnail size.
_INKS: tuple[tuple[str, str], ...] = (
    ("#1e1b4b", "#c7d2fe"),  # indigo
    ("#7f1d1d", "#fecaca"),  # crimson
    ("#064e3b", "#a7f3d0"),  # forest
    ("#78350f", "#fde68a"),  # amber
    ("#581c87", "#e9d5ff"),  # violet
    ("#0c4a6e", "#bae6fd"),  # ocean
    ("#3f1d38", "#fbcfe8"),  # plum
    ("#134e4a", "#99f6e4"),  # teal
    ("#422006", "#fed7aa"),  # umber
    ("#1e293b", "#e2e8f0"),  # slate
)


def _ink(title: str) -> tuple[str, str]:
    """Pick a colour pair from the title.

    Hashed rather than random so a film keeps its colour across re-seeds and
    between processes -- a poster that changed hue on every restart would look
    like a bug.
    """
    digest = blake2b(title.encode("utf-8"), digest_size=2).digest()
    return _INKS[int.from_bytes(digest, "big") % len(_INKS)]


def _wrap(title: str, per_line: int) -> list[str]:
    """Greedy word wrap. Long single words are left to overflow rather than
    hyphenated -- a broken word reads worse than a slightly wide line."""
    lines: list[str] = []
    current = ""
    for word in title.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= per_line or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def poster_svg(title: str, width: int = 400, height: int = 600) -> str:
    """An SVG card carrying the film's title."""
    bg, fg = _ink(title)

    # Type scales with the card so one function serves posters and backdrops.
    size = max(14, int(min(width, height) * 0.085))
    per_line = max(8, int(width / (size * 0.58)))
    lines = _wrap(title, per_line)

    leading = size * 1.25
    start = height / 2 - (len(lines) - 1) * leading / 2

    spans = "".join(
        f'<text x="{width / 2:.0f}" y="{start + i * leading:.0f}" fill="{fg}" '
        f'font-family="Georgia,\'Times New Roman\',serif" font-size="{size}" '
        f'font-weight="700" text-anchor="middle">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )

    # A faint rule under the title, and a border, so the card reads as artwork
    # rather than a failed image.
    rule_y = start + (len(lines) - 1) * leading + size * 0.9
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        f'<rect width="{width}" height="{height}" fill="{bg}"/>'
        f'<rect x="6" y="6" width="{width - 12}" height="{height - 12}" fill="none" '
        f'stroke="{fg}" stroke-opacity="0.28" stroke-width="1.5"/>'
        f'{spans}'
        f'<rect x="{width / 2 - size:.0f}" y="{rule_y:.0f}" width="{size * 2:.0f}" '
        f'height="2" fill="{fg}" fill-opacity="0.5"/>'
        f"</svg>"
    )
