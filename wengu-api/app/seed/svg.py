"""内联 SVG 白名单净化（AGENTS §5；TICKETS P1-10）。

题库配图是上游分发的内联 SVG，按不可信 HTML 处理：只保留画图所需的标签与属性，
`script` / `on*` 事件 / `javascript:` 链接 / `foreignObject` 一律剥掉。
使用需求里既有的 bleach（不新增依赖），净化在后端装载时完成，前端只渲染净化后的字符串。
"""

from __future__ import annotations

import re

import bleach

# bleach 剥标签但保留标签内文本；脚本/样式正文本身不是配图内容，先整块删掉。
_BLOCK_ELEMENTS = re.compile(
    r"<\s*(script|style|foreignObject)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)

SVG_TAGS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "marker",
        "path",
        "line",
        "polyline",
        "polygon",
        "rect",
        "circle",
        "ellipse",
        "text",
        "tspan",
        "title",
        "desc",
    }
)

# html5lib 保留 SVG 属性的 camelCase（viewBox / markerWidth / refX …），按原样白名单。
SVG_ATTRIBUTES = {
    "*": [
        "xmlns",
        "viewBox",
        "preserveAspectRatio",
        "id",
        "class",
        "d",
        "points",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "width",
        "height",
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-dasharray",
        "stroke-linecap",
        "stroke-linejoin",
        "opacity",
        "transform",
        "clip-path",
        "marker-start",
        "marker-end",
        "markerWidth",
        "markerHeight",
        "refX",
        "refY",
        "orient",
        "font-family",
        "font-size",
        "font-weight",
        "text-anchor",
        "dominant-baseline",
    ]
}

_ALLOWED_PROTOCOLS = frozenset({"http", "https"})


def sanitize_svg(markup: object) -> str | None:
    """净化内联 SVG；空值/非字符串返回 None（拒绝把任意 HTML 当配图）。"""

    if not isinstance(markup, str) or not markup.strip():
        return None
    cleaned = bleach.clean(
        _BLOCK_ELEMENTS.sub("", markup),
        tags=sorted(SVG_TAGS),
        attributes=SVG_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return cleaned or None
