from basepanel import *
from dash import no_update
from dataclasses import field
import numpy as np
import pandas as pd


def _no_data_figure(message):
    """A blank figure with a centered message -- used instead of crashing
    when a 'line N' radius filter leaves zero rows (e.g. a drawn line with
    no TEM sites nearby), so the caller can still overlay other content
    (e.g. nearby boreholes) on top of it."""
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=16, color="gray"),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def latlon_to_utm(lat, lon):
    """
    UTM easting/northing arrays for lat/lon arrays, NaN where either input
    is missing. Uses one zone for all points (the utm package picks it from
    the input), which is what a single survey area needs.
    """
    import utm
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    easting = np.full(len(lat), np.nan)
    northing = np.full(len(lat), np.nan)
    ok = np.isfinite(lat) & np.isfinite(lon)
    if ok.any():
        easting[ok], northing[ok], _, _ = utm.from_latlon(lat[ok], lon[ok])
    return easting, northing


def utm_zone_label(lat, lon):
    """' 32V'-style zone suffix for hover labels, or '' if no valid point."""
    import utm
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    ok = np.isfinite(lat) & np.isfinite(lon)
    if not ok.any():
        return ''
    _, _, zone, letter = utm.from_latlon(float(np.mean(lat[ok])), float(np.mean(lon[ok])))
    return f' {zone}{letter}'


def _log_colorbar_ticks(vmin, vmax):
    """
    Nice round Ωm values (1/2/5 per decade -- 1, 2, 5, 10, 20, 50, ...)
    between vmin and vmax, for labeling a colorbar whose underlying z data
    is log10(resistivity) with real resistivity values instead of raw
    log10 exponents. Returns (tickvals, ticktext): tickvals are each
    value's log10 position (where it actually falls on the z-axis),
    ticktext is the value itself formatted for display.
    """
    if vmin <= 0 or vmax <= 0 or vmax <= vmin:
        return [np.log10(max(vmin, 1e-6))], [f"{vmin:g}"]
    lo = int(np.floor(np.log10(vmin)))
    hi = int(np.ceil(np.log10(vmax)))
    values = [
        mult * 10 ** decade
        for decade in range(lo, hi + 1)
        for mult in (1, 2, 5)
        if vmin <= mult * 10 ** decade <= vmax
    ]
    if not values:
        values = [vmin, vmax]
    values = sorted(set(values))
    return [np.log10(v) for v in values], [f"{v:g}" for v in values]


def resistivity_colorbar_tick_kwargs(vmin, vmax, log_colorbar):
    """
    tickmode/tickvals/ticktext kwargs for a Plotly colorbar whose
    underlying data is log10(resistivity): real Ωm values at their
    correct log-spaced positions (see _log_colorbar_ticks) when
    log_colorbar is False, or {} (Plotly's own auto log10-exponent
    ticks -- 0, 0.5, 1, ...) when True. Shared by ModelSection's 2D
    colorbar and Model3D's Mesh3d colorbar so both panels' colorbars
    tick the same way for the same settings.
    """
    if log_colorbar:
        return {}
    tick_vals, tick_text = _log_colorbar_ticks(vmin, vmax)
    return dict(tickmode='array', tickvals=tick_vals, ticktext=tick_text)


# Resistivity colorscale (dark blue -> blue -> cyan -> green -> yellow ->
# orange -> red -> magenta -> purple -> light lavender), low resistivity/
# conductive = blue, high resistivity/resistive = lavender -- the exact 16
# RGB triplets from a reference TEM software's "base colors" panel,
# evenly spaced across the colorscale in the same low-to-high order shown
# there (that panel lists them high-to-low, top to bottom).
RESISTIVITY_COLORSCALE = [
    [0 / 15, 'rgb(0,0,190)'],
    [1 / 15, 'rgb(0,75,220)'],
    [2 / 15, 'rgb(0,150,235)'],
    [3 / 15, 'rgb(0,200,255)'],
    [4 / 15, 'rgb(80,240,255)'],
    [5 / 15, 'rgb(30,210,0)'],
    [6 / 15, 'rgb(180,255,30)'],
    [7 / 15, 'rgb(255,255,0)'],
    [8 / 15, 'rgb(255,195,0)'],
    [9 / 15, 'rgb(255,115,0)'],
    [10 / 15, 'rgb(255,0,0)'],
    [11 / 15, 'rgb(255,0,120)'],
    [12 / 15, 'rgb(140,40,180)'],
    [13 / 15, 'rgb(165,70,220)'],
    [14 / 15, 'rgb(195,130,240)'],
    [15 / 15, 'rgb(230,155,240)'],
]


@nosj
class ModelGraphSettings(PanelSettings):
    z: Literal['depth', 'elevation'] = 'depth'
    color_by: Literal['site_id', 'misfit'] = 'site_id'
    rho_min: float = 1.0
    rho_max: float = 1000.0

