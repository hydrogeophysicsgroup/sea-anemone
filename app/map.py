from basepanel import *
import plotly.io as pio
from typing import Literal
import plotly.express as px
import plotly.graph_objects as go
from dash import dash_table, ctx, no_update, Patch, ClientsideFunction
import numpy as np
from nosj import nosj
import utm
from pandas import DataFrame, concat
from session import clean_table


DEPTH_INTERVALS = ['0-5', '5-10', '10-15', '15-20', '20-30', '30-40', '40-50', '50-75', '75-100', '100-125', '125-150', '150-200', '200-250', '300-400', '400-500']

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
 
        n_pts = projections.shape[2]
        projections = projections[idx_min[0], :, np.arange(n_pts)]  # (n_pts, 2)
        projections = projections.T  # (2, n_pts)


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
        title = kwargs.pop('colorbar_title', 'mean res, log\u2081\u2080(\u03a9\u00b7m) \u25be')
        return go.Choroplethmap(
            geojson=self.geojson,
            locations=self.ids,
            z=z_mesh,
            showlegend=True,
            marker=dict(opacity=opacity, line=dict(width=0, color=None)),
            showscale=True,
            hoverinfo="skip",
            selectedpoints=[],
            unselected=dict(marker=dict(opacity=opacity)),
            colorbar=dict(
                orientation="h",
                y=-0.01,
                x=0.5,
                xanchor="center",
                yanchor="top",
                len=0.75,
                thickness=10,
                title=dict(text=title, side="bottom")
            ),
            **kwargs
        )


@nosj
class MapSettings(PanelSettings):
    zoom: int = 10
    color: str = '#ff0000'
    highlight_color: str= '#ffff00'  # Default highlight color
    plot_by: Literal['', 'misfit', 'doi', 'date', 'mean-res'] = ''
    buffer_color: str= "#ffffff"  # Default buffer color
    hover_color: str= "#00ffff"  # marker for the site under the cursor in the section panels
    dragmode: str='select'
    view: dict = None
    markersize: int=14
    line_width: int=3
    legend: bool = False
    mean_res: str = '0-5'


