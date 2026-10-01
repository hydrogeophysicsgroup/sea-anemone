from basepanel import *
import time
import plotly.io as pio
from typing import Literal
import plotly.express as px
import plotly.graph_objects as go
from dash import dash_table, ctx, no_update, Patch
import numpy as np
from nosj import nosj
import utm
import pandas as pd
from pandas import DataFrame
from dataclasses import field


line_colors = [
    '#1f77b4',  # muted blue
    '#ff7f0e',  # safety orange
    '#2ca02c',  # cooked asparagus green
    '#d62728',  # brick red
    '#9467bd',  # muted purple
    '#8c564b',  # chestnut brown
    '#e377c2',  # raspberry yogurt pink
    '#7f7f7f',  # middle gray
    '#bcbd22',  # curry yellow-green
    '#17becf'   # blue-teal
]


# Define a custom template
custom_template = {
    "layout": {
        "font": {"family": "Arial", "size": 14, "color": "black"},
        "plot_bgcolor": "white",
        "paper_bgcolor": "white",
        "margin": {"l": 50, "r": 50, "t": 50, "b": 50},
        "xaxis": {
            "showgrid": True,
            "gridcolor": "#e5e5e5",
            "zeroline": False,
            "showline": True,
            "linecolor": "black",
            "ticks": "outside",
        },
        "yaxis": {
            "showgrid": True,
            "gridcolor": "#e5e5e5",
            "zeroline": False,
            "showline": True,
            "linecolor": "black",
            "ticks": "outside",
        },
    }
}
pio.templates["custom"] = custom_template
pio.templates.default = "custom"




def cdist(lat1,lon1,lat2,lon2):
    lat1rad = lat1/(180./np.pi)
    lon1rad = lon1/(180./np.pi)
    lat2rad = lat2/(180./np.pi)
    lon2rad = lon2/(180./np.pi)
    d = 3963. * np.arccos((np.sin(lat1rad)*np.sin(lat2rad))+ \
            np.cos(lat1rad)*np.cos(lat2rad)*np.cos(lon2rad-lon1rad)) * \
            1.609344 * 1000.
    return d


class ProjectionLine:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        dx,dy = x[1]-x[0], y[1]-y[0]
        self.phi = -np.arctan2(dy,dx)
        self.R = np.array([[np.cos(self.phi), -np.sin(self.phi)],
                           [np.sin(self.phi), np.cos(self.phi)]])
        self.iR = np.array([[np.cos(-self.phi), -np.sin(-self.phi)],
                            [np.sin(-self.phi), np.cos(-self.phi)]])

        self.length = np.sqrt(dx**2 + dy**2)
        self.m = dy/dx
        self.b = y[0] - self.m*x[0]

    def inbounds(self, x, y, buffer=np.inf):
        xp,yp = self.to_line_coords(x,y)
        inbounds = (xp>=0) * (xp<=self.length)
        inbounds *= np.abs(yp) <= buffer
        return inbounds
        
    def to_line_coords(self, x, y):
        xt,yt = x-self.x[0], y-self.y[0]
        return np.dot(self.R, np.array([xt,yt]))
    
    def from_line_coords(self, xp, yp):
        xt,yt = np.dot(self.iR, np.array([xp,yp]))
        return xt+self.x[0], yt+self.y[0]
    

    
class Profile:
    def __init__(self, lat, lon):
        x,y,zone,letter = utm.from_latlon(lat, lon)
        self.x = x
        self.y = y
        self.zone = zone
        self.letter = letter
        self.n_segments = len(x)-1
        self.lines = [ProjectionLine(x[i:i+2], y[i:i+2]) for i in range(self.n_segments)]
        self.cumulative_length = np.cumsum([0]+[line.length for line in self.lines])

    @classmethod
    def from_point_list(cls, points):
        x = np.array([point[0] for point in points])
        y = np.array([point[1] for point in points])
        return cls(x,y)
    
    @property
    def length(self):
        return self.cumulative_length[-1]
    
    @property
    def m(self):
        return np.array([line.m for line in self.lines]).squeeze()

    @property
    def b(self):
        return np.array([line.b for line in self.lines]).squeeze()
        
    def inbounds(self, x, y, buffer=np.inf):
        inbounds = np.zeros_like(x, dtype=bool)
        for line in self.lines:
            inbounds += line.inbounds(x,y, buffer=buffer)
        return inbounds

    def to_line_coords(self, x, y, return_segment_index=False):
        if not isinstance(x, np.ndarray): x = np.array([x], dtype=float)
        if not isinstance(y, np.ndarray): y = np.array([y], dtype=float)
        projections = np.zeros((self.n_segments, 2, len(x)))
        projection_dist = np.zeros_like(projections)
        for i,line in enumerate(self.lines):
            projections[i] = line.to_line_coords(x,y)
            projection_dist[i] = projections[i]
            # not in bound points lie beyond the ends of the line segement.
            # There are instances when the extension of a particular line segement gets closer to a point than the line segment that is actually closest to the point. To avoid this, out of bound points get additional perpendicular distance added to them, so the ideal line segment is more likely to get assigned.
            not_inbounds = np.logical_not(line.inbounds(x,y))
            
            projection_dist[i,1,not_inbounds] = np.abs(projection_dist[i,1,not_inbounds]) + np.abs(projections[i,0,not_inbounds])
        idx_min = np.nanargmin(np.abs(projection_dist[:,1:,:]), axis=0)

        projections = idx_min.choose(projections)

        projections[0,:] += np.squeeze(self.cumulative_length[idx_min])
        if return_segment_index:
            return projections[0], projections[1], idx_min[0]
        else:
            return projections[0], projections[1]
    
    
    def from_line_coords(self, xp, yp):
        if isinstance(xp, (int, float)):
            xp, yp = np.array([xp], dtype=float), np.array([yp], dtype=float)
        idx = np.clip(np.searchsorted(self.cumulative_length, xp, side='right')-1, 0, self.n_segments-1)
        x = np.zeros_like(xp)
        y = np.zeros_like(yp)
        for i in range(len(xp)):
            x[i], y[i] = self.lines[idx[i]].from_line_coords(xp[i]-self.cumulative_length[idx[i]], yp[i])
        return x,y
    
    @property
    def line_x(self):
        xp,yp = self.to_line_coords(self.x, self.y)
        return xp
    
    @property
    def line_y(self):
        xp,yp = self.to_line_coords(self.x, self.y)
        return yp
    
    def __call__(self, lat, lon):
        x,y,_,__ = utm.from_latlon(lat, lon, force_zone_number=self.zone, force_zone_letter=self.letter)
        x,y = self.to_line_coords(x,y)
        y[x<0] = np.inf
        y[x>self.length] = np.inf
        return x,y


