#! python3  # noqa: E265
import unicodedata as uni
from functools import lru_cache

from qgis.PyQt.QtWidgets import QToolBar


@lru_cache(maxsize=5)
def xpm_cursor(main_color: str = "#000000", buffer_color: str = "#FFFFFF") -> list:
    """Returns a XPM cursor"""
    return [
        "16 16 3 1",
        "      c None",
        f".     c {main_color}",
        f"+     c {buffer_color}",
        "                ",
        "       +.+      ",
        "      ++.++     ",
        "     +.....+    ",
        "    +.     .+   ",
        "   +.   .   .+  ",
        "  +.    .    .+ ",
        " ++.    .    .++",
        " ... ...+... ...",
        " ++.    .    .++",
        "  +.    .    .+ ",
        "   +.   .   .+  ",
        "   ++.     .+   ",
        "    ++.....+    ",
        "      ++.++     ",
        "       +.+      ",
    ]


def find_or_create_toolbar(iface, title: str) -> QToolBar:
    """Finds or create a new toolbar
    param iface: a QGIS interface
    param title: title of the toolbar to search or create
    """
    obj_name = title_normalize(title)
    toolbars = iface.mainWindow().findChildren(QToolBar, obj_name)
    if len(toolbars) >= 1:
        return toolbars[0]
    else:
        new_toolbar = iface.addToolBar(title)
        new_toolbar.setObjectName(obj_name)
        return new_toolbar


def title_normalize(title: str) -> str:
    """Normalizes a title
    param title: title to normalize by deleting spaces and uppercase letters
    """
    new_title = title.lower()
    new_title = "".join(
        c for c in uni.normalize("NFD", new_title) if uni.category(c) != "Mn"
    )
    # delete multi-spaces
    new_title = " ".join(new_title.split())
    chars_to_replace = [" ", "-"]
    for char in chars_to_replace:
        new_title = new_title.replace(char, "_")

    return new_title


def tolerance_threshold(distance: float) -> float:
    """Returns a tolerance from a distance
    param distance: a cartesian distance
    """
    return 0.014 * distance**0.5 + 0.0001 * distance + 0.03
