"""
Alt+click / Alt+Ctrl+click comparison popups for the model section plot on
the Interpret tab.

Alt+click a site opens a draggable window with a 'TEM' tab (resistivity
depth profile and dB/dt decay curves as subtabs) plus a nearby borehole log
tab if one falls within mod2's Borehole_radius setting. Alt+click directly
on a borehole (rather than a site) instead opens a window with just that
borehole's log -- no TEM tab, since no site was picked.

Alt+Ctrl+click accumulates more items -- sites AND/OR boreholes, in any
mix -- into the same combined window (overlaid/side-by-side together)
until the window is closed, at which point the next alt+ctrl+click starts
a fresh comparison.

Site resolution mirrors app.py's cross_panel_click: a model_section click
doesn't always land on the heatmap (it can land on the misfit line, DOI
fill, or a borehole bar), so the clientside half of this only extracts the
click's x position and trace `meta` -- meta identifies a borehole click
directly (see model.py's add_boreholes_to_section_fig, which tags its
traces with meta='BH:<bh_id>'; deliberately trace-level `meta` rather than
per-point `customdata`, since the borehole trace's hoveron='fills' -- needed
so a click anywhere inside the filled box registers at all -- makes Plotly
try to numerically reduce customdata across the fill's points, which
crashes on non-numeric values); anything else is resolved server-side to a
site_id via nearest-x match against mod2's own x-axis, the same way
cross_panel_click does it.
"""
import json
import textwrap

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

from Sections_plotting import (
    build_combined_step_figure,
    create_draggable_window,
    generate_res_step_graph_elev,
    preprocess_new_df,
)

# Shared by _tem_component and _borehole_panel -- both need this SAME fixed
# height (rather than one of them flexing to fill) for their plot areas to
# actually line up vertically; see _borehole_panel for why.
_COMPARE_GRAPH_HEIGHT = '700px'


def _nearby_borehole_ids(site_id, sesh, mod2):
    if sesh.boreholes is None or sesh.boreholes.empty:
        return []
    if sesh.data is None or 'utm_x' not in sesh.data.columns:
        return []
    site_rows = sesh.data[sesh.data['site_id'] == site_id]
    if site_rows.empty:
        return []
    x, y = site_rows['utm_x'].iloc[0], site_rows['utm_y'].iloc[0]
    radius = mod2.settings.Borehole_radius
    dist = np.hypot(sesh.boreholes['bh_x'] - x, sesh.boreholes['bh_y'] - y)
    return sorted(sesh.boreholes.loc[dist <= radius, 'bh_id'].unique().tolist())


def _site_bh_distances(site_ids, bh_ids, sesh):
    """{site_id: {bh_id: distance_m}} (planar UTM distance) for every
    (site, borehole) pair -- same distance sites are matched to boreholes
    by elsewhere (_nearby_borehole_ids)."""
    distances = {}
    if (sesh.data is None or 'utm_x' not in sesh.data.columns
            or sesh.boreholes is None or sesh.boreholes.empty):
        return distances
    for site_id in site_ids:
        site_rows = sesh.data[sesh.data['site_id'] == site_id]
        if site_rows.empty:
            continue
        x, y = site_rows['utm_x'].iloc[0], site_rows['utm_y'].iloc[0]
        per_site = {}
        for bh_id in bh_ids:
            bh_rows = sesh.boreholes[sesh.boreholes['bh_id'] == bh_id]
            if bh_rows.empty:
                continue
            bx, by = bh_rows['bh_x'].iloc[0], bh_rows['bh_y'].iloc[0]
            per_site[bh_id] = float(np.hypot(bx - x, by - y))
        if per_site:
            distances[site_id] = per_site
    return distances


