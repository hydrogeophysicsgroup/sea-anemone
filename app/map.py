from basepanel import *
import plotly.io as pio
from typing import Literal
import plotly.express as px
import plotly.graph_objects as go
from dash import dash_table, ctx, no_update, Patch
import numpy as np
from nosj import nosj
import utm
from pandas import DataFrame


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
            **kwargs
        )


@nosj
class MapSettings(PanelSettings):
    zoom: int = 10
    color: str = '#ff0000'
    highlight_color: str= '#ffff00'  # Default highlight color
    plot_by: Literal['', 'misfit', 'doi', 'date', '_line_1_x', '_line_1_y'] = ''
    buffer_color: str= "#ffffff"  # Default buffer color
    dragmode: str='select'
    view: dict = None
    markersize: int=14
    line_width: int=3
    legend: bool = False
    mean_res: int = 0


class Map(Panel):
    dataframe: None
    highlighted: int = None
    buffer_sites: list = None
    lines = None
    

    

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
                text='',
                side="bottom"))
            )
            c_layers.append('sites')
        else:
            fig = px.scatter_map(df_plot, lat="latitude", lon="longitude", custom_data='site_id',
                                 zoom=zoom, center=center, color_discrete_sequence=[self.settings.color])
            fig.update_traces(marker=dict(size=self.settings.markersize), name='sites')
            c_layers.append('sites')

        if self.buffer_sites is not None:
            self.buffer_sites = self.dataframe['site_id'].unique().tolist()
            df_buffer = self.dataframe.copy()
        else:
            df_buffer = self.dataframe.copy()[self.dataframe["site_id"].isin(self.buffer_sites)]
            buffer_trace = px.scatter_map(
                df_buffer,
                lat="latitude",
                lon="longitude",
                zoom=zoom, center=center, 
            )
            c_layers.append('buffer')
            buffer_trace.update_traces(
                marker=dict(size=self.settings.markersize*1.5, color=self.settings.buffer_color),
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
        if self.highlighted is not None:
            highlight_trace = px.scatter_map(df_plot[df_plot.index == self.highlighted], lat="latitude", lon="longitude", zoom=zoom, center=center, color_discrete_sequence=[self.settings.highlight_color])
            highlight_trace.update_traces(marker=dict(size=self.settings.markersize*2))
            for trace in highlight_trace.data:
                fig.add_trace(
                    trace
                )

        if self.lines is not None and self.settings.dragmode=='drawline':
            for line_id in self.lines.line.unique():
                fig.add_shape(self.line2path(line_id))
        elif self.lines is not None:
            fig2 = px.line_map(self.lines, lat='latitude', lon='longitude', line_group='line', color='line', zoom=zoom, center=center, color_discrete_sequence=line_colors)
            fig2.update_traces(mode='lines', hovertemplate='Line%{line:.0f}', line=dict(width=self.settings.line_width))
            fig = go.Figure(data=fig.data+fig2.data, layout=fig.layout)
            for i in range(len(fig2.data)):
                c_layers.append(f'line_{i:02d}')

        hovermode = False if self.settings.dragmode=='drawline' else None
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0},
                          modebar=dict(add=['drawline', 'eraseshape'], remove=['zoomIn', 'zoomOut', 'lasso', 'toImage', 'plotly-logomark']),
                          newshape=dict(line_color='black', line_width=3, line_dash='dash'),
                          dragmode=self.settings.dragmode, hovermode=hovermode)
        
        if hasattr(self, 'grid') and self.grid is not None:
            from __main__ import sesh
            z_new = np.array([self.settings.mean_res, self.settings.mean_res+1])*10.
            res_grid = np.log10(rediscretize(sesh.models, z_new))
            # res_grid = 
            fig.add_trace(self.grid.graph_object(res_grid, zmin=0, zmax=2, colorscale='Turbo', name='Mean Res'))
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
                reordered_labels.append(c_layers[i])

        fig.data = reordered_data
        self._layers = reordered_labels

        if self.settings.legend:
            fig.update_layout(showlegend=True,
                legend=dict(x=0.01, y=0.99,
                    xanchor="left",yanchor="top",
                    bgcolor="rgba(255,255,255,0.5)",  # semi-transparent background
                    bordercolor="black",borderwidth=1,
                )
            )

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
                                'marginBottom': '50px'
                            }
                        ),

                        dbc.Select(
                            options=self.settings.schema['properties']['plot_by']['enum'],
                            id=self.id+'_plot_by',
                            value=self.settings.plot_by,
                            style={
                                'position': 'absolute',
                                'bottom': '10px',
                                'left': '50%',
                                'transform': 'translateX(-50%)',
                                'width': '150px'
                            }
                        ),

                        dbc.Input(
                            type='number',
                            step=1,
                            value=0,
                            id=self.id+'_mean_res',
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

    def make_grid(self):
        self.grid = Grid(self.dataframe.latitude.values, self.dataframe.longitude.values, pixel_size=25., buffer_pixel=4)

    def add_callbacks(self, app):
        super().add_callbacks(app)


        @app.callback(
            self.output,
            Input(self.id+'_plot_by', 'value'),
            prevent_initial_call=True
        )
        def update_plotby(value):
            if value not in self.dataframe.columns:
                raise PreventUpdate
            self.settings.plot_by = value
            return self.render()  
        
        @app.callback(
            self.output,
            Input(self.id+'_mean_res', 'value'),
            prevent_initial_call=True
        )
        def update_mean_res(value):
            self.settings.mean_res = value
            m1_patch = Patch()
            from __main__ import sesh
            z_new = np.array([self.settings.mean_res, self.settings.mean_res+1])*10.
            res_grid = np.log10(rediscretize(sesh.models, z_new))

            m1_patch['data'][self._layers.index('meanres')]['z'] = self.grid.grid_values(res_grid)
            return m1_patch

        @app.callback(
            self.output,
            Output('model_section_axis', 'options', allow_duplicate=True),
            Output({'type': f'settings-model_section', 'key': 'x_axis'}, 'options', allow_duplicate=True),
            Input(self.id, 'relayoutData'),
            State('model_section_axis', 'options'),
            prevent_initial_call=True
        )
        def update_view(relayout_data, options):
            from __main__ import sesh
            if 'map.center' in relayout_data:
                self.settings.view = relayout_data
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
                    for line_id, path in zip(self.lines.line.unique(), saved_paths):
                        if path not in remaining_paths:
                            self.lines = self.lines[self.lines.line!=line_id]
                    sesh.lines = self.lines.copy()
                    sesh.update_site_table()
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