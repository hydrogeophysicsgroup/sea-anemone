from basepanel import *
from dataclasses import field
import io
import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import utm
from PIL import Image

from map import Grid, mean_resistivity_band
from model import RESISTIVITY_COLORSCALE, resistivity_colorbar_tick_kwargs


@nosj
class Model3DSettings(PanelSettings):
    z: Literal['depth', 'elevation'] = 'elevation'
    vmin: float = 1.0
    vmax: float = 500.0
    # Same meaning as ModelSection's Log Colorbar toggle (see model.py) --
    # off (default) labels the colorbar with real Ωm values at their
    # correct log-spaced positions, on shows the raw log10 exponent.
    log_colorbar: bool = field(default=False, metadata={'title': 'Log Colorbar'})
    line_width: float = 8.0
    box_half_width: float = 4.0
    vertical_exaggeration: float = 1.0
    mask_below_doi: bool = False
    below_doi_opacity: float = 0.15
    show_boreholes: bool = True
    show_legend: bool = False
    show_site_markers: bool = False
    show_map_layer: bool = False
    map_layer_zoom: int = 15
    map_layer_resolution: int = 400
    map_layer_z_offset: float = 0.0
    show_mean_res_layer: bool = False
    # Same fixed 10m-band depth choices as the 2D map's mean-res dropdown
    # (map.py's Map._mean_res_z_new/dbc.Select) -- kept in exact sync so a
    # depth picked here means the same thing there. Literal requires each
    # value written directly here (not a variable) per PEP 586.
    mean_res_depth: Literal[
        0, -10, -20, -30, -40, -50, -60, -70, -80, -90, -100,
        -110, -120, -130, -140, -150, -160, -170, -180, -190, -200,
        -210, -220, -230, -240, -250, -260, -270, -280, -290, -300,
    ] = 0


