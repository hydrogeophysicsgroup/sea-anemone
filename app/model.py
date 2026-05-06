from basepanel import *
import numpy as np
import pandas as pd

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

        if self.highlighted is None:
            heatmap_df = df_layers_long.set_index('site_id').sort_index(ascending=True)
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
                title="1D Resistivity Profile",
            )
        else:
            fig = go.Figure(layout=dict(title="1D Resistivity Profile"))
            df_highlighted = df_layers_long[df_layers_long['site_id'] == self.highlighted]
            fig.add_trace(
                go.Scatter(
                    x=df_highlighted["resistivity"],
                    y=df_highlighted["depth"],
                    

                    
                    mode="lines",
                    line=dict(width=2, color='red'),
                    zorder=10,
                    name=f"Site {self.highlighted}"
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
        return fig        
    
@nosj
class ModelSectionSettings(PanelSettings):
    y_axis: Literal['depth', 'elevation'] = 'depth'
    x_axis: Literal['daytime', 'site_id'] = 'site_id'
    bars: bool=True
    misfit: bool=True
    doi: bool=True
    radius : float=100.0
    vmin: float=1.0
    vmax: float=500.
    Min_bar_spacing: float = 0.3
    Width_factor: float = 10
    Borehole_radius : float=100.0


class ModelSection(Panel):
    highlighted: int = None
    buffer_len = 50
    buffer_start = 0
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

        label_style = {"width": "110px", "textAlign": "right", "fontSize": "14px"}

        return  html.Div([
                    html.Div(
                        [
                        dcc.Graph(
                        id=self.id,
                        figure=self.render(),
                        mathjax=True,
                        style={"height": "95%"}
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        dbc.Label(
                                            "x-axis",
                                            html_for=self.id + "_axis",
                                            class_name="mb-0",
                                            # style={"width": "70px", "textAlign": "right"},
                                            style=label_style
                                        ),
                                        dbc.Select(
                                            id=self.id + "_axis",
                                            options=options,
                                            value="site_id",
                                            style={"width": "120px"},
                                        ),
                                    ],
                                    style={"display": "flex", "alignItems": "center", "gap": "8px"},
                                ),
                                html.Div(
                                    [
                                        dbc.Label(
                                            "radius",
                                            html_for=self.id + "_radius",
                                            class_name="mb-0",
                                            # style={"width": "70px", "textAlign": "right"},
                                            style=label_style
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
                                    style={"display": "flex", "alignItems": "center", "gap": "8px"},
                                ),
                                html.Div(
                                    [
                                        dbc.Label(
                                            "Borehole_radius",
                                            html_for=self.id + "_bor_radius",
                                            class_name="mb-0",
                                            # style={"width": "70px", "textAlign": "right"},
                                            style=label_style
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
                                    style={"display": "flex", "alignItems": "center", "gap": "8px"},
                                ),
                            ],
                            style={
                                "position": "absolute",
                                "bottom": "12px",
                                "left": "12px",
                                "display": "flex",
                                "flexDirection": "column",
                                "gap": "8px",
                                "zIndex": 1000,
                                "backgroundColor": "rgba(255,255,255,0.85)",
                                "padding": "6px 8px",
                                "borderRadius": "6px",
                            },
                        ),
                        ],
                        style={"position": "relative", "height": "100%"}
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

                fig.add_trace(go.Scatter(
                    x=x_box, y=y_box,
                    fill="toself",
                    fillcolor=color,
                    mode="lines",
                    line=dict(width=1, color="black"),
                    name=rock,
                    showlegend=False,
                    hovertext=f"<b>BH: {bh_id}</b><br>{rock}<br>Depth: {row['layer_top']}-{row['layer_bottom']}m",
                    hoverinfo="text"
                ))

            # Add Borehole ID Label at the top
            fig.add_annotation(
                x=bh_x, y=first_row["bh_elev"],
                text=f"<b>{bh_id}</b>",
                showarrow=False, yshift=15,
                font=dict(size=10, color="black"),
                bgcolor="rgba(255,255,255,0.8)")
            
        return fig

    def render_base(self):

        if self.dataframe is None: return self.empty_render()

        # --- Select dataframe ---
        x_axis = self.settings.x_axis

        if x_axis.startswith('line'):
            line_id = int(float(x_axis.split(' ')[-1]))
            x_axis = f'_line_{line_id:0.0f}_x'

        if 'line' in x_axis:
            from __main__ import sesh
            df = sesh.models.copy()
            df = df.loc[np.abs(df[x_axis.replace('_x', '_y')]) < self.settings.radius]
            width = self.settings.Min_bar_spacing * self.settings.Width_factor
        else:
            df = self.dataframe.copy()
            width = self.settings.Min_bar_spacing 

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

        
        if y_axis == 'depth':
            # FAKE flat elevation
            elev = np.zeros(len(pivot.index))
            center_elev = elev[:, None] - depth[None, :]

            d_elev = int(center_elev.max() - center_elev.min()) + 50
            elev_axis = np.arange(d_elev) + center_elev.min() - 25

            dist = np.abs(elev_axis[:, None, None] - center_elev[None, :, :])
            nearest_idx = dist.argmin(axis=-1)

            n_elev, n_sites = nearest_idx.shape
            station_idx = np.broadcast_to(np.arange(n_sites), (n_elev, n_sites))

            res_grid = pivot.values[station_idx, nearest_idx]

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
            nearest_idx = dist.argmin(axis=-1)

            n_elev, n_sites = nearest_idx.shape
            station_idx = np.broadcast_to(np.arange(n_sites), (n_elev, n_sites))

            res_grid = pivot.values[station_idx, nearest_idx]

            # mask air / below model
            heaven = elev_axis[:, None] > elev[None, :]
            hell   = elev_axis[:, None] < (elev[None, :] - depth.max() * 1.1)

            res_grid[heaven] = np.nan
            res_grid[hell]   = np.nan

            y = elev_axis

        else:
            raise ValueError(f"Unknown y_axis: {y_axis}")

        id_map = df.groupby(x_axis)[['site_id', 'latitude', 'longitude']].first()
        site_info = id_map.reindex(pivot.index)[['site_id', 'latitude', 'longitude']].values
        
        if self.settings.bars:
            
            n_sites = len(x)
            n_depths = res_grid.shape[0]

            # Use 4 points per site: [Left_Gap, Left_Edge, Right_Edge, Right_Gap]
            x_plot = np.zeros(n_sites * 4)
            res_new = np.full((n_depths, n_sites * 4), np.nan)

            for i in range(n_sites):
                idx = 4 * i
                center_x = x[i]
                
                # 1. Coordinate slightly left of the bar (NaN)
                x_plot[idx]     = center_x - width - 0.0001
                # 2. Left edge of bar
                x_plot[idx + 1] = center_x - width
                # 3. Right edge of bar
                x_plot[idx + 2] = center_x + width
                # 4. Coordinate slightly right of the bar (NaN)
                x_plot[idx + 3] = center_x + width + 0.0001
                
                # Assign values only to the edges (idx+1 and idx+2)
                # This creates a solid block of color between them
                res_new[:, idx + 1] = res_grid[:, i]
                res_new[:, idx + 2] = res_grid[:, i]

            x_final = x_plot
            res_grid_final = res_new

            # for the hovermarker
            site_info_expanded = np.repeat(site_info, 4, axis=0)
            custom_data_grid = np.tile(site_info_expanded, (len(y), 1, 1))
        else:
            x_final = x
            print("x final 2", x_final)
            res_grid_final = res_grid

            custom_data_grid = np.tile(site_info, (len(y), 1, 1))

        # Final Plotting using Graph Objects for precision
        import plotly.graph_objects as go
                
        fig = go.Figure(data=go.Heatmap(
            z=np.log10(res_grid_final),
            x=x_final,
            y=y,
            customdata=custom_data_grid,
            hovertemplate="Site: %{customdata[0]}<extra></extra>",
            zsmooth=False,
            hoverongaps=False,
            colorscale='turbo',
            zmin=np.log10(self.settings.vmin),
            zmax=np.log10(self.settings.vmax),
            # colorbar=dict(title='Resistivity [Ω·m]')
            colorbar=dict(
                orientation="h",
                y=-0.75,        # Adjusted to move it below the X-axis title
                x=0.5,
                xanchor="center",
                len=0.5,
                thickness=15,
                title=dict(text="Resistivity [log10 Ωm]", side="bottom"))
        ))

        if y_axis == 'depth':
            fig.update_yaxes(autorange="reversed")

        pad = self.settings.Min_bar_spacing * 2
        
        # Filter out NaNs to find the real min/max for the range
        valid_x = x_final[~np.isnan(x_final)]
        x_min, x_max = np.min(valid_x), np.max(valid_x)

        # 3. Update Layout
        fig.update_layout(
            xaxis=dict(
                type='linear', 
                title=x_axis.replace('_x', '').replace('_', ' ').strip(),
                range=[x_min, x_max], # Forces the first bar to show fully
                title_standoff=4
            ),
            yaxis=dict(title=y_axis),
            plot_bgcolor='white',
            # hovermode="x",
            hovermode="closest",
            margin=dict(b=100) # Add bottom margin to make room for horizontal colorbar
        )

        return fig

    def render(self):
       
        if self.dataframe is None: return self.empty_render()
        fig = self.render_base()

        df = self.dataframe.copy()
        x_axis = self.settings.x_axis
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
            current_width = self.settings.Min_bar_spacing * self.settings.Width_factor

            # Filter the line from session
            c_line = sesh.lines.loc[sesh.lines.line == line_id] 
            
            if not c_line.empty:
                from pyproj import Transformer
                epsg = self.get_utm_epsg(c_line.latitude.iloc[0], c_line.longitude.iloc[0])
                
                transformer = Transformer.from_crs("epsg:4326", f"epsg:{epsg}", always_xy=True)
                utmx, utmy = transformer.transform(c_line.longitude.values, c_line.latitude.values)
                
                line_coords_utm = (utmx, utmy)
        else:
            current_width = self.settings.Min_bar_spacing
            x_min = None
            x_max = None

        from __main__ import sesh
        if sesh.boreholes is not None and not sesh.boreholes.empty:
           fig = self.add_boreholes_to_section_fig(fig, sesh.boreholes, sesh.rock_map, x_axis,current_width,
                line_utm=line_coords_utm)


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
            doi_df['doi'] = df.groupby(x_axis)['elevation'].first().values - doi_df['doi'].values
            ylim = [doi_df["doi"].min()-8, df_layers_long["elevation"].max()+8]
        else:
            ylim = [doi_df["doi"].max()+8, df_layers_long["depth"].min()-8]
        
        if x_min is None:
            x_min = df_layers_long[x_axis].min()
        if x_max is None:
            x_max = df_layers_long[x_axis].max()

        if self.settings.doi:    
            if not doi_df.empty:

                y_max = df_layers_long["depth"].max()

                fig.add_trace(
                    go.Scatter(
                        x=np.concatenate([
                            [x_min],
                            doi_df[x_axis].values,
                            [x_max],
                            [x_min]
                        ]),
                        y=np.concatenate([
                            [y_max + 50],
                            doi_df["doi"].values,
                            [y_max + 50],
                            [y_max + 50]
                        ]),
                        


                        fill="toself",
                        fillcolor="rgba(255,255,255,0.6)",
                        line=dict(width=0),
                        name="Below DOI",
                    )
                )

            if self.highlighted is not None and self.dataframe is not None:

                selected_df = df[df["site_id"] == self.highlighted]

                if not selected_df.empty:
                    x_value = selected_df[x_axis].iloc[0]

                    x_vals = np.sort(df[x_axis].dropna().unique())

                    if len(x_vals) > 1:
                        diffs = np.diff(x_vals)
                        dx = np.median(diffs) * 0.5
                    else:
                        dx = 0.5

                    fig.add_shape(
                        type="rect",
                        x0=x_value - dx,
                        x1=x_value + dx,
                        y0=df_layers_long["depth"].min(),
                        y1=df_layers_long["depth"].max()+20,
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