class Map(Panel):
    dataframe: None
    highlighted: int = None
    buffer: SiteBuffer = None
    lines = None
    drawing: bool = False  # click-drawing lines (assets/linedraw.js)
    res_panel = None  # panel whose settings.vmin/vmax set the mean-res colour range, so it matches that panel (model section)
    

    

    def __init__(self, data, **kwargs):
        settings = MapSettings(id='map', **kwargs)
        super().__init__(id='map', settings=settings)
        self.dataframe = data
        self.layer_order=['tif', 'meanres', 'buffer', 'sites', 'highlight', 'lines']

    def render(self):
        if self.dataframe is None: return self.empty_render()
        df_plot = self.dataframe
        if 'site_id' in df_plot.columns:
            df_plot = df_plot[df_plot['site_id'] != -1]

        zoom = self.settings.view['map.zoom'] if self.settings.view is not None else self.settings.zoom
        center = self.settings.view['map.center'] if self.settings.view is not None else None

        if center is None and len(df_plot) > 0:
            center = dict(lat=df_plot['latitude'].mean(), lon=df_plot['longitude'].mean())
            # until the user pans/zooms, fit the survey into view (the default zoom hides small surveys and the mean-res grid)
            span = max(np.ptp(df_plot['latitude']), np.ptp(df_plot['longitude'])*np.cos(np.radians(center['lat'])), 1e-3)
            zoom = float(np.clip(np.log2(360./span) - 1.5, 1, 18))

        c_layers = []

        if self.settings.plot_by in self.dataframe.columns:

            fig = px.scatter_map(df_plot, lat="latitude", lon="longitude", zoom=zoom, center=center, 
                                 color=self.settings.plot_by, color_continuous_scale='turbo',
                                 custom_data='site_id'
                                 )
            fig.update_traces(marker=dict(size=self.settings.markersize), name='sites')
            fig.update_layout(
                coloraxis_colorbar=dict(
                    orientation="h", 
                    y=-0.01,
                    x=0.5,          
                    xanchor="center",
                    yanchor="top",
                    len=0.75,
                    thickness = 10,
                    title=dict(
                text=self.settings.plot_by+' ▾',
                side="bottom"))
            )
            c_layers.append('sites')
        else:
            fig = px.scatter_map(df_plot, lat="latitude", lon="longitude", custom_data='site_id',
                                 zoom=zoom, center=center, color_discrete_sequence=[self.settings.color])
            fig.update_traces(marker=dict(size=self.settings.markersize), name='sites',
                              showlegend=(self.settings.plot_by == 'mean-res'))
            c_layers.append('sites')

        if self.buffer is not None:
            df_buffer = self.dataframe[self.dataframe["site_id"].isin(self.buffer.window())]
            buffer_trace = px.scatter_map(
                df_buffer,
                lat="latitude",
                lon="longitude",
                custom_data='site_id',
                zoom=zoom, center=center, 
            )
            c_layers.append('buffer')
            buffer_trace.update_traces(
                marker=dict(size=self.settings.markersize*1.2, color=self.settings.buffer_color),
                name="Buffer window"
            )

            for trace in buffer_trace.data:
                fig.add_trace(trace)

        fig.update_layout(map_style="white-bg",
            map_layers=[
                {
                    "below": 'traces',
                    "sourcetype": "raster",
                    "source": ['https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}']
                }])
        # selected sites (one clicked, or several selected on the map or in the tTEM section)
        selected = self.buffer.selected if self.buffer is not None else [self.highlighted]
        highlighted_sites = df_plot[df_plot['site_id'].isin(selected)]
        if not highlighted_sites.empty:
            highlight_trace = px.scatter_map(highlighted_sites, lat="latitude", lon="longitude",
                                             custom_data='site_id', zoom=zoom, center=center,
                                             color_discrete_sequence=[self.settings.buffer_color])
            highlight_trace.update_traces(marker=dict(size=self.settings.markersize*1.2))
            fig.add_trace(highlight_trace.data[0])
        else:
            fig.add_trace(go.Scattermap(
                lat=[], lon=[], customdata=[], mode='markers', name='highlight',
                hoverinfo='skip', showlegend=False,
                marker=dict(size=self.settings.markersize*1.2, color=self.settings.buffer_color)
            ))
        c_layers.append('highlight')

        if self.lines is not None:
            fig2 = px.line_map(self.lines, lat='latitude', lon='longitude', line_group='line', color='line', zoom=zoom, center=center, color_discrete_sequence=line_colors)
            fig2.update_traces(mode='lines', line=dict(width=self.settings.line_width),
                               showlegend=self.settings.legend)
            fig2.for_each_trace(lambda t: t.update(hovertemplate=f'Line {t.name}<extra></extra>'))
            fig = go.Figure(data=fig.data+fig2.data, layout=fig.layout)
            for i in range(len(fig2.data)):
                c_layers.append(f'line_{i:02d}')

        # lines are click-drawn (assets/linedraw.js); 'drawline' may still be in settings saved with plotly's own line drawing
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0},
                          modebar=dict(remove=['zoomIn', 'zoomOut', 'lasso', 'toImage', 'plotly-logomark']),
                          dragmode='pan' if self.settings.dragmode == 'drawline' else self.settings.dragmode)
        
        from __main__ import sesh
        if self.settings.plot_by == 'mean-res' and sesh.models is not None:
            self.make_grid(sesh.models)
            kind, top, bot = parse_mean_res(self.settings.mean_res)
            if kind == 'elevation':
                res_grid = np.log10(elevation_mean_res(sesh.models, top, bot))
                interval = f'{top:g} to {bot:g} m elev.'
            else:
                res_grid = np.log10(rediscretize(sesh.models, np.array([top, bot])))
                interval = f'{top:g}-{bot:g} m depth'
            zmin, zmax = (0, 2) if self.res_panel is None else np.log10([self.res_panel.settings.vmin, self.res_panel.settings.vmax])
            fig.add_trace(self.grid.graph_object(res_grid, zmin=zmin, zmax=zmax, colorscale='Turbo', name='Mean Res',
                                                 colorbar_title=f'mean res {interval}, log\u2081\u2080(\u03a9\u00b7m) \u25be'))
        else:
            # plotly.js keeps a trace's map layers where they were first created, so the mean-res layer must exist
            # (empty) from the first render, otherwise switching to mean-res later draws it on top of the sites
            fig.add_trace(go.Choroplethmap(geojson={'type': 'FeatureCollection', 'features': []}, locations=[], z=[],
                                           showscale=False, showlegend=False, hoverinfo='skip', name='Mean Res'))
        c_layers.append('meanres')

        data_list = list(fig.data)
        reordered_data = []
        reordered_labels = []
        used_id = np.zeros(len(data_list), dtype=bool)
        
        for layer in self.layer_order:
            if layer in c_layers: 
                reordered_data.append(data_list[c_layers.index(layer)])
                used_id[c_layers.index(layer)] = True
                reordered_labels.append(layer)
        for i,add in zip(np.arange(len(data_list)), ~used_id):
            if add:
                reordered_data.append(data_list[i])
                if i<len(c_layers):
                    print('need to figure out why this happens?')
                    reordered_labels.append(c_layers[i])

        fig.data = reordered_data
        self._layers = reordered_labels

        # empty trace moved client-side (Plotly.restyle) when hovering the section panels; kept last so curve numbers don't shift
        fig.add_trace(go.Scattermap(lat=[], lon=[], mode='markers', name='hover', hoverinfo='skip', showlegend=False,
                                    marker=dict(size=self.settings.markersize*2, color=self.settings.hover_color)))
        self._layers.append('hover')

        # line being click-drawn, filled client-side by assets/linedraw.js
        fig.add_trace(go.Scattermap(lat=[], lon=[], mode='lines+markers', name='draft', hoverinfo='skip', showlegend=False,
                                    line=dict(width=self.settings.line_width, color='black'), marker=dict(size=8, color='black')))
        self._layers.append('draft')

        # stable trace ids, so plotly matches map layers by role when traces come and go (lines deleted, highlight
        # shown/hidden); with the default index-based ids, maplibre was asked to remove layers that didn't exist
        seen = {}
        for trace, label in zip(fig.data, self._layers):
            key = f'line-{trace.name}' if label.startswith('line_') else label
            seen[key] = seen.get(key, -1) + 1
            trace.uid = key if seen[key] == 0 else f'{key}-{seen[key]}'

        if self.settings.legend:
            fig.update_layout(showlegend=True,
                legend=dict(x=0.01, y=0.99,
                    xanchor="left",yanchor="top",
                    bgcolor="rgba(255,255,255,0.5)",  # semi-transparent background
                    bordercolor="black",borderwidth=1,
                )
            )

        # clicking the colour bar title picks what the sites are coloured by (assets/axismenu.js); without a colour bar, an annotation stands in
        plot_by = [o for o in self.settings.schema['properties']['plot_by']['enum']
                   if o == '' or o in self.dataframe.columns or (o == 'mean-res' and sesh.models is not None)]
        fig.update_layout(meta={'menus': {'colorbar': axis_menu(self.id+'_plot_by', plot_by, self.settings.plot_by, live=False)}})
        if self.settings.plot_by not in self.dataframe.columns and not (self.settings.plot_by == 'mean-res' and sesh.models is not None):
            fig.add_annotation(name='menu:colorbar', text='colour by ▾', x=0.5, y=0.01, xref='paper', yref='paper', yanchor='bottom',
                               showarrow=False, bgcolor='rgba(255,255,255,0.8)')
        return fig
    
        
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
                                'marginBottom': '50px'
                            }
                        ),

                        dbc.Button(
                            "Draw line [L]",
                            id=self.id+'_drawline',
                            color='primary',
                            outline=True,
                            active=self.drawing,
                            style={
                                'position': 'absolute',
                                'bottom': '10px',
                                'left': '10px',
                            }
                        ),
                        dbc.Tooltip("Click to add nodes, double-click to finish a line. Backspace removes the last node, Esc drops the line in progress.",
                                    target=self.id+'_drawline', placement='top'),
                        dcc.Store(id=self.id+'_line_draw'),
                        dbc.DropdownMenu(
                            self.delete_line_items(),
                            id=self.id+'_delete_line',
                            label="Delete line",
                            color='danger',
                            direction='up',
                            size='sm',
                            style={
                                'position': 'absolute',
                                'bottom': '12px',
                                'left': '140px',
                            }
                        ),

                        dbc.Select(
                            options=self.settings.schema['properties']['plot_by']['enum'],
                            id=self.id+'_plot_by',
                            value=self.settings.plot_by,
                            # kept as the state behind the colour bar title menu (assets/axismenu.js)
                            style={
                                'display': 'none',
                                'position': 'absolute',
                                'bottom': '10px',
                                'left': '50%',
                                'transform': 'translateX(-50%)',
                                'width': '150px'
                            }
                        ),

                        dbc.Select(
                            options=self.mean_res_options(self.res_panel.settings.y_axis if self.res_panel is not None else 'depth'),
                            id=self.id+'_mean_res',
                            value='0-5',
                            disabled=self.settings.plot_by != 'mean-res',
                            style={
                                'position': 'absolute',
                                'bottom': '10px',
                                'left': '75%',
                                'transform': 'translateX(-50%)',
                                'width': '150px'
                            }                            
                        )
                    ],
                    style={
                        'flex': '1',
                        'minHeight': 0,
                        'position': 'relative',
                        'display': 'flex'
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

    def delete_line_items(self):
        # one entry per line, with a swatch in the line's map colour (px.line_map assigns line_colors in order)
        if self.lines is None or len(self.lines) == 0:
            return [dbc.DropdownMenuItem("No lines", disabled=True)]
        items = [dbc.DropdownMenuItem([html.Span(style={'display': 'inline-block', 'width': '12px', 'height': '4px', 'marginRight': '8px',
                                                         'verticalAlign': 'middle', 'backgroundColor': line_colors[i % len(line_colors)]}),
                                       f'Line {line_id:0.0f}'],
                                      id={'type': self.id+'_delete_line_item', 'line': int(line_id)})
                 for i, line_id in enumerate(self.lines['line'].unique())]
        return items + [dbc.DropdownMenuItem(divider=True),
                        dbc.DropdownMenuItem("All lines", id={'type': self.id+'_delete_line_item', 'line': -1})]

    def mean_res_options(self, y_axis):
        """mean-res intervals for the dropdown: depth intervals, or (y_axis 'elevation') elevation slices covering the models"""
        from __main__ import sesh
        models = sesh.models
        if y_axis != 'elevation' or models is None or 'elevation' not in models.columns:
            return [{'label': f'{i} m', 'value': i} for i in DEPTH_INTERVALS]
        surface = models.groupby('site_id')['elevation'].first()
        top = surface.max()
        deepest = (surface - models.groupby('site_id')['bottom_depth'].max()).min()
        # about 25 slices, in round steps
        step = min([1, 2, 5, 10, 20, 25, 50, 100, 200, 500], key=lambda st: abs((top - deepest) / 25 - st))
        edges = np.arange(np.ceil(top / step) * step, np.floor(deepest / step) * step - step / 2, -step)
        return [{'label': f'{a:g} to {b:g} m', 'value': f'elev {a:g} {b:g}'} for a, b in zip(edges[:-1], edges[1:])]

    def convert_mean_res(self, value, options):
        """the option nearest to interval `value`; switching between depth and elevation goes via the median ground elevation"""
        from __main__ import sesh
        values = [o['value'] for o in options]
        if value in values:
            return value
        kind, top, bot = parse_mean_res(value)
        centre = (top + bot) / 2
        if kind != parse_mean_res(values[0])[0] and sesh.models is not None and 'elevation' in sesh.models.columns:
            centre = sesh.models.groupby('site_id')['elevation'].first().median() - centre
        return min(values, key=lambda v: abs(sum(parse_mean_res(v)[1:]) / 2 - centre))

    def make_grid(self, models):
        # grid points must be the model sites in rediscretize's row order (sorted site_id), so the gridded values line up
        site_ids = np.sort(models['site_id'].unique())
        src = models if {'latitude', 'longitude'} <= set(models.columns) else self.dataframe
        locs = src.groupby('site_id')[['latitude', 'longitude']].first().reindex(site_ids).values
        if getattr(self, 'grid', None) is not None and np.array_equal(getattr(self, '_grid_locs', None), locs):
            return
        self.grid = Grid(locs[:, 0], locs[:, 1], pixel_size=25., buffer_pixel=4)
        self._grid_locs = locs

    def add_callbacks(self, app):
        super().add_callbacks(app)


        @app.callback(
            self.output, Output(self.id+'_mean_res', 'disabled', allow_duplicate=True),
            Input(self.id+'_plot_by', 'value'),
            prevent_initial_call=True
        )
        def update_plotby(value):
            if value not in self.dataframe.columns and value != 'mean-res':
                raise PreventUpdate
            self.settings.plot_by = value
            disabled = value != 'mean-res'
            return self.render(), disabled
        
        @app.callback(
            Output(self.id+'_mean_res', 'options'),
            Output(self.id+'_mean_res', 'value'),
            Input({'type': 'settings-model_section', 'key': 'y_axis'}, 'value'),
            Input(self.id, 'figure'),
            State(self.id+'_mean_res', 'options'),
            State(self.id+'_mean_res', 'value'),
            prevent_initial_call=True
        )
        def update_mean_res_options(y_axis, _, options, value):
            # depth intervals or elevation slices, following the model section's y-axis; the map figure input catches a
            # newly loaded session (other models, other elevations)
            new_options = self.mean_res_options(y_axis)
            new_value = self.convert_mean_res(value, new_options)
            if new_options == options and new_value == value:
                raise PreventUpdate
            return new_options, new_value if new_value != value else no_update

        @app.callback(
            self.output,
            Input(self.id+'_mean_res', 'value'),
            prevent_initial_call=True
        )
        def update_mean_res(value):
            self.settings.mean_res = value
            return self.render()

        @app.callback(
            self.output,
            Input(self.id, 'relayoutData'),
            prevent_initial_call=True
        )
        def update_view(relayout_data):
            if 'map.center' in relayout_data:
                self.settings.view = relayout_data
            elif 'dragmode' in relayout_data:
                self.settings.dragmode = relayout_data['dragmode']
            else:
                raise PreventUpdate
            return self.render()

        app.clientside_callback(
            ClientsideFunction('anemone', 'toggleLineDraw'),
            Output(self.id+'_line_draw', 'data', allow_duplicate=True),
            Input(self.id+'_drawline', 'n_clicks'),
            prevent_initial_call=True
        )

        @app.callback(
            self.output,
            Output(self.id+'_drawline', 'active'),
            Output('model_section_axis', 'options', allow_duplicate=True),
            Output({'type': f'settings-model_section', 'key': 'x_axis'}, 'options', allow_duplicate=True),
            Input(self.id+'_line_draw', 'data'),
            State('model_section_axis', 'options'),
            prevent_initial_call=True
        )
        def draw_line(event, options):
            # events from assets/linedraw.js: 'start'/'stop' toggle click-drawing, 'line' and 'stop' carry the nodes ([lon, lat]) of a finished line
            from __main__ import sesh
            if not event:
                raise PreventUpdate
            if event['action'] == 'start' and not self.drawing:
                self.drawing = True
                self._dragmode_before_drawing = self.settings.dragmode
                self.settings.dragmode = 'pan'

            nodes = event.get('nodes', [])
            if len(nodes) >= 2:
                line_id = 1 if self.lines is None or len(self.lines) == 0 else int(self.lines['line'].max()) + 1
                new_line = DataFrame({'latitude': [n[1] for n in nodes], 'longitude': [n[0] for n in nodes], 'line': line_id,
                                      'node': np.arange(len(nodes)), 'length': -1., 'total_length': -1., 'radius': 100.})
                self.lines = new_line if self.lines is None else concat([self.lines, new_line], ignore_index=True)
                sesh.lines = self.lines.copy()
                sesh.update_site_table()

            if event['action'] == 'stop' and self.drawing:
                self.drawing = False
                self.settings.dragmode = self._dragmode_before_drawing

            options = options or []
            if sesh.lines is not None:
                line_options = [f'line {line_id:0.0f}' for line_id in sesh.lines['line'].unique()]
                options = line_options + [option for option in options if not option.startswith('line')]
            return self.render(), self.drawing, options, options

        @app.callback(
            Output(self.id+'_delete_line', 'children'),
            Input(self.id, 'figure'),
        )
        def update_delete_line_menu(_):
            return self.delete_line_items()

        @app.callback(
            self.output,
            Output('model_section_axis', 'options', allow_duplicate=True),
            Output({'type': f'settings-model_section', 'key': 'x_axis'}, 'options', allow_duplicate=True),
            Output('model_section_axis', 'value', allow_duplicate=True),
            Input({'type': self.id+'_delete_line_item', 'line': ALL}, 'n_clicks'),
            State('model_section_axis', 'options'),
            State('model_section_axis', 'value'),
            prevent_initial_call=True
        )
        def delete_line(n_clicks, options, x_axis):
            # the menu items are re-created with each map render, which fires this with n_clicks None
            from __main__ import sesh
            if not ctx.triggered_id or not any(n_clicks) or self.lines is None:
                raise PreventUpdate
            line_id = ctx.triggered_id['line']
            self.lines = self.lines[self.lines['line'] != line_id] if line_id != -1 else self.lines.iloc[0:0]
            if len(self.lines) == 0:
                self.lines = None
                # line_update only rebuilds the per-line columns while there are lines
                for df in (sesh.data, sesh.site, sesh.models):
                    if df is not None:
                        clean_table(df)
            sesh.lines = None if self.lines is None else self.lines.copy()
            sesh.update_site_table()

            options = [option for option in (options or []) if not option.startswith('line')]
            if sesh.lines is not None:
                options = [f'line {i:0.0f}' for i in sesh.lines['line'].unique()] + options
            # the sections can't stay on a deleted line
            if x_axis and x_axis.startswith('line') and int(float(x_axis.split(' ')[-1])) not in (sesh.lines['line'].unique() if sesh.lines is not None else []):
                x_axis = 'site_id'
            else:
                x_axis = no_update
            return self.render(), options, options, x_axis

        @app.callback(
            Output('model_section_axis', 'value', allow_duplicate=True),
            Input(self.id, 'clickData'),
            prevent_initial_call=True
        )
        def update_highlight(click_data):
            result = no_update
            if self.lines is None:
                return result

            if 'points' in click_data and len(click_data['points'])==1:
                curve_number = click_data['points'][0]['curveNumber']
                if self._layers[curve_number].startswith('line_'):
                    all_dist = cdist(click_data['points'][0]['lat'], click_data['points'][0]['lon'], self.lines['latitude'].values, self.lines['longitude'].values)
                    line_id = self.lines['line'].values[np.argmin(all_dist)]
                    x_axis = 'line '+f'{line_id:0.0f}'
                    result = x_axis
            return result
        

def rediscretize_matrix(z_old, z_new):
    """this function rediscretizes values onto a new grid. if an interval on the new discretization spans several layers, the resulting average will be thickness averaged."""
    if type(z_old) is tuple:
        z_old1,z_old2 = z_old
    elif isinstance(z_old, np.ndarray):
        z_old1 = np.insert(z_old, 0,0)[:-1]
        z_old2 = z_old*1

    if type(z_new) is tuple:
        z_new1,z_new2 = z_new
    elif isinstance(z_new, np.ndarray):
        z_new1 = np.insert(z_new, 0,0)[:-1]
        z_new2 = z_new*1

    zo1,zn1 = np.meshgrid(z_old1, z_new1, indexing='ij')
    zo2,zn2 = np.meshgrid(z_old2, z_new2, indexing='ij')

    ov1 = np.max(np.stack([zo1,zn1]), axis=0)
    ov2 = np.min(np.stack([zo2,zn2]), axis=0)
    ov = ov2-ov1
    ov[ov<0] = 0

    if z_new2[-1] > z_old2[-1]:
        ov[-1, -1] = 1.
    
    ov /= ov.sum(0, keepdims=True)
    
    return ov

def elevation_mean_res(model_df, top, bot):
    """thickness-weighted mean resistivity of each site's model between elevations top and bot (rows in sorted site_id
    order, like rediscretize); NaN where the slice is above ground or below the model"""
    res = model_df.pivot_table('resistivity', 'site_id', 'center_depth')
    layers = model_df.groupby('center_depth')[['top_depth', 'bottom_depth']].first().reindex(res.columns)
    surface = model_df.groupby('site_id')['elevation'].first().reindex(res.index).values[:, None]
    z1 = np.clip(surface - top, 0, None)  # depth of the slice at each site
    z2 = np.clip(surface - bot, 0, None)
    overlap = np.clip(np.minimum(layers['bottom_depth'].values[None, :], z2) - np.maximum(layers['top_depth'].values[None, :], z1), 0, None)
    thickness = overlap.sum(1)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(thickness > 0, np.nansum(res.values * overlap, 1) / thickness, np.nan)


def rediscretize(model_df, z_new):
    d_top = model_df['top_depth'].unique()
    d_bot = model_df['bottom_depth'].unique()
    res_grid = model_df.pivot_table('resistivity', 'site_id', 'center_depth').values
    # print(res_grid.shape)
    # model_df=model_df[model_df.site_id.isin(res_grid.index)]
    z_old = np.unique(np.concatenate((d_top[1:],d_bot)))
    z_old.sort()
    redisc_mat = np.nan_to_num(rediscretize_matrix(z_old, z_new))

    if len(z_new)==2:
        redisc_mat = redisc_mat[:, 1:].squeeze()
    return res_grid @ redisc_mat