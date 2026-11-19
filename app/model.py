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
        # ...existing code...
        df_layers_long = pd.melt(
            self.dataframe,
            id_vars=['site_id', 'layer', 'resistivity'],
            value_vars=['top_depth', 'bottom_depth'],
            var_name='depth_type',
            value_name='depth'
        ).sort_values(['site_id', 'layer', 'depth'])

        df_layers_long = df_layers_long.drop(columns=['depth_type'])

        if self.highlighted is None:
            buffer_start = self.buffer_start
            buffer_len   = self.buffer_len

            x_values = df_layers_long['site_id'].unique().tolist()
            n_sites  = len(x_values)

            plot_start = max(0, buffer_start)
            plot_end   = min(n_sites, buffer_start + buffer_len)

            x_slice = x_values[plot_start:plot_end]

            fig = go.Figure(layout=dict(
                title="1D Resistivity Profile",
                legend=dict(title_text="Site ID"),
            ))
            plot_data = df_layers_long[df_layers_long['site_id'].isin(x_slice)]
            colors = px.colors.qualitative.Plotly
            for color_index, (site_id, site_data) in enumerate(
                plot_data.groupby('site_id', sort=False)
            ):
                fig.add_trace(go.Scatter(
                    x=site_data["resistivity"],
                    y=site_data["depth"],
                    mode="lines",
                    name=str(site_id),
                    legendgroup=str(site_id),
                    line=dict(color=colors[color_index % len(colors)]),
                    hovertemplate=(
                        f"Site ID={site_id}<br>ρ [Ω·m]=%{{x}}<br>"
                        "depth=%{y}<extra></extra>"
                    ),
                ))
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

    def __getattribute__(self, name):
        x_axis = super().__getattribute__(name)
        if name == 'x_axis':
            if x_axis.lower().startswith('line'):
                line_id = int(float(x_axis.split(' ')[-1]))
                x_axis = f'_line_{line_id:0.0f}_x'        
        return x_axis