def _distance_caption(site_ids, bh_ids, sesh):
    """
    A small text line reporting each TEM sounding's distance from the
    borehole(s) shown alongside it -- with one borehole, "Site X: Nm"; with
    several, "Site X -> BH: Nm" per pair, so it stays readable either way.
    """
    distances = _site_bh_distances(site_ids, bh_ids, sesh)
    if not distances:
        return None
    parts = []
    single_bh = len(bh_ids) == 1
    for site_id in site_ids:
        per_site = distances.get(site_id)
        if not per_site:
            continue
        if single_bh:
            d = per_site.get(bh_ids[0])
            if d is not None:
                parts.append(f"Site {site_id}: {d:.0f} m")
        else:
            for bh_id, d in per_site.items():
                parts.append(f"Site {site_id} → {bh_id}: {d:.0f} m")
    if not parts:
        return None
    label = "Distance from borehole" if single_bh else "Distances from boreholes"
    return html.Div(
        f"{label}: " + "  |  ".join(parts),
        style={'fontSize': '0.85rem', 'color': '#555', 'marginBottom': '8px'},
    )


def _sync_elevation_axis(*figs, pad=5):
    """
    Forces every figure passed in onto the same y (elevation) range, taken
    from the union of their own data -- so a horizontal line drawn by eye
    across the Res/Depth and Borehole log panels lines up at the same
    elevation in both, instead of each panel auto-ranging to its own
    (different) depth extent.
    """
    y_vals = []
    for fig in figs:
        if fig is None:
            continue
        for trace in fig.data:
            if trace.y is not None:
                y_vals.extend(v for v in trace.y if v is not None)
    if not y_vals:
        return
    y_min, y_max = min(y_vals), max(y_vals)
    for fig in figs:
        if fig is not None:
            fig.update_yaxes(range=[y_min - pad, y_max + pad], autorange=False)


_LEGEND_LABEL_WIDTH = 17


def _wrap_legend_label(text, width=_LEGEND_LABEL_WIDTH):
    """
    Word-wraps a legend label longer than `width` chars (not a mid-word
    cut) onto multiple lines -- otherwise a long rock name overflows its
    grid column and overlaps its neighbor. Returns a list of Dash children
    (text interspersed with html.Br()), for direct use as an html.Span's
    children -- NOT a Plotly-style '<br>'-joined string, since this legend
    is a plain HTML block (_borehole_legend_html), not a Plotly figure,
    and React renders "<br>" as literal text rather than a line break.
    """
    lines = textwrap.wrap(text, width=width) or [text]
    children = [lines[0]]
    for line in lines[1:]:
        children.append(html.Br())
        children.append(line)
    return children


def _build_borehole_log_figure(bh_ids, boreholes_df, rock_color_map):
    """
    Returns (fig, legend) -- the rock-type legend is built as a small,
    separately-scrollable HTML block (see _borehole_legend_html) rather
    than Plotly's own in-figure legend, so it can be capped to a small
    fixed height instead of eating a large chunk of the figure's own
    margin, leaving far more room for the actual borehole log. `fig`'s
    margin is matched to generate_res_step_graph_elev's (t=30, b=50) so it
    lines up vertically with the Res/Depth panel it's shown beside.
    """
    fig = go.Figure()
    rock_colors = {}  # first-seen order, rock -> color
    for x_pos, bh_id in enumerate(bh_ids):
        group = boreholes_df[boreholes_df['bh_id'] == bh_id]
        if group.empty:
            continue
        elev = group['bh_elev'].iloc[0]
        for _, row in group.iterrows():
            z_top = elev - float(row['layer_top'])
            z_bottom = elev - float(row['layer_bottom'])
            rock = str(row.get('layer_desc', '')).strip()
            color = (rock_color_map or {}).get(rock, 'lightgray')
            w = 0.4
            fig.add_trace(go.Scatter(
                x=[x_pos - w, x_pos + w, x_pos + w, x_pos - w, x_pos - w],
                y=[z_top, z_top, z_bottom, z_bottom, z_top],
                fill='toself', fillcolor=color, mode='lines',
                line=dict(width=0.8, color='black'),
                # name is kept (even with showlegend=False, so it still
                # doesn't appear in Plotly's own legend -- our custom HTML
                # one is what's shown) because Plotly falls back to an
                # auto-generated "trace N" for it when unset, and that
                # fallback surfaces in places hovertemplate doesn't
                # control (e.g. accessibility/ARIA hover labels), which is
                # what was showing up instead of the rock name.
                name=rock,
                showlegend=False,
                # Explicit hovertemplate rather than hoverinfo='text' +
                # hovertext -- more reliable for controlling the visible
                # hover box content in this Plotly build. <extra></extra>
                # suppresses the secondary trace-name box.
                hovertemplate=f"<b>{bh_id}</b><br>{rock}<br>{row['layer_top']}-{row['layer_bottom']} m<extra></extra>",
            ))
            rock_colors.setdefault(rock, color)
        fig.add_annotation(x=x_pos, y=elev, text=f"<b>{bh_id}</b>", showarrow=False, yshift=15)

    fig.update_layout(
        template='plotly_white', showlegend=False,
        xaxis=dict(tickvals=list(range(len(bh_ids))), ticktext=bh_ids,
                   range=[-1, max(1, len(bh_ids))], showgrid=False, linecolor='black', mirror=True),
        yaxis=dict(title='Elevation (m.a.s.l.)', gridcolor='lightgray', linecolor='black', mirror=True),
        margin=dict(l=60, r=20, t=30, b=50),
    )
    return fig, _borehole_legend_html(rock_colors)


