from dataclasses import field
from basepanel import *
import temframe

from dash import ctx
import numpy as np
from nosj import nosj
import pandas as pd

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import os
from anemone.inversion import LogResistivity

@nosj
class MultiInversionSettings(PanelSettings):
    line_color: str='#ff0000'

class MultiInversion(Panel):
    misfit = None
    starting_rho = 10.
    log_time_value = None
    dbdt = None
    def __init__(self, dataframe,rho=10., **kwargs):
        self.starting_rho = rho
        self.title = "Spatially Constrained Inversion"
        self.misfit = None
        self.iterations = []
        settings = MultiInversionSettings(id='multi_inv', **kwargs)
        super().__init__(id='multi_inv', settings=settings)
        self.dataframe = dataframe
    def render_init(self):
        COMMON_LAYOUT = dict(
            margin=dict(l=60, r=40, t=90, b=45),
        )
        # self.dataframe = self.dataframe.reset_index(drop=True)
        if self.dataframe is None:
            df = pd.DataFrame({
                "resistivity": [self.starting_rho] * 31,
                "depth": np.cumsum(np.logspace(0, 1.3, 31))
            })
        else:
            df = self.dataframe
        from __main__ import sesh
        fig = make_subplots(rows=1,cols=2,column_widths=[0.45, 0.55],subplot_titles=('Starting Model','Sounding curve'))
        fig.update_layout(uirevision="multi_inv")
        depth = np.cumsum(np.logspace(0, 1.3, 31))
        rho = df['resistivity'][:31] if 'resistivity' in df.columns else [self.starting_rho]*31
        # print(df['resistivity'] if 'resistivity' in df.columns else 0)
        # -------- Left subplot: resistivity vs depth --------
        fig.add_trace(go.Scatter(x=rho,y=depth,mode='lines+markers',line=dict(color=self.settings.line_color),marker=dict(color=self.settings.line_color),hovertemplate='ρ: %{x:.2f} Ω⋅m<br>depth: %{y:.2f} m'),row=1,col=1        )
        # dbdt = sesh.data.dmfwr(rho,depth)
        # time = sesh.data.time
        # Vertical reference line
        fig.add_shape(type='line',x0=self.starting_rho,x1=self.starting_rho,y0=depth.min(),y1=depth.max(),line=dict(color=self.settings.line_color, dash='dash'),row=1,col=1        )

        # for i, row in df.iterrows():
        #     fig.add_shape(
        #         type="line",
        #         x0=row["resistivity"] * 0.9,
        #         x1=row["resistivity"] * 1.1,
        #         y0=row["depth"],
        #         y1=row["depth"],
        #         editable=True,
        #         name=f"layer-{i}",
        #         # dragmode = 'select'
        #     )
        # fig.update_layout(dragmode="select")
        fig.update_xaxes(title_text='Resistivity [Ω⋅m]',type='log',range=[0, 2.7],showline=True,mirror=True,row=1,col=1        )

        fig.update_yaxes(title_text='Depth [m]',range=[180, -0.5],showline=True,mirror=True,row=1,col=1        )

        fig.update_xaxes(title_text='Time [s]',type = 'log',range=[-6,-2.1],showline=True,mirror=True,row=1,col=2        )

        fig.update_yaxes(title_text='dB/dt [V / m²]',type = 'log',range = [-12, -5],showline=True,mirror=True,row=1,col=2        )


        if sesh.data is None:
            fig.add_trace(go.Scatter(x=[1e-6, 1e-2],y=[1e-10, 1e-3],mode="markers",marker=dict(opacity=0),showlegend=False),row=1,col=2            )
        else:
            global_median = sesh.data['dbdt'].median()

            # 2. Median per site
            site_medians = (
                sesh.data
                    .dropna(subset=['dbdt'])
                    .groupby('site_id')['dbdt']
                    .median()
            )
            site_with_median_dbdt = (site_medians - global_median).abs().idxmin()
            df_site = sesh.data[sesh.data['site_id'] == site_with_median_dbdt].dropna(subset=['dbdt'])
            df_lm = df_site[df_site['system_id'] == 0]
            df_hm = df_site[df_site['system_id'] == 1]

            time_lm = df_lm['time'].values
            time_hm = df_hm['time'].values

            d_obs_lm = df_lm['dbdt'].values
            d_obs_hm = df_hm['dbdt'].values

            d_err = sesh.data[sesh.data['site_id']==site_with_median_dbdt].error.dropna().values
            d_obs = sesh.data[sesh.data['site_id']==site_with_median_dbdt].dbdt.dropna().values
            dbdt = sesh.dmfwr(rho,depth).exp()
            dbdt_lm = dbdt[:len(time_lm)]
            dbdt_hm = dbdt[len(time_lm):len(time_lm)+len(time_hm)]
            e = d_err / 100
            e_lm = e[:len(time_lm)]
            e_hm = e[len(time_lm):len(time_lm)+len(time_hm)]
            err_plus_lm  = d_obs_lm * e_lm
            err_minus_lm = d_obs_lm * e_lm / (1 + e_lm)
            err_plus_hm  = d_obs_hm * e_hm
            err_minus_hm = d_obs_hm * e_hm / (1 + e_hm)
            # err_plus  = d_obs * e
            # err_minus = d_obs * e / (1 + e)
            time = sesh.data[sesh.data['site_id']==site_with_median_dbdt].time.dropna().values
            # fig.add_trace(go.Scatter(x=time,y=dbdt,mode="lines",line=dict(color=self.settings.line_color),name="Starting model"), row=1, col=2        )
            # fig.add_trace(go.Scatter(x=time,y=d_obs,mode="markers",name="Observed dB/dt",marker=dict(color="black",size=6,),
            fig.add_trace(
                    go.Scatter(
                        x=time_lm,
                        y=d_obs_lm*8,
                        mode="markers",
                        marker=dict(color="black", size=6),
                        name="Observed LM",
                        error_y=dict(type="data",array=err_plus_lm,arrayminus=err_minus_lm,visible=True,thickness=1,width=0),
                    ),
                    row=1, col=2
                )

            fig.add_trace(
                go.Scatter(
                    x=time_hm,
                    y=d_obs_hm,
                    mode="markers",
                    marker=dict(color="black", size=6),
                    name="Observed HM",
                    error_y=dict(type="data",array=err_plus_hm,arrayminus=err_minus_hm,visible=True,thickness=1,width=0),
                ),
                row=1, col=2
            )

            fig.add_trace(go.Scatter(x=time_lm, y=dbdt_lm*8, mode="lines",
                        line=dict(color="blue"), name="LM model"),row=1, col=2)

            fig.add_trace(go.Scatter(x=time_hm, y=dbdt_hm, mode="lines",line=dict(color="red"), name="HM model"),row=1, col=2)
            vals = np.concatenate([d_obs, dbdt])
            vals = vals[np.isfinite(vals) & (vals > 0)]

            if len(vals) > 0:
                logvals = np.log10(vals)
                ymin = np.floor(logvals.min()) - 1
                ymax = np.ceil(logvals.max()) + 1
            else:
                ymin, ymax = -12, -5

            fig.update_yaxes(
                title_text='dB/dt [V / m²]',
                type='log',
                range=[ymin, ymax],
                showline=True,
                mirror=True,
                row=1,
                col=2
            )
            fig.update_xaxes(title_text='Time [s]',type = 'log',range=[np.log10(time).min()-0.2,np.log10(time).max()+0.2],showline=True,mirror=True,row=1,col=2)
            

        # -------- Axes & layout formatting --------


        fig.update_layout(
            title = self.title,
            showlegend=False,
            modebar=dict(
                remove=['toImage', 'zoom']
            )
        )
        fig.update_layout(
                **COMMON_LAYOUT,
                #title='Select constraints and interact with map',
                showlegend=False
            )
        return fig

    def render(self):
        if not isinstance(self.misfit, list):

            fig = self.render_init()

        elif len(self.misfit) == 0:
            fig = go.Figure()
            fig.update_layout(title=self.title,xaxis_title='Iterations',yaxis_title='Misfit',xaxis_type='linear',yaxis_type='log',yaxis=dict(range=[-1,2]), 
            xaxis=dict(range=[-0.1,3+len(self.misfit)]),showlegend=True)
            fig.update_xaxes(showline=True, mirror=True)
            fig.update_yaxes(showline=True, mirror=True)
        else:
            fig = px.line(
                x=self.iterations,
                y=self.misfit, labels={'x':'Iterations', 'y':'Misfit'},
                markers=True,
                color_discrete_sequence=[self.settings.line_color, self.settings.line_color],

            )

            fig.update_traces(name="Total misfit", showlegend=True)

            fig.update_layout(title=self.title,xaxis_title='Iterations',yaxis_title='Misfit',xaxis_type='linear',yaxis_type='log',yaxis=dict(range=[-1,2]),
            xaxis=dict(range=[-0.1,3+len(self.misfit)]),  showlegend=True            )
            fig.update_xaxes(showline=True, mirror=True)
            fig.update_yaxes(showline=True, mirror=True)
        return fig
    

    def initialize(self):
        init = html.Div([dcc.Store(id="vc-level", data="medium"),dcc.Store(id="hc-level", data="medium"),
            dbc.Container([
                dbc.Row([
                    dbc.Col(
                        dcc.Graph(figure=self.render_init(), id=self.id, mathjax=True, 
                                    config=dict(edits={'shapePosition':True}, displayModeBar=False)),
                            width=10),
                    dbc.Col([dbc.Button("invert all", id='invert_all_button', style={'width':'100%'}),
                            #  html.Div(style={'height':'10px'}),
                            #  dbc.Button("invert selected", id='invert_selected_button', style={'width':'100%'}),
                             html.Div(style={'height':'30px'}), 
                             html.Div(
                            "Vertical constraints", style={"fontWeight": "bold", 'textAlign':'center'}),
                            html.Div(style={'height':'10px'}),
                            dbc.Button("Loose", id='vc_loose_button', color='secondary', outline=True, style={'width':'100%'}),
                            html.Div(style={'height':'10px'}),
                            dbc.Button("Medium",id='vc_medium_button',color='primary',outline=False,style={'width':'100%'}),
                            html.Div(style={'height':'10px'}),
                            dbc.Button("Tight", id='vc_tight_button',color='secondary', outline=True, style={'width':'100%'}),
                            html.Div(style={'height':'30px'}), 
                             html.Div(
                            "Horizontal constraints", style={"fontWeight": "bold", 'textAlign':'center'}),
                            html.Div(style={'height':'10px'}),
                             dbc.Button("Loose", id='hc_loose_button', color='secondary', outline=True, style={'width':'100%'}),
                             html.Div(style={'height':'10px'}),
                             dbc.Button("Medium",id="hc_medium_button",color="primary",outline=False,style={"width": "100%"}),
                             html.Div(style={'height':'10px'}),
                             dbc.Button("Tight", id='hc_tight_button',color='secondary', outline=True, style={'width':'100%'}),
                             html.Div(style={'height':'30px'}),
                             dbc.Button("Starting model", id='reset_inv_model_button', color='secondary', style={'width':'100%'}),
                             html.Div(style={'height':'40px'}),
                             html.Div("Elapsed time: 0:00",id="inv-timer",style={"fontWeight": "bold","whiteSpace":"pre-line"}),] , width=2),
                            dbc.Tooltip('Constraint value of (2.0). Inversion will allow a lot of vertical variation in resistivity', target='vc_loose_button'),
                            dbc.Tooltip('Constraint value of (0.8). Inversion will allow a standard vertical variation in resistivity', target='vc_medium_button'),
                            dbc.Tooltip('Constraint value of (0.2). Inversion will be very smooth vertically and have a higher misfit.', target='vc_tight_button'),
                            dbc.Tooltip('Constraint value of (0.6). Inversion will allow a lot of horizontal variation in resistivity', target='hc_loose_button'),
                            dbc.Tooltip('Constraint value of (0.3). Inversion will allow a standard horizontal variation in resistivity', target='hc_medium_button'),
                            dbc.Tooltip('Constraint value of (0.1). Inversion will be very smooth horizontally and have a higher misfit.', target='hc_tight_button'),
                            dbc.Tooltip('Reset to starting model', target='reset_inv_model_button'),
                            dbc.Tooltip('Inverts all data with spatial constraints, with strengths set below and the starting model selected.', target='invert_all_button'),
                ], style={'height':'100%'})], style={'height':'95%', 'padding':'25px'}),
                # html.Div(
                #             "Elapsed time: 0:00",
                #             id="inv-timer",
                #             style={"fontWeight": "bold"}
                #         ),
                 gear_maker(self.id)], style={'height': '100%', 'overflow': 'hidden'},
                  )
        return init                   
    
    def add_callbacks(self, app):
        super().add_callbacks(app)

        @app.callback(
            Output(self.id, 'figure', allow_duplicate=True),
            Output("inv-timer", "children"),
            Input('inv-log-poll', 'n_intervals'),
            prevent_initial_call=True
        )

        def update_misfit(n_intervals):
            log_time_value = None
            elapsed_seconds = n_intervals
            minutes, seconds = divmod(elapsed_seconds, 60)
            timer_text = f"Elapsed time: {int(minutes)}:{int(seconds):02d}"
            self.iterations = []
            self.misfit = []
            from __main__ import sesh

            for line in getattr(sesh, "inv_status", ()):
                if not line.strip():
                    continue  # skip empty lines

                parts = line.split()

                # Iteration number is the first token
                if not parts[0].isdigit():
                    continue  # skip lines that don't start with an iteration number
                iteration = int(parts[0])

                # Find "Total misfit:" and take the number after it
                total_misfit_index = parts.index("Total") + 2
                total_misfit = float(parts[total_misfit_index])

                self.iterations.append(iteration)
                self.misfit.append(total_misfit)

                if "Last" in parts:
                    last_index = parts.index("Last")
                    target_index = last_index + 3
                    if target_index < len(parts):
                        log_time_value = parts[target_index]

            timer_text = f"Elapsed time: {int(minutes)}:{int(seconds):02d}"
            if log_time_value is not None:
                timer_text += f"\nLast iteration: {log_time_value} s"
            return self.render(), timer_text
        @app.callback(
            Output("starting_model", "figure"),
            Input("starting-model", "data"),
        )
        def sync_starting_model(data):
            df = pd.DataFrame({
                "resistivity": [data["rho"]] * len(data["depth"]),
                "depth": data["depth"]
            })
            self.dataframe = df
            return self.render()
        
        @app.callback(
            Output("multi_inv", "figure", allow_duplicate=True),
            Input("reset_inv_model_button", "n_clicks"),
            prevent_initial_call=True
        )
        def reset_inv_model(n_clicks):
            self.starting_rho = 10
            return self.render_init()

        @app.callback(
            Output("multi_inv", "figure", allow_duplicate=True),
            Input("invert_layout", "n_clicks"),
            State("invert_all_button", "disabled"),
            prevent_initial_call=True
        )
        def reset_stale_progress(_, inversion_running):
            if inversion_running or self.misfit != []:
                raise PreventUpdate
            self.misfit = None
            self.iterations = []
            self.title = "Spatially Constrained Inversion"
            return self.render_init()


        
        @app.callback(
                [Output('review_layout', 'disabled', allow_duplicate=True),
                Output('interpret_layout', 'disabled', allow_duplicate=True),
                Output("multi_inv", "figure", allow_duplicate=True),
                Output("review_layout","color", allow_duplicate=True),
                Output("map_plot_by",'value', allow_duplicate=True),
                Output("model_graph", "figure", allow_duplicate=True),
                Output("model_section", "figure", allow_duplicate=True)],
            Input('invert_all_button', 'n_clicks'),
            State('review_layout', 'n_clicks'),  # Add this state to get current value
            State("vc-level", "data"),
            State("hc-level", "data"),
            State("starting-model", "data"),
            running=[(Output("invert_all_button", "disabled"), True, False),
            (Output("invert_selected_button", "disabled"), True, False), 
            (Output("inv-log-poll", "disabled"), False, True),    
            (Output("vc_loose_button", "disabled"), True, False),
            (Output("vc_medium_button", "disabled"), True, False),
            (Output("vc_tight_button", "disabled"), True, False),
            (Output("hc_loose_button", "disabled"), True, False),
            (Output("hc_medium_button", "disabled"), True, False),
            (Output("hc_tight_button", "disabled"), True, False),
            (Output('reset_inv_model_button', "disabled"), True, False)],
            prevent_initial_call=True
        )
        def launch_inversion(n_clicks, current_review_clicks, vc_level,hc_level,starting_model):
            from __main__ import sesh
            if n_clicks:
                self.misfit = []
                self.iterations = []
                self.title = "Inversion in progress"
                from torch import from_numpy, tensor
                print('starting model:', starting_model["rho"])
                rho = tensor(starting_model["rho"]).repeat(len(starting_model["depth"]))
                # z   = tensor(starting_model["depth"][:-1])
                depth = self.build_depth_from_loop(time=sesh.data.time.unique()[-1])
                # rho = tensor(starting_model["rho"]).repeat(len(depth))
                z   = tensor(depth[:-1])

                if vc_level == "loose":
                    Vert = 2.0
                elif vc_level == "medium":
                    Vert = 0.8
                elif vc_level == "tight":
                    Vert = 0.2

                if hc_level == "loose":
                    Horz = 0.6
                elif hc_level == "medium":
                    Horz = 0.3
                elif hc_level == "tight":
                    Horz = 0.1
                res_start                        = LogResistivity.smooth(rho,z) 
                sesh.models, sesh.data, _ = temframe.invert(sesh.data, sesh.dmfwr, res_start,vc = Vert, hc = Horz)
                sesh.update_site_table()
                self.map_panel.dataframe = sesh.site.copy()
                self.model_graph.dataframe = sesh.models.copy()
                self.model_section.dataframe = sesh.models.copy()
                self.title = "Inversion Finished"
                new_review_clicks = (current_review_clicks or 0) + 1
                return (False, False, self.render(), "success", "misfit",
                        self.model_graph.render(), self.model_section.render())
            raise PreventUpdate
        
        @app.callback(
            Output("vc-level", "data"),
            Output("vc_loose_button",  "color"),
            Output("vc_medium_button","color"),
            Output("vc_tight_button", "color"),
            Output("vc_loose_button",  "outline"),
            Output("vc_medium_button","outline"),
            Output("vc_tight_button", "outline"),
            Input("vc_loose_button", "n_clicks"),
            Input("vc_medium_button", "n_clicks"),
            Input("vc_tight_button", "n_clicks"),
            State("vc-level", "data"),
            prevent_initial_call=True
        )
        def select_vc_constraint(loose, medium, tight, current):
            if not ctx.triggered:
                raise PreventUpdate

            trigger = ctx.triggered[0]["prop_id"].split(".")[0]

            if trigger == "vc_loose_button":
                selected = "loose"
            elif trigger == "vc_medium_button":
                selected = "medium"
            elif trigger == "vc_tight_button":
                selected = "tight"
            else:
                selected = current

            def style(name):
                selected_flag = (selected == name)
                return (
                    "primary" if selected_flag else "secondary",
                    not selected_flag   # outline=True if NOT selected
                )

            loose_color, loose_outline = style("loose")
            med_color,   med_outline   = style("medium")
            tight_color, tight_outline = style("tight")

            return (
                selected,
                loose_color, med_color, tight_color,
                loose_outline, med_outline, tight_outline
            )
        @app.callback(
            Output("hc-level", "data"),
            Output("hc_loose_button", "color"),
            Output("hc_medium_button", "color"),
            Output("hc_tight_button", "color"),
            Output("hc_loose_button", "outline"),
            Output("hc_medium_button", "outline"),
            Output("hc_tight_button", "outline"),
            Input("hc_loose_button", "n_clicks"),
            Input("hc_medium_button", "n_clicks"),
            Input("hc_tight_button", "n_clicks"),
            State("hc-level", "data"),
            prevent_initial_call=True
        )
        def select_hc_constraint(loose, medium, tight, current):
            if not ctx.triggered:
                raise PreventUpdate

            trigger = ctx.triggered[0]["prop_id"].split(".")[0]

            if trigger == "hc_loose_button":
                selected = "loose"
            elif trigger == "hc_medium_button":
                selected = "medium"
            elif trigger == "hc_tight_button":
                selected = "tight"
            else:
                selected = current

            def style(name):
                is_selected = (selected == name)
                return (
                    "primary" if is_selected else "secondary",  # color
                    not is_selected                              # outline
                )

            loose_color, loose_outline   = style("loose")
            med_color, med_outline       = style("medium")
            tight_color, tight_outline  = style("tight")

            return (
                selected,
                loose_color, med_color, tight_color,
                loose_outline, med_outline, tight_outline
            )
        
        @app.callback(
            Output(self.id, 'figure', allow_duplicate=True),
            Input(self.id, 'relayoutData'),
            prevent_initial_call=True
        )
        def update_starting_model(relayoutData):
            if relayoutData is None:
                raise PreventUpdate

            # Ignore zoom / pan events
            if any(k.startswith("xaxis.range") or k.startswith("yaxis.range") for k in relayoutData):
                raise PreventUpdate

            # Only update when the starting-model line moves
            if "shapes[0].x0" not in relayoutData:
                raise PreventUpdate

            self.starting_rho = float(relayoutData["shapes[0].x0"])
            self.dataframe['resistivity'] = self.starting_rho
            return self.render()
        


    @classmethod
    def standard(cls, misfit=None, rho=10.):
        return cls(data=misfit, rho=rho)
    def build_depth_from_loop(self, time, n_layers=31):
        import numpy as np

        if time <0.005:
            depth = np.cumsum(np.logspace(0, 1.3, 31)).tolist()
        elif time >0.005:
            depth = np.cumsum(np.logspace(0, 1.8, 31)).tolist()
        return depth

