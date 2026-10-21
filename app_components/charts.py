"""Plotly figure builders for the UI. Pure functions (no Streamlit import) so they can be rendered to PNG in tests.

Design (dataviz skill): one y-axis per chart (no dual axes), thin 2px lines, >=8px markers with a 2px surface ring,
recessive grid, text in ink tokens (never series colour), status colours reserved for risk zones and carried with text
labels, legends present for >=2 series, light AND dark token sets (``mode`` = "light" | "dark").
Missing values are gaps (None), never zeros.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

import plotly.graph_objects as go

from .formatting import (PEER_METRIC_LABELS, ZONES, finite, flag_label, agent_of_flag, AGENT_LABELS)

TOKENS = {
    "light": {"ink": "#0b0b0b", "ink2": "#52514e", "grid": "rgba(0,0,0,0.09)", "ring": "#ffffff", "series1": "#2a78d6",
              "series2": "#eb6834", "series3": "#1baf7a", "series4": "#eda100", "muted": "#8a8985", "template": "plotly_white"},
    "dark": {"ink": "#f2f2ee", "ink2": "#c3c2b7", "grid": "rgba(255,255,255,0.12)", "ring": "#0e1117", "series1": "#3987e5",
             "series2": "#d95926", "series3": "#199e70", "series4": "#c98500", "muted": "#9a9a94", "template": "plotly_dark"},
}
ZONE_ALPHA = {"light": 0.16, "dark": 0.20}
FLAG_RED = "#d03b3b"


def tok(mode: str) -> dict:
    return TOKENS["dark" if mode == "dark" else "light"]


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def _base(mode: str, height: int = 360, title: str = "") -> go.Figure:
    t = tok(mode)
    fig = go.Figure()
    fig.update_layout(
        template=t["template"], height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=13, color=t["ink"]),
        title=dict(text=title, x=0.0, xanchor="left", font=dict(size=15, color=t["ink"])) if title else None,
        margin=dict(l=56, r=24, t=56 if title else 24, b=48), hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0, font=dict(color=t["ink2"])),
    )
    fig.update_xaxes(showgrid=False, linecolor=t["grid"], tickfont=dict(color=t["ink2"]), zeroline=False)
    fig.update_yaxes(gridcolor=t["grid"], zeroline=False, tickfont=dict(color=t["ink2"]), linecolor=t["grid"])
    return fig


def _year_axis(fig: go.Figure, years: Sequence[int]) -> None:
    if years:
        fig.update_xaxes(tickmode="array", tickvals=list(years), ticktext=[f"FY{y}" for y in years],
                         range=[min(years) - 0.5, max(years) + 0.5])


def _zone_label_annot(fig, y, text, mode, xref="paper", x=1.0):
    fig.add_annotation(xref=xref, x=x, y=y, text=text, showarrow=False, xanchor="right", yanchor="middle",
                       font=dict(size=11, color=tok(mode)["ink2"]), bgcolor="rgba(0,0,0,0)")


# --------------------------------------------------------------------------------------------- forensic timeline
def timeline_chart(timeline: list[dict], first_detection_year: Optional[int] = None, mode: str = "light",
                   height: int = 460) -> go.Figure:
    """The headline visual: suspicion score by fiscal year over green/yellow/orange/red zones + flag markers."""
    t = tok(mode)
    fig = _base(mode, height)
    for lo, hi, name, col in ZONES:
        fig.add_hrect(y0=lo, y1=hi, fillcolor=_rgba(col, ZONE_ALPHA[mode]), line_width=0, layer="below")
        fig.add_annotation(xref="paper", x=0.995, y=(lo + hi) / 2, text=f"<b>{name.upper()}</b> {lo}-{hi}", showarrow=False,
                           xanchor="right", yanchor="middle", font=dict(size=11, color=t["ink2"]))
    rows = [r for r in timeline if isinstance(r.get("year"), int)]
    years = [r["year"] for r in rows]
    scores = [finite(r.get("suspicion_score")) for r in rows]
    if not rows:
        fig.add_annotation(text="No timeline data (temporal agent unavailable)", xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(size=14, color=t["ink2"]))
        fig.update_yaxes(range=[0, 100])
        return fig
    hover = []
    for r in rows:
        nf = r.get("new_flags_this_year") or []
        txt = (f"<b>FY{r['year']}</b><br>Suspicion score: {r.get('suspicion_score')}<br>Level: {r.get('risk_level')}"
               f"<br>Signal change: {r.get('signal_change')}<br>Flags fired: {r.get('flags_fired')}")
        if nf:
            txt += "<br><b>New this year:</b><br>" + "<br>".join("&bull; " + flag_label(f) for f in nf[:8])
            if len(nf) > 8:
                txt += f"<br>&hellip; +{len(nf) - 8} more"
        hover.append(txt)
    fig.add_trace(go.Scatter(
        x=years, y=scores, mode="lines+markers", name="Suspicion score", line=dict(color=t["series1"], width=3),
        marker=dict(size=11, color=t["series1"], line=dict(color=t["ring"], width=2)), hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>", connectgaps=False))
    # flag markers: years where new flags appeared
    fx, fy, ftxt, fhov = [], [], [], []
    for r, s, h in zip(rows, scores, hover):
        nf = r.get("new_flags_this_year") or []
        if nf and s is not None:
            fx.append(r["year"]); fy.append(s); ftxt.append(f"+{len(nf)} new"); fhov.append(h)
    if fx:
        fig.add_trace(go.Scatter(
            x=fx, y=fy, mode="markers+text", name="Year with new flags", text=ftxt, textposition="top center",
            textfont=dict(size=12, color=t["ink"]), marker=dict(symbol="diamond", size=18, color="rgba(0,0,0,0)",
                                                                 line=dict(color=FLAG_RED, width=3)),
            hovertext=fhov, hovertemplate="%{hovertext}<extra></extra>", cliponaxis=False))
    if first_detection_year in years:
        fig.add_shape(type="line", x0=first_detection_year, x1=first_detection_year, y0=0, y1=100, layer="below",
                      line=dict(color=t["ink2"], width=2, dash="dash"))
        fig.add_annotation(x=first_detection_year, y=3, yref="y", text=f"<b>First detection FY{first_detection_year}</b>",
                           showarrow=False, xanchor="left", xshift=6, yanchor="bottom", font=dict(size=12, color=t["ink"]))
    _year_axis(fig, years)
    fig.update_yaxes(range=[0, 100], tickvals=[0, 30, 60, 80, 100], title_text="Suspicion score (0-100)")
    fig.update_layout(margin=dict(l=64, r=24, t=64, b=48), legend=dict(y=1.08))
    return fig


# --------------------------------------------------------------------------------------------- banded line (Beneish/Altman)
def banded_line(title: str, years: Sequence[int], values: Sequence[Optional[float]], bands: Sequence[tuple],
                ytitle: str, flags: Sequence[bool], mode: str = "light", height: int = 340,
                value_name: str = "value", hover_extra: Optional[Sequence[str]] = None) -> go.Figure:
    """Line of one metric per year over labelled zone bands. bands = [(lo, hi, label, hex)] (lo/hi may be None=open)."""
    t = tok(mode)
    fig = _base(mode, height, title)
    vals = [finite(v) for v in values]
    present = [v for v in vals if v is not None]
    lo_all = min(present + [b[0] for b in bands if b[0] is not None], default=0)
    hi_all = max(present + [b[1] for b in bands if b[1] is not None], default=1)
    pad = (hi_all - lo_all) * 0.12 or 1
    ymin, ymax = lo_all - pad, hi_all + pad
    for lo, hi, label, col in bands:
        y0 = ymin if lo is None else lo
        y1 = ymax if hi is None else hi
        fig.add_hrect(y0=y0, y1=y1, fillcolor=_rgba(col, ZONE_ALPHA[mode]), line_width=0, layer="below")
        fig.add_annotation(xref="paper", x=0.995, y=(max(y0, ymin) + min(y1, ymax)) / 2, text=label, showarrow=False,
                           xanchor="right", yanchor="middle", font=dict(size=11, color=t["ink2"]))
    hov = [f"<b>FY{y}</b><br>{value_name}: {'unavailable' if v is None else f'{v:.2f}'}" + (f"<br>{hover_extra[i]}" if hover_extra else "")
           for i, (y, v) in enumerate(zip(years, vals))]
    fig.add_trace(go.Scatter(x=list(years), y=vals, mode="lines+markers", name=value_name, line=dict(color=t["series1"], width=2),
                             marker=dict(size=10, color=t["series1"], line=dict(color=t["ring"], width=2)), hovertext=hov,
                             hovertemplate="%{hovertext}<extra></extra>", connectgaps=False))
    fx = [y for y, v, f in zip(years, vals, flags) if f and v is not None]
    fy = [v for v, f in zip(vals, flags) if f and v is not None]
    if fx:
        fig.add_trace(go.Scatter(x=fx, y=fy, mode="markers", name="Flag fired", hoverinfo="skip",
                                 marker=dict(symbol="diamond", size=17, color="rgba(0,0,0,0)", line=dict(color=FLAG_RED, width=3))))
    _year_axis(fig, list(years))
    fig.update_yaxes(range=[ymin, ymax], title_text=ytitle)
    return fig


def small_trend(title: str, years: Sequence[int], values: Sequence[Optional[float]], flags: Sequence[bool], ytitle: str,
                mode: str = "light", threshold: Optional[float] = None, threshold_label: str = "", height: int = 280,
                value_name: str = "value", fmt: str = ".2f") -> go.Figure:
    t = tok(mode)
    fig = _base(mode, height, title)
    vals = [finite(v) for v in values]
    hov = [f"<b>FY{y}</b><br>{value_name}: {'unavailable' if v is None else format(v, fmt)}" for y, v in zip(years, vals)]
    fig.add_trace(go.Scatter(x=list(years), y=vals, mode="lines+markers", name=value_name, line=dict(color=t["series1"], width=2),
                             marker=dict(size=9, color=t["series1"], line=dict(color=t["ring"], width=2)), hovertext=hov,
                             hovertemplate="%{hovertext}<extra></extra>", connectgaps=False))
    fx = [y for y, v, f in zip(years, vals, flags) if f and v is not None]
    fy = [v for v, f in zip(vals, flags) if f and v is not None]
    if fx:
        fig.add_trace(go.Scatter(x=fx, y=fy, mode="markers", name="Flag fired", hoverinfo="skip",
                                 marker=dict(symbol="diamond", size=16, color="rgba(0,0,0,0)", line=dict(color=FLAG_RED, width=3))))
    if threshold is not None:
        fig.add_hline(y=threshold, line=dict(color=t["ink2"], width=1.5, dash="dash"), annotation_text=threshold_label,
                      annotation_position="top left", annotation_font=dict(size=11, color=t["ink2"]))
    _year_axis(fig, list(years))
    fig.update_yaxes(title_text=ytitle)
    fig.update_layout(margin=dict(l=56, r=16, t=56, b=40), legend=dict(y=1.12, font=dict(size=11)))
    return fig


# --------------------------------------------------------------------------------------------- radar
RADAR_CLIP = 4.0


def radar_chart(metric_zscores: dict, mode: str = "light", height: int = 460) -> tuple[go.Figure, list[str]]:
    """Radar of company z-scores vs the peer mean (=0 ring). z clipped to +/-4 for display only (listed in the returned
    notes). Metrics with an undefined z-score are omitted from the radar (they stay in the table)."""
    t = tok(mode)
    fig = _base(mode, height)
    axes, zs, hov, notes = [], [], [], []
    for m, d in metric_zscores.items():
        z = finite(d.get("z_score"))
        if z is None:
            continue
        label = PEER_METRIC_LABELS.get(m, m)
        zc = max(-RADAR_CLIP, min(RADAR_CLIP, z))
        if zc != z:
            notes.append(f"{label}: z={z:+.1f} drawn at the {zc:+.0f} edge (display clip)")
        axes.append(label); zs.append(zc)
        hov.append(f"<b>{label}</b><br>company {d.get('company_value'):.4g} vs peer mean {d.get('peer_mean'):.4g}<br>z = {z:+.2f}"
                   f"<br>{'FLAG (|z|>2)' if d.get('flag') else 'within 2 sd'}")
    if len(axes) < 3:
        return fig, notes
    close = lambda xs: list(xs) + [xs[0]]  # noqa: E731
    for r, name, dash, col in ((2.0, "+2 sd flag line", "dot", t["muted"]), (-2.0, "-2 sd flag line", "dot", t["muted"])):
        fig.add_trace(go.Scatterpolar(r=[r] * (len(axes) + 1), theta=close(axes), mode="lines", name=name,
                                      line=dict(color=col, width=1, dash=dash), hoverinfo="skip", showlegend=(r > 0)))
    fig.update_traces(selector=dict(name="+2 sd flag line"), name="+/-2 sd flag lines")
    fig.add_trace(go.Scatterpolar(r=[0] * (len(axes) + 1), theta=close(axes), mode="lines", name="Peer mean (z = 0)",
                                  line=dict(color=t["ink2"], width=2, dash="dash"), hoverinfo="skip"))
    fig.add_trace(go.Scatterpolar(r=close(zs), theta=close(axes), mode="lines+markers", name="Company (z-score)",
                                  line=dict(color=t["series1"], width=3),
                                  marker=dict(size=10, color=t["series1"], line=dict(color=t["ring"], width=2)),
                                  hovertext=close(hov), hovertemplate="%{hovertext}<extra></extra>"))
    fig.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)",
                                 radialaxis=dict(range=[-RADAR_CLIP, RADAR_CLIP], tickvals=[-4, -2, 0, 2, 4], gridcolor=t["grid"],
                                                 linecolor=t["grid"], tickfont=dict(size=10, color=t["ink2"])),
                                 angularaxis=dict(gridcolor=t["grid"], linecolor=t["grid"], tickfont=dict(size=12, color=t["ink"]))),
                      margin=dict(l=80, r=80, t=40, b=40), legend=dict(y=-0.08, yanchor="top", x=0.5, xanchor="center"))
    return fig, notes


# --------------------------------------------------------------------------------------------- misc
def stacked_flags_chart(timeline: list[dict], mode: str = "light", height: int = 320) -> go.Figure:
    """Flags fired per year, stacked by agent (identity encoded by legend + hover, 2px surface gaps between segments)."""
    t = tok(mode)
    fig = _base(mode, height, "Flags fired per year, by agent")
    order = [("quantitative", t["series1"]), ("language", t["series2"]), ("network", t["series3"]), ("peer", t["series4"])]
    years = [r["year"] for r in timeline if isinstance(r.get("year"), int)]
    for agent, col in order:
        ys = [sum(1 for f in (r.get("flags") or []) if agent_of_flag(f) == agent) for r in timeline if isinstance(r.get("year"), int)]
        fig.add_trace(go.Bar(x=years, y=ys, name=AGENT_LABELS[agent], marker=dict(color=col, line=dict(color=t["ring"], width=2)),
                             hovertemplate=f"{AGENT_LABELS[agent]}: %{{y}} flag(s)<extra>FY%{{x}}</extra>"))
    fig.update_layout(barmode="stack", bargap=0.45)
    _year_axis(fig, years)
    fig.update_yaxes(title_text="Flags fired", dtick=1)
    return fig


def risk_history_chart(history: list[dict], mode: str = "light", height: int = 400) -> tuple[go.Figure, int]:
    """Watchlist history: suspicion score per analysis date. Rows without a score are skipped (returned count)."""
    t = tok(mode)
    fig = _base(mode, height)
    for lo, hi, name, col in ZONES:
        fig.add_hrect(y0=lo, y1=hi, fillcolor=_rgba(col, ZONE_ALPHA[mode]), line_width=0, layer="below")
        fig.add_annotation(xref="paper", x=0.995, y=(lo + hi) / 2, text=name.upper(), showarrow=False, xanchor="right",
                           font=dict(size=11, color=t["ink2"]))
    pts = [(h.get("analysis_date"), finite(h.get("suspicion_score")), h.get("risk_grade") or "Unknown", h.get("flags_fired")) for h in history]
    skipped = sum(1 for p in pts if p[1] is None)
    pts = [p for p in pts if p[1] is not None]
    if pts:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines+markers", name="Suspicion score",
            line=dict(color=t["series1"], width=2), marker=dict(size=11, color=t["series1"], line=dict(color=t["ring"], width=2)),
            hovertext=[f"<b>{p[0]}</b><br>Score {p[1]:.0f} | grade {p[2]}<br>Flags fired: {p[3]}" for p in pts],
            hovertemplate="%{hovertext}<extra></extra>"))
    fig.update_yaxes(range=[0, 100], title_text="Suspicion score (0-100)", tickvals=[0, 30, 60, 80, 100])
    fig.update_xaxes(title_text="Analysis date")
    return fig, skipped


def hbar(title: str, labels: Sequence[str], series: Sequence[tuple], xtitle: str, mode: str = "light", height: int = 340,
         texttemplate: str = "%{x:.0f}", xrange: Optional[tuple] = None) -> go.Figure:
    """Horizontal bars. series = [(name, values, hex_or_None)]. Single series needs no legend."""
    t = tok(mode)
    fig = _base(mode, height, title)
    cols = [t["series1"], t["series2"], t["series3"], t["series4"]]
    for i, (name, vals, col) in enumerate(series):
        fig.add_trace(go.Bar(y=list(labels), x=[finite(v) for v in vals], orientation="h", name=name,
                             marker=dict(color=col or cols[i % 4], line=dict(color=t["ring"], width=2)),
                             text=[None if finite(v) is None else format(finite(v), ".0f") for v in vals], textposition="outside",
                             textfont=dict(color=t["ink"]), cliponaxis=False,
                             hovertemplate="%{y}: %{x:.1f}<extra>" + name + "</extra>"))
    fig.update_layout(barmode="group", showlegend=len(series) > 1, bargap=0.4)
    fig.update_xaxes(title_text=xtitle, showgrid=True, gridcolor=t["grid"], range=list(xrange) if xrange else None)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig
