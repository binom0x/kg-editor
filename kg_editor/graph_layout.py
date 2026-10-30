"""Force-directed layout + интерактивная PyVis-визуализация графа знаний.

PyVis — основной и единственный способ визуализации:
  * рендерится в <iframe srcdoc> с тёмной темой;
  * имеет тот же размер, что раньше имел SVG (aspect-ratio 12/7, cap 700px);
  * перестраивается на каждое изменение графа через _refresh;
  * цвета узлов — из той же палитры, что в таблицах и Prolog-превью.

Функция render_svg оставлена для обратной совместимости (не используется
редактором). Основная точка входа — render_pyvis().

Требуется: pip install pyvis
"""
from __future__ import annotations

import math
import random
import traceback
from html import escape as _esc
from typing import Dict, List, Tuple

# ---- PyVis (опционально) ---------------------------------------------
try:
    from pyvis.network import Network  # type: ignore
    _PYVIS_OK = True
except ImportError:
    Network = None  # type: ignore
    _PYVIS_OK = False


# =====================================================================
# Палитра типов узлов (согласована с HTML-таблицами и Prolog-превью)
# =====================================================================
_TYPE_COLORS = {
    "concept": "#58a6ff",
    "person":  "#7ee787",
    "org":     "#f0883e",
    "organization": "#f0883e",
    "place":   "#d2a8ff",
    "loc":     "#d2a8ff",
    "event":   "#ff7b72",
    "thing":   "#79c0ff",
    "product": "#ffa657",
    "default": "#8b949e",
}


def _type_color(t: str) -> str:
    return _TYPE_COLORS.get((t or "").lower(), _TYPE_COLORS["default"])


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit - 1] + "…"


# =====================================================================
# Общий «пустой» контейнер — сохраняет размер, чтобы layout не прыгал
# =====================================================================
_EMPTY_STYLE = (
    "width:100%;aspect-ratio:12/7;max-height:700px;min-height:400px;"
    "border:1px dashed #3a4250;border-radius:6px;background:#21262d;"
    "display:flex;align-items:center;justify-content:center;"
    "color:#8b949e;font-family:ui-sans-serif,system-ui,sans-serif;"
    "font-size:12px;text-align:center;padding:16px;box-sizing:border-box;"
)


def _empty_html(msg: str, hint: str = "") -> str:
    hint_html = (f'<br><span style="color:#6e7681;font-size:11px;'
                 f'margin-top:8px;display:inline-block;">{hint}</span>'
                 if hint else "")
    return f'<div style="{_EMPTY_STYLE}">{_esc(msg)}{hint_html}</div>'


# =====================================================================
# PyVis — основной рендерер
# =====================================================================
_PYVIS_OPTIONS = """{
  "physics": {
    "enabled": true,
    "barnesHut": {
      "gravitationalConstant": -8000,
      "centralGravity": 0.3,
      "springLength": 180,
      "springConstant": 0.04,
      "damping": 0.09
    },
    "stabilization": {
      "enabled": true,
      "iterations": 300,
      "updateInterval": 50,
      "fit": true
    }
  },
  "interaction": {
    "hover": true,
    "navigationButtons": true,
    "keyboard": true,
    "tooltipDelay": 150,
    "zoomView": true,
    "dragView": true
  },
  "nodes": {
    "font": {
      "color": "#c7cbd1",
      "size": 14,
      "face": "ui-monospace, monospace",
      "strokeWidth": 4,
      "strokeColor": "#21262d"
    }
  },
  "edges": {
    "width": 2.5,
    "smooth": { "type": "continuous" },
    "color": {
      "color": "#8b949e",
      "highlight": "#58a6ff",
      "hover": "#a5d6ff"
    },
    "arrows": { "to": { "enabled": true, "scaleFactor": 0.8 } },
    "font": {
      "color": "#79c0ff",
      "size": 12,
      "face": "ui-monospace, monospace",
      "strokeWidth": 4,
      "strokeColor": "#21262d",
      "align": "middle"
    }
  }
}"""