def _borehole_legend_html(rock_colors):
    """
    A compact, capped-height, scrollable rock-type legend (colored swatch
    + wrapped label) laid out in a 2- or 3-column grid -- kept out of the
    Plotly figure itself so it can't eat into the plot's own height.
    """
    if not rock_colors:
        return None
    n_cols = 3 if len(rock_colors) > 4 else 2
    items = [
        html.Div([
            html.Span(style={
                'display': 'inline-block', 'width': '10px', 'height': '10px',
                'backgroundColor': color, 'border': '1px solid black',
                'marginRight': '6px', 'flexShrink': '0',
            }),
            html.Span(_wrap_legend_label(rock), style={'lineHeight': '1.15'}),
        ], style={'display': 'flex', 'alignItems': 'flex-start'})
        for rock, color in rock_colors.items()
    ]
    return html.Div(items, style={
        'display': 'grid',
        'gridTemplateColumns': f'repeat({n_cols}, 1fr)',
        'gap': '4px 12px',
        'maxHeight': '64px',
        'overflowY': 'auto',
        'padding': '6px 8px',
        'border': '1px solid #ddd',
        'borderRadius': '4px',
        'fontSize': '0.75rem',
        'marginTop': '4px',
        'flexShrink': '0',
    })


def _borehole_panel(bh_fig, legend, graph_height=_COMPARE_GRAPH_HEIGHT):
    """
    The borehole graph with its legend stacked below, wrapped in a
    single-tab dcc.Tabs (labeled 'Borehole'). `graph_height` matches
    _tem_component's fixed height (see its docstring for why fixed rather
    than flexed). The fake single tab exists purely so this panel's own
    tab-bar height matches _tem_component's real one -- without it, the
    TEM graph (pushed down by its actual tab bar) and this graph (with no
    tab bar at all) start at different vertical offsets, throwing off
    their alignment even though both now share the same height and
    y-range.
    """
    graph = dcc.Graph(figure=bh_fig, style={'height': graph_height})
    children = [graph] if legend is None else [graph, legend]
    return html.Div(
        [dcc.Tabs([dcc.Tab(label='Borehole', children=children)])],
        style={'display': 'flex', 'flexDirection': 'column', 'height': '100%'},
    )