@nosj
class SinglesiteSettings(PanelSettings):
    line_color: str='#ff0000'
    lm_factor: int = 8

class Single_site(Panel):
    curves = None
    def __init__(self, dataframe,rho=10., **kwargs):
        self.starting_rho = rho
        settings = SinglesiteSettings(id='inv-single', **kwargs)
        super().__init__(id='inv-single', settings=settings)
        self.dataframe = dataframe

    def render(self):
        COMMON_LAYOUT = dict(
            margin=dict(l=60, r=40, t=90, b=45),
        )
        if self.curves is None:
            from __main__ import sesh
            df = pd.DataFrame({
                'resistivity': [self.starting_rho] * 31,
                'depth': np.cumsum(np.logspace(0, 1.3, 31))
            })
            depth = df['depth'].values# if 'depth' in df.columns else np.cumsum(np.logspace(0, 1.3, 31))
            rho = df['resistivity'][:31] if 'resistivity' in df.columns else [self.starting_rho]*31
            

            fig = make_subplots(
                rows=1,
                cols=2,
                column_widths=[0.45, 0.55],
                subplot_titles=(
                    "Starting Model",
                    "Sounding curve"
                )
            )

            # ---- Resistivity model (left subplot) ----
            fig.add_trace(
                go.Scatter(
                    x=df['resistivity'],
                    y=df['depth'],
                    mode='lines+markers',
                    line=dict(color=self.settings.line_color),
                    marker=dict(color=self.settings.line_color),
                    hovertemplate="Resistivity: %{x:.2f} Ω⋅m<br>Depth: %{y:.2f} m<extra></extra>",
                    name="Starting model"
                ),
                row=1,
                col=1
            )
            fig.add_shape(type='line', x0=self.starting_rho, x1=self.starting_rho,
                y0=df['depth'].min(), y1=df['depth'].max(),
                xref='x1', yref='y1',
                line=dict(color=self.settings.line_color, dash='dash'),
                editable=True)

            fig.update_xaxes(title_text='Resistivity [Ω⋅m]',type='log',range=[0, 2.7],row=1,col=1,showline=True,mirror=True           )

            fig.update_yaxes(
                title_text='Depth [m]',
                range=[180, -0.5],  # depth increasing downward
                row=1,
                col=1,
                showline=True,
                mirror=True,
            )

            fig.update_xaxes(title_text='Time [s]',type = 'log',range=[-6,-2.1],showline=True,mirror=True,row=1,col=2        )
            fig.update_yaxes(title_text='dB/dt [V / m²]',type = 'log',range = [-12, -5],showline=True,mirror=True,row=1,col=2        )

            fig.add_trace(go.Scatter(x=[1e-6, 1e-2],y=[1e-10, 1e-3],mode="markers",marker=dict(opacity=0),showlegend=False),row=1,col=2            )
            fig.update_layout(
                **COMMON_LAYOUT,
                # title='Select constraints and interact with map',
                uirevision="single_site",
                showlegend=False
            )
            if sesh.data is None:
                fig.add_trace(go.Scatter(x=[1e-6, 1e-2],y=[1e-10, 1e-3],mode="markers",marker=dict(opacity=0),showlegend=False),row=1,col=2            )
            else:
                global_median = sesh.data['dbdt'].median()

                # 2. Median per site
                site_medians = (
                    sesh.data
                        .dropna(subset=['dbdt'])
                        .groupby('site_id')['dbdt']
                        .median()
                )
                site_with_median_dbdt = (site_medians - global_median).abs().idxmin()
                df_site = sesh.data[sesh.data['site_id'] == site_with_median_dbdt].dropna(subset=['dbdt'])

                df_lm = df_site[df_site['system_id'] == 0]
                df_hm = df_site[df_site['system_id'] == 1]

                time_lm = df_lm['time'].values
                time_hm = df_hm['time'].values

                d_obs_lm = df_lm['dbdt'].values
                d_obs_hm = df_hm['dbdt'].values

                d_err = sesh.data[sesh.data['site_id']==site_with_median_dbdt].error.dropna().values
                d_obs = sesh.data[sesh.data['site_id']==site_with_median_dbdt].dbdt.dropna().values
                dbdt = sesh.dmfwr(rho,depth).exp()
                dbdt_lm = dbdt[:len(time_lm)]
                dbdt_hm = dbdt[len(time_lm):len(time_lm)+len(time_hm)]
                e = d_err / 100
                e_lm = e[:len(time_lm)]
                e_hm = e[len(time_lm):len(time_lm)+len(time_hm)]
                err_plus_lm  = d_obs_lm * e_lm
                err_minus_lm = d_obs_lm * e_lm / (1 + e_lm)
                err_plus_hm  = d_obs_hm * e_hm
                err_minus_hm = d_obs_hm * e_hm / (1 + e_hm)
                # err_plus  = d_obs * e
                # err_minus = d_obs * e / (1 + e)
                time = sesh.data[sesh.data['site_id']==site_with_median_dbdt].time.dropna().values
                # fig.add_trace(go.Scatter(x=time,y=dbdt,mode="lines",line=dict(color=self.settings.line_color),name="Starting model"), row=1, col=2        )
                # fig.add_trace(go.Scatter(x=time,y=d_obs,mode="markers",name="Observed dB/dt",marker=dict(color="black",size=6,),
                fig.add_trace(
                        go.Scatter(
                            x=time_lm,
                            y=d_obs_lm*self.settings.lm_factor,
                            mode="markers",
                            marker=dict(color="black", size=6),
                            name="Observed LM",
                            error_y=dict(type="data",array=err_plus_lm,arrayminus=err_minus_lm,visible=True,thickness=1,width=0),
                        ),
                        row=1, col=2
                    )

                fig.add_trace(
                    go.Scatter(
                        x=time_hm,
                        y=d_obs_hm,
                        mode="markers",
                        marker=dict(color="black", size=6),
                        name="Observed HM",
                        error_y=dict(type="data",array=err_plus_hm,arrayminus=err_minus_hm,visible=True,thickness=1,width=0),
                    ),
                    row=1, col=2
                )

                fig.add_trace(go.Scatter(x=time_lm, y=dbdt_lm*self.settings.lm_factor, mode="lines",
                            line=dict(color="blue"), name="LM model"),row=1, col=2)

                fig.add_trace(go.Scatter(x=time_hm, y=dbdt_hm, mode="lines",line=dict(color="red"), name="HM model"),row=1, col=2)
                # error_y=dict(type="data",array=err_plus,arrayminus=err_minus,visible=True,thickness=1,width=0),),row=1,col=2)
                vals = np.concatenate([d_obs, dbdt])
                vals = vals[np.isfinite(vals) & (vals > 0)]

                if len(vals) > 0:
                    logvals = np.log10(vals)
                    ymin = np.floor(logvals.min()) - 1
                    ymax = np.ceil(logvals.max()) + 1
                else:
                    ymin, ymax = -12, -5

                fig.update_yaxes(
                    title_text='dB/dt [V / m²]',
                    type='log',
                    range=[ymin, ymax],
                    showline=True,
                    mirror=True,
                    row=1,
                    col=2
                )
                fig.update_xaxes(title_text='Time [s]',type = 'log',range=[np.log10(time).min()-0.2,np.log10(time).max()+0.2],showline=True,mirror=True,row=1,col=2        )
            return fig

        
        VC_COLORS = {
        "loose":  "#2D81FF",
        "medium": "#00A676",
        "tight":  "#E63946",
        }

        fig = make_subplots(rows=1,cols=2,column_widths=[0.45, 0.55],subplot_titles=(    "Resistivity Model",    "Sounding curve")        )
        curves = self.curves
        include = curves[0][9]   # include mask (same for all curves)
        time    = curves[0][7]
        dbdt_obs = curves[0][5]
        error    = curves[0][8]

        opacity = np.where(include, 1.0, 0.2)
        time_inc = time[include]
        dt = np.diff(time_inc)

        idx = np.where(dt<0)[0][0]+1
        time_lm = time_inc[:idx]
        time_hm = time_inc[idx:]

        inc = include

        y_lm = dbdt_obs[:idx][inc[:idx]]*self.settings.lm_factor
        y_hm = dbdt_obs[idx:][inc[idx:]]
        # y = dbdt_obs[inc]

        e_lm = error[:idx][inc[:idx]] / 100
        e_hm = error[idx:][inc[idx:]] / 100
        # e = error[inc] / 100

        # err_plus  = y * e
        # err_minus = y * e / (1 + e)

        err_plus_lm  = y_lm * e_lm
        err_minus_lm = y_lm * e_lm / (1 + e_lm)
        err_plus_hm  = y_hm * e_hm
        err_minus_hm = y_hm * e_hm / (1 + e_hm)

        fig.add_trace(
            go.Scatter(
                x=time_lm,
                y=y_lm,
                mode="markers",
                name="Observed LM",
                marker=dict(color="black", size=6),
                error_y=dict(type="data",array=err_plus_lm,arrayminus=err_minus_lm,visible=True,thickness=1,width=0),
            ),
            row=1, col=2
        )
        fig.add_trace(
            go.Scatter(
                x=time_hm,
                y=y_hm,
                mode="markers",
                name="Observed HM",
                marker=dict(color="black", size=6),
                error_y=dict(type="data",array=err_plus_hm,arrayminus=err_minus_hm,visible=True,thickness=1,width=0),
            ),
            row=1, col=2
        )
        # fig.add_trace(go.Scatter(x=time[inc],y=y,mode="markers",name="Observed dB/dt",marker=dict(color="black",size=6,),
        # error_y=dict(type="data",array=err_plus,arrayminus=err_minus,visible=True,thickness=1,width=0),),row=1,col=2)
        
        exc = ~include
        # Excluded data (split the same way)
        fig.add_trace(
            go.Scatter(
                x=time[:idx][exc[:idx]],
                y=dbdt_obs[:idx][exc[:idx]]*self.settings.lm_factor,
                mode="markers",
                showlegend=False,
                marker=dict(color="black", size=6, opacity=0.2),
            ),
            row=1, col=2
        )

        fig.add_trace(
            go.Scatter(
                x=time[idx:][exc[idx:]],
                y=dbdt_obs[idx:][exc[idx:]],
                mode="markers",
                showlegend=False,
                marker=dict(color="black", size=6, opacity=0.2),
            ),
            row=1, col=2
        )
        # fig.add_trace(go.Scatter(x=time[exc],y=dbdt_obs[exc],mode="markers",showlegend=False,marker=dict(color="black",size=6,opacity=0.2,),),row=1,col=2,        )

        for (vc,rho,depth,misfit,df_layers,dbdt_obs,dbdt_syn,time,error,include, doi) in curves:
            rho = np.insert(np.array(rho),0,rho[0])
            depth = np.insert(np.array(depth),0,0)
            color = VC_COLORS.get(vc, "black")
            dbdt_syn_lm = dbdt_syn[:len(time_lm)]*self.settings.lm_factor
            dbdt_syn_hm = dbdt_syn[len(time_lm):len(time_lm)+len(time_hm)]

            fig.add_trace(
                go.Scatter(
                    x=rho,
                    y=depth,
                    mode="lines",
                    line=dict(color=color, width=3),
                    line_shape="hv",
                    name=f"{vc.capitalize()} (misfit = {misfit:.2f})",
                    legendgroup=vc,
                ),
                row=1,
                col=1
            )
            fig.add_trace(go.Scatter(x=time_lm,y=dbdt_syn_lm,mode="lines",line=dict(color=color),name=f"{vc} LM",legendgroup=vc,showlegend=False), row=1, col=2 )
            fig.add_trace(go.Scatter(x=time_hm,y=dbdt_syn_hm,mode="lines",line=dict(color=color),name=f"{vc} HM",legendgroup=vc,showlegend=False), row=1, col=2 )
            # fig.add_trace(go.Scatter(x=time,y=dbdt_syn,mode="lines",line=dict(color=color),name=f"{vc} syn",legendgroup=vc,showlegend=False), row=1, col=2 )
        
        fig.add_trace(go.Scatter(x=[0.1,1000],y=[doi[0],doi[0]],mode="lines",line=dict(color="black",width=2,dash="dash"),showlegend=False),row=1,col=1)

        fig.update_yaxes(range=[doi[0]+30, -0.5],title_text="Depth [m]",row=1,col=1,showline=True,mirror=True,linewidth=1,linecolor='black')

        fig.update_xaxes(type="log",range=[0,2.7],title_text="Resistivity [Ωm]",row=1,col=1,showline=True,mirror=True,linewidth=1,linecolor='black')

        fig.update_xaxes(title_text='Time [s]',type = 'log',range=[np.log10(time).min()-0.2,np.log10(time).max()+0.2],showline=True,mirror=True,row=1,col=2)

        fig.update_yaxes(title_text='dB/dt [V / m²]',type = 'log',range = [np.log10(dbdt_obs).min()-1, np.log10(dbdt_obs).max()+1],showline=True,mirror=True,row=1,col=2)

        # ---- LAYOUT ----
        fig.update_layout(
            **COMMON_LAYOUT,
            legend=dict(
                #title="Vertical constraint",
                orientation="h",
                yanchor="bottom",
                y=1.05,
                xanchor="center",
                x=0.5,
            ),
            modebar=dict(remove=['toImage', 'zoom', 'zoomIn', 'zoomOut', 'pan', 'select']),
        )

        return fig
    

    def initialize(self):
        init = html.Div([dbc.Container([dcc.Store(id="vc-single-levels", data=["medium"]),
                dbc.Row([
                    dbc.Col([html.Div("Select constraints and interact with map",id="single-inv-status",style={"fontWeight": "bold", "textAlign": "center", "fontSize": "20px"}),
                        dcc.Graph(figure=self.render(),id=self.id,mathjax=True,config=dict(edits={'shapePosition':True}, displayModeBar=False, responsive=True),style={"height": "100%","width": "100%"}),],
                            width=10),
                    dbc.Col([html.Div(
                            "Vertical constraints", style={"fontWeight": "bold", 'textAlign':'center'}),
                            html.Div(style={'height':'10px'}),
                             dbc.Button("Loose", id='vc_sing_loose_button', color='secondary', outline=True, style={'width':'100%'}),
                             html.Div(style={'height':'10px'}),
                             dbc.Button("Medium",id="vc_sing_medium_button",color="primary",outline=False,style={"width": "100%"}),
                             html.Div(style={'height':'10px'}),
                             dbc.Button("Tight", id='vc_sing_tight_button',color='secondary', outline=True, style={'width':'100%'}),
                             html.Div(style={'height':'30px'}), 
                             html.Div(style={'height':'10px'}),
                             dbc.Button("Invert single site", id='invert-single', color='primary', style={'width':'100%'}),
                             html.Div(style={'height':'10px'}),
                             dbc.Button("Starting model",id="reset_single_model_button",color="secondary",style={"width": "100%"}),
                             ], width=2),
                             dbc.Tooltip('Constraint value of (2.0). Inversion will allow a lot of variation in resistivity', target='vc_sing_loose_button'),
                             dbc.Tooltip('Constraint value of (0.8). Inversion will allow a standard variation in resistivity', target='vc_sing_medium_button'),
                             dbc.Tooltip('Constraint value of (0.2). Inversion will be very smooth and have a higher misfit.', target='vc_sing_tight_button'),
                             dbc.Tooltip('Inverts the currently selected site on the map with the starting model and constraints selected.', target='invert-single'),
                             dbc.Tooltip('Reset to starting model', target='reset_single_model_button'),
                ], style={'height':'100%'})], style={'height':'95%', 'padding':'25px'}),
                 gear_maker(self.id)], style={'height': '100%', 'overflow': 'hidden'},
                  )
        return init
    
    def add_callbacks(self, app):
        super().add_callbacks(app)
        
        @app.callback(
            Output("starting_model_Sing", "figure"),
            Input("starting-model", "data"),
        )
        def sync_starting_model(data):
            df = pd.DataFrame({
                "resistivity": [data["rho"]] * len(data["depth"]),
                "depth": data["depth"]
            })
            self.dataframe = df
            return self.render()

        @app.callback(
            Output("inv-single", "figure", allow_duplicate=True),
            Input("reset_single_model_button", "n_clicks"),
            prevent_initial_call=True
        )
        def reset_inv_model(n_clicks):
            self.curves = None
            return self.render()

        @app.callback(
            Output("vc-single-levels", "data"),
            Output("vc_sing_loose_button", "color"),
            Output("vc_sing_medium_button", "color"), 
            Output("vc_sing_tight_button", "color"),
            Output("vc_sing_loose_button",  "outline"),
            Output("vc_sing_medium_button","outline"),
            Output("vc_sing_tight_button", "outline"),
            Input("vc_sing_loose_button", "n_clicks"),
            Input("vc_sing_medium_button", "n_clicks"),
            Input("vc_sing_tight_button", "n_clicks"),
            State("vc-single-levels", "data"),
            prevent_initial_call=True
        )
        def toggle_single_site_vc(loose, medium, tight, active):
            if not ctx.triggered:
                raise PreventUpdate

            button = ctx.triggered_id.replace("vc_sing_", "").replace("_button", "")

            if button in active:
                active.remove(button)
            else:
                active.append(button)

            def style(name):
                is_active = name in active
                return (
                    "primary" if is_active else "secondary",  # color
                    not is_active                              # outline
                )

            loose_color,  loose_outline  = style("loose")
            med_color,    med_outline    = style("medium")
            tight_color,  tight_outline  = style("tight")

            return (
                active,
                loose_color, med_color, tight_color,
                loose_outline, med_outline, tight_outline
            )
        @app.callback(
            Output("inv-single", "figure", allow_duplicate=True),
            Input("invert-single", "n_clicks"),
            State("vc-single-levels", "data"),
            State("starting-model", "data"),
            State("invert_layout", "color"),
            running=[(Output("vc_sing_loose_button", "disabled"), True, False),
            (Output("vc_sing_medium_button", "disabled"), True, False), 
            (Output("vc_sing_tight_button", "disabled"), True, False),
            (Output('reset_single_model_button', "disabled"), True, False),
            (Output('invert-single','disabled'),True,False),
            (Output("single-inv-status", "children"), "Inversion running", "Select constraints and choose site on map      ")],
            prevent_initial_call=True
        )
        def invert_single_site(n_clicks, vc_levels, starting_model, layout):
            # if not click_data or 'points' not in click_data or not layout=='primary':
            #     raise PreventUpdate

            from __main__ import sesh,m1
            from torch import tensor
            if m1.highlighted is None:
                raise PreventUpdate
            else:
                site_id = m1.highlighted

            # if trigger == "map" and click_data and "points" in click_data:
            #     site_id = sesh.data['site_id'].iloc[click_data['points'][0]['pointNumber']]
            # else:
            #     raise PreventUpdate
            if site_id is None or sesh.data[sesh.data['site_id'] == site_id].empty:
                raise PreventUpdate
            self.curves = []
            print('starting model:', starting_model["rho"])
            rho = tensor(starting_model["rho"]).repeat(len(starting_model["depth"]))
            depth = self.build_depth_from_loop(time=sesh.data.time.unique()[-1])
            z   = tensor(depth[:-1])

            for vc in vc_levels:
                
                Vert = {"loose": 2.0, "medium": 0.8, "tight": 0.2}[vc]
                res_start = LogResistivity.smooth(rho, z)
                df_layers, df_site, _ = temframe.invert_site(sesh.data, sesh.dmfwr, site_id=site_id, res_start=res_start, vc=Vert)
                self.curves.append((vc, df_layers['resistivity'].values, df_layers['bottom_depth'].values,df_layers['misfit'].values[-1],df_layers, df_site['dbdt'].values, df_site['dbdt_syn'].values, df_site['time'].values, df_site['error'].values,df_site['include'].values, df_layers['doi'].values))

            return self.render()
        
        @app.callback(
            Output(self.id, 'figure', allow_duplicate=True),
            Input(self.id, 'relayoutData'),
            prevent_initial_call=True
        )
        def update_starting_model(relayoutData):
            if relayoutData is None:
                raise PreventUpdate

            # Ignore zoom / pan events
            if any(k.startswith("xaxis.range") or k.startswith("yaxis.range") for k in relayoutData):
                raise PreventUpdate

            # Only update when the starting-model line moves
            if "shapes[0].x0" not in relayoutData:
                raise PreventUpdate

            self.starting_rho = float(relayoutData.get('shapes[0].x0', self.starting_rho))
            self.dataframe['resistivity'] = self.starting_rho
            return self.render()
        


    @classmethod
    def standard(cls, misfit=None, rho=10.):
        return cls(data=misfit, rho=rho)#cls(data=df)

    def build_depth_from_loop(self, time, n_layers=31):
        import numpy as np
        if time <0.005:
            depth = np.cumsum(np.logspace(0, 1.3, 31)).tolist()
        elif time >0.005:
            depth = np.cumsum(np.logspace(0, 1.8, 31)).tolist()
        return depth