# Замораживает physics сразу после stabilization.
# Без этого vis-network продолжает пересчитывать силы каждый кадр
# → «дрожит»/«вращается». Хук ставится на window.network — PyVis
# создаёт network как top-level var, поэтому он доступен глобально.
_PYVIS_FREEZE_JS = """
<script>
(function () {
    'use strict';

    function freeze(network) {
        var frozen = false;
        function doFreeze() {
            if (frozen) return;
            frozen = true;
            try { network.setOptions({ physics: false }); } catch (e) {}
        }
        try {
            network.once('stabilizationIterationsDone', doFreeze);
        } catch (e) {}
        // Fallback: если событие уже прошло или не сработает —
        // замораживаем по таймеру, чтобы не висеть в нестабильном виде.
        setTimeout(doFreeze, 2500);
    }

    function waitNetwork(tries) {
        tries = tries | 0;
        if (window.network
                && typeof window.network.setOptions === 'function') {
            freeze(window.network);
            return;
        }
        if (tries > 120) return;   // ~6 секунд ожидания, потом сдаёмся
        setTimeout(function () { waitNetwork(tries + 1); }, 50);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            waitNetwork(0);
        });
    } else {
        waitNetwork(0);
    }
})();
</script>
"""

def render_pyvis(graph,
                 height_ratio: str = "12/7",
                 max_height: int = 700,
                 min_height: int = 400) -> str:
    """Строит интерактивный PyVis-граф и вкладывает его в iframe (srcdoc)."""
    if not _PYVIS_OK:
        return _empty_html(
            "PyVis не установлен.",
            "pip install pyvis"
        )
    if graph is None or not getattr(graph, "nodes", None):
        return _empty_html(
            "",
            "Добавьте узлы — здесь появится интерактивная схема."
        )

    try:
        # ---- Степени — для размера узлов ----
        deg: Dict[str, int] = {nid: 0 for nid in graph.nodes}
        for e in graph.edges:
            if e.source in deg:
                deg[e.source] += 1
            if e.target in deg:
                deg[e.target] += 1

        # Вычисляем минимальную и максимальную степень для нормализации
        if deg:
            min_deg = min(deg.values())
            max_deg = max(deg.values())
        else:
            min_deg = max_deg = 0

        def _calc_node_size(d: int) -> int:
            min_size = 16
            max_size = 40  # Жесткий предел, чтобы хабы не закрывали весь экран
            if max_deg == min_deg:
                return (min_size + max_size) // 2
            
            # Нормализация: значение от 0 до 1
            norm = (d - min_deg) / (max_deg - min_deg)
            
            # Квадратный корень делает рост размера плавным:
            # если у узла 10% связей от максимального, он вырастет не на 10%, а на ~31%
            scale = norm ** 0.5
            
            return int(min_size + scale * (max_size - min_size))

        # ---- Строим сеть ----
        net = Network(
            height="100%",
            width="100%",
            bgcolor="#21262d",
            font_color="#c7cbd1",
            directed=True,
            cdn_resources="remote",
        )

        # ---- Узлы ----
        for nid, n in graph.nodes.items():
            color = _type_color(n.type)
            size = _calc_node_size(deg.get(nid, 0))
            net.add_node(
                nid,
                label=nid,
                title=f"{nid} ({n.type}) — degree {deg.get(nid, 0)}",
                color={
                    "background": color,
                    "border": "#0b0d11",
                    "highlight": {
                        "background": color,
                        "border": "#79c0ff",
                    },
                },
                shape="dot",
                size=size,
            )

        # ---- Рёбра (с увеличенной толщиной и контрастным цветом) ----
        for e in graph.edges:
            if e.source not in graph.nodes or e.target not in graph.nodes:
                continue
            net.add_edge(
                e.source, e.target,
                label=e.predicate,
                title=f"{e.source} —[{e.predicate}]→ {e.target}",
                arrows="to",
                width=2.5,
                color={"color": "#8b949e", "highlight": "#58a6ff", "hover": "#a5d6ff"},
                font={
                    "color": "#79c0ff",
                    "size": 12,
                    "face": "ui-monospace, monospace",
                    "strokeWidth": 4,
                    "strokeColor": "#21262d",
                },
                smooth={"type": "dynamic"},
            )

        net.set_options(_PYVIS_OPTIONS)
        html_content = net.generate_html()

        # ---- Цепочка height:100% от <body> до canvas ----
        _PYVIS_INJECT = (
            "html,body{margin:0;padding:0;height:100%;overflow:hidden;"
            "background:#21262d;}"
            "body>div{height:100%!important;margin:0!important;"
            "padding:0!important;}"
            ".card{height:100%!important;margin:0!important;"
            "padding:0!important;background:transparent!important;"
            "border:none!important;box-shadow:none!important;"
            "display:block!important;}"
            ".card-body{height:100%!important;margin:0!important;"
            "padding:0!important;display:block!important;}"
            "#mynetwork{height:100%!important;width:100%!important;"
            "display:block!important;border:none!important;"
            "background:#21262d!important;}"
            "#mynetwork>canvas{outline:none!important;"
            "display:block!important;}"
            "#loadingBar{background:#21262d!important;"
            "border:none!important;}"
            "#loadingBar>.lds-ring>div{"
            "border-color:#58a6ff transparent transparent transparent"
            "!important;}"

            # === Навигационные кнопки vis-network ===
            ".vis-network .vis-navigation{"
            "background:transparent!important;}"
            ".vis-network .vis-navigation .vis-button{"
            "background-color:transparent!important;"
            "filter:brightness(0) invert(1)"
            "drop-shadow(0 1px 2px rgba(0,0,0,0.9))!important;"
            "opacity:0.85!important;"
            "border-radius:6px!important;"
            "transition:opacity 0.15s ease,filter 0.15s ease!important;}"
            ".vis-network .vis-navigation .vis-button:hover{"
            "opacity:1!important;"
            "filter:brightness(0) invert(1)"
            "drop-shadow(0 0 4px rgba(88,166,255,0.7))!important;}"
            ".vis-network .vis-close{"
            "filter:brightness(0) invert(1)!important;"
            "opacity:0.85!important;}"
            ".vis-network .vis-close:hover{"
            "opacity:1!important;}"

            # === Тултип при наведении ===
            "div.vis-tooltip{"
            "background-color:#161a20!important;"
            "border:1px solid #2a313d!important;"
            "color:#c7cbd1!important;"
            "border-radius:4px!important;"
            "box-shadow:0 2px 8px rgba(0,0,0,0.6)!important;"
            "font-family:ui-monospace,monospace!important;"
            "font-size:11px!important;"
            "padding:6px 10px!important;"
            "pointer-events:none!important;}"
        )
        html_content = html_content.replace(
            "</head>",
            f"<style>{_PYVIS_INJECT}</style></head>",
        )
        html_content = html_content.replace(
            "</body>",
            _PYVIS_FREEZE_JS + "</body>",
        )

        escaped = _esc(html_content)   # html.escape(quote=True) → srcdoc-safe

        # ---- Обёртка ----
        wrapper_style = (
            f"width:100%;"
            f"aspect-ratio:{height_ratio};"
            f"max-height:{max_height}px;"
            f"min-height:{min_height}px;"
            f"position:relative;"
            f"border:1px solid #3a4250;"
            f"border-radius:6px;"
            f"overflow:hidden;"
            f"background:#21262d;"
        )
        iframe_style = (
            "position:absolute;inset:0;width:100%;height:100%;"
            "border:none;display:block;background:#21262d;"
        )

        return (
            f'<div class="pyvis-wrap" style="{wrapper_style}">'
            '<button class="graph-fs-btn" title="Развернуть на весь экран" '
            'onclick="window.toggleGraphFullscreen(this)">⛶</button>'
            f'<iframe srcdoc="{escaped}" style="{iframe_style}" '
            'sandbox="allow-scripts allow-same-origin allow-popups">'
            '</iframe></div>'
        )
    except Exception as e:  # noqa: BLE001
        return (
            '<div style="color:#ff7b72;padding:16px;font-size:12px;'
            'font-family:ui-monospace,monospace;white-space:pre-wrap;'
            'border:1px solid #f8514966;border-radius:6px;'
            'background:#21262d;">'
            f'PyVis ошибка: {_esc(str(e))}\n\n'
            f'{_esc(traceback.format_exc())}'
            '</div>'
        )