class Grid:
    def __init__(self, lat, lon, pixel_size=25., buffer_pixel=4):
        self.lat = lat
        self.lon = lon
        utm_x, utm_y, zone, letter = utm.from_latlon(lat.mean(), lon.mean())
        self.utm_x, self.utm_y, _, __ = utm.from_latlon(lat, lon, force_zone_number=zone, force_zone_letter=letter)
        self.zone, self.letter = zone, letter
        self.points_latlon = np.column_stack((self.lon, self.lat))
        self.points_xy = np.column_stack((self.utm_x, self.utm_y))
        self.pixel_size = pixel_size
        self.buffer_pixel = buffer_pixel
        self.calculate_grid()

    def calculate_grid(self):
        from scipy.spatial import cKDTree

        kdtree = cKDTree(self.points_xy)
        nn_dists, _ = kdtree.query(self.points_xy, k=2)
        self.pixel_size = self.pixel_size

        # 2. Compute bounding box with margin for 4 pixels
        margin = self.buffer_pixel * self.pixel_size
        xmin, ymin = self.points_xy.min(axis=0) - margin
        xmax, ymax = self.points_xy.max(axis=0) + margin

        # 3. Generate grid of pixel centers
        nx = int(np.ceil((xmax - xmin) / self.pixel_size)) + 1
        ny = int(np.ceil((ymax - ymin) / self.pixel_size)) + 1
        x_centers = np.linspace(xmin, xmax, nx)
        y_centers = np.linspace(ymin, ymax, ny)
        xx, yy = np.meshgrid(x_centers, y_centers)
        pixel_centers = np.column_stack([xx.ravel(), yy.ravel()])


        dists, _ = kdtree.query(pixel_centers, k=1)
        mask = dists <= margin
        covered_pixels = pixel_centers[mask]
        mesh_points = covered_pixels

        coordinates_x = mesh_points[:, 0][:, None] + np.array([-1,  1, 1, -1, -1])[None,:]*self.pixel_size/2.
        coordinates_y = mesh_points[:, 1][:, None] + np.array([-1, -1, 1,  1, -1])[None,:]*self.pixel_size/2.

        clat, clon = utm.to_latlon(mesh_points[:, 0], mesh_points[:, 1], self.zone, self.letter)
        self.mesh_points = np.column_stack([clon, clat])

        coordinates_lat, coordinates_lon = utm.to_latlon(coordinates_x, coordinates_y, self.zone, self.letter)

        tree = cKDTree(self.points_xy)
        self.mesh_dists, self.mesh_idxs = tree.query(mesh_points, k=6)

        features = []
        ids = []

        for i, (cx, cy) in enumerate(mesh_points):
            coords = [(x,y) for x,y in zip(coordinates_lon[i], coordinates_lat[i])]
            cell_id = str(i)
            ids.append(cell_id)
            features.append({
                "type": "Feature",
                "id": cell_id,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords]
                }
            })
        self.geojson = {"type": "FeatureCollection", "features": features}
        self.ids = ids
        print('n_pixels:', len(self.mesh_points))

    def grid_values(self, z_data):
        weight = 1./self.mesh_dists
        weight /= weight.sum(axis=1, keepdims=True)
        z_mesh = weight[:, 0] * z_data[self.mesh_idxs[:, 0]]
        for i in range(1, self.mesh_idxs.shape[1]):
            z_mesh += weight[:, i] * z_data[self.mesh_idxs[:, i]]
        return z_mesh
    
    def graph_object(self, z_data, **kwargs):
        z_mesh = self.grid_values(z_data)
        opacity = kwargs.pop('opacity', 1)
        showlegend = kwargs.pop('showlegend', True)
        return go.Choroplethmap(
            geojson=self.geojson,
            locations=self.ids,
            z=z_mesh,
            showlegend=showlegend,
            marker=dict(opacity=opacity, line=dict(width=0, color=None)),
            showscale=True,
            hoverinfo="skip",
            selectedpoints=[],
            unselected=dict(marker=dict(opacity=opacity)),
            **kwargs
        )


PLOT_BY_LABELS = {
    'none': 'From Import',
    'enabled_disabled': 'Enabled/Disabled',
    'misfit': 'Misfit',
    'doi': 'DOI',
    'date': 'Date',
}

PLOT_BY_COLORBAR_TITLES = {
    'misfit': 'Misfit',
    'doi': 'DOI [m]',
}


# Shared horizontal placement for every colorbar on this map (plot_by's
# misfit/doi/date coloraxis colorbar, and mean res's own colorbar) plus
# their add_colorbar_title() labels, so they always move together. Shifted
# toward the right and shortened from a near-full-width bar so there's
# real room on the left for the title text -- at the old x=0.5/len=0.75 the
# bar's own left edge sat at x=0.125, leaving almost no space and clipping
# longer titles like "Resistivity [log10 Ωm]".
COLORBAR_X = 0.55
COLORBAR_LEN = 0.65


def add_colorbar_title(fig, text, bar_x=COLORBAR_X, bar_len=COLORBAR_LEN, bar_y=-0.01, bar_thickness=10):
    """
    Plotly colorbar titles only support top/right/bottom placement (no
    'left') -- fake a left-of-bar title with a plain annotation positioned
    just outside the bar's left edge, matching the horizontal colorbar
    layout used throughout this file (x/len/y/thickness kept in sync with
    it). The bar itself is yanchor='top' at bar_y (its top edge sits
    there, extending down by bar_thickness px) -- match that anchor and
    nudge down by half the thickness so the label lines up with the
    vertical center of the bar rather than its top edge.
    """
    if not text:
        return
    fig.add_annotation(
        text=text, x=bar_x - bar_len / 2, y=bar_y, xref='paper', yref='paper',
        xanchor='right', yanchor='top', xshift=-8, yshift=-bar_thickness / 2,
        showarrow=False,
        font=dict(size=14, color='black'),
    )


@nosj
class MapSettings(PanelSettings):
    # zoom/view are internal viewport state (view in particular is a dict,
    # which the generic settings-form text Input can't round-trip safely
    # -- see the hidden_settings docstring in basepanel.py), and legend
    # isn't meaningful as a standalone toggle here. mean_res and dragmode
    # already have their own dedicated controls (the "Mean res depth"
    # select in the panel body, and the map's own drag-mode toolbar
    # buttons) so a second copy in the gear form is just clutter. Excluded
    # from the gear-icon settings form; still fully functional as plain
    # attributes.
    hidden_settings = {'zoom', 'view', 'legend', 'mean_res', 'dragmode'}
    enum_labels = {'plot_by': PLOT_BY_LABELS}

    plot_by: Literal['none', 'enabled_disabled', 'misfit', 'doi', 'date'] = field(
        default='none', metadata={'title': 'Plot by'})
    mean_res: int = field(default=-1, metadata={'title': 'Mean res depth'})
    markersize: int = field(default=14, metadata={'title': 'Data points size'})
    line_width: int = field(default=3, metadata={'title': 'Line width'})
    dragmode: str = field(default='select', metadata={'title': 'Map mode'})
    color: str = field(default='#ff0000', metadata={'title': 'Data points default color'})
    # Matches the orange used app-wide for the cross-panel selection
    # highlight (see unified_handler in app.py).
    highlight_color: str = field(default='#ffb835', metadata={'title': 'Highlight color'})
    buffer_color: str = field(default='#ffffff', metadata={'title': 'Buffer color'})
    Borehole_markersize: int = field(default=12, metadata={'title': 'Borehole point size'})
    Borehole_color: str = field(default='#00e1ff', metadata={'title': 'Borehole color'})

    zoom: int = 10
    view: dict = None
    legend: bool = False