class ModelGraph(Panel):
    highlighted=None
    buffer_len = 50
    buffer_start = 0
    buffer_sites = None

    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', ModelGraphSettings(id='model_graph'))
        super().__init__(id='model_graph', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def render(self):
        if self.dataframe is None: return self.empty_render()
        df_layers_long = pd.melt(
            self.dataframe,
            id_vars=['site_id', 'daytime', 'longitude', 'latitude', 'date', 'elevation', 'layer', 'resistivity'],
            value_vars=['top_depth', 'bottom_depth'],
            var_name='depth_type',
            value_name='depth'
        ).sort_values(['site_id', 'daytime', 'layer', 'depth'])

        df_layers_long = df_layers_long.drop(columns=['depth_type'])
        utm_e, utm_n = latlon_to_utm(df_layers_long['latitude'].values, df_layers_long['longitude'].values)
        df_layers_long['utm_e'] = utm_e
        df_layers_long['utm_n'] = utm_n
        zone_label = utm_zone_label(df_layers_long['latitude'].values, df_layers_long['longitude'].values)
        hovertemplate = (
            "Site: %{customdata[0]}<br>"
            f"UTM{zone_label}: %{{customdata[1]:.0f}} E, %{{customdata[2]:.0f}} N<br>"
            "ρ: %{x:.1f} Ω·m<br>Depth: %{y:.1f} m<extra></extra>"
        )

        if self.highlighted is None:
            heatmap_df = df_layers_long.set_index('site_id').sort_index(ascending=True)

            if self.buffer_sites is not None:
                # Explicit site list (e.g. from the Transect view's buffer
                # window) -- avoids assuming buffer_start/buffer_len are in
                # site_id units, since the transect x-axis may be in minutes
                # or meters instead.
                x_slice = list(self.buffer_sites)
            else:
                buffer_start = self.buffer_start
                buffer_len   = self.buffer_len

                x_values = df_layers_long['site_id'].unique().tolist()
                n_sites  = len(x_values)

                plot_start = max(0, buffer_start)
                plot_end   = min(n_sites, buffer_start + buffer_len)

                x_slice = x_values[plot_start:plot_end]

            fig = px.line(
                df_layers_long[df_layers_long['site_id'].isin(x_slice)],
                x="resistivity",
                y="depth",
                color="site_id",
                labels={
                    "resistivity": "ρ [Ω·m]",  # Unicode rho
                    "site_id": "Site ID"
                },
                custom_data=['site_id', 'utm_e', 'utm_n'],
                title="1D Resistivity Profile",
            )
            fig.update_traces(hovertemplate=hovertemplate)
        else:
            fig = go.Figure(layout=dict(title="1D Resistivity Profile"))
            # self.highlighted is a scalar from single-site callbacks
            # (cross_panel_click, highlight_change) but a list from
            # multi-select ones (unified_handler) -- this view shows one
            # profile, so use the first site either way rather than
            # crashing on `series == a_list`.
            highlighted = self.highlighted
            if isinstance(highlighted, (list, tuple, set, np.ndarray, pd.Series)):
                highlighted = next(iter(highlighted), None)
            df_highlighted = df_layers_long[df_layers_long['site_id'] == highlighted]
            fig.add_trace(
                go.Scatter(
                    x=df_highlighted["resistivity"],
                    y=df_highlighted["depth"],
                    customdata=df_highlighted[['site_id', 'utm_e', 'utm_n']].values,
                    hovertemplate=hovertemplate,
                    mode="lines",
                    line=dict(width=2, color='red'),
                    zorder=10,
                    name=f"Site {highlighted}"
                ),
            )
            # fig.add_trace(
            #     go.Scatter(
            #         x=df_layers_long["resistivity"],
            #         y=df_layers_long["depth"],
            #         mode="lines",
            #         line=dict(color='gray'),
            #         name='All Sites'
            #     ), 
            # )



        # Reverse y-axis so depth increases downward
        # fig.update_yaxes(autorange="reversed")
        # fig.update_xaxes(type="log", range=[np.log10(self.settings.rho_min), np.log10(self.settings.rho_max)])
        fig.update_xaxes(title_text='Resistivity [Ω⋅m]',type='log',range=[0, 2.7],showline=True,mirror=True           )

        fig.update_yaxes(
            title_text='Depth [m]',
            range=[180, -0.5],  # depth increasing downward
            showline=True,
            mirror=True,
        )
        fig.update_layout(showlegend=False)
        return fig

@nosj
class ModelSectionSettings(PanelSettings):
    # Order here drives the order the gear-icon settings form shows them
    # in (PanelSettings.render() walks the schema properties in
    # declaration order) -- titles are explicit since the default
    # fallback is the raw attribute name (e.g. 'Bar_length_width_factor').
    x_axis: Literal['daytime', 'site_id'] = field(default='site_id', metadata={'title': 'x axis'})
    y_axis: Literal['depth', 'elevation'] = field(default='elevation', metadata={'title': 'y axis'})
    vmin: float = field(default=1.0, metadata={'title': 'vmin'})
    vmax: float = field(default=500., metadata={'title': 'vmax'})
    bars: bool = field(default=True, metadata={'title': 'Show as bars'})
    log_colorbar: bool = field(default=False, metadata={'title': 'Log Colorbar'})
    # ONE factor for every x-axis mode (site_id, daytime, 'line N') and for
    # boreholes: bar/box half-width = total_length * Bar_length_width_factor
    # / 2, where total_length is the drawn line's actual total_length in
    # meters (line mode) or the plotted x-range (site_id/daytime, the
    # closest analog). Reference cross-sections from other TEM inversion
    # software size bars off the whole SECTION's length, not local point
    # density -- a short, sparsely-sampled line's bars stretch out to a
    # size proportional to its own total length instead of leaving big
    # blank gaps wherever the nearest neighbor happens to be far away, so
    # lines of very different lengths still look similarly "full" (see
    # _bar_width / _local_half_widths). A tight local cluster of points
    # still gets squeezed below this target (never overlapping) -- see
    # _local_half_widths -- "if a line is packed with data, they will be
    # squeezed and that's how it is."
    # 0.025 (2.5% of section length) calibrated against reference
    # screenshots from another TEM software (lines ~500 m-4000 m with
    # ~15-150 m wide bars); tune to taste.
    Bar_length_width_factor: float = field(default=0.025, metadata={'title': 'Bar Width (% of section length)'})
    misfit: bool = field(default=True, metadata={'title': 'Misfit'})
    doi: bool = field(default=True, metadata={'title': 'DOI'})
    radius: float = field(default=100.0, metadata={'title': 'TEM radius'})
    Borehole_radius: float = field(default=100.0, metadata={'title': 'Borehole radius'})


class ModelSection(Panel):
    highlighted: int = None
    buffer_len = 50
    buffer_start = 0
    # This panel is the same shared instance on both the QC and Interpret
    # tabs. On QC it should page through the buffer window like the rest
    # of that tab, with its x-axis/radius/Borehole_radius controls
    # hidden; on Interpret it should show every site with those controls
    # available instead -- see add_callbacks()'s toggle_qc_vs_interpret,
    # which flips this (and the controls box's visibility) based on which
    # tab is active. Defaults to the QC behavior, matching the controls
    # box's own default-hidden state in initialize(), for before the
    # first tab switch happens.
    use_buffer = True
    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', ModelSectionSettings(id='model_section'))
        settings.radius=100.
        settings.Borehole_radius = 100.
        
        super().__init__(id='model_section', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def initialize(self):
        from __main__ import sesh
        options=['site_id', 'daytime']
        if sesh.lines is not None:
            line_id = np.unique(sesh.lines.line.values)
            options += [f'line {i:02d}' for i in line_id]

        return  html.Div([
                    html.Div(
                        [
                        dcc.Graph(
                        id=self.id,
                        figure=self.render(),
                        mathjax=True,
                        # Less than 100% so there's visible gap above the
                        # plot, between it and the subtabs (Model section /
                        # model_section_settings / 3D Model) -- the wrapper
                        # below is a flex column with justifyContent:
                        # 'flex-end', so the leftover space collects at the
                        # TOP instead of the bottom (flexShrink: 0 keeps the
                        # graph at exactly this height rather than flex
                        # shrinking it further to fit content).
                        style={"height": "95%", "flexShrink": 0} #style={"height": "100%"}
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dbc.Label(
                                            "x-axis",
                                            html_for=self.id + "_axis",
                                            class_name="mb-0",
                                            style=FLOATING_BOX_LABEL_STYLE
                                        ),
                                        dbc.Select(
                                            id=self.id + "_axis",
                                            options=options,
                                            value="site_id",
                                            style={"width": "120px"},
                                        ),
                                    ],
                                    style=FLOATING_BOX_ROW_STYLE,
                                ),
                                html.Div(
                                    [
                                        dbc.Label(
                                            "radius",
                                            html_for=self.id + "_radius",
                                            class_name="mb-0",
                                            style=FLOATING_BOX_LABEL_STYLE
                                        ),
                                        dbc.Input(
                                            id=self.id + "_radius",
                                            value=100.0,
                                            type="number",
                                            step=10.0,
                                            disabled=True,
                                            style={"width": "120px"},
                                        ),
                                    ],
                                    style=FLOATING_BOX_ROW_STYLE,
                                ),
                                html.Div(
                                    [
                                        dbc.Label(
                                            "Borehole radius",
                                            html_for=self.id + "_bor_radius",
                                            class_name="mb-0",
                                            style=FLOATING_BOX_LABEL_STYLE
                                        ),
                                        dbc.Input(
                                            id=self.id + "_bor_radius",
                                            value=100.0,
                                            type="number",
                                            step=10.0,
                                            disabled=True,
                                            style={"width": "120px"},
                                        ),
                                    ],
                                    style=FLOATING_BOX_ROW_STYLE,
                                ),
                            ],
                            id=self.id + '_controls',
                            # Hidden by default -- shown only on the
                            # Interpret tab, see add_callbacks()'s
                            # toggle_qc_vs_interpret. The QC tab shares
                            # this exact same panel instance but has no
                            # use for line-mode/radius controls, since it
                            # always just shows every site by site_id.
                            style={'display': 'none'},
                        ),
                        ],
                        # display:flex + justifyContent:'flex-end' pushes
                        # the graph (see its own height:78% above) to the
                        # bottom of this box, so the gap from the height
                        # reduction shows up above the plot instead of
                        # below it. The '_controls' floating box stays
                        # anchored to THIS div's own bottom-left corner
                        # (position:absolute, bottom/left set in
                        # toggle_qc_vs_interpret) regardless, since this
                        # div's own size is unchanged -- only the graph's
                        # position within it moves.
                        style={"position": "relative", "height": "100%", "display": "flex", "flexDirection": "column", "justifyContent": "flex-end"}
                    ),
                    gear_maker(self.id)],
                    style={'height': '100%'}
                )

    def project_borehole_to_line(self, bh_x, bh_y, line_x, line_y):
        from shapely.geometry import Point, LineString
        """
        bh_x, bh_y: UTM coordinates of borehole
        line_x, line_y: Lists of UTM coordinates for the section line
        returns: (distance_along_line, distance_from_line)
        """
        line = LineString(zip(line_x, line_y))
        point = Point(bh_x, bh_y)
        
        # 1. How far away is the borehole from the line?
        dist_from_line = point.distance(line)

        search_radius = self.settings.Borehole_radius
        if search_radius is None:
            search_radius = 100.0
        
        if dist_from_line > search_radius:
            return None, dist_from_line
        
        # 2. How far along the line is the nearest point to the borehole?
        dist_along_line = line.project(point)
        
        return dist_along_line, dist_from_line

    def get_utm_epsg(self,lat, lon):
        """
        Returns the EPSG code for the UTM zone based on lat/lon.
        """
        zone = int(np.floor((lon + 180) / 6) + 1)
        # 32600 is North, 32700 is South
        base = 32600 if lat >= 0 else 32700
        return base + zone

    def transform_line_to_utm(self, lats, lons):
        from pyproj import Transformer
        """
        Dynamically finds the EPSG and transforms the line coordinates.
        """
        if len(lats) == 0: return None, None
        
        # 1. Get EPSG from the first point of the line
        epsg = self.get_utm_epsg(lats[0], lons[0]) 
        
        # 2. Create transformer
        transformer = Transformer.from_crs("epsg:4326", f"epsg:{epsg}", always_xy=True)
        
        # 3. Transform
        utmx, utmy = transformer.transform(lons, lats)
        return utmx, utmy

    def add_boreholes_to_section_fig(self, fig, df_boreholes, rock_map, x_axis_name, width, line_utm=None):
        if df_boreholes is None or df_boreholes.empty:
            return fig
        
        y_mode = self.settings.y_axis.lower()

        # Group flat CSV rows by borehole ID
        grouped = df_boreholes.groupby('bh_id')

        for bh_id, group in grouped:
            first_row = group.iloc[0]
            
            # COORDINATE LOGIC
            if 'line' in x_axis_name and line_utm:
                # Project UTM bh_x/bh_y onto the UTM line coordinates
                bh_x, dist_to_line = self.project_borehole_to_line( first_row["bh_x"], first_row["bh_y"],  line_utm[0],  line_utm[1])
                if bh_x is None:
                    continue # Skip if outside radius
            else:
                # when plotted in site id
                bh_x = first_row.get("bh_x") or bh_id


            surface_z = 0 if y_mode == 'depth' else first_row["bh_elev"]

            # PLOT THE LAYERS
            for _, row in group.iterrows():
                # Note: 'bh_elev' is the surface, layer_top/bottom are depths
                z_top    = surface_z - float(row["layer_top"])
                z_bottom = surface_z - float(row["layer_bottom"])

                if y_mode == 'depth':
                    z_top= - z_top
                    z_bottom= - z_bottom
                    pass
                
                x_box = [bh_x - width, bh_x + width, bh_x + width, bh_x - width, bh_x - width]
                y_box = [z_top, z_top, z_bottom, z_bottom, z_top]

                rock  = str(row.get("layer_desc", "")).strip()
                color = rock_map.get(rock, "lightgray")

                # Purely visual (the colored box + border) -- hover/click
                # are handled entirely by the marker trace added below.
                # An earlier version put hoveron='fills' + hovertext here
                # to make the box's interior hoverable/clickable, but a
                # 'fills' hit produces a minimal clickData point with no
                # x/y/data at all (confirmed via a debug clickData dump:
                # only curveNumber came through), so it can never carry the
                # bh_id needed to resolve the click, and it also wins the
                # hit-test over an overlapping marker, blocking that path.
                fig.add_trace(go.Scatter(
                    x=x_box, y=y_box,
                    fill="toself",
                    fillcolor=color,
                    mode="lines",
                    line=dict(width=1, color="black"),
                    name=rock,
                    showlegend=False,
                    hoverinfo='skip',
                ))

                # The box's actual hover/click target: a real marker point
                # has proper x/y/data, unlike a fill-area hit. `meta` is
                # what compare_popups' alt-click handler resolves against
                # (clickData.points[0].data.meta -- read via the live graph
                # element client-side, since points[i].data is unpopulated
                # in this Plotly build). `customdata` is set too, since
                # unlike `meta` it IS included in the clickData prop Dash
                # sends to plain server-side callbacks -- app.py's
                # cross_panel_click (which highlights the nearest site on
                # ANY model_section click, alt or not) uses it to recognize
                # a borehole click and skip highlighting a site for it.
                # Sized to approximately cover the visible box; being a
                # circle centered in a rectangular box, corner clicks may
                # still miss.
                fig.add_trace(go.Scatter(
                    x=[bh_x], y=[(z_top + z_bottom) / 2],
                    mode='markers',
                    marker=dict(size=30, color='rgba(0,0,0,0)'),
                    meta=f'BH:{bh_id}',
                    customdata=[f'BH:{bh_id}'],
                    # Kept (even with showlegend=False) since Plotly falls
                    # back to an auto-generated "trace N" for it when
                    # unset, in places hovertemplate doesn't control (e.g.
                    # accessibility/ARIA hover labels).
                    name=rock,
                    showlegend=False,
                    # Explicit hovertemplate rather than hoverinfo='text' +
                    # hovertext -- more reliable for controlling the
                    # visible hover box content in this Plotly build.
                    # <extra></extra> suppresses the secondary trace-name
                    # box. (The real "Hover Unpack Error" console message
                    # this trace's customdata used to trigger came from
                    # app.py's sync_hover_to_map, a server-side callback
                    # that assumed ALL model_section hover customdata was
                    # the heatmap's [site_id, lat, lon] tuple -- fixed
                    # there directly, not a hovertemplate issue at all.)
                    hovertemplate=(
                        f"<b>BH: {bh_id}</b><br>{rock}<br>"
                        f"Depth: {row['layer_top']}-{row['layer_bottom']}m<extra></extra>"
                    ),
                ))

            # Add Borehole ID Label at the top
            fig.add_annotation(
                x=bh_x, y=first_row["bh_elev"],
                text=f"<b>{bh_id}</b>",
                showarrow=False, yshift=15,
                font=dict(size=10, color="black"),
                bgcolor="rgba(255,255,255,0.8)")
            
        return fig

    def _prepare_x_axis(self, df):
        """
        Resolve the configured x-axis to a plottable column. site_id is
        left as-is; daytime is decoded from its `date*100 + decimal_hour`
        encoding (see temframe._sweeps_to_df: `daytime = date*100 +
        daytime`, where date is YYYYMMDD) into milliseconds since epoch,
        matching dbdtSection's transect-view handling, so it renders on a
        real date axis instead of the raw, nearly-constant composite
        number. 'line N' resolves to that line's _line_N_x projection
        column, computed fresh from sesh.models and filtered to sites
        within settings.radius of the line -- mirrors render()'s own
        inline line-mode handling (and dbdtSection._prepare_x_axis in
        panels.py) since callers other than render() (cross_panel_click,
        compare_popups' alt-click site resolution) need the same
        resolution but previously got the raw 'line N' string back
        unresolved, which isn't a real column -> KeyError.
        """
        x_axis = self.settings.x_axis
        if x_axis.startswith('line'):
            from __main__ import sesh
            line_id = int(float(x_axis.split(' ')[-1]))
            line_col = f'_line_{line_id:0.0f}_x'
            df = sesh.models.copy()
            df = df.loc[np.abs(df[line_col.replace('_x', '_y')]) < self.settings.radius]
            return df, line_col
        if x_axis == 'daytime' and 'daytime' in df.columns:
            df = df.copy()
            date_int = np.floor(df['daytime'] / 100).astype('int64')
            hours    = df['daytime'] - date_int * 100
            date_df = pd.DataFrame({
                'year':  date_int // 10000,
                'month': (date_int // 100) % 100,
                'day':   date_int % 100,
            })
            dt = pd.to_datetime(date_df) + pd.to_timedelta(hours, unit='h')
            df['_daytime_ms'] = dt.astype('int64') // 10**6
            return df, '_daytime_ms'
        return df, x_axis

    # Fallback bar width (meters along the profile) for 'line N' mode
    # when there's only one (or zero) plotted point AND the line's
    # total_length itself is unknown -- essentially never happens (line
    # mode always has total_length from sesh.lines), kept only as a last
    # resort so a malformed/zero-length line can't divide-by-zero its way
    # into a zero-width bar.
    _LINE_BAR_WIDTH_FALLBACK = 5.0

    # Local-neighbor squeeze multiplier used only as an anti-overlap
    # safety net for tightly-packed points (see _local_half_widths) -- 0.5
    # means a packed pair squeezes down to exactly touch (half_width =
    # 0.5 * their gap on each side), never overlapping. Not user-tunable:
    # it only ever kicks in below the section-length-based target
    # (Bar_length_width_factor), which is the one setting that actually
    # controls how bars look in the normal (non-packed) case.
    _LOCAL_SQUEEZE_FACTOR = 0.5

    def _bar_width(self, df, x_axis, raw_x_axis, total_length=None):
        """
        Bar/borehole-box half-width in the same units as the resolved
        x-axis column -- total_length * Bar_length_width_factor / 2 (see
        that field), where total_length is the drawn line's actual
        total_length in meters (line mode, passed in by the caller) or,
        when not given, this view's own plotted x-range (site_id/daytime,
        the closest analog to a "section length"). Boreholes use this
        same scalar (see add_boreholes_to_section_fig's `width` param),
        so a borehole box is always the same width as a "normal"
        (non-squeezed) TEM model bar in the same view.
        """
        x_sorted = np.sort(df[x_axis].dropna().unique())
        if total_length is None and len(x_sorted) > 1:
            total_length = x_sorted[-1] - x_sorted[0]
        if total_length:
            return total_length * self.settings.Bar_length_width_factor / 2
        # No length info at all -- e.g. a single site_id/daytime point, or
        # (essentially never) a line whose total_length is unknown.
        if raw_x_axis == 'daytime':
            return 60_000.0  # 1 minute -- Bar_length_width_factor has nothing to scale against here
        if raw_x_axis.startswith('line'):
            return self._LINE_BAR_WIDTH_FALLBACK
        return 1.0  # site_id's own natural unit is ~1

    def _local_half_widths(self, x_sorted, fallback, total_length=None):
        """
        Per-point bar half-width for the bars heatmap (see the 'Show as
        bars' block in render_base()): normally the section-length-based
        target (total_length * Bar_length_width_factor / 2 -- see that
        field and _bar_width), the SAME target every bar in the view
        shares, so a sparse line's bars stretch out toward a size
        proportional to the WHOLE section instead of however far its
        nearest neighbor happens to be -- e.g. a 500 m line and a 4000 m
        line with similarly-spaced stations end up looking similarly
        "full" rather than the short line showing tiny slivers with huge
        gaps.

        Capped, per point, at that point's own LOCAL nearest-neighbor gap
        (left or right, whichever is smaller) times _LOCAL_SQUEEZE_FACTOR
        -- so a tight local cluster of sites still squeezes its own bars
        down to fit without overlapping, while normally-spaced points
        elsewhere in the same view keep the full section-length target.
        fallback is used only when total_length is completely unknown AND
        there's just one point plotted (no neighbor, no length to derive
        anything from) -- pass the already-computed _bar_width() scalar
        for that case, same as before.
        """
        n = len(x_sorted)
        if total_length is None and n > 1:
            total_length = x_sorted[-1] - x_sorted[0]
        target_half_width = (total_length * self.settings.Bar_length_width_factor / 2
                              if total_length else None)
        if n <= 1:
            return np.full(n, target_half_width if target_half_width is not None else fallback)
        gaps = np.diff(x_sorted)
        local_gap = np.empty(n)
        local_gap[0] = gaps[0]
        local_gap[-1] = gaps[-1]
        local_gap[1:-1] = np.minimum(gaps[:-1], gaps[1:])
        half_widths = local_gap * self._LOCAL_SQUEEZE_FACTOR
        if target_half_width is not None:
            half_widths = np.minimum(half_widths, target_half_width)
        # Never thinner than _MIN_BAR_FRACTION of the normal width, even
        # for sites packed closer than that -- those bars then overlap,
        # which _bar_layers handles by drawing them in a layer on top.
        min_half_width = (target_half_width if target_half_width is not None else fallback) * self._MIN_BAR_FRACTION
        return np.maximum(half_widths, min_half_width)

    # Smallest bar width, as a fraction of the normal (section-length
    # based) width. Below this a bar becomes a hard-to-see sliver, so
    # tightly packed sites are allowed to overlap instead.
    _MIN_BAR_FRACTION = 0.4

    @staticmethod
    def _bar_layers(x, half_widths, res_above, res_below, site_info):
        """
        Split the section's bars into heatmap "layers" with exact edges.

        Each bar i spans exactly [x_i - w_i, x_i + w_i]. A heatmap given
        len(columns) + 1 x values treats them as column EDGES, so each
        layer is laid out as alternating bar / gap columns with real edge
        positions -- no tiny offset columns. (The old layout put a NaN
        column 0.0001 x-units outside each bar edge; on the daytime axis
        (milliseconds since 1970, ~1.7e12) that offset is below floating
        point precision, and wherever two bars touched the offsets crossed
        over, giving out-of-order x values that Plotly draws as half or
        missing bars.)

        Bars that would overlap a neighbour (only possible because of the
        minimum width, see _local_half_widths) go into a later layer,
        which is drawn on top. Returns a list of
        (edges, res_above, res_below_or_None, site_info) per layer, where
        the arrays have one column per bar/gap column (NaN for gaps).
        """
        left, right = x - half_widths, x + half_widths
        span = float(np.nanmax(right) - np.nanmin(left)) if len(x) else 0.0
        tol = 1e-9 * max(span, 1.0)

        # Greedy interval layering: each bar goes into the first layer
        # whose last bar ends at or before this bar's left edge.
        layer_members, layer_end = [], []
        for i in np.argsort(left, kind='stable'):
            for k, end in enumerate(layer_end):
                if left[i] >= end - tol:
                    layer_members[k].append(i)
                    layer_end[k] = right[i]
                    break
            else:
                layer_members.append([i])
                layer_end.append(right[i])

        nan_info = np.full(site_info.shape[1], np.nan)
        layers = []
        for members in layer_members:
            edges = [left[members[0]]]
            cols = []
            for i in members:
                if left[i] > edges[-1] + tol:
                    cols.append(-1)           # gap column up to this bar
                    edges.append(left[i])
                cols.append(i)
                edges.append(right[i])
            cols = np.array(cols)
            is_gap = cols < 0
            safe = np.where(is_gap, 0, cols)

            def pick(grid):
                out = grid[:, safe].astype(float)
                out[:, is_gap] = np.nan
                return out

            info = site_info[safe].astype(float)
            info[is_gap] = nan_info
            layers.append((np.array(edges, dtype=float), pick(res_above),
                           pick(res_below) if res_below is not None else None, info))
        return layers

    def _empty_line_figure(self, x_axis):
        """Axes-only shell for 'line N' mode when there are no TEM models
        within radius. Mirrors render_base()'s normal axis setup (title,
        orientation, reversed depth axis) but carries no heatmap trace, so
        a boreholes-only view (drawn on top by render()) still lines up
        x-axis wise with the regular TEM section instead of looking like a
        blank/unrelated plot. render() fills in the x-range (from the
        line's total length) once it's built; callers fall back to a "no
        data" message only if no borehole traces end up drawn on it either.
        """
        fig = go.Figure()
        y_axis = self.settings.y_axis
        if y_axis == 'depth':
            fig.update_yaxes(autorange='reversed')
        fig.update_layout(
            xaxis=dict(title=x_axis.replace('_x', '').replace('_', ' ').strip(), title_standoff=4, type='linear'),
            yaxis=dict(title=y_axis),
            plot_bgcolor='white',
            hovermode='closest',
            # Keep in sync with render()'s margin=dict(b=...) and both
            # colorbar y= values in this file -- all sized around the
            # same horizontal colorbar gap.
            margin=dict(b=110),
        )
        return fig

    def _typical_ylim(self, df):
        """
        A DOI-based y-axis range computed from `df` (a models-like
        dataframe with site_id, top_depth/bottom_depth, doi, elevation,
        layer columns), using the same logic render() uses for its own
        y-range. Used as a fallback when a drawn line has no TEM sites in
        radius, so a boreholes-only view still uses the same vertical
        scale as a normal TEM section (computed from the full,
        unfiltered model set) instead of autoranging to fit just the
        boreholes, which made it look taller/shorter than the regular
        plots.
        """
        if df is None or df.empty:
            return None
        df_layers_long = df.melt(
            id_vars=['site_id', 'doi', 'layer', 'elevation'],
            value_vars=['top_depth', 'bottom_depth'],
            var_name='depth_type', value_name='depth')
        doi_df = df_layers_long.groupby('site_id')['doi'].first().reset_index()

        if self.settings.y_axis == 'elevation':
            boundary_elevation = df_layers_long['elevation'] - df_layers_long['depth']
            model_bottom_elev = boundary_elevation.min()
            doi_df['doi'] = df.groupby('site_id')['elevation'].first().values - doi_df['doi'].values
            y_bottom = doi_df["doi"].min() - 8
            if not np.isfinite(y_bottom) or y_bottom >= model_bottom_elev:
                y_bottom = model_bottom_elev - 8
            return [y_bottom, df_layers_long["elevation"].max() + 8]
        else:
            y_bottom = doi_df["doi"].max() + 8
            if not np.isfinite(y_bottom) or y_bottom <= df_layers_long["depth"].max():
                y_bottom = df_layers_long["depth"].max() + 8
            return [y_bottom, df_layers_long["depth"].min() - 8]

    def render_base(self):

        if self.dataframe is None: return self.empty_render()

        # --- Select dataframe ---
        raw_x_axis = self.settings.x_axis
        x_axis = raw_x_axis

        if x_axis.startswith('line'):
            line_id = int(float(x_axis.split(' ')[-1]))
            x_axis = f'_line_{line_id:0.0f}_x'

        total_length = None
        if 'line' in x_axis:
            from __main__ import sesh
            total_length = sesh.lines[sesh.lines.line == line_id].total_length.max()
            df = sesh.models.copy()
            df = df.loc[np.abs(df[x_axis.replace('_x', '_y')]) < self.settings.radius]
            if df.empty:
                # No inverted sites within the drawn line's radius -- render()
                # still needs a valid figure to overlay boreholes onto (with
                # the same axis setup a normal render would have, so a
                # boreholes-only view lines up with the regular TEM section),
                # rather than a crash from the empty-pivot/empty-array math
                # below. It falls back to a "no data" message itself only if
                # no boreholes turn out to be nearby either.
                return self._empty_line_figure(x_axis)
            width = self._bar_width(df, x_axis, raw_x_axis, total_length=total_length)
        else:
            df = self.dataframe.copy()
            df, x_axis = self._prepare_x_axis(df)
            width = self._bar_width(df, x_axis, raw_x_axis)

        # --- Clean + stabilize ---
        df = df.copy()
        df[x_axis] = df[x_axis].round(2)

        y_axis = self.settings.y_axis

        pivot = df.pivot_table(
            values='resistivity', index=x_axis, columns='center_depth',
            aggfunc='first').sort_index()

        # enforce consistent axis
        x = pivot.index.values
        depth = pivot.columns.values.squeeze()

        # A layer is "below DOI" once any part of it (its bottom edge) has
        # crossed the site's depth of investigation -- from that layer down
        # it's unreliable, so it gets drawn transparently (see below) rather
        # than the old smooth polygon overlay, which only followed one
        # boundary line interpolated between site x-positions and couldn't
        # reflect a per-layer/per-site DOI crossing. Computed here (before
        # the y-axis remap) in plain depth units, same units 'doi' is in
        # regardless of whether the display axis is depth or elevation.
        if self.settings.doi and 'doi' in df.columns and 'bottom_depth' in df.columns:
            bottom_pivot = df.pivot_table(
                values='bottom_depth', index=x_axis, columns='center_depth',
                aggfunc='first').reindex(index=pivot.index, columns=pivot.columns)
            doi_by_site = df.groupby(x_axis)['doi'].first().reindex(pivot.index).values
            below_doi_orig = bottom_pivot.values >= doi_by_site[:, None]
        else:
            below_doi_orig = None

        if y_axis == 'depth':
            # FAKE flat elevation
            elev = np.zeros(len(pivot.index))
            center_elev = elev[:, None] - depth[None, :]

            d_elev = int(center_elev.max() - center_elev.min()) + 50
            elev_axis = np.arange(d_elev) + center_elev.min() - 25

            dist = np.abs(elev_axis[:, None, None] - center_elev[None, :, :])
            # Sites can have different depth discretizations (e.g. different
            # instruments), so `depth` is the union of every site's layer
            # boundaries -- most columns are NaN for any given site. Restrict
            # the nearest-neighbor search to that site's own valid columns,
            # otherwise it can snap to a numerically-closer but foreign (NaN)
            # column and punch holes in that site's profile.
            valid = ~np.isnan(pivot.values)
            dist = np.where(valid[None, :, :], dist, np.inf)
            nearest_idx = dist.argmin(axis=-1)

            n_elev, n_sites = nearest_idx.shape
            station_idx = np.broadcast_to(np.arange(n_sites), (n_elev, n_sites))

            res_grid = pivot.values[station_idx, nearest_idx]
            below_doi_grid = below_doi_orig[station_idx, nearest_idx] if below_doi_orig is not None else None

            # mask air / below model
            heaven = elev_axis[:, None] > elev[None, :]
            hell   = elev_axis[:, None] < (elev[None, :] - depth.max() * 1.1)

            res_grid[heaven] = np.nan
            res_grid[hell]   = np.nan

            y = -elev_axis

            # y = depth
            # res_grid = pivot.values.T  # (depth, site)

        elif y_axis == 'elevation':

            # elevation per site (aligned with pivot index!)
            elev = df.groupby(x_axis)['elevation'].first().reindex(pivot.index).values

            center_elev = elev[:, None] - depth[None, :]

            d_elev = int(center_elev.max() - center_elev.min()) + 50
            elev_axis = np.arange(d_elev) + center_elev.min() - 25

            dist = np.abs(elev_axis[:, None, None] - center_elev[None, :, :])
            # See comment in the 'depth' branch above: restrict the search to
            # each site's own valid (non-NaN) depth columns.
            valid = ~np.isnan(pivot.values)
            dist = np.where(valid[None, :, :], dist, np.inf)
            nearest_idx = dist.argmin(axis=-1)

            n_elev, n_sites = nearest_idx.shape
            station_idx = np.broadcast_to(np.arange(n_sites), (n_elev, n_sites))

            res_grid = pivot.values[station_idx, nearest_idx]
            below_doi_grid = below_doi_orig[station_idx, nearest_idx] if below_doi_orig is not None else None

            # mask air / below model
            heaven = elev_axis[:, None] > elev[None, :]
            hell   = elev_axis[:, None] < (elev[None, :] - depth.max() * 1.1)

            res_grid[heaven] = np.nan
            res_grid[hell]   = np.nan

            y = elev_axis

        else:
            raise ValueError(f"Unknown y_axis: {y_axis}")

        if below_doi_grid is not None:
            res_grid_above = np.where(below_doi_grid, np.nan, res_grid)
            res_grid_below = np.where(below_doi_grid, res_grid, np.nan)
        else:
            res_grid_above = res_grid
            res_grid_below = None

        id_map = df.groupby(x_axis)[['site_id', 'latitude', 'longitude']].first().reindex(pivot.index)
        # customdata columns: [site_id, lat, lon, utm E, utm N] -- app.py's
        # sync_hover_to_map relies on the first three staying in this order.
        utm_e, utm_n = latlon_to_utm(id_map['latitude'].values, id_map['longitude'].values)
        zone_label = utm_zone_label(id_map['latitude'].values, id_map['longitude'].values)
        site_info = np.column_stack([id_map[['site_id', 'latitude', 'longitude']].values, utm_e, utm_n])

        if self.settings.bars:
            # Per-point half-width (see _local_half_widths) rather than
            # the single `width` scalar for every bar -- `width` (from
            # _bar_width, the view's overall median spacing) is still
            # used as the single-point fallback and for boreholes/the
            # highlight rect below, where a per-site value doesn't apply.
            half_widths = self._local_half_widths(x, fallback=width, total_length=total_length)
            layers = self._bar_layers(x, half_widths, res_grid_above, res_grid_below, site_info)
        else:
            layers = [(x, res_grid_above, res_grid_below, site_info)]

        # Final Plotting using Graph Objects for precision
        import plotly.graph_objects as go

        # The z data/color mapping is ALWAYS log10(resistivity) -- that
        # part never changes. log_colorbar (default off) only changes how
        # the colorbar's ticks are LABELED: off shows real Ωm values (at
        # their correct log-spaced positions, via _log_colorbar_ticks), on
        # shows the raw log10 exponent Plotly would auto-tick otherwise
        # (0, 0.5, 1, ...). Keep colorbar_kwargs in sync with the
        # boreholes-only dummy colorbar below, which mirrors this same
        # geometry/labeling so automargin reserves the same space either way.
        zmin, zmax = np.log10(self.settings.vmin), np.log10(self.settings.vmax)
        title_text = "Resistivity [log10 Ωm]" if self.settings.log_colorbar else "Resistivity [Ωm]"
        colorbar_kwargs = dict(
            title=dict(text=title_text, side="bottom"),
            **resistivity_colorbar_tick_kwargs(self.settings.vmin, self.settings.vmax, self.settings.log_colorbar),
        )

        y_label = 'Elevation' if y_axis == 'elevation' else 'Depth'
        hovertemplate = (
            f"Site: %{{customdata[0]}}<br>"
            f"UTM{zone_label}: %{{customdata[3]:.0f}} E, %{{customdata[4]:.0f}} N<br>"
            f"{y_label}: %{{y:.1f}} m<br>"
            "Resistivity: %{customdata[5]:.1f} Ωm<extra></extra>"
        )
        colorbar = dict(
            orientation="h",
            # In paper-fraction units (a % of the whole figure's
            # height), not axis-relative -- keep in sync with the
            # dummy colorbar below and both margin=dict(b=...) calls
            # in this file, which all assume the same gap.
            y=-0.45,
            x=0.5,
            xanchor="center",
            len=0.5,
            thickness=15,
            **colorbar_kwargs)

        # One heatmap (plus its faded below-DOI twin) per layer -- normally
        # a single layer; extra layers only hold bars that would otherwise
        # overlap a neighbour (see _bar_layers) and are drawn on top. The
        # first layer's main trace stays fig.data[0] and carries the colorbar.
        fig = go.Figure()
        for k, (layer_x, layer_above, layer_below, layer_info) in enumerate(layers):
            # customdata columns: [site_id, lat, lon, utm E, utm N, resistivity]
            # -- the resistivity column lets the hovertemplate show the
            # actual (non-log) value per cell.
            customdata = np.concatenate(
                [np.tile(layer_info, (len(y), 1, 1)), layer_above[:, :, None]], axis=-1)
            heatmap_kwargs = dict(
                x=layer_x,
                y=y,
                customdata=customdata,
                zsmooth=False,
                hoverongaps=False,
                colorscale=RESISTIVITY_COLORSCALE,
                zmin=zmin,
                zmax=zmax,
            )
            fig.add_trace(go.Heatmap(
                z=np.log10(layer_above),
                hovertemplate=hovertemplate,
                showscale=(k == 0),
                colorbar=colorbar,
                **heatmap_kwargs
            ))
            if layer_below is not None:
                fig.add_trace(go.Heatmap(
                    z=np.log10(layer_below),
                    opacity=0.35,
                    showscale=False,
                    hoverinfo='skip',
                    name='Below DOI',
                    **heatmap_kwargs
                ))

        # Heatmap traces don't support Plotly's box/lasso select at all --
        # only scatter-like traces with discrete markers do -- so a drawn
        # selection box over the heatmap alone never produces any
        # selectedData, and app.py's unified_handler (which syncs a
        # selection here to Sounding/Model Graph) never fires. An
        # invisible column of markers per site, spanning the full y-range,
        # gives box-select something real to hit -- same trick used for
        # borehole hit-testing elsewhere in this app. customdata[0] is the
        # site_id, matching what unified_handler reads.
        n_select_rows = 15
        y_select = np.linspace(y.min(), y.max(), n_select_rows)
        select_customdata = np.repeat(site_info, n_select_rows, axis=0)
        fig.add_trace(go.Scatter(
            x=np.repeat(x, n_select_rows),
            y=np.tile(y_select, len(x)),
            mode='markers',
            marker=dict(size=14, color='rgba(0,0,0,0)'),
            customdata=select_customdata,
            hoverinfo='skip',
            showlegend=False,
            name='select-targets',
        ))

        if y_axis == 'depth':
            fig.update_yaxes(autorange="reversed")

        # Filter out NaNs to find the real min/max for the range
        all_x = np.concatenate([np.asarray(layer[0], dtype=float) for layer in layers])
        valid_x = all_x[~np.isnan(all_x)]
        x_min, x_max = np.min(valid_x), np.max(valid_x)

        # 3. Update Layout
        xaxis_kwargs = dict(
            title=('Daytime' if raw_x_axis == 'daytime' else x_axis.replace('_x', '').replace('_', ' ').strip()),
            range=[x_min, x_max], # Forces the first bar to show fully
            title_standoff=4
        )
        if raw_x_axis == 'daytime':
            # _daytime_ms is milliseconds since epoch (see _prepare_x_axis)
            # -- render it on a real date axis instead of a raw number,
            # same scheme as dbdtSection's transect view.
            day_ms = 1000 * 60 * 60 * 24
            xaxis_kwargs.update(
                type='date',
                tickformatstops=[
                    dict(dtickrange=[None, day_ms], value='%H:%M:%S'),
                    dict(dtickrange=[day_ms, None], value='%Y-%m-%d %H:%M'),
                ],
            )
        else:
            xaxis_kwargs['type'] = 'linear'

        fig.update_layout(
            xaxis=xaxis_kwargs,
            yaxis=dict(title=y_axis),
            plot_bgcolor='white',
            # hovermode="x",
            hovermode="closest",
            margin=dict(b=110), # Bottom margin for the horizontal colorbar -- keep in sync with render_base()'s and the y=-0.45 colorbar positions above
            # Box select active by default, same as Sounding/Apparent
            # res/Transect view, so selecting sites here to sync with
            # those panels (and Model Graph) doesn't require first
            # clicking the modebar's select tool.
            dragmode='select',
        )

        return fig

    def render(self):
       
        if self.dataframe is None: return self.empty_render()
        fig = self.render_base()

        df = self.dataframe.copy()
        raw_x_axis = self.settings.x_axis
        x_axis = raw_x_axis
        if x_axis.startswith('line'):
            line_id = int(float(x_axis.split(' ')[-1]))
            x_axis = f'_line_{line_id:0.0f}_x'

        line_coords_utm = None

        if 'line' in x_axis:
            from __main__ import sesh
            df = sesh.models.copy()
            df = df.loc[np.abs(df[x_axis.replace('_x', '_y')])<self.settings.radius]
            x_min = 0
            x_max = sesh.lines[sesh.lines.line==line_id].total_length.max()
            current_width = self._bar_width(df, x_axis, raw_x_axis, total_length=x_max)

            # Filter the line from session
            c_line = sesh.lines.loc[sesh.lines.line == line_id]

            if not c_line.empty:
                from pyproj import Transformer
                epsg = self.get_utm_epsg(c_line.latitude.iloc[0], c_line.longitude.iloc[0])

                transformer = Transformer.from_crs("epsg:4326", f"epsg:{epsg}", always_xy=True)
                utmx, utmy = transformer.transform(c_line.longitude.values, c_line.latitude.values)

                line_coords_utm = (utmx, utmy)
        else:
            # Match render_base()'s decoding (daytime -> milliseconds since
            # epoch) so the overlaid misfit/DOI/highlight traces below line
            # up with the heatmap's x positions.
            df, x_axis = self._prepare_x_axis(df)
            current_width = self._bar_width(df, x_axis, raw_x_axis)
            x_min = None
            x_max = None

        from __main__ import sesh
        n_traces_before_boreholes = len(fig.data)
        if sesh.boreholes is not None and not sesh.boreholes.empty:
           fig = self.add_boreholes_to_section_fig(fig, sesh.boreholes, sesh.rock_map, x_axis,current_width,
                line_utm=line_coords_utm)
        boreholes_drawn = len(fig.data) > n_traces_before_boreholes

        if df.empty:
            # No inverted sites within the drawn line's radius --
            # render_base() already returned the axes-only shell (with
            # boreholes now drawn on top of it, if any were nearby); the
            # misfit/DOI/highlight overlays below all assume non-empty
            # data, so there's nothing more to add. Still apply the same
            # x-range the full case uses below, so a boreholes-only view
            # isn't left on Plotly's default autorange.
            if x_min is not None and x_max is not None:
                fig.update_xaxes(range=[x_min, x_max], autorange=False)
            if not boreholes_drawn:
                # Neither TEM models nor boreholes are in the search
                # radius -- nothing to show at all.
                fig.add_annotation(
                    text="No TEM models and Boreholes in the search radius",
                    xref="paper", yref="paper", x=0.5, y=0.5,
                    showarrow=False, font=dict(size=16, color="gray"),
                )
                fig.update_xaxes(visible=False)
                fig.update_yaxes(visible=False)
            else:
                # Boreholes-only: match the same DOI-based y-scale a
                # normal TEM section uses, rather than leaving the axis
                # autoranged to just the boreholes' own depths.
                ylim = self._typical_ylim(sesh.models)
                if ylim is not None:
                    fig.update_yaxes(range=ylim, autorange=False)
                # A normal render's heatmap colorbar (horizontal, anchored
                # at y=-0.45) makes Plotly's automargin reserve extra
                # bottom space beyond the plain margin=dict(b=110) both
                # figures share -- without it, this boreholes-only figure
                # ends up visibly taller (its plot area expands to fill
                # the space the colorbar would have used). A dummy trace
                # with the same colorbar geometry (thickness/length/font
                # sizes -- what automargin actually sizes around) reserves
                # that same space, but is made fully transparent (colors,
                # tick labels and title all rgba(0,0,0,0)) rather than
                # visible, since there's no resistivity data here for a
                # colorbar to legitimately represent.
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='markers',
                    marker=dict(
                        size=0, opacity=0,
                        colorscale=[[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0)']],
                        cmin=0, cmax=1,
                        color=[0], showscale=True,
                        colorbar=dict(
                            orientation="h", y=-0.45, x=0.5, xanchor="center",
                            len=0.5, thickness=15, outlinewidth=0,
                            tickfont=dict(color='rgba(0,0,0,0)'),
                            title=dict(text="Resistivity [log10 Ωm]" if self.settings.log_colorbar else "Resistivity [Ωm]",
                                       side="bottom", font=dict(color='rgba(0,0,0,0)'))),
                    ),
                    showlegend=False, hoverinfo='skip',
                ))
            return fig

        df_layers_long = df.melt(
            id_vars=[x_axis, 'resistivity', 'misfit','doi', 'layer', 'elevation'],
            value_vars=['top_depth', 'bottom_depth'],
            var_name='depth_type',
            value_name='depth').sort_values([x_axis, 'layer', 'depth'])
        fig.update_layout(yaxis2=dict(title='Misfit',overlaying='y',side='right',showgrid=False))
        # ---- Misfit only for buffered sites ----
        if self.settings.misfit:
            misfit_df = (df_layers_long.groupby(x_axis)['misfit'].first().reset_index())

            misfit_trace = go.Scatter(x=misfit_df[x_axis],y=misfit_df['misfit'],mode='lines',line=dict(color='black', width=2),
                name='Misfit',yaxis='y2')

            y_dashed = misfit_df['misfit'].copy()
            y_dashed[y_dashed <= 8] = np.nan
            y_dashed[y_dashed > 8] = 7.95

            fig.add_trace(go.Scatter(
                x=misfit_df[x_axis],
                y=y_dashed,
                mode="lines",
                line=dict(color="rgba(0,0,0,0.7)", dash="dash"),
                showlegend=False,
                yaxis='y2'))

            fig.add_trace(misfit_trace)

            fig.update_layout(
                legend=dict(x=0.89, y=0.2,xanchor="left",yanchor="top",bgcolor="rgba(255,255,255,0.8)")
                )

            fig.update_layout(yaxis2=dict(title=dict(text="Misfit",standoff=10),overlaying="y",side="right",showgrid=False))
        
        doi_df = (df_layers_long.groupby(x_axis)["doi"].first().reset_index())

        if self.settings.y_axis=='elevation':
            # df_layers_long['elevation'] is each site's constant SURFACE
            # elevation (an id_var carried through the melt unchanged, not
            # a per-layer value) -- using its min() as the deep-end
            # fallback only captured the shallowest site's surface, not
            # how deep any model actually goes, which is what was
            # producing a near-zero-height y-range whenever the doi-based
            # value got rejected below. The real per-boundary elevation is
            # elevation - depth (top_depth/bottom_depth from the melt).
            boundary_elevation = df_layers_long['elevation'] - df_layers_long['depth']
            model_bottom_elev = boundary_elevation.min()

            doi_df['doi'] = df.groupby(x_axis)['elevation'].first().values - doi_df['doi'].values
            y_bottom = doi_df["doi"].min() - 8
            # doi should be at or below the deepest (lowest-elevation) actual
            # layer boundary; if it isn't (e.g. a bad/misaligned doi value --
            # see temframe.invert's `doi[::2]` slicing, which assumes a fixed
            # doi-count-to-site-count ratio that per-instrument inversion
            # runs can violate), fall back to the real layer extent instead
            # of silently producing a degenerate (non-inverted) axis.
            if not np.isfinite(y_bottom) or y_bottom >= model_bottom_elev:
                y_bottom = model_bottom_elev - 8
            ylim = [y_bottom, df_layers_long["elevation"].max()+8]
        else:
            y_bottom = doi_df["doi"].max() + 8
            if not np.isfinite(y_bottom) or y_bottom <= df_layers_long["depth"].max():
                y_bottom = df_layers_long["depth"].max() + 8
            ylim = [y_bottom, df_layers_long["depth"].min()-8]
        
        if x_min is None and x_max is None:
            x_vals = np.sort(df_layers_long[x_axis].dropna().unique())
            if len(x_vals) > 0:
                if self.use_buffer:
                    # Zoom into the buffer window, same as dbdtSection, so
                    # this panel stays in sync when paging the buffer.
                    # Falls back to the full range if the window doesn't
                    # overlap any data at all (e.g. its default
                    # site-id-scale value landing on a daytime-scale axis).
                    x_slice = x_vals[(x_vals >= self.buffer_start) & (x_vals <= self.buffer_start + self.buffer_len)]
                    if len(x_slice) > 0:
                        x_min, x_max = x_slice.min(), x_slice.max()
                    else:
                        x_min, x_max = x_vals.min(), x_vals.max()
                else:
                    # Interpret tab: always show every site, unbuffered.
                    x_min, x_max = x_vals.min(), x_vals.max()
            else:
                x_min, x_max = 0, 1

        # The below-DOI fade itself is drawn per-layer inside
        # render_base() (a second, semi-transparent Heatmap trace), since
        # a per-site/per-layer fade can't be expressed as one smooth
        # polygon interpolated between site x-positions. doi_df above is
        # still needed for ylim.
        #
        # Black-boundary highlight rect(s) for the currently selected
        # site(s) -- moved out from under `if self.settings.doi:` (which
        # only ever gated the now-elsewhere below-DOI fade) since
        # highlighting shouldn't silently stop working just because the
        # DOI setting is off. self.highlighted is a scalar from
        # single-site callbacks (cross_panel_click, highlight_change) but
        # a list/set from multi-select ones (unified_handler) -- draw one
        # rect per selected site either way.
        if self.highlighted is not None and self.dataframe is not None:
            highlighted = self.highlighted
            if isinstance(highlighted, (list, tuple, set, np.ndarray, pd.Series)):
                highlighted_ids = list(highlighted)
            else:
                highlighted_ids = [highlighted]

            x_vals = np.sort(df[x_axis].dropna().unique())
            if len(x_vals) > 1:
                diffs = np.diff(x_vals)
                dx = np.median(diffs) * 0.5
            else:
                dx = 0.5

            for site_id in highlighted_ids:
                selected_df = df[df["site_id"] == site_id]
                if selected_df.empty:
                    continue
                x_value = selected_df[x_axis].iloc[0]
                fig.add_shape(
                    type="rect",
                    x0=x_value - dx,
                    x1=x_value + dx,
                    # Spans the actual visible y-range (ylim, computed
                    # above -- elevation-scale when y_axis=='elevation',
                    # depth-scale otherwise), not raw depth unconditionally.
                    # Elevation values (site surface elevation minus depth)
                    # live on a completely different scale than plain
                    # depth, so a hardcoded depth-based rect landed
                    # entirely outside the visible range and never showed
                    # up whenever y_axis was 'elevation' (the default).
                    y0=min(ylim),
                    y1=max(ylim),
                    line=dict(color="black", width=1.5),
                    fillcolor="rgba(0,0,0,0.0)",
                )

        fig.update_xaxes(range=[x_min, x_max], autorange=False)
        fig.update_yaxes(range=ylim, autorange=False)

        if self.settings.misfit:
            fig.update_layout(yaxis2=dict(range=[0, 8]))
        return fig
        


        # def add_callbacks(self, app):
        #     super().add_callbacks(app)

        #     @app.callback(
        #         Output(self.id, 'figure', allow_duplicate=True),
        #         Output('data-buffer','data', allow_duplicate=True),
        #         Input('next-buffer', 'data'),
        #         Input('prev-buffer', 'data'),
        #         State('buffer','length'),
        #         prevent_initial_call=True
        #     )
        #     def update_buffer(data,length):
        #         if not ctx.triggered:
        #             raise PreventUpdate
        #         trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

        #         highlighted = m1.highlighted
        #         if trigger_id == 'next-buffer':
        #             self.buffer_start += length
        #             if self.buffer_start > len(self.dataframe): self.buffer_start-=length 
        #         elif trigger_id == 'prev-buffer':
        #             self.buffer_start -= length
        #             if self.buffer_start>0: self.buffer_start=0
                    
        #         return self.render(), {"length": length, "start_site": self.buffer_start}
            
        #     @app.callback(
        #         Output(self.id, 'figure', allow_duplicate=True),
        #         Input('next-buffer', 'data'),
        #         prevent_initial_call=True
        #     )
        #     def update_buffer(data,length):
        #         if not ctx.triggered:
        #             raise PreventUpdate
        #         trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

        #         highlighted = m1.highlighted
        #         if trigger_id == 'next-buffer':
        #             self.buffer_start += length
        #             if self.buffer_start > len(self.dataframe): self.buffer_start-=length 
        #         elif trigger_id == 'prev-buffer':
        #             self.buffer_start -= length
        #             if self.buffer_start>0: self.buffer_start=0
        #         return self.render()
        #     return fig

    def add_callbacks(self, app):
        super().add_callbacks(app)
    
        @app.callback(
            Output({'type': f'settings-{self.id}', 'key': 'radius'}, 'value'),
            Input(self.id+'_radius', 'value'),
            prevent_initial_call=True
        )
        def update_radius(radius):
            self.settings.radius=radius
            return radius
        

        @app.callback(
            # Combine all Outputs triggered by the x-axis dropdown here
            Output(self.id + '_radius', 'disabled'),    # The model radius slider
            Output(self.id + '_bor_radius', 'disabled'), # The borehole radius slider
            Output({'type': f'settings-{self.id}', 'key': 'x_axis'}, 'value'),
            Input(self.id + '_axis', 'value'),
            prevent_initial_call=True
        )
        def update_xaxis_and_ui_states(x_axis):
            # Determine if radius controls should be enabled
            # (Only enabled if we are in 'line' mode)
            is_not_line = not str(x_axis).startswith('line')
            
            # Update the internal settings object
            self.settings.x_axis = x_axis
            
            # Return values for all three outputs in order
            return is_not_line, is_not_line, x_axis

        @app.callback(
            Output({'type': f'settings-{self.id}', 'key': 'Borehole_radius'}, 'value'),
            Input(self.id+'_bor_radius', 'value'),
            prevent_initial_call=True
        )
        def update_Borehole_radius(Borehole_radius):
            self.settings.Borehole_radius=Borehole_radius
            return Borehole_radius

        @app.callback(
            Output(self.id + '_controls', 'style'),
            Output(self.id + '_axis', 'value'),
            self.output,
            Input('interpret_layout', 'color'),
            prevent_initial_call=True
        )
        def toggle_qc_vs_interpret(color):
            # This panel is shared between the QC and Interpret tabs. On
            # QC there's no use for line-mode/radius controls (it always
            # just shows every site by site_id), so hide them, force back
            # to that view, and page it via the buffer like the rest of
            # the QC tab does; on Interpret, show the controls instead and
            # always show every site (paging doesn't apply there).
            is_interpret = (color == 'primary')
            self.use_buffer = not is_interpret
            if not is_interpret:
                self.settings.x_axis = 'site_id'
                controls_style = {'display': 'none'}
                axis_dropdown_value = 'site_id'
            else:
                controls_style = {**FLOATING_BOX_STYLE, 'bottom': '12px', 'left': '12px'}
                axis_dropdown_value = no_update
            return controls_style, axis_dropdown_value, self.render()