def _resolve_click_item(click_data, mod2):
    """
    Identify what a model_section alt-click landed on: a borehole (tagged
    via its trace's `meta`, a flat 'BH:<id>' string -- see model.py's
    add_boreholes_to_section_fig) or a site (resolved via nearest-x match,
    same as app.py's cross_panel_click, since a click can land on the
    heatmap, misfit line, or DOI fill, none of which carry a site_id
    directly). Returns {'type': 'bh'|'site', 'id': ...} or None.
    """
    meta = click_data.get('meta')
    if isinstance(meta, str) and meta.startswith('BH:'):
        return {'type': 'bh', 'id': meta[len('BH:'):]}

    if mod2.dataframe is None or mod2.dataframe.empty:
        return None
    df, x_col = mod2._prepare_x_axis(mod2.dataframe)
    df = df[df['site_id'] != -1]
    if df.empty:
        return None
    x_value = click_data['x']
    if mod2.settings.x_axis == 'daytime':
        x_value = pd.Timestamp(x_value).value // 10**6
    site_id = df.loc[(df[x_col] - x_value).abs().idxmin(), 'site_id']
    return {'type': 'site', 'id': site_id}


def _tem_component(step_fig, dbdt_fig, res_label='Res/Depth', graph_height=_COMPARE_GRAPH_HEIGHT):
    """
    Res/Depth and dB/dt as subtabs (whichever one is active), returned
    unwrapped so the caller can place it directly beside a borehole log --
    see _side_by_side -- rather than behind a separate tab click.
    """
    subtabs = []
    if step_fig is not None:
        subtabs.append(dcc.Tab(label=res_label, children=[dcc.Graph(figure=step_fig, style={'height': graph_height})]))
    if dbdt_fig is not None:
        subtabs.append(dcc.Tab(label='dB/dt', children=[dcc.Graph(figure=dbdt_fig, style={'height': graph_height})]))
    if not subtabs:
        return None
    return dcc.Tabs(subtabs)


def _side_by_side(tem_component, bh_panel):
    """
    Places the TEM subtabs and a borehole panel (see _borehole_panel) next
    to each other so both are visible at once -- comparing them shouldn't
    require clicking between separate tabs. Degrades to just whichever one
    is present when only one of the two exists.
    """
    panels = []
    if tem_component is not None:
        panels.append(html.Div([tem_component], style={'flex': '1', 'minWidth': '0'}))
    if bh_panel is not None:
        panels.append(html.Div([bh_panel], style={'flex': '1', 'minWidth': '0'}))
    if not panels:
        return None
    if len(panels) == 1:
        return html.Div(panels, style={'height': '100%'})
    return html.Div(panels, style={'display': 'flex', 'gap': '14px', 'height': '100%'})


def _borehole_window_content(bh_id, sesh):
    if sesh.boreholes is None or sesh.boreholes.empty:
        return None, None
    bh_fig, bh_legend = _build_borehole_log_figure([bh_id], sesh.boreholes, sesh.rock_map)
    return _borehole_panel(bh_fig, bh_legend), f'Borehole {bh_id}'


def _prepare_dbdt_site_df(dbdt_df, site_id, dbdt2):
    """
    Filter to one site and apply the same LM/HM gain factors dbdt2/dbdt1
    apply (panels.py's compare_synthetic) so amplitudes match what's shown
    elsewhere in the app. Sorting by system_id keeps LM and HM rows
    grouped, which _dbdt_traces relies on to draw them as separate lines.
    """
    df = dbdt_df[dbdt_df['site_id'] == int(site_id)].copy()
    if df.empty:
        return df
    include = df['inuse_manual'].astype(bool).fillna(df['inuse_auto'])
    df = df[include]
    if df.empty:
        return df
    lm_factor = dbdt2.settings.lm_factor
    hm_factor = dbdt2.settings.hm_factor
    is_lm = df['system_id'] % 2 == 0
    df.loc[is_lm, 'dbdt']       *= lm_factor
    df.loc[is_lm, 'dbdt_syn']   *= lm_factor
    df.loc[~is_lm, 'dbdt']      *= hm_factor
    df.loc[~is_lm, 'dbdt_syn']  *= hm_factor
    return df.sort_values(['system_id', 'time'])


