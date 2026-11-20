"""Ícones da interface: traços simples (24×24), servidos como um sprite SVG no layout.

Uso nos templates: `{{ icon('home') }}`. No JavaScript: `<svg class="i"><use href="#i-home"/></svg>`.
Os ícones das redes são desenhos genéricos, não os logotipos oficiais.
"""

from markupsafe import Markup

ICONS: dict[str, str] = {
    "home": '<path d="M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z"/>',
    "operations": '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M10 8.5v7l6-3.5z"/>',
    "queue": '<path d="M4 13h4.5l1.5 2.5h4l1.5-2.5H20"/><path d="M6 4h12l2 9v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6z"/>',
    "approval": '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m8 12.5 3 3 5.5-6.5"/>',
    "chart": '<path d="M5 20V11M12 20V4M19 20v-6"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.4 3.2-5.2 6.5-5.2s5.9 1.8 6.5 5.2"/><path d="M16 4.6a3.3 3.3 0 0 1 0 6.4M17.6 14.9c2.1.6 3.5 2.3 3.9 5.1"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-up": '<path d="m6 15 6-6 6 6"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "save": '<path d="M5 3h11l3 3v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="currentColor"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "grid": '<circle cx="6" cy="6" r="1.4"/><circle cx="12" cy="6" r="1.4"/><circle cx="18" cy="6" r="1.4"/><circle cx="6" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18" cy="12" r="1.4"/><circle cx="6" cy="18" r="1.4"/><circle cx="12" cy="18" r="1.4"/><circle cx="18" cy="18" r="1.4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
    "log": '<path d="M6 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v4h4M8.5 12h7M8.5 16h7"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "fit": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
    "map": '<rect x="3" y="5" width="18" height="14" rx="2"/><rect x="6" y="8" width="7" height="5" rx="1"/>',
    "cursor": '<path d="M5.5 3.5 19 10l-6 1.8-2.2 6.2z" fill="currentColor"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4v4.5H8M12 7.5V12l3 2"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7.5 4v16M16.5 4v16M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"/><path d="M10.5 9.5v5l4-2.5z" fill="currentColor"/>',
    "send": '<path d="M21 3 10 14"/><path d="M21 3 14.5 21l-4.5-7-7-4.5z"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="m21 15.5-5-5L5 20"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7"/>',
    "check-box": '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="m8 12.5 3 3 5-6"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "alert": '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4M12 17v.5"/>',
    "trash": '<path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "upload": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "dots": '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
    "logout": '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 8l-4 4 4 4M6 12h10"/>',
    "audio": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "frame": '<rect x="3" y="3" width="18" height="18" rx="3"/><rect x="7.5" y="5.5" width="9" height="13" rx="1.5"/>',
    "mask": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 15h18M8 3v18" opacity=".5"/>',
    "stamp": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M13 17h5v-3h-5z"/>',
    "text": '<path d="M5 6V4.5h14V6M12 4.5v15M9 19.5h6"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "broom": '<path d="m14 4-4.5 8M6 14h9l1 6H5z"/>',
    "account": '<circle cx="12" cy="9" r="3.5"/><path d="M5 20c.9-3.5 3.6-5 7-5s6.1 1.5 7 5"/>',
    "shield": '<path d="M12 3 4.5 6v6c0 4.2 3.1 7.6 7.5 9 4.4-1.4 7.5-4.8 7.5-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "database": '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16.5 6.5l2.5 2.5"/>',
    # Redes (desenhos genéricos)
    "reddit": '<circle cx="12" cy="13.5" r="6.5"/><circle cx="9.5" cy="13" r="1" fill="currentColor"/><circle cx="14.5" cy="13" r="1" fill="currentColor"/><path d="M9.5 16.2c1.5 1 3.5 1 5 0M12 7l1.2-3.5 3.3.8"/><circle cx="17.5" cy="4.8" r="1.3"/>',
    "x-logo": '<path d="M4.5 4.5 19.5 19.5M19.5 4.5 4.5 19.5"/>',
    "youtube": '<rect x="2.5" y="5.5" width="19" height="13" rx="4"/><path d="M10 9.2v5.6l4.8-2.8z" fill="currentColor"/>',
    "tiktok": '<path d="M13 4v10.5a3.5 3.5 0 1 1-3.5-3.5"/><path d="M13 4c.4 2.6 2.2 4.3 5 4.6"/>',
    "instagram": '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17" cy="7" r="1" fill="currentColor"/>',
}


def sprite() -> Markup:
    symbols = "".join(
        f'<symbol id="i-{name}" viewBox="0 0 24 24">{body}</symbol>' for name, body in ICONS.items()
    )
    return Markup(
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">'
        f"{symbols}</svg>"
    )


def icon(name: str, cls: str = "") -> Markup:
    if name not in ICONS:
        name = "dots"
    return Markup(f'<svg class="i {cls}" aria-hidden="true"><use href="#i-{name}"/></svg>')