class ModelSection(Panel):
    highlighted: int = None
    buffer_len = 50
    buffer_start = 0
    buffer: SiteBuffer = None
    mean_res_interval: tuple = None
    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', ModelSectionSettings(id='model_section'))
        settings.radius=100.
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
                        clear_on_unhover=True,
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
                                            style={"width": "70px", "textAlign": "right"},
                                        ),
                                        dbc.Select(
                                            id=self.id + "_axis",
                                            options=options,
                                            value="site_id",
                                            style={"width": "120px"},
                                        ),
                                    ],
                                    # kept as the state behind the x-axis title menu (assets/axismenu.js)
                                    style={"display": "none"},
                                ),
                                html.Div(
                                    [
                                        dbc.Label(
                                            "radius",
                                            html_for=self.id + "_radius",
                                            class_name="mb-0",
                                            style={"width": "70px", "textAlign": "right"},
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
                            ],
                            id=self.id + "_axis_controls",
                            style=self.axis_controls_style(False),
                        ),
                        ],
                        style={"position": "relative", "height": "100%"}
                    ),
                    gear_maker(self.id)],
                    style={'height': '100%'} 
                )
    
    def axis_controls_style(self, show):
        # the radius box only applies to lines, so it's only shown while the x-axis is a line
        return {
            "position": "absolute",
            "bottom": "12px",
            "left": "12px",
            "display": "flex" if show else "none",
            "flexDirection": "column",
            "gap": "8px",
            "zIndex": 1000,
            "backgroundColor": "rgba(255,255,255,0.85)",
            "padding": "6px 8px",
            "borderRadius": "6px",
        }

    def render_base(self):
        
        if self.dataframe is None: return self.empty_render()
        df = self.dataframe.copy()
        x_axis = self.settings.x_axis


        if 'line' in x_axis:
            from __main__ import sesh
            df = sesh.models.copy()
            df = df.loc[np.abs(df[x_axis.replace('_x', '_y')])<self.settings.radius]
        
        y_axis = self.settings.y_axis
        res_grid = df.pivot_table('resistivity', x_axis, 'center_depth')
        x   = np.sort(np.unique(df[x_axis].values))
        y   = res_grid.columns.values.squeeze()

        if y_axis=='elevation':
            elev= df.pivot_table('elevation', x_axis).values.squeeze()
            depth = res_grid.columns.values
            center_elev = elev[:, None] - depth[None, :]
            d_elev = int(center_elev.max()-center_elev.min())+50
            elev_axis = np.arange(d_elev)+center_elev.min()-25
            dist = np.abs(elev_axis[:, None, None] - center_elev[None, :, :])
            nearest_idx = dist.argmin(axis=-1)  # (n_elev, n_station)

            # Build station index grid
            n_elev, n_station = nearest_idx.shape
            station_idx = np.broadcast_to(
                np.arange(n_station),
                (n_elev, n_station)
            )

            # Direct advanced indexing
            res_grid = res_grid.values[station_idx, nearest_idx]
            heaven = elev_axis[:, None] > elev[None, :]
            hell   = elev_axis[:, None] < (elev[None, :]-depth.max()*1.1)

            res_grid[heaven] = np.nan
            res_grid[hell]   = np.nan

            y = elev_axis
        else:
            res_grid = res_grid.values.T

        if self.settings.bars:
            n = len(x)
            if n > 1:
                inter_dx = np.diff(x)
                # floor prevents tightly-packed clusters from collapsing all bars to invisible width
                dx_min = max(inter_dx.min() * 0.49, (x.max() - x.min()) * 0.005)
            else:
                dx_min = max(x[0] * 0.1, 1.0)

            x_rep = np.empty(n * 3)
            x_rep[0::3] = x - dx_min
            x_rep[1::3] = x
            x_rep[2::3] = x + dx_min

            res_grid = np.repeat(res_grid, 3, axis=1)
            x = x_rep

            dx = np.abs(np.diff(x, prepend=x[0]))
            x_len = x.max() - x.min()
            needs_gap = dx > 0.03 * x_len
            only_between_bars = np.zeros(len(needs_gap), dtype=bool)
            only_between_bars[3::3] = True
            needs_gap = needs_gap & only_between_bars

            if needs_gap.any():
                x_with_gaps = np.full(len(x) + 2 * needs_gap.sum(), np.nan)
                i_x = np.arange(len(x)) + np.cumsum(2 * needs_gap.astype(int))
                x_with_gaps[i_x] = x
                res_with_gaps = np.full(res_grid.shape[:1] + x_with_gaps.shape, np.nan)
                res_with_gaps[:, i_x] = res_grid
                x = x_with_gaps
                res_grid = res_with_gaps
        res_grid = np.log10(res_grid)        

        fig = px.imshow(
            res_grid, x=x, y=y,
            aspect='auto',
            origin='lower',
            color_continuous_scale='turbo',
            labels={'x': axis_label(x_axis)+' ▾', 'y': y_axis+' ▾', 'color': 'Resistivity [Ω·m]'},
            zmin=np.log10(self.settings.vmin),
            zmax=np.log10(self.settings.vmax),
        )
        if y_axis=='depth':
            fig.update_yaxes(autorange="reversed")
        fig.update_layout(
            coloraxis_colorbar=dict(
                # tickvals = [0, 1, 2, np.log10(self.settings.vmax)],
                # ticktext = ["1", "10", "100", str(int(self.settings.vmax))],
                orientation="h",     # horizontal
                y=-0.45,              # move below plot
                x=0.5,               # center horizontally
                xanchor="center",
                len=0.5,
                thickness = 10,
                title=dict(
                    text="Resistivity [Ωm]",
                    side="bottom")
                ),
            xaxis=dict(
                title_standoff=4   # default is ~15–20
            ),
            hovermode="x")
        return fig
    
    def axis_menus(self):
        return {'x': section_x_menu(),
                'y': axis_menu({'type': f'settings-{self.id}', 'key': 'y_axis'}, ['depth', 'elevation'], self.settings.y_axis)}

    def render(self):
        if self.dataframe is None: return self.empty_render()
        from __main__ import sesh
        x_axis = self.settings.x_axis
        if x_axis.startswith('_line'):
            near = sesh.models.loc[np.abs(sesh.models[x_axis.replace('_x', '_y')]) < self.settings.radius] if x_axis in sesh.models.columns else sesh.models.iloc[0:0]
            if len(site_positions(near, x_axis)) == 0:
                self._site_buffer_site_x = pd.Series(dtype=float)
                fig = self.message_render(f'No models within {self.settings.radius:g} m of {axis_label(x_axis)}')
                fig.update_layout(xaxis_title=axis_label(x_axis)+' ▾', yaxis_title=self.settings.y_axis+' ▾', meta={'menus': self.axis_menus()})
                self._site_buffer_static_shapes = site_buffer_static_shapes(fig)
                return fig
        fig = self.render_base()

        df = self.dataframe.copy()
        x_axis = self.settings.x_axis
        if x_axis.startswith('_line'):
            line_id = int(float(x_axis.split('_')[-2]))

        if 'line' in x_axis:
            from __main__ import sesh
            df = sesh.models.copy()
            df = df.loc[np.abs(df[x_axis.replace('_x', '_y')])<self.settings.radius]        
            x_min = 0
            x_max = sesh.lines[sesh.lines.line==line_id].total_length.max()

        else:
            x_min = None
            x_max = None

        df_layers_long = df.melt(
            id_vars=[x_axis, 'resistivity', 'misfit','doi', 'layer', 'elevation'],
            value_vars=['top_depth', 'bottom_depth'],
            var_name='depth_type',
            value_name='depth'
        ).sort_values([x_axis, 'layer', 'depth'])
        fig.update_layout(
            margin=dict(l=55, r=120, t=10, b=50, autoexpand=False),
            yaxis2=dict(title='Misfit', overlaying='y', side='right', showgrid=False)
        )
        # ---- Misfit only for buffered sites ----
        if self.settings.misfit:
            misfit_df = (
                df_layers_long
                .groupby(x_axis)['misfit']
                .first()
                .reset_index()
            )

            misfit_trace = go.Scatter(
                x=misfit_df[x_axis],
                y=misfit_df['misfit'],
                mode='lines',
                line=dict(color='black', width=2),
                name='Misfit',
                yaxis='y2'
            )

            y_dashed = misfit_df['misfit'].copy()
            y_dashed[y_dashed <= 8] = np.nan
            y_dashed[y_dashed > 8] = 7.95

            fig.add_trace(go.Scatter(
                x=misfit_df[x_axis],
                y=y_dashed,
                mode="lines",
                line=dict(color="rgba(0,0,0,0.7)", dash="dash"),
                showlegend=False,
                yaxis='y2'
            ))

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

                # in elevation mode ylim[0] is the bottom; in depth mode depth.max() is the bottom
                if self.settings.y_axis == 'elevation':
                    y_fill = ylim[0] - 50
                else:
                    y_fill = df_layers_long["depth"].max() + 50

                fig.add_trace(
                    go.Scatter(
                        x=np.concatenate([
                            [x_min],
                            doi_df[x_axis].values,
                            [x_max],
                            [x_min]
                        ]),
                        y=np.concatenate([
                            [y_fill],
                            doi_df["doi"].values,
                            [y_fill],
                            [y_fill]
                        ]),
                        fill="toself",
                        fillcolor="rgba(255,255,255,0.6)",
                        line=dict(width=0, shape='hvh' if self.settings.bars else 'linear'),
                        name="Below DOI",
                    )
                )

        site_x = site_positions(df, x_axis)
        self._site_buffer_site_x = site_x
        fig.update_xaxes(range=[x_min, x_max], autorange=False)
        apply_site_buffer(fig, site_x, self.buffer)
        fig.update_yaxes(range=ylim, autorange=False)

        if self.settings.misfit:
            fig.update_layout(yaxis2=dict(range=[0, 8]))

        # the map's mean-res interval, when it's in this section's y units (depth interval or elevation slice)
        if self.mean_res_interval is not None and self.mean_res_interval[0] == self.settings.y_axis:
            _, top, bot = self.mean_res_interval
            fig.add_hrect(
                y0=top, y1=bot,
                fillcolor='rgba(255,255,255,0.25)',
                line_color='rgba(255,255,255,0.8)',
                line_width=1,
                layer='above',
            )
        fig.update_layout(meta={**site_lookup(df, x_axis), 'menus': self.axis_menus()})
        self._site_buffer_static_shapes = site_buffer_static_shapes(fig)
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
            Output(self.id+'_radius', 'disabled'),
            Output(self.id+'_axis_controls', 'style'),
            Output({'type': f'settings-{self.id}', 'key': 'x_axis'}, 'value'),
            Input(self.id+'_axis', 'value'),
            prevent_initial_call=True
        )
        def update_xaxis(x_axis):
            disabled=True
            if x_axis.startswith('line'):
                disabled = False
            self.settings.x_axis=x_axis
            return disabled, self.axis_controls_style(not disabled), x_axis
    
        @app.callback(
            Output({'type': f'settings-{self.id}', 'key': 'radius'}, 'value'),
            Input(self.id+'_radius', 'value'),
            prevent_initial_call=True
        )
        def update_radius(radius):
            self.settings.radius=radius
            return radius

        @app.callback(
            self.output,
            Input('map_mean_res', 'value'),
            Input('map_plot_by', 'value'),
            prevent_initial_call=True
        )
        def update_depth_indicator(mean_res_value, plot_by):
            if plot_by != 'mean-res':
                self.mean_res_interval = None
            else:
                self.mean_res_interval = parse_mean_res(mean_res_value)
            return self.render()


if __name__ == "__main__":

    m1 = ModelSectionSettings('setting_mod')
    m1.x_axis = 'Line 1'
    m1.__post_init__()
    print(m1.x_axis)