def _dbdt_traces(df_site, label, base_color):
    """
    Splits a prepared site dataframe into separate LM and HM traces --
    system_id is even for LM gates, odd for HM -- so the two channels
    (which don't share a continuous time axis) never draw as one
    artificially-connected line. Dash style marks observed (dotted) vs.
    inverted (solid) response. LM and HM share one legend entry each
    (per site, "<label> inverted" / "<label> observed") via a common
    legendgroup -- only the first non-empty one of the pair sets
    showlegend=True so there's no duplicate entry, but toggling that one
    entry still hides/shows both.
    """
    traces = []
    shown_inverted = False
    shown_observed = False
    for sys_name, is_sys in (('LM', df_site['system_id'] % 2 == 0),
                              ('HM', df_site['system_id'] % 2 == 1)):
        sub = df_site[is_sys].dropna(subset=['dbdt', 'time'])
        if sub.empty:
            continue
        e = sub['error'].values / 100
        d_obs = sub['dbdt'].values
        err_plus  = d_obs * e
        err_minus = d_obs * e / (1 + e)

        if 'dbdt_syn' in sub.columns:
            traces.append(go.Scatter(
                x=sub['time'], y=sub['dbdt_syn'], mode='lines',
                line=dict(color=base_color, width=2, dash='solid'),
                name=f'{label} inverted', legendgroup=f'{label}-inverted', showlegend=not shown_inverted,
            ))
            shown_inverted = True
        traces.append(go.Scatter(
            x=sub['time'], y=d_obs, mode='lines+markers',
            line=dict(color=base_color, width=1, dash='dot'),
            marker=dict(color=base_color, size=5, symbol='circle-open'),
            name=f'{label} observed', legendgroup=f'{label}-observed', showlegend=not shown_observed,
            error_y=dict(type='data', array=err_plus, arrayminus=err_minus, visible=True, thickness=0.8, width=0),
        ))
        shown_observed = True
    return traces


def _dbdt_figure(dbdt_df, site_ids, dbdt2, dbdt1=None):
    fig = go.Figure()
    standard_colors = [c for c in px.colors.qualitative.Plotly if c.lower() != '#ef553b']
    colors = ['red'] + standard_colors

    for count, site_id in enumerate(site_ids):
        df_site = _prepare_dbdt_site_df(dbdt_df, site_id, dbdt2)
        if df_site.empty:
            continue
        color = colors[count % len(colors)]
        label = f'Site {site_id}'
        for tr in _dbdt_traces(df_site, label, color):
            fig.add_trace(tr)

    xaxis_kwargs = dict(title='Time (s)', type='log', gridcolor='lightgray', linecolor='black', linewidth=1, mirror=True,
                         exponentformat='power', showexponent='all')
    yaxis_kwargs = dict(title='dB/dt [V/m²]', type='log', gridcolor='lightgray', linecolor='black', linewidth=1, mirror=True,
                         exponentformat='power', showexponent='all')

    # Match the live Sounding panel's own axis limits (dbdt1) rather than
    # auto-scaling to whatever subset of sites happens to be in this
    # comparison popup -- otherwise the same site can look different here
    # than in the Sounding panel just because it's viewed alongside fewer
    # (or different) other sites.
    if dbdt1 is not None:
        yaxis_kwargs['range'] = [dbdt1.settings.dbdt_min, dbdt1.settings.dbdt_max]

        x_col = dbdt1.settings.x_axis
        if dbdt1.dataframe is not None and x_col in dbdt1.dataframe.columns:
            x_vals = dbdt1.dataframe[x_col]
            if x_col == 'time':
                x_vals = x_vals[np.isfinite(x_vals) & (x_vals > 0)]
            else:
                x_vals = x_vals.dropna()
            if len(x_vals) > 0:
                x_min, x_max = x_vals.min(), x_vals.max()
                xaxis_kwargs['range'] = [np.log10(x_min), np.log10(x_max)] if x_col == 'time' else [x_min, x_max]
                xaxis_kwargs['type'] = 'log' if x_col == 'time' else 'linear'

    fig.update_layout(
        xaxis=xaxis_kwargs,
        yaxis=yaxis_kwargs,
        legend=dict(yanchor='top', y=0.98, xanchor='right', x=0.98,
                    bgcolor='rgba(255,255,255,0.7)', bordercolor='black', borderwidth=1),
        template='plotly_white', margin=dict(l=50, r=40, t=50, b=50), plot_bgcolor='white',
    )
    return fig