class Map(Panel):
    dataframe: None
    highlighted: int = None
    buffer_sites: list = None
    lines = None
    boreholes = None
    rock_color_map = None
    # Suppressing the highlight/buffer-window overlays on Interpret only
    # (not Review/QC, where they're still wanted) needs render() to know
    # which tab is active -- toggled directly in app.py's update_layout on
    # tab switch.
    suppress_highlight = False
    # report.py sets this for every report figure except the dedicated
    # Enabled/Disabled one -- the gray+ring overlay is otherwise always
    # drawn regardless of plot_by mode, which cluttered every other
    # report figure with it.
    suppress_disabled_overlay = False
    # app.py's export_interpret_view() sets this while exporting -- the
    # editable/erasable line shape (see the 'eraseshape' overlay below) is
    # positioned in fixed paper coordinates baked in at whatever pixel
    # size the live browser last rendered at, so re-rendering the same
    # figure at the export's own PNG dimensions (a different width/height
    # than the live browser) leaves the shape visibly offset from the
    # real Scattermap line trace underneath it -- a second, near-identical,
    # dashed line. It's purely an interactive drag-to-edit affordance with
    # nothing to add to a static export, so skip it there entirely rather
    # than trying to keep two independently-positioned copies of the same
    # line in sync.
    suppress_line_shape_overlay = False
    # Mean-res grid parameters (see make_grid()) -- how far a site's
    # colored patch extends (buffer_pixel * pixel_size, in meters) before
    # the base map shows through. Tuned for the live GUI's usual zoomed-in
    # view; report.py temporarily raises grid_buffer_pixel for Appendix B,
    # whose figures are zoomed out to the whole survey area, where the
    # default ~100m buffer around each site is imperceptibly small.
    grid_pixel_size = 25.
    grid_buffer_pixel = 4


    def __init__(self, data, **kwargs):
        settings = MapSettings(id='map', **kwargs)
        super().__init__(id='map', settings=settings)
        self.dataframe = data
        self.layer_order=['tif', 'meanres', 'buffer', 'sites', 'disabled_sites_ring', 'disabled_sites', 'highlight', 'lines', 'boreholes_outline', 'boreholes']

    @staticmethod
    def _gates_used_groups(df_plot, enabled_label):
        """
        Per-site legend-group mapping for modes whose only real
        categorization is enabled vs. disabled (the "Enabled"/"From
        Import" and "Disabled" legend entries) -- used to split the
        buffer-window overlay in render() so it hides/shows in sync with
        those legend entries, the same way the discrete 'date' mode's
        buffer split follows its date legend entries.
        """
        if 'gates_used' in df_plot.columns:
            is_disabled = df_plot['gates_used'] == 0
        else:
            is_disabled = pd.Series(False, index=df_plot.index)
        group_col = np.where(is_disabled, 'Disabled', enabled_label)
        site_group_map = pd.Series(group_col, index=df_plot['site_id'].values)
        return site_group_map, [enabled_label, 'Disabled']

    def render(self):
        if self.dataframe is None: return self.empty_render()
        df_plot = self.dataframe
        if 'site_id' in df_plot.columns:
            df_plot = df_plot[df_plot['site_id'] != -1]

        zoom = self.settings.view['map.zoom'] if self.settings.view is not None else self.settings.zoom
        center = self.settings.view['map.center'] if self.settings.view is not None else None

        c_layers = []
        # Set below by whichever branch uses a discrete/categorical legend
        # (date, enabled_disabled, and the plain "From Import" view) --
        # site_group_map maps site_id -> that site's legend group name,
        # buffer_group_labels lists the groups in display order. Left None
        # for the continuous misfit/doi colorbar view, which has no
        # legend entries to sync against. Lets the buffer-window overlay
        # further down split itself the same way, so each group's buffer
        # markers share that group's legendgroup and hide/show together
        # with it when its legend entry is clicked.
        site_group_map = None
        buffer_group_labels = None
        # Set below by the misfit/doi branch to the set of site_ids that
        # actually have a marker in the CURRENT mode (disabled sites are
        # excluded from that base trace there -- see df_plot_here). None
        # (every other mode) means no restriction. Used further down to
        # keep the buffer-window/highlight rings from being drawn around
        # a disabled site that has no colored marker underneath them to
        # ring in the first place.
        plottable_site_ids = None

        if self.settings.plot_by == 'enabled_disabled':
            # Categorical, not a continuous colorscale -- no colorbar, so
            # this can't collide with the mean-res colorbar the way
            # misfit/doi/date do (those are mutually exclusive with mean
            # res in the callbacks below anyway). Disabled sites get their
            # own gray+black-ring overlay further down, drawn regardless
            # of mode -- excluded here (rather than included and just
            # drawn over) so a disabled site has exactly one on-map
            # representation: hiding the "Disabled" legend entry then
            # actually removes it from the map instead of leaving its
            # plain black dot from this trace behind underneath.
            enabled_df = df_plot[df_plot['gates_used'] != 0] if 'gates_used' in df_plot.columns else df_plot
            fig = px.scatter_map(enabled_df, lat="latitude", lon="longitude", custom_data='site_id',
                                 zoom=zoom, center=center, color_discrete_sequence=['black'])
            fig.update_traces(marker=dict(size=self.settings.markersize), name='Enabled',
                              legendgroup='Enabled', showlegend=True)
            site_group_map, buffer_group_labels = self._gates_used_groups(df_plot, enabled_label='Enabled')
        elif self.settings.plot_by == 'date' and 'date' not in self.dataframe.columns:
            # No 'date' column at all yet (shouldn't normally happen --
            # unlike misfit/doi it's populated from raw import, not only
            # after inversion -- but fall back to the plain view rather
            # than a KeyError if it's ever missing).
            fig = px.scatter_map(df_plot, lat="latitude", lon="longitude", custom_data='site_id',
                                 zoom=zoom, center=center, color_discrete_sequence=[self.settings.color])
            fig.update_traces(marker=dict(size=self.settings.markersize), name='From Import',
                              legendgroup='From Import', showlegend=True)
            site_group_map, buffer_group_labels = self._gates_used_groups(df_plot, enabled_label='From Import')
        elif self.settings.plot_by == 'date':
            # Discrete/categorical, like enabled_disabled above -- one
            # solid color AND legend entry per distinct survey date,
            # rather than a shared colorbar (banded or otherwise). Tried
            # after the continuous banded-colorbar approach (still used
            # for misfit/doi below) got hard to read past ~17 distinct
            # dates: a legend scales better than a color strip once there
            # are that many categories, since each date gets its own
            # named, individually togglable entry instead of a shared
            # narrow band.
            df_plot = df_plot.copy()
            dt = pd.to_datetime(df_plot['date'].astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
            df_plot['_date_label'] = dt.dt.strftime('%Y-%m-%d')
            df_plot.loc[dt.isna(), '_date_label'] = 'Unknown date'
            unique_labels = sorted(df_plot['_date_label'].unique())
            if 'Unknown date' in unique_labels:
                unique_labels.remove('Unknown date')
                unique_labels.append('Unknown date')
            n_labels = len(unique_labels)
            sample_points = [i / (n_labels - 1) for i in range(n_labels)] if n_labels > 1 else [0.5]
            palette = px.colors.sample_colorscale('turbo', sample_points)
            fig = px.scatter_map(df_plot, lat="latitude", lon="longitude", custom_data='site_id',
                                 zoom=zoom, center=center, color='_date_label',
                                 category_orders={'_date_label': unique_labels},
                                 color_discrete_sequence=palette)
            fig.update_traces(marker=dict(size=self.settings.markersize), showlegend=True)
            site_group_map = df_plot.set_index('site_id')['_date_label']
            buffer_group_labels = unique_labels
        elif self.settings.plot_by in self.dataframe.columns:

            # Disabled sites' misfit/doi values are stale/meaningless (see
            # the disabled-overlay note further down) -- excluded from
            # this continuous-colorbar view entirely, same as every mode
            # except Enabled/Disabled itself (the only place disabled
            # sites are still shown, via their own gray+ring overlay). A
            # separate df_plot_here (not reassigning df_plot) since the
            # disabled-overlay trace below still needs the FULL,
            # unfiltered df_plot to find those sites in the first place.
            df_plot_here = df_plot[df_plot['gates_used'] != 0] if 'gates_used' in df_plot.columns else df_plot
            plottable_site_ids = set(df_plot_here['site_id'])
            # Buffer-window sub-traces always get one trace per group,
            # same as every other mode (see the constant-trace-count note
            # below) -- plottable_site_ids above keeps the 'Disabled'
            # group's own sub-trace empty regardless of what's actually
            # in self.buffer_sites, rather than relying on this grouping
            # alone (a disabled site CAN legitimately end up in
            # buffer_sites, e.g. via a box-select spanning both).
            site_group_map, buffer_group_labels = self._gates_used_groups(df_plot, enabled_label='sites')

            # plot_by columns like 'misfit'/'doi' only get populated once a
            # site has actually been inverted -- they're global columns on
            # sesh.data as soon as ANY site anywhere has, so a newly
            # uploaded/not-yet-inverted site shows NaN here, which Plotly
            # renders with no color at all (looks black). Pin those to the
            # colorscale's own max instead of leaving them NaN: 'turbo'
            # is dark red at its high end, close to the plain marker color
            # sites get when no plot_by is selected at all, and pinning to
            # the EXISTING data's own max (via an explicit range_color)
            # rather than leaving it to auto-scale keeps the color mapping
            # for sites that DO have real values unchanged.
            color_col = df_plot_here[self.settings.plot_by]
            has_value = color_col.notna()
            if has_value.any():
                cmin = float(color_col[has_value].min())
                cmax = float(color_col[has_value].max())
            else:
                cmin, cmax = 0.0, 1.0
            df_plot_here = df_plot_here.copy()
            df_plot_here.loc[~has_value, self.settings.plot_by] = cmax

            fig = px.scatter_map(df_plot_here, lat="latitude", lon="longitude", zoom=zoom, center=center,
                                 color=self.settings.plot_by, color_continuous_scale='turbo',
                                 range_color=[cmin, cmax],
                                 custom_data='site_id'
                                 )
            # A discrete legend swatch doesn't mean anything for a
            # continuous colorscale trace -- the colorbar above already
            # communicates it.
            fig.update_traces(marker=dict(size=self.settings.markersize), name='sites', showlegend=False)
            fig.update_layout(
                coloraxis_colorbar=dict(
                    orientation="h",
                    y=-0.01,
                    x=COLORBAR_X,
                    xanchor="center",
                    yanchor="top",
                    len=COLORBAR_LEN,
                    thickness = 10,
                    # Plotly Express defaults the colorbar title to the
                    # raw column name (e.g. "misfit") -- clear it
                    # explicitly, since add_colorbar_title below draws the
                    # real label to the left instead. Without this the two
                    # ended up showing side by side.
                    title=dict(text=''),
                )
            )
            add_colorbar_title(fig, PLOT_BY_COLORBAR_TITLES.get(self.settings.plot_by, ''))
        else:
            fig = px.scatter_map(df_plot, lat="latitude", lon="longitude", custom_data='site_id',
                                 zoom=zoom, center=center, color_discrete_sequence=[self.settings.color])
            fig.update_traces(marker=dict(size=self.settings.markersize), name='From Import',
                              legendgroup='From Import', showlegend=True)
            site_group_map, buffer_group_labels = self._gates_used_groups(df_plot, enabled_label='From Import')

        # Every branch above builds `fig` from exactly the site markers --
        # normally a single trace, but the discrete 'date' branch produces
        # one trace per distinct date. Label all of them generically here
        # (rather than each branch guessing its own trace count) so the
        # layer-reordering pass below can find and position every one of
        # them, however many there turned out to be.
        site_layer_names = [f'sites_{i}' for i in range(len(fig.data))] if len(fig.data) > 1 else ['sites']
        c_layers.extend(site_layer_names)
        layer_order = list(self.layer_order)
        if site_layer_names != ['sites']:
            sites_idx = layer_order.index('sites')
            layer_order[sites_idx:sites_idx + 1] = site_layer_names

        # Sites where every gate was manually disabled still get a model
        # from the joint SCI inversion (spatially interpolated from
        # neighbors, with zero actual weight from their own data) --
        # temframe.invert() strips that model/synthetic fit back out, so
        # 'gates_used'==0 (from sesh.update_site_table's per-site sum of
        # 'include') is what's left to flag them here. Drawn as a separate,
        # always-present (even when empty) pair of overlay traces -- named
        # something other than 'sites' so they can never satisfy
        # `curve_number = m1._layers.index('sites')` in
        # handle_map_interactions, meaning clicks/lasso-select on these
        # markers are silently ignored rather than mis-selecting a site.
        # Gray fill with a black ring, distinct from every other marker
        # color used on this map (site colors, highlight, buffer, mean
        # res). Two stacked circle traces (black underneath, slightly
        # larger; gray on top) fake the ring, since go.Scattermap's marker
        # has no 'line'/border property the way ordinary go.Scatter does.
        # Only actually populated in Enabled/Disabled mode -- in every
        # other plot_by (From Import, misfit, doi, date), disabled sites
        # are colored the same as everyone else and this overlay would
        # just clutter a view that isn't about enabled/disabled status.
        if ('gates_used' in df_plot.columns and not self.suppress_disabled_overlay
                and self.settings.plot_by == 'enabled_disabled'):
            disabled_df = df_plot[df_plot['gates_used'] == 0]
        else:
            disabled_df = df_plot.iloc[0:0]
        fig.add_trace(go.Scattermap(
            lat=disabled_df['latitude'], lon=disabled_df['longitude'],
            mode='markers',
            marker=dict(size=self.settings.markersize + 4, color='black'),
            name='Disabled sites',
            legendgroup='Disabled',
            hoverinfo='skip',
            showlegend=False,
            # Wrapped in a single-column 2D array, matching the [site_id]
            # per-point shape px.scatter_map's custom_data='site_id'
            # produces elsewhere on this figure -- handle_map_interactions
            # reads point['customdata'][0] uniformly across every trace.
            customdata=disabled_df[['site_id']].values,
        ))
        c_layers.append('disabled_sites_ring')
        # customdata=site_id (added here, not present before) lets
        # app.py's handle_map_interactions box-select handler recognize
        # points on this trace and resolve them back to a real site_id --
        # previously this trace carried no customdata at all specifically
        # so box-selecting a disabled site would be silently ignored;
        # disabled sites are now includable in a selection just like any
        # other site.
        fig.add_trace(go.Scattermap(
            lat=disabled_df['latitude'], lon=disabled_df['longitude'],
            mode='markers',
            marker=dict(size=self.settings.markersize, color='#999999'),
            name='Disabled',
            legendgroup='Disabled',
            hoverinfo='skip',
            showlegend=True,
            # Wrapped in a single-column 2D array, matching the [site_id]
            # per-point shape px.scatter_map's custom_data='site_id'
            # produces elsewhere on this figure -- handle_map_interactions
            # reads point['customdata'][0] uniformly across every trace.
            customdata=disabled_df[['site_id']].values,
        ))
        c_layers.append('disabled_sites')

        # Always add the buffer/highlight traces, even with zero points,
        # instead of only adding them when there's something to show. The
        # map's trace COUNT must stay constant across renders: Plotly's
        # MapLibre-based scatter_map traces are fragile when Plotly.react()
        # has to add/remove entire layers (vs. just updating data within
        # existing ones) -- conditionally including these traces caused the
        # browser to throw "Map error" from its internal MapLibre layer
        # management, and once that failed once the map stopped updating
        # at all on every subsequent render.
        if self.buffer_sites is not None and not self.suppress_highlight:
            df_buffer = self.dataframe[self.dataframe["site_id"].isin(self.buffer_sites)]
        else:
            df_buffer = self.dataframe.iloc[0:0]
        if plottable_site_ids is not None:
            # A disabled site can legitimately end up in buffer_sites
            # (e.g. box-selected together with enabled ones) -- without
            # this, its buffer-window ring would still get drawn even
            # though the current mode (misfit/doi) has no colored marker
            # under it, leaving a ring floating with nothing inside it.
            df_buffer = df_buffer[df_buffer['site_id'].isin(plottable_site_ids)]

        if site_group_map is not None:
            # Split to match whichever discrete/categorical legend the
            # current mode uses (date, Enabled/Disabled, or From Import/
            # Disabled), sharing each group's legendgroup (showlegend=
            # False so it adds no legend row of its own) -- Plotly toggles
            # every trace sharing a legendgroup together on a single
            # legend click, so hiding a group from the legend now also
            # hides its buffer-window ring. Emit one sub-trace per group
            # that exists in df_plot OVERALL (not just ones represented in
            # the current buffer), even when empty for this particular
            # buffer window, so the trace count stays constant as the
            # buffer pages -- only the data, not the trace count, should
            # change between renders within the same mode (see the
            # constant-trace-count note above).
            df_buffer = df_buffer.copy()
            df_buffer['_group'] = df_buffer['site_id'].map(site_group_map)
            for label in buffer_group_labels:
                df_group = df_buffer[df_buffer['_group'] == label]
                buffer_trace = px.scatter_map(df_group, lat="latitude", lon="longitude", zoom=zoom, center=center)
                buffer_trace.update_traces(
                    marker=dict(size=self.settings.markersize*1.5, color=self.settings.buffer_color),
                    name="Buffer window", legendgroup=label, showlegend=False,
                )
                for trace in buffer_trace.data:
                    fig.add_trace(trace)
            buffer_layer_names = [f'buffer_{i}' for i in range(len(buffer_group_labels))]
        else:
            buffer_trace = px.scatter_map(
                df_buffer,
                lat="latitude",
                lon="longitude",
                zoom=zoom, center=center,
            )
            buffer_trace.update_traces(
                marker=dict(size=self.settings.markersize*1.5, color=self.settings.buffer_color),
                name="Buffer window", showlegend=False
            )
            for trace in buffer_trace.data:
                fig.add_trace(trace)
            buffer_layer_names = ['buffer']
        c_layers.extend(buffer_layer_names)
        if buffer_layer_names != ['buffer']:
            buffer_idx = layer_order.index('buffer')
            layer_order[buffer_idx:buffer_idx + 1] = buffer_layer_names

        fig.update_layout(map_style="white-bg",
            map_layers=[
                {
                    "below": 'traces',
                    "sourcetype": "raster",
                    "source": ['https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}']
                }])

        # self.highlighted holds site_id values (set throughout
        # unified_handler from df_data["site_id"]), not row positions --
        # match against the site_id column, same as buffer_sites above,
        # rather than the dataframe's row index (which only happens to
        # line up with site_id by coincidence, and drifts once the
        # dataframe gets filtered/reordered). It's set to a plain scalar
        # by single-site callbacks (cross_panel_click, highlight_change)
        # and to a list by multi-select ones (unified_handler) -- isin()
        # requires list-like, so normalize a scalar into a single-item list.
        if self.highlighted is not None and not self.suppress_highlight:
            highlighted_ids = self.highlighted if isinstance(self.highlighted, (list, tuple, set, np.ndarray, pd.Series)) else [self.highlighted]
            highlighted_df = df_plot[df_plot['site_id'].isin(highlighted_ids)]
            if plottable_site_ids is not None:
                # Same reasoning as the buffer-window ring above -- don't
                # ring a disabled site in a mode that draws no marker for
                # it at all.
                highlighted_df = highlighted_df[highlighted_df['site_id'].isin(plottable_site_ids)]
        else:
            highlighted_df = df_plot.iloc[0:0]
        highlight_trace = px.scatter_map(
            highlighted_df,
            lat="latitude",
            lon="longitude",
            zoom=zoom,
            center=center,
            color_discrete_sequence=[self.settings.highlight_color])
        highlight_trace.update_traces(marker=dict(size=self.settings.markersize*2), showlegend=False)
        for trace in highlight_trace.data:
            fig.add_trace(trace)
            c_layers.append("highlight")

        if self.lines is not None:
            # Always draw the click-detectable trace (used by
            # update_highlight() below to set the model_section x-axis on
            # click) regardless of the current map tool -- previously this
            # was only added outside 'drawline' mode, which meant the
            # figure's trace count changed every time the user toggled the
            # draw tool on/off with the same set of lines drawn. MapLibre
            # traces are fragile about this (see the always-present
            # 'disabled_sites' overlay elsewhere in this file for the same
            # reasoning): an inconsistent trace count across renders can
            # permanently break the map, which is a plausible reason the
            # eraser button/line interactions felt unreliable.
            fig2 = px.line_map(self.lines, lat='latitude', lon='longitude', line_group='line', color='line', zoom=zoom, center=center, color_discrete_sequence=line_colors)
            fig2.update_traces(mode='lines', hovertemplate='Line%{line:.0f}', line=dict(width=self.settings.line_width))
            fig = go.Figure(data=fig.data+fig2.data, layout=fig.layout)
            for i in range(len(fig2.data)):
                c_layers.append(f'line_{i:02d}')

            # Also always draw the editable/erasable shape overlay (used
            # only for the modebar's "eraseshape" button), not just while
            # dragmode=='drawline'. Plotly only allows shapes to actually
            # be dragged/edited while dragmode is one of the draw tools or
            # 'select', so leaving them in during 'pan'/'zoom' doesn't
            # interfere with normal map navigation -- but restricting them
            # to 'drawline' only meant the eraser button had nothing to
            # act on the moment the user switched to any other tool
            # (e.g. the default 'select' mode), which is most of the time.
            # Guarded on settings.view, since paper2latlon/line2path need
            # a viewport bounding box that isn't set yet on the very first
            # render before any pan/zoom has happened -- specifically
            # 'map._derived', populated by a real relayoutData event from
            # the browser (map.bearing/pitch alone aren't enough). report.py
            # sets a minimal, synthetic view (center/zoom only, no real
            # viewport) to frame report figures, which doesn't have this --
            # skip the shape overlay in that case rather than crashing.
            # It's purely an interactive affordance for the "eraseshape"
            # modebar button anyway, invisible on top of the already-drawn
            # line trace, so a report figure loses nothing by omitting it.
            if (self.settings.view is not None and 'map._derived' in self.settings.view
                    and not self.suppress_line_shape_overlay):
                for line_id in self.lines.line.unique():
                    fig.add_shape(self.line2path(line_id))

        hovermode = False #if self.settings.dragmode=='drawline' else None
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0},
                          modebar=dict(add=['drawline', 'eraseshape'], remove=['zoomIn', 'zoomOut', 'lasso', 'toImage', 'plotly-logomark']),
                          newshape=dict(line_color='black', line_width=3, line_dash='dash'),
                          dragmode=self.settings.dragmode, hovermode=hovermode)
        
        # Add boreholes
        if self.boreholes is not None:
            bh_lats = [bh['map_lat'] for bh in self.boreholes]
            bh_lons = [bh['map_lon'] for bh in self.boreholes]
            bh_ids  = [bh['id'] for bh in self.boreholes]
            # Outline trace. Shares the main trace's legendgroup (with its
            # own showlegend=False, so it adds no separate legend row) --
            # without this, toggling "Boreholes" off in the legend only
            # hid the colored dots and left this black ring stuck on the
            # map, the same problem the buffer-window rings had before
            # they were grouped with their site traces.
            fig.add_trace(go.Scattermap(
                    lat=bh_lats, lon=bh_lons,
                    mode='markers',
                    marker=dict(size=self.settings.Borehole_markersize+2, color='black', symbol='circle'),
                    legendgroup='Boreholes', showlegend=False, hoverinfo='skip',
                ))
            c_layers.append('boreholes_outline')
            fig.add_trace(go.Scattermap(
                lat=bh_lats,
                lon=bh_lons,
                mode='markers',
                marker=dict(size=self.settings.Borehole_markersize, color=self.settings.Borehole_color, symbol='circle'),
                name='Boreholes',
                legendgroup='Boreholes',
                text=bh_ids,
                hovertemplate='%{text}<extra></extra>',
                # showlegend=False,
              ))
            c_layers.append('boreholes')

        
        # Same constant-trace-count requirement as buffer/highlight above:
        # this MUST add exactly one 'meanres' trace on every single render,
        # from the very first one (before any data/model exists), or the
        # first time it turns from absent to present is itself a trace-
        # count change that risks wedging the MapLibre map. So build the
        # grid lazily here (self-healing if the site set has changed since
        # the last build) rather than relying on make_grid() having been
        # called externally, and fall back to an empty placeholder trace
        # when there's nothing to show yet.
        from __main__ import sesh
        self._ensure_grid()

        if (self.settings.mean_res != -1 and getattr(self, 'grid', None) is not None
                and sesh.models is not None and not sesh.models.empty):
            depth_top, depth_bottom = self._mean_res_z_new()
            mean_res_by_site = mean_resistivity_band(sesh.models, depth_top, depth_bottom)
            # Reindex to self.dataframe's site order -- Grid's mesh_idxs
            # are positional against that same order, not against
            # whatever order/coverage sesh.models happens to have.
            res_grid = mean_res_by_site.reindex(self.dataframe['site_id'].values).values
            with np.errstate(invalid='ignore', divide='ignore'):
                res_grid = np.log10(res_grid)
            # Match the Model Section panel's own resistivity colorscale
            # range (mod2.settings.vmin/vmax) rather than a hardcoded
            # 1-100 Ohm*m, so a given color means the same resistivity in
            # both places.
            from __main__ import mod2
            zmin = np.log10(mod2.settings.vmin)
            zmax = np.log10(mod2.settings.vmax)
            fig.add_trace(self.grid.graph_object(
                res_grid, zmin=zmin, zmax=zmax, colorscale='Turbo', name='Mean Res',
                # Continuous colorscale, communicated via the colorbar --
                # not a discrete legend entry.
                showlegend=False,
                # Same horizontal, bottom-centered placement as the
                # misfit/doi/date coloraxis colorbar above, so whichever
                # one is currently showing (mean res and plot_by are
                # mutually exclusive) always appears in the same spot.
                colorbar=dict(
                    orientation="h",
                    y=-0.01,
                    x=COLORBAR_X,
                    xanchor="center",
                    yanchor="top",
                    len=COLORBAR_LEN,
                    thickness=10,
                    title=dict(text=''),
                ),
            ))
            add_colorbar_title(fig, 'Resistivity [log10 Ωm]')
        else:
            fig.add_trace(go.Choroplethmap(
                geojson={"type": "FeatureCollection", "features": []},
                locations=[], z=[],
                showscale=False, name='Mean Res',
            ))
        c_layers.append('meanres')

        data_list = list(fig.data)
        reordered_data = []
        reordered_labels = []
        used_id = np.zeros(len(data_list), dtype=bool)
        
        for layer in layer_order:
            if layer in c_layers:
                reordered_data.append(data_list[c_layers.index(layer)])
                used_id[c_layers.index(layer)] = True
                reordered_labels.append(layer)
        for i,add in zip(np.arange(len(data_list)), ~used_id):
            if add:
                reordered_data.append(data_list[i])
                reordered_labels.append(c_layers[i])

        fig.data = reordered_data
        self._layers = reordered_labels

        # Stable, name-derived uid per trace -- without this, Plotly falls
        # back to matching traces by their ARRAY POSITION when deciding
        # what UI state (e.g. a legend-hidden trace, see legend.uirevision
        # below) to carry over from the previous render. This reordering
        # step alone can shift a trace's index between renders even when
        # nothing about it changed, and legend-click toggling was landing
        # on the wrong trace on the next render as a result (a hidden
        # trace's legend row could vanish, or reappear unclickable) --
        # tagging each trace by its own layer name instead makes that
        # matching correct regardless of index/order.
        for trace, label in zip(fig.data, reordered_labels):
            trace.uid = f"map-{label}"

        # Per-layer, point-index -> site_id lookup, built from each
        # trace's OWN customdata (server-side, on the Python trace object
        # -- reliable) rather than trusting that a point's position in
        # its trace equals its site_id (only true when a trace's source
        # dataframe happens to be in site_id order with no rows removed,
        # which broke the moment 'sites' started excluding disabled
        # sites) or reading customdata back off the browser's
        # selectedData payload (confirmed elsewhere in this app -- see
        # unified_handler's Model Section note -- that Dash/Plotly here
        # never actually includes customdata in that payload, only
        # curveNumber/pointNumber/x/y/lat/lon). app.py's
        # handle_map_interactions uses this dict, keyed by the SAME
        # layer names as self._layers, to resolve a box-selected point
        # back to its real site_id using only curveNumber+pointNumber,
        # both of which selectedData does reliably include.
        self._layer_site_ids = {}
        for trace, label in zip(fig.data, reordered_labels):
            if trace.customdata is not None:
                self._layer_site_ids[label] = [int(row[0]) for row in trace.customdata]

        # A fresh, guaranteed-unique top-level uirevision on EVERY single
        # render, set here rather than trusted to each caller -- several
        # call sites (e.g. update_plotby/update_mean_res below, triggered
        # by the plot-by/mean-res dropdowns) return self.render()'s figure
        # directly with no uirevision override of their own, which left
        # layout.uirevision at Plotly's default (effectively constant/
        # unset) for those renders. Once traces got stable uids (see
        # above) and a constant legend.uirevision (see below), a constant
        # TOP-level uirevision too meant Plotly tried to carry over
        # whatever visibility state it last had for a given uid across
        # renders where the underlying data had genuinely changed --
        # e.g. the disabled-sites overlay going from real points to zero
        # points (switching plot_by away from Enabled/Disabled) and back,
        # which could leave it stuck hidden with no explicit user click
        # ever responsible. Callers that separately set their own fresh
        # uirevision (unified_handler, handle_map_interactions) just
        # overwrite this with an equally-fresh one -- harmless either way.
        fig.update_layout(uirevision=f"map-render-{time.time()!r}")

        # legend.uirevision (see below) used to be one hardcoded constant
        # -- confirmed via live console debugging (browser-side
        # plotly_afterplot logs compared against these render() prints)
        # that this made a legend-click hide (e.g. "Disabled") persist
        # not just across pans/zooms within the SAME mode (wanted -- see
        # the comment below) but FOREVER, across every future mode
        # switch too, since it's the exact same string every single
        # render regardless of plot_by. Switching to Misfit carried the
        # hide over (nothing wrong with that on its own), but switching
        # BACK to Enabled/Disabled kept it hidden too, with no click
        # available to undo it that actually worked as one -- the only
        # fix was a full page reload. Bumping this counter every time
        # plot_by actually changes (not on every render -- e.g. plain
        # panning/zooming within one mode doesn't touch it) gives each
        # mode its own fresh, never-repeated legend.uirevision value:
        # hides still persist across renders WITHIN a mode, but every
        # mode switch starts that mode's legend clean.
        if getattr(self, '_last_plot_by_for_legend', None) != self.settings.plot_by:
            self._legend_revision = getattr(self, '_legend_revision', 0) + 1
            self._last_plot_by_for_legend = self.settings.plot_by

        # Always on now (the old settings.legend toggle is hidden --
        # see MapSettings.hidden_settings): with disabled sites, the
        # enabled/disabled color mode, and the plain "From Import" view
        # all needing a legend to be readable, there's no longer a mode
        # where the map has nothing worth labeling.
        fig.update_layout(showlegend=True,
            legend=dict(x=0.01, y=0.99,
                xanchor="left",yanchor="top",
                bgcolor="rgba(255,255,255,0.5)",  # semi-transparent background
                bordercolor="black",borderwidth=1,
                # Every buffer-window ring/disabled-ring trace above is
                # wired to share a legendgroup with its "real" legend
                # entry (Disabled, Enabled, From Import, etc.) but has
                # showlegend=False itself, so there's only ever ONE
                # clickable row per group. Plotly's default groupclick
                # ('toggleitem') only toggles the exact trace you clicked,
                # NOT its showlegend=False groupmates -- so without this,
                # clicking e.g. "Disabled" hid the gray fill but left its
                # black ring (and buffer-window ring, if any) on the map.
                # 'togglegroup' makes one click hide every trace sharing
                # that legendgroup together, which is what all of this
                # grouping was actually meant to achieve.
                groupclick="togglegroup",
                # app.py's unified_handler (and other callbacks) give this
                # figure a fresh, guaranteed-unique layout.uirevision on
                # every single render -- deliberately, so stale selection
                # highlighting never survives across re-renders (see
                # unified_handler's own uirevision comment). But Plotly
                # ties legend-click visibility ("hide this trace") to
                # uirevision too by default, so every pan/zoom/click that
                # triggers a re-render was also silently un-hiding
                # anything the user had just clicked off in the legend
                # (e.g. "Disabled"). legend.uirevision is independent of
                # the top-level one -- pinning it to a constant here means
                # legend-driven visibility survives re-renders regardless
                # of what the caller sets layout.uirevision to. See the
                # _legend_revision comment above for why this is no
                # longer a bare constant.
                uirevision=f"map-legend-{self._legend_revision}",
            ),
        )

        # TEMPORARY DEBUG -- tracking down the disabled-overlay/legend
        # visibility bug. Prints exactly what this render is telling
        # Plotly, every single time render() runs, so it can be compared
        # against what the browser console (see the matching TEMPORARY
        # DEBUG block in panels.py) says Plotly actually did with it.
        # Remove once the bug's root cause is confirmed.
        print(f"[map.render DEBUG] plot_by={self.settings.plot_by!r} uirevision={fig.layout.uirevision!r} "
              f"legend.uirevision={fig.layout.legend.uirevision!r}")
        for t in fig.data:
            print(f"    trace name={t.name!r:20} uid={t.uid!r:28} legendgroup={t.legendgroup!r:12} "
                  f"showlegend={t.showlegend!r:5} visible={t.visible!r:6} n_points={len(t.lat) if hasattr(t, 'lat') and t.lat is not None else 'n/a'}")

        return fig
    
        
    def line2path(self, line_id):
        c_line = self.lines.loc[self.lines.line==line_id]
        path_dict = {'editable': True, 'type':'path', 'line': {'color': line_colors[int(line_id)%len(line_colors)-1], 'width': 3, 'dash': 'dash'}}
        cxs,cys = self.latlon2paper(c_line.latitude.values, c_line.longitude.values)

        path = f'M{cxs[0]},{cys[0]}'
        for cx,cy in zip(cxs[1:-1],cys[1:-1]):
            path += f'L{cx},{cy}'

        # this is a little stupid, but it makes it possible to continuously click and piece a line together. Clicking on an identical point prevented the drag functionality to extend the line.

        dx = cxs[-1]-cxs[-2]
        dy = cys[-1]-cys[-2]
        path += f'L{cxs[-2]+0.95*dx},{cys[-2]+0.95*dy}'
        
        path_dict['path'] = path
        return path_dict
    
    def path2line(self, path_str):
        points = path_str[1:].split('L')
        lat, lon = [], []
        for point in points:
            cx, cy = map(float, point.split(','))
            plat, plon = self.paper2latlon(cx, cy)
            lat.append(plat)
            lon.append(plon)
        return lat, lon

    @property
    def lat0(self):
        return min([p[1] for p in self.settings.view['map._derived']['coordinates']])
    @property
    def lat1(self):
        return max([p[1] for p in self.settings.view['map._derived']['coordinates']])
    @property
    def lon0(self):
        return min([p[0] for p in self.settings.view['map._derived']['coordinates']])
    @property
    def lon1(self):
        return max([p[0] for p in self.settings.view['map._derived']['coordinates']])
        
    def paper2latlon(self, x, y):
        if self.settings.view is None:
            raise Warning("no view, please zoom")
        elif self.settings.view['map.bearing']!=0 or self.settings.view['map.pitch']!=0:
            raise Warning("non-standard view, bearing and pitch must be zero, reset axis and zoom")
        else:
            lat = self.lat0 + (self.lat1-self.lat0)*y
            lon = self.lon0 + (self.lon1-self.lon0)*x
            return lat,lon
        
    def latlon2paper(self, lat,lon):
        if self.settings.view is None:
            raise Warning("no view, please zoom")
        elif self.settings.view['map.bearing']!=0 or self.settings.view['map.pitch']!=0:
            raise Warning("non-standard view, bearing and pitch must be zero, reset axis and zoom")
        
        x = (lon - self.lon0) / (self.lon1-self.lon0)
        y = (lat - self.lat0) / (self.lat1-self.lat0)
        return x,y

    def initialize(self):
        return html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            dcc.Graph(
                                figure=self.render(),
                                id=self.id,
                                mathjax=True,
                                responsive=True,
                                style={
                                    'height': '100%',
                                    'width': '100%'
                                }
                            ),
                            style={
                                'flex': '1',
                                'minHeight': 0,
                                'boxSizing': 'border-box',
                            }
                        ),

                        # Sits in normal flow below the graph (not overlaid on
                        # top of it) -- a plain row, not the absolutely
                        # positioned floating box style used elsewhere, since
                        # there's no map content underneath here to float over.
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dbc.Label("Color by", html_for=self.id+'_plot_by', class_name="mb-0", style=FLOATING_BOX_LABEL_STYLE),
                                        dbc.Select(
                                            options=[{'label': PLOT_BY_LABELS.get(v, v), 'value': v}
                                                     for v in self.settings.schema['properties']['plot_by']['enum']],
                                            id=self.id+'_plot_by',
                                            value=self.settings.plot_by,
                                            style={'width': '150px'},
                                        ),
                                    ],
                                    style=FLOATING_BOX_ROW_STYLE,
                                ),
                                html.Div(
                                    [
                                        dbc.Label("Mean res depth", html_for=self.id+'_mean_res', class_name="mb-0", style=FLOATING_BOX_LABEL_STYLE),
                                        dbc.Select(
                                            options=[{'label': 'Hidden', 'value': -1}] +
                                                     [{'label': (str(d) if d == 0 else f'-{d}'), 'value': d} for d in range(0, 301, 10)],
                                            value=self.settings.mean_res,
                                            id=self.id+'_mean_res',
                                            style={'width': '150px'},
                                        ),
                                    ],
                                    style=FLOATING_BOX_ROW_STYLE,
                                ),
                            ],
                            style={
                                'display': 'flex',
                                'flexDirection': 'row',
                                'justifyContent': 'center',
                                'gap': '24px',
                                'padding': '8px 0',
                                'flexShrink': 0,
                            },
                        ),
                    ],
                    style={
                        'flex': '1',
                        'minHeight': 0,
                        'display': 'flex',
                        'flexDirection': 'column',
                    }
                ),
                gear_maker(self.id)
            ],
            style={
                'display': 'flex',
                'flexDirection': 'column',
                'height': '100%',
                'minHeight': 0
            }
        )

    def make_grid(self):
        self.grid = Grid(self.dataframe.latitude.values, self.dataframe.longitude.values,
                          pixel_size=self.grid_pixel_size, buffer_pixel=self.grid_buffer_pixel)

    def _ensure_grid(self):
        """
        (Re)build self.grid if it's missing or stale relative to the
        current site set or grid_pixel_size/grid_buffer_pixel. Called from
        render() so the mean-res grid self-heals whenever the site list
        (or, e.g., report.py's temporary buffer override) has changed,
        without needing make_grid() to be called externally first.
        """
        if self.dataframe is None or self.dataframe.empty:
            return
        grid_key = (len(self.dataframe), self.grid_pixel_size, self.grid_buffer_pixel)
        if getattr(self, 'grid', None) is None or getattr(self, '_grid_key', None) != grid_key:
            self.make_grid()
            self._grid_key = grid_key

    def _mean_res_z_new(self):
        """
        mean_res is the depth (in meters) at the top of a 10m band, chosen
        from the dropdown's fixed 0/-10/-20/.../-300 options (displayed
        negative to match an elevation-style "down is negative"
        convention, stored as the positive depth). E.g. selecting "-20"
        shows the mean resistivity of the 20-30m band.
        """
        depth = self.settings.mean_res
        return np.array([depth, depth + 10], dtype=float)

    def add_callbacks(self, app):
        super().add_callbacks(app)


        @app.callback(
            self.output,
            Output(self.id+'_mean_res', 'value', allow_duplicate=True),
            # plot_by is also exposed as a field in the auto-generated gear
            # settings form (basepanel.py's PanelSettings.render()), as a
            # second control bound to the same underlying setting. That
            # duplicate never hears about changes made via this dedicated
            # dropdown, so it goes stale -- and Panel.add_callbacks'
            # generic update_render callback writes EVERY gear-form
            # field's *currently displayed* value back on any single
            # field's change (they share one callback), which would
            # silently stomp self.settings.plot_by back to the stale value
            # the next time e.g. Data points size changes. Pushing the new
            # value into the gear-form twin here keeps it from ever going
            # stale in the first place. Same established pattern already
            # used for model_section's x_axis field further down (see
            # update_view). mean_res has no such twin -- it's in
            # hidden_settings, so it never appears in the gear form at all.
            Output({'type': f'settings-{self.id}', 'key': 'plot_by'}, 'value', allow_duplicate=True),
            Input(self.id+'_plot_by', 'value'),
            prevent_initial_call=True
        )
        def update_plotby(value):
            if value not in ('none', 'enabled_disabled') and value not in self.dataframe.columns:
                raise PreventUpdate
            self.settings.plot_by = value
            # Mean-res and plot_by (misfit/doi/date/enabled-disabled/line)
            # each drive their own color and colorbar -- showing both at
            # once is confusing and stacks two colorbars on the map. Only
            # one can be active at a time, so switching one on turns the
            # other off.
            mean_res_value = no_update
            if value != 'none' and self.settings.mean_res != -1:
                self.settings.mean_res = -1
                mean_res_value = -1
            return self.render(), mean_res_value, value

        @app.callback(
            self.output,
            Output(self.id+'_plot_by', 'value', allow_duplicate=True),
            Output({'type': f'settings-{self.id}', 'key': 'plot_by'}, 'value', allow_duplicate=True),
            Input(self.id+'_mean_res', 'value'),
            prevent_initial_call=True
        )
        def update_mean_res(value):
            # dbc.Select/HTML <select> always yields the option value as a
            # string, even though it was registered as an int.
            self.settings.mean_res = int(value)
            # See update_plotby above -- mean res and plot_by are mutually
            # exclusive so only one colorbar is ever on screen.
            plot_by_value = no_update
            gear_plot_by_value = no_update
            if self.settings.mean_res != -1 and self.settings.plot_by != 'none':
                self.settings.plot_by = 'none'
                plot_by_value = 'none'
                gear_plot_by_value = 'none'
            # A partial Patch() here previously only touched the trace's
            # 'z' values and missed 'geojson'/'locations' entirely, so it
            # silently did nothing whenever the on-screen trace was still
            # the empty placeholder. render() is cheap and self-healing
            # (see _ensure_grid) and, now that the map keeps a constant
            # trace count on every render, a full re-render is just as
            # safe as a Patch -- so return one, matching update_plotby.
            return self.render(), plot_by_value, gear_plot_by_value

        @app.callback(
            self.output,
            Output('model_section_axis', 'options', allow_duplicate=True),
            Output({'type': f'settings-model_section', 'key': 'x_axis'}, 'options', allow_duplicate=True),
            Input(self.id, 'relayoutData'),
            State('model_section_axis', 'options'),
            prevent_initial_call=True
        )
        def update_view(relayout_data, options):
            from __main__ import sesh, mod2, dbdt2
            # A relayout event only carries the view keys that actually
            # changed -- a wheel-zoom with no panning can arrive as just
            # {'map.zoom': ..., 'map._derived': ...} with no 'map.center'
            # at all. Gating on 'map.center' specifically meant zoom-only
            # interactions never updated settings.view, so line2path() kept
            # projecting drawn lines against a stale viewport bounding box
            # (self.lat0/lat1/lon0/lon1, derived from map._derived) --
            # exactly the "line drifts on zoom" symptom. Catch any map.*
            # key instead, and merge into the existing view rather than
            # replacing it outright, since a partial event shouldn't wipe
            # out keys (center/bearing/pitch) it didn't actually report.
            if any(k.startswith('map.') for k in relayout_data):
                self.settings.view = {**(self.settings.view or {}),
                                       **{k: v for k, v in relayout_data.items() if k.startswith('map.')}}
            elif 'dragmode' in relayout_data:
                self.settings.dragmode=relayout_data['dragmode']
                if self.settings.dragmode!='drawline':
                    sesh.update_site_table()

            elif 'shapes' in relayout_data:
                if relayout_data['shapes'][-1]['type']=='line':
                    
                    lat0,lon0 = self.paper2latlon(relayout_data['shapes'][-1]['x0'], relayout_data['shapes'][-1]['y0'])
                    lat1,lon1 = self.paper2latlon(relayout_data['shapes'][-1]['x1'], relayout_data['shapes'][-1]['y1'])
                    line_id = 1
                    node = 0
                    if self.lines is None:
                        self.lines = DataFrame({'latitude':[lat0], 'longitude':[lon0], 'line':[line_id], 'node':[node], 'length':[-1], 'total_length':[-1], 'radius':[100]})
                    else:
                        lat, lon, line_id, node, _, __, ___ = self.lines.loc[len(self.lines)-1].tolist()
                        if cdist(lat,lon, lat0, lon0) > 50:
                            line_id +=1 
                            node = 0
                            self.lines.loc[len(self.lines)] = [lat0, lon0, line_id, node, -1, -1, 100]
                    self.lines.loc[len(self.lines)] = [lat1, lon1, line_id, node+1, -1, -1, 100]
                    del relayout_data['shapes']
                    sesh.lines = self.lines.copy()
                    sesh.update_site_table()
                    fig=self.render()
                elif len(relayout_data['shapes'])==len(self.lines.line.unique())-1:
                    saved_paths = [self.line2path(line_id)['path'] for line_id in self.lines.line.unique()]
                    remaining_paths = [shape['path'] for shape in relayout_data['shapes']]
                    removed_line_ids = []
                    for line_id, path in zip(self.lines.line.unique(), saved_paths):
                        if path not in remaining_paths:
                            self.lines = self.lines[self.lines.line!=line_id]
                            removed_line_ids.append(line_id)
                    sesh.lines = self.lines.copy()
                    sesh.update_site_table()
                    # A panel left pointed at a just-erased line's x_axis
                    # mode is a dangling reference: sesh.data/sesh.models
                    # no longer have that line's _line_N_x/_line_N_y
                    # projection columns (update_site_table() above just
                    # recomputed them from the now-shorter sesh.lines), so
                    # the next render/refresh crashes with a KeyError on
                    # that column instead of just falling back cleanly.
                    for removed_id in removed_line_ids:
                        removed_option = f'line {removed_id:0.0f}'
                        if mod2.settings.x_axis == removed_option:
                            mod2.settings.x_axis = 'site_id'
                        if dbdt2.settings.x_axis == removed_option:
                            dbdt2.settings.x_axis = 'site_id'
            else:
                key, value = list(relayout_data.items())[0]
                if key.startswith('shapes[') and key.endswith('].path'):
                    line_id = int(key.split('[')[1].split(']')[0])+1
                    lat, lon = self.path2line(value)
                    self.lines.loc[self.lines.line==line_id, ['latitude', 'longitude']] = np.array([lat, lon]).T
                    sesh.lines = self.lines.copy()
                    sesh.update_site_table()

            if sesh.lines is not None:
                line_ids = sesh.lines['line'].unique()
                line_options = [f'line {line_id:0.0f}' for line_id in line_ids]
                options = line_options + [option for option in options if not option.startswith('line')]
            return self.render(), options, options

        @app.callback(
            Output('model_section_axis', 'value', allow_duplicate=True),
            Input(self.id, 'clickData'),
            prevent_initial_call=True
        )
        def update_highlight(click_data):
            result = no_update
            if self.lines is None:
                return result

            line_threshold = 1
            # if self.buffer_sites is not None:
            #     line_threshold+=1
            if 'points' in click_data and len(click_data['points'])==1:
                curve_number = click_data['points'][0]['curveNumber']
                if curve_number>line_threshold:
                    all_dist = cdist(click_data['points'][0]['lat'], click_data['points'][0]['lon'], self.lines['latitude'].values, self.lines['longitude'].values)
                    line_id = self.lines['line'].values[np.argmin(all_dist)]
                    x_axis = 'line '+f'{line_id:0.0f}'
                    result = x_axis
            return result
        