# =====================================================================
# SVG — оставлено для обратной совместимости (редактором не используется)
# =====================================================================
def spring_layout(node_ids: List[str],
                  edges: List[Tuple[str, str]],
                  iterations: int = 200,
                  seed: int = 42,
                  canvas: int = 1200) -> Dict[str, Tuple[float, float]]:
    rnd = random.Random(seed)
    n = len(node_ids)
    if n == 0:
        return {}
    if n == 1:
        return {node_ids[0]: (canvas / 2, canvas / 2)}
    pos = {nid: (rnd.uniform(0, canvas), rnd.uniform(0, canvas))
           for nid in node_ids}
    k = math.sqrt(canvas * canvas / max(1, n))
    for it in range(iterations):
        t = 1.0 - it / iterations
        disp = {nid: [0.0, 0.0] for nid in node_ids}
        for i in range(n):
            for j in range(i + 1, n):
                a, b = node_ids[i], node_ids[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) or 0.01
                f = k * k / d
                dxn, dyn = dx / d, dy / d
                disp[a][0] += dxn * f
                disp[a][1] += dyn * f
                disp[b][0] -= dxn * f
                disp[b][1] -= dyn * f
        for s, tgt in edges:
            if s not in pos or tgt not in pos or s == tgt:
                continue
            dx = pos[s][0] - pos[tgt][0]
            dy = pos[s][1] - pos[tgt][1]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k
            dxn, dyn = dx / d, dy / d
            disp[s][0] -= dxn * f
            disp[s][1] -= dyn * f
            disp[tgt][0] += dxn * f
            disp[tgt][1] += dyn * f
        for nid in node_ids:
            dx, dy = disp[nid]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, 20 * t) / d
            x = max(20, min(canvas - 20, pos[nid][0] + dx * step))
            y = max(20, min(canvas - 20, pos[nid][1] + dy * step))
            pos[nid] = (x, y)
    return pos