def _site_window_content(site_id, sesh, mod2, dbdt2, dbdt1):
    step_fig = None
    site_models = sesh.models[sesh.models['site_id'] == site_id] if sesh.models is not None else None
    if site_models is not None and not site_models.empty:
        models_df, _, _ = preprocess_new_df(site_models)
        row = models_df[models_df['site_id'] == site_id]
        if not row.empty:
            step_fig = generate_res_step_graph_elev(row.iloc[0], site_id, elevation=row.iloc[0].get('elevation'))

    dbdt_fig = _dbdt_figure(sesh.data, [site_id], dbdt2, dbdt1) if sesh.data is not None else None

    bh_ids = _nearby_borehole_ids(site_id, sesh, mod2)
    bh_fig, bh_legend = _build_borehole_log_figure(bh_ids, sesh.boreholes, sesh.rock_map) if bh_ids else (None, None)

    # Elevation range must match before the step figure gets wrapped into
    # tem_component below (dcc.Graph freezes whatever figure it's given).
    _sync_elevation_axis(step_fig, bh_fig)
    tem_component = _tem_component(step_fig, dbdt_fig)
    bh_panel = _borehole_panel(bh_fig, bh_legend) if bh_fig is not None else None

    panels = _side_by_side(tem_component, bh_panel)
    if panels is None:
        return None, None
    caption = _distance_caption([site_id], bh_ids, sesh) if bh_ids else None
    content = panels if caption is None else html.Div(
        [caption, html.Div([panels], style={'flex': '1', 'minHeight': '0'})],
        style={'height': '100%', 'display': 'flex', 'flexDirection': 'column'},
    )
    return content, f'Site {site_id}'


def _combined_window_content(site_items, bh_items, sesh, mod2, dbdt2, dbdt1):
    """
    site_items/bh_items: the site_ids and borehole ids accumulated across
    successive alt+ctrl+clicks (any mix, in click order) -- see
    manage_compare_windows.
    """
    step_fig = None
    if site_items:
        site_models = sesh.models[sesh.models['site_id'].isin(site_items)] if sesh.models is not None else None
        if site_models is not None and not site_models.empty:
            models_df, _, _ = preprocess_new_df(site_models)
            step_fig = build_combined_step_figure(models_df, site_items, use_elevation=True)

    dbdt_fig = _dbdt_figure(sesh.data, site_items, dbdt2, dbdt1) if (site_items and sesh.data is not None) else None

    # Boreholes near any of the accumulated sites, plus any boreholes
    # explicitly alt+ctrl+clicked directly.
    all_bh_ids = list(bh_items)
    for site_id in site_items:
        for bh_id in _nearby_borehole_ids(site_id, sesh, mod2):
            if bh_id not in all_bh_ids:
                all_bh_ids.append(bh_id)
    bh_fig, bh_legend = _build_borehole_log_figure(all_bh_ids, sesh.boreholes, sesh.rock_map) if all_bh_ids else (None, None)

    # Elevation range must match before the step figure gets wrapped into
    # tem_component below (dcc.Graph freezes whatever figure it's given).
    _sync_elevation_axis(step_fig, bh_fig)
    tem_component = _tem_component(step_fig, dbdt_fig, res_label=f'Res/Depth ({len(site_items)})')
    bh_panel = _borehole_panel(bh_fig, bh_legend) if bh_fig is not None else None

    panels = _side_by_side(tem_component, bh_panel)
    if panels is None:
        return None, None
    caption = _distance_caption(site_items, all_bh_ids, sesh) if (site_items and all_bh_ids) else None
    content = panels if caption is None else html.Div(
        [caption, html.Div([panels], style={'flex': '1', 'minHeight': '0'})],
        style={'height': '100%', 'display': 'flex', 'flexDirection': 'column'},
    )

    title_bits = []
    if site_items:
        title_bits.append(f"{len(site_items)} site" + ("s" if len(site_items) != 1 else ""))
    if all_bh_ids:
        title_bits.append(f"{len(all_bh_ids)} borehole" + ("s" if len(all_bh_ids) != 1 else ""))
    return content, 'Comparison: ' + ', '.join(title_bits)