class Model3D(Panel):
    """
    3D viewer: each site's inverted resistivity profile as a colored
    vertical 'log' in UTM space, alongside borehole layers using the same
    rock-color map as ModelSection. Meant to sit as a tab next to
    ModelSection in the interpret layout.

    No custom initialize()/add_callbacks() -- like ModelGraph, this relies
    on the Panel base class's default dcc.Graph + gear_maker() layout,
    which auto-generates settings controls from Model3DSettings' fields.
    Add a custom initialize() (see ModelSection for the pattern) if you
    want hand-built controls instead of the auto-generated gear panel.
    """
    highlighted = None
    boreholes = None
    rock_color_map = None

    # Keyed by (rounded bbox, zoom) -> (xs, ys, surfacecolor_idx, colorscale).
    # Fetching/stitching satellite tiles is slow and network-bound, and
    # render() fires on every settings tweak while the map layer is on, so
    # only actually rebuild the texture when the site extent or zoom moves.
    _map_layer_cache = None

    # The interpolation Grid (cKDTree build + mesh generation) is the
    # expensive part of the mean-res layer, not the per-depth lookup --
    # cache it keyed by site count and rebuild only when that changes.
    _mean_res_grid = None
    _mean_res_grid_site_count = None

    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', Model3DSettings(id='model_3d'))
        super().__init__(id='model_3d', settings=settings)
        self._map_layer_cache = {}
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _project_latlon(self, lat, lon):
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        x = np.full(len(lat), np.nan)
        y = np.full(len(lat), np.nan)
        ok = np.isfinite(lat) & np.isfinite(lon)
        if ok.any():
            ux, uy, _, _ = utm.from_latlon(lat[ok], lon[ok])
            x[ok] = ux
            y[ok] = uy
        return x, y

    _TILE_URL = 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}'
    _TILE_SIZE = 256
    _MAX_TILES = 128
    _TEXTURE_GRID_CAP = 800  # hard ceiling regardless of map_layer_resolution, so the setting can't hang the browser

    @staticmethod
    def _deg2num(lat_deg, lon_deg, zoom):
        lat_rad = math.radians(lat_deg)
        n = 2.0 ** zoom
        xtile = int((lon_deg + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        return xtile, ytile

    @staticmethod
    def _num2deg(xtile, ytile, zoom):
        n = 2.0 ** zoom
        lon_deg = xtile / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
        return math.degrees(lat_rad), lon_deg

    def _build_basemap_texture(self, lat_min, lat_max, lon_min, lon_max, zoom, resolution):
        """
        Fetch and stitch the same Google satellite tiles the 2D map uses
        (see map.py's map_layers raster source) covering the given lat/lon
        box, then reduce it to a small palette-indexed grid suitable for
        draping as a go.Surface's surfacecolor -- Plotly's 3D scenes have
        no native photo-texture support, so an "adaptive palette + discrete
        colorscale" is the closest approximation to true color.

        Returns (xs, ys, surfacecolor_idx, colorscale) in UTM space, or
        None if no tile could be fetched.
        """
        x_min, y_min = self._deg2num(lat_max, lon_min, zoom)
        x_max, y_max = self._deg2num(lat_min, lon_max, zoom)
        while (x_max - x_min + 1) * (y_max - y_min + 1) > self._MAX_TILES and zoom > 1:
            zoom -= 1
            x_min, y_min = self._deg2num(lat_max, lon_min, zoom)
            x_max, y_max = self._deg2num(lat_min, lon_max, zoom)

        n_x = x_max - x_min + 1
        n_y = y_max - y_min + 1
        stitched = Image.new('RGB', (n_x * self._TILE_SIZE, n_y * self._TILE_SIZE), 'white')
        headers = {'User-Agent': 'Mozilla/5.0'}
        fetched_any = False
        for i, xt in enumerate(range(x_min, x_max + 1)):
            for j, yt in enumerate(range(y_min, y_max + 1)):
                url = self._TILE_URL.format(x=xt, y=yt, z=zoom)
                try:
                    resp = requests.get(url, headers=headers, timeout=5)
                    resp.raise_for_status()
                    tile_img = Image.open(io.BytesIO(resp.content)).convert('RGB')
                    stitched.paste(tile_img, (i * self._TILE_SIZE, j * self._TILE_SIZE))
                    fetched_any = True
                except Exception:
                    continue
        if not fetched_any:
            return None

        grid_w = min(resolution, self._TEXTURE_GRID_CAP, stitched.width)
        grid_h = max(1, round(grid_w * stitched.height / stitched.width))
        resized = stitched.resize((grid_w, grid_h), Image.LANCZOS)
        pal_img = resized.convert('P', palette=Image.ADAPTIVE, colors=256)
        idx = np.array(pal_img)
        palette = pal_img.getpalette()[:256 * 3]
        colorscale = [
            [i / 255.0, f'rgb({palette[3 * i]},{palette[3 * i + 1]},{palette[3 * i + 2]})']
            for i in range(256)
        ]

        nw_lat, nw_lon = self._num2deg(x_min, y_min, zoom)
        se_lat, se_lon = self._num2deg(x_max + 1, y_max + 1, zoom)
        utm_x, utm_y = self._project_latlon([nw_lat, se_lat], [nw_lon, se_lon])
        x_left, x_right = sorted(utm_x)
        y_bottom, y_top = sorted(utm_y)

        xs = np.linspace(x_left, x_right, grid_w)
        ys = np.linspace(y_top, y_bottom, grid_h)  # row 0 = image top = north
        return xs, ys, idx, colorscale

    def _get_map_layer_trace(self, df, z_mode):
        lat_min, lat_max = df['latitude'].min(), df['latitude'].max()
        lon_min, lon_max = df['longitude'].min(), df['longitude'].max()
        pad_lat = max((lat_max - lat_min) * 0.15, 0.001)
        pad_lon = max((lon_max - lon_min) * 0.15, 0.001)
        lat_min, lat_max = lat_min - pad_lat, lat_max + pad_lat
        lon_min, lon_max = lon_min - pad_lon, lon_max + pad_lon

        zoom = self.settings.map_layer_zoom
        resolution = self.settings.map_layer_resolution
        cache_key = (round(lat_min, 4), round(lat_max, 4), round(lon_min, 4), round(lon_max, 4), zoom, resolution)
        cached = (self._map_layer_cache or {}).get(cache_key)
        if cached is None:
            cached = self._build_basemap_texture(lat_min, lat_max, lon_min, lon_max, zoom, resolution)
            if cached is None:
                return None
            self._map_layer_cache = {cache_key: cached}
        xs, ys, idx, colorscale = cached

        plane_z = df['elevation'].min() if z_mode == 'elevation' and 'elevation' in df.columns else 0.0
        plane_z += self.settings.map_layer_z_offset
        zs = np.full((len(ys), len(xs)), plane_z)

        return go.Surface(
            x=xs, y=ys, z=zs,
            surfacecolor=idx,
            colorscale=colorscale,
            cmin=0, cmax=255,
            showscale=False,
            hoverinfo='skip',
            lighting=dict(ambient=1.0, diffuse=0.0, specular=0.0),
            name='Basemap',
            showlegend=False,
        )

    def _ensure_mean_res_grid(self, site_df):
        """
        (Re)build the interpolation Grid from the currently-shown sites'
        lat/lon, reusing map.py's Grid/mean_resistivity_band exactly as
        the 2D map's mean-res layer does (see Map._ensure_grid there) --
        same gridding, same per-site depth-band averaging, just draped
        horizontally in 3D as a Mesh3d instead of a 2D Choroplethmap.
        site_df must be one row per site (not per layer) -- Grid.points_xy
        and the later z_data reindex both rely on that positional 1:1
        correspondence.
        """
        if len(site_df) != self._mean_res_grid_site_count:
            self._mean_res_grid = Grid(site_df['latitude'].values, site_df['longitude'].values, pixel_size=25., buffer_pixel=4)
            self._mean_res_grid_site_count = len(site_df)
        return self._mean_res_grid

    def _get_mean_res_layer_trace(self, site_df, z_mode, ve):
        """
        Choroplethmap has no 3D equivalent in Plotly at all (it's a
        MapLibre-only 2D trace type), so a Mesh3d is the closest thing to
        a filled, continuous layer here rather than discrete markers.

        Grid's mesh points are already masked to the same buffer radius
        around each site as the 2D map's mean-res layer -- but letting
        Mesh3d do its own Delaunay triangulation (delaunayaxis='z')
        triangulates over the *convex hull* of those points regardless,
        which bridges straight across any real gaps in coverage (a
        scattered/linear survey layout, DOI holes, etc.), covering far
        more area than the 2D map ever shows. So the triangulation is
        done explicitly here instead, dropping any triangle with an edge
        longer than a couple of grid cells -- that edge only gets that
        long by cutting across a gap the buffer radius was supposed to
        exclude.
        """
        from __main__ import sesh
        if sesh.models is None or sesh.models.empty:
            return None

        grid = self._ensure_mean_res_grid(site_df)
        # dbc.Select/HTML <select> always yields the option value as a
        # string, even though it was registered as an int. The dropdown's
        # enum values are themselves negative (unlike map.py's, which
        # stores a positive depth and only prefixes the *label* with "-"),
        # since the auto-generated Select here uses one raw value for both
        # label and value -- abs() it back to the real (non-negative)
        # depth used everywhere else.
        depth_top = abs(int(self.settings.mean_res_depth))
        depth_bottom = depth_top + 10
        mean_res_by_site = mean_resistivity_band(sesh.models, depth_top, depth_bottom)
        res = mean_res_by_site.reindex(site_df['site_id'].values).values
        with np.errstate(invalid='ignore', divide='ignore'):
            log_res = np.log10(res)
        if np.all(np.isnan(log_res)):
            return None
        z_mesh = grid.grid_values(log_res)

        utm_x, utm_y = self._project_latlon(grid.mesh_points[:, 1], grid.mesh_points[:, 0])
        valid = np.isfinite(z_mesh) & np.isfinite(utm_x) & np.isfinite(utm_y)
        if valid.sum() < 3:
            return None
        utm_x, utm_y, z_mesh = utm_x[valid], utm_y[valid], z_mesh[valid]

        from scipy.spatial import Delaunay
        points_2d = np.column_stack([utm_x, utm_y])
        try:
            simplices = Delaunay(points_2d).simplices
        except Exception:
            return None

        p0, p1, p2 = points_2d[simplices[:, 0]], points_2d[simplices[:, 1]], points_2d[simplices[:, 2]]
        max_edge = grid.pixel_size * 2.0
        keep = (
            (np.linalg.norm(p0 - p1, axis=1) <= max_edge)
            & (np.linalg.norm(p1 - p2, axis=1) <= max_edge)
            & (np.linalg.norm(p2 - p0, axis=1) <= max_edge)
        )
        simplices = simplices[keep]
        if len(simplices) == 0:
            return None

        if z_mode == 'elevation':
            plane_z = site_df['elevation'].min() - depth_top * ve
        else:
            plane_z = -depth_top * ve

        return go.Mesh3d(
            x=utm_x, y=utm_y, z=np.full(len(utm_x), plane_z),
            i=simplices[:, 0], j=simplices[:, 1], k=simplices[:, 2],
            intensity=z_mesh,
            intensitymode='vertex',
            colorscale=RESISTIVITY_COLORSCALE,
            cmin=np.log10(self.settings.vmin),
            cmax=np.log10(self.settings.vmax),
            showscale=False,
            flatshading=True,
            lighting=dict(ambient=1.0, diffuse=0.0, specular=0.0),
            hoverinfo='skip',
            name=f'Mean res {depth_top}-{depth_bottom}m',
            showlegend=False,
        )

    def _build_layer_boxes(self, df, half_width):
        """
        Build one batched Mesh3d worth of cuboids: an 8-vertex box per
        layer (top-4 + bottom-4 corners), 12 triangular faces each. All
        boxes go into ONE trace by offsetting each box's face indices by
        its position in the vertex array -- boxes don't share vertices
        with each other, so there's no color bleeding between them despite
        being a single mesh.
        """
        n = len(df)
        x0 = df['_utm_x'].values - half_width
        x1 = df['_utm_x'].values + half_width
        y0 = df['_utm_y'].values - half_width
        y1 = df['_utm_y'].values + half_width
        zt = df['_z_top'].values
        zb = df['_z_bottom'].values
        logrho = np.log10(df['resistivity'].values)

        verts_x = np.empty(n * 8); verts_y = np.empty(n * 8); verts_z = np.empty(n * 8)
        intensity = np.empty(n * 8)

        # local vertex layout: 0-3 = top corners (CCW from x0,y0), 4-7 = bottom corners
        verts_x[0::8] = x0; verts_y[0::8] = y0; verts_z[0::8] = zt
        verts_x[1::8] = x1; verts_y[1::8] = y0; verts_z[1::8] = zt
        verts_x[2::8] = x1; verts_y[2::8] = y1; verts_z[2::8] = zt
        verts_x[3::8] = x0; verts_y[3::8] = y1; verts_z[3::8] = zt
        verts_x[4::8] = x0; verts_y[4::8] = y0; verts_z[4::8] = zb
        verts_x[5::8] = x1; verts_y[5::8] = y0; verts_z[5::8] = zb
        verts_x[6::8] = x1; verts_y[6::8] = y1; verts_z[6::8] = zb
        verts_x[7::8] = x0; verts_y[7::8] = y1; verts_z[7::8] = zb
        for v in range(8):
            intensity[v::8] = logrho

        local_faces = np.array([
            [0, 1, 2], [0, 2, 3],   # top
            [4, 6, 5], [4, 7, 6],   # bottom
            [0, 4, 5], [0, 5, 1],   # y0 side
            [1, 5, 6], [1, 6, 2],   # x1 side
            [2, 6, 7], [2, 7, 3],   # y1 side
            [3, 7, 4], [3, 4, 0],   # x0 side
        ])
        offsets = (np.arange(n) * 8).reshape(-1, 1, 1)
        faces = (local_faces[None, :, :] + offsets).reshape(-1, 3)
        i, j, k = faces[:, 0], faces[:, 1], faces[:, 2]

        hover_per_box = [
            f"Site {s}<br>Layer {l}<br>ρ = {r:.1f} Ω·m"
            for s, l, r in zip(df['site_id'], df['layer'], df['resistivity'])
        ]
        hovertext = np.repeat(hover_per_box, 8)

        return verts_x, verts_y, verts_z, intensity, i, j, k, hovertext

    def _add_box_trace(self, fig, df, opacity=1.0, showscale=True):
        verts_x, verts_y, verts_z, intensity, i, j, k, hovertext = self._build_layer_boxes(
            df, self.settings.box_half_width
        )
        title_text = 'log10 Resistivity<br>[Ω·m]' if self.settings.log_colorbar else 'Resistivity<br>[Ω·m]'
        fig.add_trace(go.Mesh3d(
            x=verts_x, y=verts_y, z=verts_z,
            i=i, j=j, k=k,
            intensity=intensity,
            intensitymode='vertex',
            colorscale=RESISTIVITY_COLORSCALE,
            cmin=np.log10(self.settings.vmin),
            cmax=np.log10(self.settings.vmax),
            showscale=showscale,
            colorbar=dict(
                title=title_text, x=1.0, len=0.7,
                **resistivity_colorbar_tick_kwargs(self.settings.vmin, self.settings.vmax, self.settings.log_colorbar),
            ),
            # Flat, unlit shading: each box reads as a solid faceted block
            # (the requested '4 corners' look) and colors stay true to the
            # colorscale instead of being darkened/shaded like a lit object.
            flatshading=True,
            lighting=dict(ambient=1.0, diffuse=0.0, specular=0.0),
            opacity=opacity,
            hoverinfo='text',
            hovertext=hovertext,
            name='Resistivity model',
            showlegend=False,
        ))

    def render(self):
        if self.dataframe is None or self.dataframe.empty:
            return self.empty_render()

        df = self.dataframe.copy()
        z_mode = self.settings.z
        ve = self.settings.vertical_exaggeration or 1.0

        utm_x, utm_y = self._project_latlon(df['latitude'].values, df['longitude'].values)
        df = df.assign(_utm_x=utm_x, _utm_y=utm_y)

        if z_mode == 'elevation':
            df['_z_top']    = df['elevation'] - df['top_depth'] * ve
            df['_z_bottom'] = df['elevation'] - df['bottom_depth'] * ve
        else:
            df['_z_top']    = -df['top_depth'] * ve
            df['_z_bottom'] = -df['bottom_depth'] * ve

        df = df.dropna(subset=['_utm_x', '_utm_y', '_z_top', '_z_bottom', 'resistivity'])
        if df.empty:
            return self.empty_render()

        below_doi = pd.Series(False, index=df.index)
        if 'doi' in df.columns:
            below_doi = df['top_depth'] > df['doi']
            if self.settings.mask_below_doi:
                df = df[~below_doi]
                below_doi = pd.Series(False, index=df.index)

        fig = go.Figure()

        if self.settings.show_map_layer:
            map_trace = self._get_map_layer_trace(df, z_mode)
            if map_trace is not None:
                fig.add_trace(map_trace)

        if self.settings.show_mean_res_layer:
            site_df = df.drop_duplicates('site_id')[['site_id', 'latitude', 'longitude', 'elevation']]
            mean_res_trace = self._get_mean_res_layer_trace(site_df, z_mode, ve)
            if mean_res_trace is not None:
                fig.add_trace(mean_res_trace)

        # Layers within the DOI render as solid boxes; layers below it
        # render as a second, faded trace (unless mask_below_doi drops them
        # entirely) so the extent of the survey stays visible without
        # implying the same confidence as the resolved part of the model.
        above_df = df[~below_doi]
        below_df = df[below_doi]

        if not above_df.empty:
            self._add_box_trace(fig, above_df, opacity=1.0, showscale=True)
        if not below_df.empty:
            self._add_box_trace(fig, below_df, opacity=self.settings.below_doi_opacity, showscale=False)

        if self.settings.show_site_markers:
            top_df = (df.sort_values(['site_id', 'layer'])
                        .groupby('site_id', as_index=False).first())
            fig.add_trace(go.Scatter3d(
                x=top_df['_utm_x'], y=top_df['_utm_y'], z=top_df['_z_top'],
                mode='markers',
                marker=dict(size=1.5, color='black'),
                customdata=top_df[['site_id']].values,
                hovertemplate='Site %{customdata[0]}<extra></extra>',
                name='Sites',
                showlegend=False,
            ))

        if self.settings.show_boreholes and self.boreholes:
            self._add_boreholes_3d(fig, z_mode, ve)

        if self.highlighted is not None:
            highlighted = self.highlighted
            if isinstance(highlighted, (list, tuple, set, np.ndarray, pd.Series)):
                highlighted = next(iter(highlighted), None)
            hi_df = df[df['site_id'] == highlighted]
            if not hi_df.empty:
                w = self.settings.box_half_width * 1.15  # just outside the box faces
                hx = hi_df['_utm_x'].iloc[0]
                hy = hi_df['_utm_y'].iloc[0]
                z_top = hi_df['_z_top'].max()
                z_bot = hi_df['_z_bottom'].min()

                # A line straight through a solid box would be hidden inside
                # it -- instead outline the 4 vertical corner edges just
                # outside the box, like a selection cage.
                xs_h, ys_h, zs_h = [], [], []
                for cx, cy in [(hx - w, hy - w), (hx + w, hy - w), (hx + w, hy + w), (hx - w, hy + w)]:
                    xs_h += [cx, cx, None]
                    ys_h += [cy, cy, None]
                    zs_h += [z_top, z_bot, None]

                fig.add_trace(go.Scatter3d(
                    x=xs_h, y=ys_h, z=zs_h,
                    mode='lines',
                    line=dict(color='black', width=6),
                    name=f'Site {highlighted}',
                    showlegend=False,
                    hoverinfo='skip',
                ))

        fig.update_layout(
            scene=dict(
                xaxis_title='Easting [m]',
                yaxis_title='Northing [m]',
                zaxis_title=('Elevation [m]' if z_mode == 'elevation' else 'Depth [m]'),
                aspectmode='data',
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            title='3D Resistivity Model',
            # Off by default -- the rock-type legend can get long and cover
            # a chunk of the 3D view. Toggle "Show Legend" in the settings
            # gear to reveal it, same pattern as the other show_* toggles
            # (show_boreholes, show_site_markers, etc.) on this panel.
            showlegend=self.settings.show_legend,
            legend=dict(x=0.01, y=0.99),
            # Without this, every full re-render (any settings tweak --
            # toggling the map layer, mean-res layer, depth, etc.) resets
            # the camera to its default view instead of keeping whatever
            # the user last rotated to, and leaves the browser's
            # relayoutData prop stale -- which is exactly what the 3D
            # export's camera-matching relies on (see app.py's
            # export_interpret_view_callback). A constant uirevision tells
            # Plotly to preserve camera/zoom/pan state across renders as
            # long as this value doesn't change.
            uirevision='model_3d',
        )
        return fig

    def _add_boreholes_3d(self, fig, z_mode, ve):
        """
        Mirrors ModelSection.add_boreholes_to_section_fig, but plots each
        borehole at its real UTM position in 3D instead of projecting onto
        a section line. self.boreholes is the list-of-dicts shape produced
        by Sections_plotting.get_borehole_projections() (each item has
        'id', 'map_lat'/'map_lon', 'elev', 'layers': [{'Top','Bottom',
        'LayerDescription',...}, ...]) -- it only carries lat/lon, so the
        UTM position used everywhere else in this panel is derived here.
        """
        lats = [bh.get('map_lat') for bh in self.boreholes]
        lons = [bh.get('map_lon') for bh in self.boreholes]
        utm_x, utm_y = self._project_latlon(lats, lons)

        seen_rock = set()
        for bh, bh_x, bh_y in zip(self.boreholes, utm_x, utm_y):
            if not np.isfinite(bh_x) or not np.isfinite(bh_y):
                continue

            bh_id = bh.get('id')
            elev = bh.get('elev')
            surface_z = elev if z_mode == 'elevation' else 0

            for layer in bh.get('layers', []):
                z_top    = surface_z - float(layer['Top']) * ve
                z_bottom = surface_z - float(layer['Bottom']) * ve
                rock  = str(layer.get('LayerDescription', '')).strip()
                color = (self.rock_color_map or {}).get(rock, 'lightgray')

                fig.add_trace(go.Scatter3d(
                    x=[bh_x, bh_x], y=[bh_y, bh_y], z=[z_top, z_bottom],
                    mode='lines',
                    line=dict(color=color, width=self.settings.line_width + 4),
                    name=rock,
                    legendgroup=rock,
                    showlegend=(rock not in seen_rock),
                    hovertext=f"<b>BH: {bh_id}</b><br>{rock}<br>{layer['Top']}-{layer['Bottom']} m",
                    hoverinfo='text',
                ))
                seen_rock.add(rock)

            fig.add_trace(go.Scatter3d(
                x=[bh_x], y=[bh_y], z=[surface_z],
                mode='text',
                text=[bh_id],
                textposition='top center',
                showlegend=False,
            ))
        return fig