def render_svg(graph, width: int = 1200, height: int = 700) -> str:
    """Статический SVG. Не используется редактором, оставлено для совместимости."""
    if graph is None or not getattr(graph, "nodes", None):
        return _empty_html("Граф пуст.")
    node_ids = list(graph.nodes.keys())
    edge_pairs = [(e.source, e.target) for e in graph.edges
                  if e.source in graph.nodes and e.target in graph.nodes]
    deg = {nid: 0 for nid in node_ids}
    for e in graph.edges:
        if e.source in deg: deg[e.source] += 1
        if e.target in deg: deg[e.target] += 1
    pos = spring_layout(node_ids, edge_pairs, iterations=200, seed=42,
                        canvas=1200)
    xs = [pos[n][0] for n in node_ids]
    ys = [pos[n][1] for n in node_ids]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    pad = 80

    def tx(x): return (pad + (x - minx) / (maxx - minx) * (width - 2 * pad)
                       if maxx - minx > 1e-6 else width / 2)
    def ty(y): return (pad + (y - miny) / (maxy - miny) * (height - 2 * pad)
                       if maxy - miny > 1e-6 else height / 2)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 {width} {height}" '
           f'style="background:#0b0d11;border:1px solid #2a313d;'
           f'border-radius:6px;width:100%;display:block;">',
           '<defs><marker id="arr" markerWidth="10" markerHeight="10" '
           'refX="10" refY="3" orient="auto" markerUnits="userSpaceOnUse">'
           '<path d="M0,0 L0,6 L9,3 z" fill="#58a6ff"/></marker></defs>']
    for e in graph.edges:
        if e.source not in pos or e.target not in pos or e.source == e.target:
            continue
        x1, y1 = tx(pos[e.source][0]), ty(pos[e.source][1])
        x2, y2 = tx(pos[e.target][0]), ty(pos[e.target][1])
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                   f'y2="{y2:.1f}" stroke="#3a4250" stroke-width="1.5" '
                   f'marker-end="url(#arr)"/>')
    for nid in node_ids:
        n = graph.nodes[nid]
        x, y = tx(pos[nid][0]), ty(pos[nid][1])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" '
                   f'fill="{_type_color(n.type)}" fill-opacity="0.85" '
                   f'stroke="#0b0d11" stroke-width="2"/>')
        out.append(f'<text x="{x:.1f}" y="{y + 27:.1f}" fill="#c7cbd1" '
                   f'font-size="11" text-anchor="middle" '
                   f'font-family="ui-monospace,monospace">{_esc(nid)}</text>')
    out.append('</svg>')
    return ''.join(out)