def register_compare_callbacks(app, mod2, dbdt2, dbdt1):
    """
    mod2: the ModelSection panel instance (its dataframe/settings resolve
    the click's x position to a site_id, and Borehole_radius drives the
    nearby-borehole search).
    dbdt2: the ModelSection's paired dB/dt panel, whose lm_factor/hm_factor
    gain settings are applied so comparison-window curves match what's
    shown in the live dB/dt panels.
    dbdt1: the Sounding panel, whose current x/y axis limits (settings.
    dbdt_min/dbdt_max, and its own dataframe's x-column range) are applied
    to the comparison popup's dB/dt plot, so a site looks the same there
    as it does in the live Sounding panel regardless of which/how many
    other sites are in the popup.

    sesh is looked up via `from __main__ import sesh` at call time (not a
    module-level import) because app.py reassigns the `sesh` global
    wholesale on session load -- capturing it once at startup would leave
    these callbacks pointed at a stale, empty session.
    """
    app.clientside_callback(
        """
        function(clickData) {
            if (!window._keyTracker.alt) {
                return window.dash_clientside.no_update;
            }
            if (!clickData || !clickData.points || !clickData.points.length) {
                return window.dash_clientside.no_update;
            }
            const pt = clickData.points[0];
            if (pt.x === undefined) {
                return window.dash_clientside.no_update;
            }
            // clickData.points[i].data is undefined in this Plotly build
            // (confirmed via a debug dump -- even a plain point hit with
            // real x/y had no .data at all), so read `meta` directly off
            // the live graph's own trace array via curveNumber instead of
            // trusting anything on the click event's point object itself.
            // dcc.Graph's own id is on a wrapper div -- the actual
            // Plotly-managed element (which .data/.layout are attached to)
            // is nested inside it and carries the 'js-plotly-plot' class.
            let meta = null;
            const wrapper = document.getElementById('model_section');
            const gd = wrapper ? (wrapper.classList.contains('js-plotly-plot') ? wrapper : wrapper.querySelector('.js-plotly-plot')) : null;
            if (gd && gd.data && gd.data[pt.curveNumber] && gd.data[pt.curveNumber].meta !== undefined) {
                meta = gd.data[pt.curveNumber].meta;
            }
            return {
                x: pt.x,
                meta: meta,
                multi: window._keyTracker.ctrl,
                timestamp: Date.now()
            };
        }
        """,
        Output('compare-click-store', 'data'),
        Input('model_section', 'clickData'),
        prevent_initial_call=True,
    )

    @app.callback(
        Output('compare-window-container', 'children'),
        Output('compare-window-store', 'data', allow_duplicate=True),
        Input('compare-click-store', 'data'),
        Input({'type': 'close-window', 'index': ALL}, 'n_clicks'),
        State('compare-window-container', 'children'),
        State('compare-window-store', 'data'),
        prevent_initial_call=True,
    )
    def manage_compare_windows(click_data, n_closes, current_windows, combined_state):
        from __main__ import sesh

        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        trigger = ctx.triggered[0]['prop_id']
        windows = list(current_windows or [])
        combined_state = combined_state or {'window_id': None, 'items': []}

        if 'compare-click-store' in trigger:
            if not click_data or 'x' not in click_data:
                raise PreventUpdate

            item = _resolve_click_item(click_data, mod2)
            if item is None:
                raise PreventUpdate

            is_multi = bool(click_data.get('multi'))
            ts = click_data.get('timestamp')

            if not is_multi:
                if item['type'] == 'bh':
                    content, title = _borehole_window_content(item['id'], sesh)
                    new_id = f"compare-win-bh-{item['id']}-{ts}"
                    win_width = '550px'
                else:
                    content, title = _site_window_content(item['id'], sesh, mod2, dbdt2, dbdt1)
                    new_id = f"compare-win-{item['id']}-{ts}"
                    # Wide enough for the TEM + borehole log side-by-side
                    # layout when this site has a nearby borehole; still
                    # fine when it's just the (single) TEM panel.
                    win_width = '900px'
                if content is None:
                    raise PreventUpdate
                windows.append(create_draggable_window(new_id, title, content, width=win_width, height='850px'))
                return windows, combined_state

            if not combined_state.get('window_id'):
                combined_state = {'window_id': f'compare-win-multi-{ts}', 'items': []}
            if item not in combined_state['items']:
                combined_state['items'].append(item)

            site_items = [it['id'] for it in combined_state['items'] if it['type'] == 'site']
            bh_items = [it['id'] for it in combined_state['items'] if it['type'] == 'bh']
            content, title = _combined_window_content(site_items, bh_items, sesh, mod2, dbdt2, dbdt1)
            if content is None:
                raise PreventUpdate
            comp_id = combined_state['window_id']
            windows = [w for w in windows if w['props']['id'] != comp_id]
            windows.append(create_draggable_window(comp_id, title, content, width='950px', height='850px'))
            return windows, combined_state

        if 'close-window' in trigger:
            try:
                closed_id = json.loads(trigger.split('.')[0]).get('index')
            except Exception:
                raise PreventUpdate
            windows = [w for w in windows if w['props']['id'] != closed_id]
            if combined_state.get('window_id') == closed_id:
                combined_state = {'window_id': None, 'items': []}
            return windows, combined_state

        raise PreventUpdate

    # Same drag-by-header behavior as the reference implementation in
    # popups.py, retargeted to this module's window container -- with a
    # clamp so a window dragged above the viewport keeps its header (the
    # only drag handle) reachable instead of vanishing off-screen.
    app.clientside_callback(
        """
        function(children) {
            if (!children) return window.dash_clientside.no_update;
            setTimeout(() => {
                const windows = document.getElementsByClassName("draggable-window");
                Array.from(windows).forEach(win => {
                    const header = win.querySelector('.window-header');
                    if (!header || header.dataset.listener === 'true') return;

                    let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
                    header.dataset.listener = 'true';
                    header.onmousedown = dragMouseDown;

                    function dragMouseDown(e) {
                        e.preventDefault();
                        pos3 = e.clientX;
                        pos4 = e.clientY;
                        document.onmouseup = closeDragElement;
                        document.onmousemove = elementDrag;
                    }
                    function elementDrag(e) {
                        e.preventDefault();
                        pos1 = pos3 - e.clientX;
                        pos2 = pos4 - e.clientY;
                        pos3 = e.clientX;
                        pos4 = e.clientY;
                        let newTop = win.offsetTop - pos2;
                        let newLeft = win.offsetLeft - pos1;
                        if (newTop < 0) newTop = 0;
                        const maxTop = window.innerHeight - header.offsetHeight;
                        if (newTop > maxTop) newTop = maxTop;
                        win.style.top = newTop + "px";
                        win.style.left = newLeft + "px";
                    }
                    function closeDragElement() {
                        document.onmouseup = null;
                        document.onmousemove = null;
                    }
                });
            }, 100);
            return window.dash_clientside.no_update;
        }
        """,
        Output('compare-window-container', 'className'),
        Input('compare-window-container', 'children'),
        prevent_initial_call=True,
    )