def mean_resistivity_band(model_df, depth_top, depth_bottom):
    """
    Thickness-weighted mean resistivity of each site's layers overlapping
    [depth_top, depth_bottom), computed directly from each row's own
    top_depth/bottom_depth/resistivity.

    The previous implementation (rediscretize/rediscretize_matrix, removed)
    pivoted resistivity into a site_id x center_depth matrix and combined
    it with a shared overlap-weighting matrix via a single matrix multiply.
    That silently assumed every site shares the same depth discretization.
    Real inversions rarely do (variable layer counts, DOI-based
    differences), so the pivot came out sparse/NaN almost everywhere, and
    one NaN cell in a site's row wipes out that entire site's result via
    ordinary matrix multiplication -- in practice every site came out NaN.
    Computing directly from each row's own depths makes no such assumption;
    a site only legitimately comes back NaN if none of its own layers
    overlap the requested band (e.g. it doesn't extend that deep).

    Also clipped to each site's own DOI, if present: a layer's effective
    bottom is capped at min(its own bottom_depth, depth_bottom, doi), so a
    band that starts below a site's DOI contributes nothing for that site
    (NaN, same as not extending that deep at all -- the grid shows the
    basemap through rather than an unreliable value), and a band straddling
    the DOI boundary is thickness-weighted only over the portion above it,
    so the last real value for a site fades out exactly at its DOI instead
    of continuing on unchanged for another whole band.

    Returns a pandas Series of mean resistivity indexed by site_id.
    """
    band_bottom = np.minimum(model_df['bottom_depth'].values, depth_bottom)
    if 'doi' in model_df.columns:
        band_bottom = np.minimum(band_bottom, model_df['doi'].values)
    overlap = np.clip(
        band_bottom - np.maximum(model_df['top_depth'].values, depth_top),
        0, None,
    )
    tmp = pd.DataFrame({
        'site_id': model_df['site_id'].values,
        'overlap': overlap,
        'weighted': overlap * model_df['resistivity'].values,
    })
    grouped = tmp.groupby('site_id')[['overlap', 'weighted']].sum()
    with np.errstate(invalid='ignore', divide='ignore'):
        return grouped['weighted'] / grouped['overlap'].replace(0, np.nan)