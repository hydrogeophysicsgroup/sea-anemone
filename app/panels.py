from dataclasses import field
from basepanel import *
from map import Map, MapSettings
from inversion_panels import MultiInversion, MultiInversionSettings, Single_site, SinglesiteSettings
from model import ModelGraph, ModelGraphSettings, ModelSection, ModelSectionSettings

from dash import dash_table, ctx, no_update
from temframe import include_mask
import plotly.io as pio

import numpy as np
import os
import re

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


@nosj
class dbdtSoundingSettings(PanelSettings):
    lm_color: str = '#2D81FF'
    hm_color: str = '#ff0000'
    lm_factor: float = 20.0
    hm_factor: float = 1.0
    plot_error: bool = False
    x_axis: Literal['time', 'gate_id'] = 'time'  # or 'site_id', 'longitude', 'latitude'
    dbdt_max: float = -3
    dbdt_min: float = -12

class dbdtSounding(Panel):
    def add_axis_menus(self, fig):
        fig.update_layout(xaxis_title=self.settings.x_axis+' ▾',
                          meta={'menus': {'x': axis_menu({'type': f'settings-{self.id}', 'key': 'x_axis'}, ['time', 'gate_id'], self.settings.x_axis)}})

    dataframe = None


    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', dbdtSoundingSettings(id='sounding'))
        super().__init__(id='sounding', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)
        
        # if self.dataframe is not None:
        #     self.settings.dbdt_min = np.abs(self.dataframe['dbdt'].values).min()
        #     self.settings.dbdt_max = np.abs(self.dataframe['dbdt'].values).max()

    def compare_synthetic(self):

        y_axis                                             = 'dbdt_syn'

        df_tmp                                             = self.dataframe.sort_values(['site_id', 'system_id',  self.settings.x_axis])
        df_tmp['include'] = include_mask(df_tmp)
        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt_syn']  *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt_syn']  *= hm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt']      *= hm_factor
        df_tmp.loc[df_tmp['site_id'] == -1, 'include']  = False
        df_tmp.loc[df_tmp['dbdt']<=0, 'dbdt'] = np.nan

        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        error_ub,error_lb = 'error_ub', 'error_lb'
        # if True:
        #     error_ub = None
        #     error_lb = None
        # title = "Sounding curve"
        # if df_tmp['site_id'].nunique()==1:
        #     title += f" site {df_tmp['site_id'].iloc[0]}"
        fig = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='dbdt',
            color_discrete_sequence=["gray", "gray"],
            color="system_id",
            # title=title,
            custom_data=["system_id", "data_id", "site_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
            # range_y=[self.settings.dbdt_min, self.settings.dbdt_max]

        )

        df_tmp.loc[df_tmp['site_id'] == -1, 'include'] = True
        df_tmp.loc[(~df_tmp['include']), 'dbdt']       = np.nan
        df_tmp.loc[(~df_tmp['include']), 'dbdt_syn']   = np.nan


        
        fig3 = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='dbdt',
            color_discrete_sequence=["black", "black"],
            color="system_id",
            # title="dbdt vs time by site_id",
            # custom_data=["system_id", "data_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
            # range_y=[self.settings.dbdt_min, self.settings.dbdt_max]

        )

        fig2 = px.line(
            df_tmp,
            x=self.settings.x_axis,
            y='dbdt_syn',
            color="system_id",
            line_group="site_id",
            color_discrete_sequence=[self.settings.lm_color, self.settings.hm_color],
            # title="dbdt vs time by site_id",
            custom_data=["system_id", "data_id", "site_id"],
            # range_y=[self.settings.dbdt_min, self.settings.dbdt_max]

        )
        fig2.update_traces(line_width=2)


        for trace in fig3.data:
            fig.add_trace(trace)

        for trace in fig2.data:
            fig.add_trace(trace)

        # fig.update_layout(yaxis_range=[self.settings.dbdt_min, self.settings.dbdt_max])


        return fig    

    def observed_only(self):

        y_axis                                             = 'dbdt_syn'
        df_tmp                                             = self.dataframe.sort_values(['site_id', 'system_id',  self.settings.x_axis])
        df_tmp['include'] = include_mask(df_tmp)
        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt']      *= hm_factor
        df_tmp.loc[df_tmp['site_id'] == -1, 'include']  = False

        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        error_ub,error_lb = 'error_ub', 'error_lb'
        # if True:
        #     error_ub = None
        #     error_lb = None
        # title = "Sounding curve"
        # if df_tmp['site_id'].nunique()==1:
        #     title += f" site {df_tmp['site_id'].iloc[0]}"
        fig = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='dbdt',
            color_discrete_sequence=["gray", "gray"],
            color="system_id",
            # title=title,
            custom_data=["system_id", "data_id", "site_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
            range_y=[self.settings.dbdt_min, self.settings.dbdt_max]
        )

        df_tmp.loc[df_tmp['site_id'] == -1, 'include'] = True
        df_tmp.loc[(~df_tmp['include']), 'dbdt'] = np.nan


        
        fig2 = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='dbdt',
            color_discrete_sequence=["black", "black"],
            color="system_id",
            # title="dbdt vs time by site_id",
            # custom_data=["system_id", "data_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
            range_y=[self.settings.dbdt_min, self.settings.dbdt_max]
        )

        fig3 = px.line(
            df_tmp,
            x=self.settings.x_axis,
            y='dbdt',
            color="system_id",
            color_discrete_sequence=[self.settings.lm_color, self.settings.hm_color],
            # title="dbdt vs time by site_id",
            custom_data=["system_id", "data_id", "site_id"],
            range_y=[self.settings.dbdt_min, self.settings.dbdt_max]
        )
        fig3.update_traces(line_width=2)
        for trace in fig2.data:
            fig.add_trace(trace)

        for trace in fig3.data:
            fig.add_trace(trace)



        return fig     

    def render(self):
        if self.dataframe is None: return self.empty_render()


        if 'dbdt_syn' in self.dataframe.columns:
            fig = self.compare_synthetic()
        else:
            fig = self.observed_only()
        
        vals = np.abs(self.dataframe["dbdt"].values)
        vals = vals[np.isfinite(vals) & (vals > 0)]

        if len(vals) > 0:
            logvals = np.log10(vals)
            ymin = np.floor(logvals.min()) - 0.2
            ymax = np.ceil(logvals.max()) + 0.2 + np.log10(self.settings.lm_factor)
        else:
            ymin, ymax = -12, -3
        self.settings.dbdt_min = ymin
        self.settings.dbdt_max = ymax
        fig.update_layout(
            yaxis_type="log",
            yaxis_range=[self.settings.dbdt_min, self.settings.dbdt_max],
            xaxis_type="log" if self.settings.x_axis == 'time' else "linear",
            xaxis_title=self.settings.x_axis,
            # yaxis_title="$\\frac{dB}{dt}$ \\[V / m$^2$\\]",
            yaxis_title = 'dB/dt [V / m²]',
            margin={"l": 50, "r": 50, "t": 10, "b": 50},
            dragmode='select',
            xaxis=dict(
            showline=True,
            mirror=True,
            linewidth=1,
            linecolor="black"
            ),
            yaxis=dict(
                showline=True,
                mirror=True,
                linewidth=1,
                linecolor="black"
            ))

        shown_groups = set()

        for trace in fig.data:

            # ----- LINES -----
            if trace.mode == "lines":
                if trace.name == "lm":
                    trace.name = "LM lines"
                    trace.legendgroup = "lm_lines"
                elif trace.name == "hm":
                    trace.name = "HM lines"
                    trace.legendgroup = "hm_lines"

            # ----- MARKERS -----
            elif trace.mode == "markers":

                if trace.marker.color == "black":
                    trace.name = "Enabled"
                    trace.legendgroup = "enabled_points"

                elif trace.marker.color == "gray":
                    trace.name = "Disabled"
                    trace.legendgroup = "disabled_points"

            # ---- SHOW LEGEND ONLY ONCE PER GROUP ----
            if trace.legendgroup not in shown_groups:
                trace.showlegend = True
                shown_groups.add(trace.legendgroup)
            else:
                trace.showlegend = False

        # ---- REMOVE LEGEND TITLE ----
        fig.update_layout(legend_title_text=None)
        self.add_axis_menus(fig)
        return fig
   

class rhoaSounding(dbdtSounding):

    @staticmethod
    def to_rhoa(time, dbdt, area=1., current=1.):
        from numpy import pi
        from __main__ import sesh
        # x = sesh.data.dmfwr.source.x
        # area = (x.max() - x.min())**2
        area=1
        mu0 = 4 * pi * 1e-7
        if dbdt.ndim > time.ndim:
            t = time[np.newaxis, :]
        else:
            t = time
        rho_a = ((current*area)**(2/3) * (mu0**(5/3))) / ((20 * dbdt)**(2/3) * (pi**(1/3)) * time**(5/3))
        return rho_a


    def _add_site_lines(self, fig, dataframe, y_axis):
        colors = {'lm': self.settings.lm_color, 'hm': self.settings.hm_color}
        custom_data = ['system_id', 'data_id', 'site_id']
        x_axis = self.settings.x_axis

        for system_id, system_data in dataframe.groupby('system_id', sort=False):
            x_values = []
            y_values = []
            point_data = []
            for _, site_data in system_data.groupby('site_id', sort=False):
                if x_values:
                    x_values.append(None)
                    y_values.append(None)
                    point_data.append([None, None, None])
                x_values.extend(site_data[x_axis].tolist())
                y_values.extend(site_data[y_axis].tolist())
                point_data.extend(site_data[custom_data].to_numpy().tolist())

            fig.add_trace(go.Scatter(
                x=x_values,
                y=y_values,
                customdata=point_data,
                mode='lines',
                line=dict(color=colors.get(system_id), width=2),
                name=system_id,
                connectgaps=False,
                hovertemplate=(
                    f'system_id={system_id}<br>{x_axis}=%{{x}}<br>'
                    f'{y_axis}=%{{y}}<extra></extra>'
                ),
            ))


    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', dbdtSoundingSettings(id='rhoa'))
        super().__init__(id='rhoa', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.settings.dbdt_min = 0
        self.settings.dbdt_max = 3


    def compare_synthetic(self):

        df_tmp                                             = self.dataframe.sort_values(['site_id', 'system_id',  self.settings.x_axis])
        df_tmp['rhoa'] = self.to_rhoa(df_tmp['time'].values, np.abs(df_tmp['dbdt'].values))
        df_tmp['rhoa_syn'] = self.to_rhoa(df_tmp['time'].values, np.abs(df_tmp['dbdt_syn'].values))
        df_tmp['include'] = include_mask(df_tmp)
        df_tmp.loc[df_tmp['site_id'] == -1, 'include']  = False


        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        error_ub,error_lb = 'error_ub', 'error_lb'
        # if True:
        #     error_ub = None
        #     error_lb = None
        # title = "Apparent Resistivity"
        # if df_tmp['site_id'].nunique()==1:
        #     title += f" site {df_tmp['site_id'].iloc[0]}"
        fig = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='rhoa',
            color_discrete_sequence=["gray", "gray"],
            color="system_id",
            # title=title,
            custom_data=["system_id", "data_id", "site_id"],
            error_y=error_ub,
            error_y_minus=error_lb
        )

        df_tmp.loc[df_tmp['site_id'] == -1, 'include'] = True
        df_tmp.loc[(~df_tmp['include']), 'rhoa']       = np.nan
        df_tmp.loc[(~df_tmp['include']), 'rhoa_syn']   = np.nan


        
        fig3 = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='rhoa',
            color_discrete_sequence=["black", "black"],
            color="system_id",

            # custom_data=["system_id", "data_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
        )

        for trace in fig3.data:
            fig.add_trace(trace)

        self._add_site_lines(fig, df_tmp, 'rhoa_syn')

        return fig    

    def observed_only(self):

        df_tmp                                             = self.dataframe.sort_values(['site_id', 'system_id',  self.settings.x_axis])
        df_tmp['rhoa'] = self.to_rhoa(df_tmp['time'].values, np.abs(df_tmp['dbdt'].values))
        df_tmp['include'] = include_mask(df_tmp)
        df_tmp.loc[df_tmp['site_id'] == -1, 'include']  = False

        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        error_ub,error_lb = 'error_ub', 'error_lb'
        # if True:
        #     error_ub = None
        #     error_lb = None
        # title = "Apparent Resistivity"
        # if df_tmp['site_id'].nunique()==1:
        #     title += f" site {df_tmp['site_id'].iloc[0]}"
        fig = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='rhoa',
            color_discrete_sequence=["gray", "gray"],
            color="system_id",
            # title=title,
            custom_data=["system_id", "data_id", "site_id"],
            error_y=error_ub,
            error_y_minus=error_lb
        )

        df_tmp.loc[df_tmp['site_id'] == -1, 'include'] = True
        df_tmp.loc[(~df_tmp['include']), 'rhoa'] = np.nan


        
        fig2 = px.scatter(
            df_tmp,
            x=self.settings.x_axis,
            y='rhoa',
            color_discrete_sequence=["black", "black"],
            color="system_id",
            # custom_data=["system_id", "data_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
        )

        for trace in fig2.data:
            fig.add_trace(trace)

        self._add_site_lines(fig, df_tmp, 'rhoa')

        return fig  

    def render(self):
        fig = super().render()

        fig.update_layout(
            yaxis_type="log",
            yaxis_range=[-1, 2.7],
            xaxis_type="log" if self.settings.x_axis == 'time' else "linear",
            xaxis_title=self.settings.x_axis,
            yaxis_title=r"$\rho_a\;[\Omega\,\mathrm{m}]$",
            margin={"l": 50, "r": 50, "t": 10, "b": 50},
            dragmode='select',
            xaxis=dict(
            showline=True,
            mirror=True,
            linewidth=1,
            linecolor="black"
            ),
            yaxis=dict(
                showline=True,
                mirror=True,
                linewidth=1,
                linecolor="black"
            ))

        shown_groups = set()

        for trace in fig.data:

            # ----- LINES -----
            if trace.mode == "lines":
                if trace.name == "lm":
                    trace.name = "LM lines"
                    trace.legendgroup = "lm_lines"
                elif trace.name == "hm":
                    trace.name = "HM lines"
                    trace.legendgroup = "hm_lines"

            # ----- MARKERS -----
            elif trace.mode == "markers":

                if trace.marker.color == "black":
                    trace.name = "Enabled"
                    trace.legendgroup = "enabled_points"

                elif trace.marker.color == "gray":
                    trace.name = "Disabled"
                    trace.legendgroup = "disabled_points"

            # ---- SHOW LEGEND ONLY ONCE PER GROUP ----
            if trace.legendgroup not in shown_groups:
                trace.showlegend = True
                shown_groups.add(trace.legendgroup)
            else:
                trace.showlegend = False

        # ---- REMOVE LEGEND TITLE ----
        fig.update_layout(legend_title_text=None)
        self.add_axis_menus(fig)
        return fig

@nosj
class dbdtSectionSettings(PanelSettings):
    lm_color: str = '#2D81FF'
    hm_color: str = '#ff0000'
    lm_factor: float = 20.0
    hm_factor: float = 1.0
    x_axis: Literal['daytime', 'site_id', 'longitude', 'latitude', 'distance'] = 'site_id'
    y_axis: str = 'dbdt_syn'
    plot_disabled: bool = True
    dbdt_max: float = -3
    dbdt_min: float = -12
    radius: float = 100.

    def __getattribute__(self, name):
        x_axis = super().__getattribute__(name)
        if name == 'x_axis':
            if x_axis.lower().startswith('line'):
                line_id = int(float(x_axis.split(' ')[-1]))
                x_axis = f'_line_{line_id:0.0f}_x'        
        return x_axis

class dbdtSection(Panel):
    dataframe = None
    highlighted: int = None
    buffer_start: int = 0
    buffer_len: int = 50
    buffer: SiteBuffer = None

    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', dbdtSectionSettings(id='tTEM'))
        super().__init__(id='tTEM', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def calc_xlim(self, site_ids):

        x_axis = self.settings.x_axis
        if x_axis.startswith('_line'):
            from __main__ import sesh
            self.dataframe = sesh.data.copy()
            self.dataframe = self.dataframe.loc[np.abs(self.dataframe[x_axis.replace('_x', '_y')])<self.settings.radius]

        new_df = self.dataframe[self.dataframe['site_id'].isin(site_ids)][x_axis].values
        if len(new_df) == 0:
            return None, None
        xmin, xmax = new_df.min(), new_df.max()
        dx = xmax-xmin
        xmax+= 0.1*dx
        xmin-= 0.1*dx
        return xmin,xmax
    
    def compare_synthetic(self):
        x_axis = self.settings.x_axis

        y_axis                                             = self.settings.y_axis
        df_tmp = self.dataframe.copy()
        df_tmp                                             = df_tmp.sort_values(['gate_id', x_axis])
        df_tmp['include'] = include_mask(df_tmp)

        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt_syn']  *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt_syn']  *= hm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt']      *= hm_factor
        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        x_vals = np.sort(df_tmp[x_axis].unique())

        if x_axis == 'site_id':
            x_vals = x_vals[x_vals > -1]

        n_sites = len(x_vals)

        xmin = x_vals.min()
        xmax = x_vals.max()

        dx = xmax - xmin

        error_ub,error_lb = 'error_ub', 'error_lb'
        if True:
            error_ub = None
            error_lb = None
        
        fig = px.scatter(
            df_tmp,
            x=x_axis,
            y='dbdt',
            color_discrete_sequence=["gray", "gray"],
            color="system_id",
            custom_data=["system_id", "data_id", "site_id"],
            error_y=error_ub,
            error_y_minus=error_lb
        )

        df_tmp.loc[(~df_tmp['include']), 'dbdt'] = np.nan
        df_tmp.loc[(~df_tmp['include']), 'dbdt_syn'] = np.nan

        
        
        fig3 = px.scatter(
            df_tmp,
            x=x_axis,
            y='dbdt',
            color_discrete_sequence=["black", "black"],
            color="system_id",
            error_y=error_ub,
            error_y_minus=error_lb,
        )

        fig2 = px.line(
            df_tmp,
            x=x_axis,
            y='dbdt_syn',
            color="system_id",
            line_group="gate_id",
            color_discrete_sequence=[self.settings.lm_color, self.settings.hm_color],
            custom_data=["system_id", "data_id", "site_id"],
        )
        fig2.update_traces(line_width=1.5)

        for trace in fig3.data:
            fig.add_trace(trace)

        for trace in fig2.data:
            fig.add_trace(trace)

        shown_groups = set()

        for trace in fig.data:

            # ----- LINES -----
            if trace.mode == "lines":
                if trace.name == "lm":
                    trace.name = "LM lines"
                    trace.legendgroup = "lm_lines"
                elif trace.name == "hm":
                    trace.name = "HM lines"
                    trace.legendgroup = "hm_lines"

            # ----- MARKERS -----
            elif trace.mode == "markers":

                if trace.marker.color == "black":
                    trace.name = "Enabled"
                    trace.legendgroup = "enabled_points"

                elif trace.marker.color == "gray":
                    trace.name = "Disabled"
                    trace.legendgroup = "disabled_points"

            # ---- SHOW LEGEND ONLY ONCE PER GROUP ----
            if trace.legendgroup not in shown_groups:
                trace.showlegend = True
                shown_groups.add(trace.legendgroup)
            else:
                trace.showlegend = False
        dx = xmax - xmin
        fig.update_layout(legend_title_text=None)
        fig.update_xaxes(range=[xmin-0.01*dx, xmax+0.01*dx])


        dx = xmax - xmin
        fig.update_xaxes(range=[xmin-0.01*dx, xmax+0.01*dx])
        return fig    

    def observed_only(self):
        y_axis                                             = self.settings.y_axis
        x_axis = self.settings.x_axis

        df_tmp = self.dataframe[self.dataframe['gate_id']>-1]
        df_tmp                                             = df_tmp.sort_values(['gate_id', x_axis])
        df_tmp['include'] = include_mask(df_tmp)
        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt']      *= hm_factor
        df_tmp.loc[df_tmp['site_id'] ==  -1, 'include']  = False
        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        # x_axis = df_tmp[x_axis].unique()#.values
        # if x_axis == 'site_id':
        #     x_axis = x_axis[x_axis>-1]
        # xmin,xmax = np.nanmin(x_axis), np.nanmax(x_axis)

        x_vals = np.sort(df_tmp[x_axis].unique())

        if x_axis == 'site_id':
            x_vals = x_vals[x_vals > -1]

        n_sites = len(x_vals)

        plot_start = max(0, self.buffer_start)
        plot_end   = min(n_sites, self.buffer_start + self.buffer_len)

        x_slice = x_vals[plot_start:plot_end]

        if len(x_slice) > 0:
            xmin = x_slice.min()
            xmax = x_slice.max()
        else:
            xmin = x_vals.min()
            xmax = x_vals.max()

        dx = xmax - xmin

        error_ub,error_lb = 'error_ub', 'error_lb'
        if True:
            error_ub = None
            error_lb = None
        buffer_start = self.buffer_start
        buffer_len   = self.buffer_len

        x_values = df_tmp.columns.tolist()
        n_sites  = len(x_values)
        plot_start = max(0, buffer_start)
        plot_end   = min(n_sites, buffer_start + buffer_len)

        x_slice = x_values[plot_start:plot_end]
        
        fig = px.scatter(
            df_tmp,
            x=x_axis,
            y='dbdt',
            color_discrete_sequence=["gray", "gray"],
            color="system_id",
            # title="Manual processing",
            custom_data=["system_id", "data_id", "site_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
        )

        df_tmp.loc[df_tmp['site_id'] == -1, 'include'] = True
        df_tmp.loc[(~df_tmp['include']), 'dbdt'] = np.nan
        
        fig3 = px.scatter(
            df_tmp,
            x=x_axis,
            y='dbdt',
            color_discrete_sequence=["black", "black"],
            color="system_id",
            # title="dbdt vs time by site_id",
            # custom_data=["system_id", "data_id"],
            error_y=error_ub,
            error_y_minus=error_lb,
        )

        fig2 = px.line(
            df_tmp,
            x=x_axis,
            y='dbdt',
            line_group="gate_id",
            color="system_id",
            color_discrete_sequence=[self.settings.lm_color, self.settings.hm_color],
            title="dbdt vs time by site_id",
            custom_data=["system_id", "data_id", "site_id"],
        )
        fig2.update_traces(line_width=1.5)

        for trace in fig3.data:
            fig.add_trace(trace)

        for trace in fig2.data:
            fig.add_trace(trace)

        shown_groups = set()

        for trace in fig.data:

            # ----- LINES -----
            if trace.mode == "lines":
                if trace.name == "lm":
                    trace.name = "LM lines"
                    trace.legendgroup = "lm_lines"
                elif trace.name == "hm":
                    trace.name = "HM lines"
                    trace.legendgroup = "hm_lines"

            # ----- MARKERS -----
            elif trace.mode == "markers":

                if trace.marker.color == "black":
                    trace.name = "Enabled"
                    trace.legendgroup = "enabled_points"

                elif trace.marker.color == "gray":
                    trace.name = "Disabled"
                    trace.legendgroup = "disabled_points"

            # ---- SHOW LEGEND ONLY ONCE PER GROUP ----
            if trace.legendgroup not in shown_groups:
                trace.showlegend = True
                shown_groups.add(trace.legendgroup)
            else:
                trace.showlegend = False
        dx = xmax - xmin
        fig.update_layout(legend_title_text=None)
        fig.update_xaxes(range=[xmin-0.01*dx, xmax+0.01*dx])
        
        return fig  

    def observed_by_gate_id(self):
        y_axis                                             = self.settings.y_axis
        x_axis = self.settings.x_axis

        df_tmp = self.dataframe.copy()
        df_tmp                                             = df_tmp.sort_values(['gate_id', x_axis])
        df_tmp['include'] = include_mask(df_tmp)
        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor
        df_tmp.loc[df_tmp['system_id'] == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] == 1, 'dbdt']      *= hm_factor
        df_tmp.loc[df_tmp['site_id'] ==  -1, 'include']  = False
        df_tmp['system_id']                                = df_tmp['system_id'].map({0: 'lm', 1: 'hm'})

        error_ub,error_lb = 'error_ub', 'error_lb'
        if True:
            error_ub = None
            error_lb = None
        
        fig = px.scatter(
            df_tmp,
            x=x_axis,
            y='gate_id',
            color="log10_dbdt",
            custom_data=["system_id", "data_id", "site_id"],
        )
        #fig.update

        # df_tmp.loc[(~df_tmp['include']), 'dbdt'] = np.nan

        
        
        # fig3 = px.scatter(
        #     df_tmp,
        #     x='gate_id',
        #     y='dbdt',
        #     color_discrete_sequence=["black", "black"],
        #     color="system_id",
        #     error_y=error_ub,
        #     error_y_minus=error_lb,
        # )

        # fig2 = px.line(
        #     df_tmp,
        #     x='gate_id',
        #     y='dbdt',
        #     line_group="site_id",
        #     color="system_id",
        #     color_discrete_sequence=[self.settings.lm_color, self.settings.hm_color],
        #     title="dbdt vs time by site_id",

        return fig

    def render(self):
        print("Rendering section")
        if self.dataframe is None: return self.empty_render()
        x_axis = self.settings.x_axis
        from __main__ import sesh
        if x_axis.startswith('_line') and x_axis in sesh.data.columns:
            line_id = int(float(x_axis.split('_')[-2]))
            self.dataframe = sesh.data.copy()
            self.dataframe = self.dataframe.loc[np.abs(self.dataframe[x_axis.replace('_x', '_y')])<self.settings.radius]
            x_min = 0
            x_max = sesh.lines[sesh.lines.line==line_id].total_length.max()
        else:
            # back to all sites (the line branch narrows self.dataframe to those near the line)
            if sesh.data is not None:
                self.dataframe = sesh.data.copy()
            x_min = None
            x_max = None
        site_x = site_positions(self.dataframe, x_axis)
        self._site_buffer_site_x = site_x
        if len(site_x) == 0:
            fig = self.message_render(f'No sites within {self.settings.radius:g} m of {axis_label(x_axis)}' if x_axis.startswith('_line') else 'No sites')
            self.add_axis_menus(fig, x_axis)
            self._site_buffer_static_shapes = site_buffer_static_shapes(fig)
            return fig

        if self.settings.y_axis=='gate_id':
            fig = self.observed_by_gate_id()
            apply_site_buffer(fig, site_x, self.buffer)
            self.add_axis_menus(fig, x_axis)
            self._site_buffer_static_shapes = site_buffer_static_shapes(fig)
            return fig

        if 'dbdt_syn' in self.dataframe.columns:
            fig = self.compare_synthetic()
        else:
            fig = self.observed_only()

        vals = np.abs(self.dataframe["dbdt"].values)
        vals = vals[np.isfinite(vals) & (vals > 0)]

        if len(vals) > 0:
            logvals = np.log10(vals)
            ymin = np.floor(logvals.min()) - 0.2
            ymax = np.ceil(logvals.max()) + 0.2 + np.log10(self.settings.lm_factor)
        else:
            ymin, ymax = -12, -3

        self.settings.dbdt_min = ymin
        self.settings.dbdt_max = ymax

        fig.update_layout(
            yaxis_type="log",
            yaxis_range=[self.settings.dbdt_min, self.settings.dbdt_max],
            yaxis_title="dB/dt [V / m²]",
            margin={"l": 55, "r": 120, "t": 10, "b": 50, "autoexpand": False},
            dragmode='select',
            xaxis=dict(
            showline=True,
            mirror=True,
            linewidth=1,
            linecolor="black"
            ),
            yaxis=dict(
                showline=True,
                mirror=True,
                linewidth=1,
                linecolor="black",
                fixedrange=True
            ))
        fig.update_layout(
            legend=dict(x=0.95, y=0.95,xanchor="right",yanchor="top",bgcolor="rgba(255,255,255,0.8)"),
            modebar=dict(add=['lasso'], remove=['zoomIn', 'zoomOut', 'toImage', 'plotly-logomark', 'autoScale', 'resetScale2d'])
        )
        if x_min is not None and x_max is not None:
            fig.update_xaxes(range=[x_min, x_max], autorange=False)
        apply_site_buffer(fig, site_x, self.buffer)
        self.add_axis_menus(fig, x_axis)
        self._site_buffer_static_shapes = site_buffer_static_shapes(fig)
        return fig

    def add_axis_menus(self, fig, x_axis):
        menus = {'x': section_x_menu(),
                 'y': axis_menu({'type': f'settings-{self.id}', 'key': 'y_axis'}, [('dB/dt', 'dbdt_syn'), ('gate id', 'gate_id')], self.settings.y_axis)}
        fig.update_layout(xaxis_title=axis_label(x_axis)+' ▾', yaxis_title=(fig.layout.yaxis.title.text or '')+' ▾',
                          meta={**site_lookup(self.dataframe, x_axis), 'menus': menus})

@nosj
class AutoProcessing(PanelSettings):
    sign_correction:  bool = False
    remove_negatives: bool = False
    Slope_Filter: bool = False
    Slope_Filter_threshold: int = 5


class Upload(Panel):
    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', AutoProcessing(id='upload', title='Auto Processing Settings'))
        super().__init__(id='upload', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def render(self):
        return html.Div(
            [
                dcc.Upload(
                    id='upload-data',
                    children=html.Div([
                        'Drag and Drop \n or \n',
                        html.A('Select Files')
                    ], style={'height': '110px', 'lineHeight': '100px', 'textAlign': 'center'}),
                    style={
                        'borderWidth': '2px',
                        'borderStyle': 'dashed',
                        'borderRadius': '5px',
                        'textAlign': 'center',
                    },
                    multiple=True,
                ),
                html.Div(id='output-data-upload'),
                html.Div(id='output-data-summary', style={'marginTop': '8px'}),
                dbc.Toast(
                    id='upload-toast',
                    header='Upload',
                    is_open=False,
                    dismissable=True,
                    duration=4000,
                    icon='primary',
                    style={'position': 'fixed', 'top': '70px', 'right': '20px', 'zIndex': 2000, 'minWidth': '280px'}
                ),
                html.Br(),
                html.Div(
                    [
                        dbc.Checkbox(
                            id='use-dem',
                            value=False,
                            label='Use DEM (optional)',
                            style={'marginLeft': '5px'}
                        ),
                        html.Div(
                            [
                                dcc.Upload(
                                    id='upload-dem',
                                    children=html.Div([
                                        'DEM: Drag and Drop \n or \n',
                                        html.A('Select DEM File')
                                    ], style={'height': '90px', 'lineHeight': '80px', 'textAlign': 'center'}),
                                    style={
                                        'borderWidth': '2px',
                                        'borderStyle': 'dashed',
                                        'borderRadius': '5px',
                                        'textAlign': 'center',
                                    },
                                    multiple=False,
                                    accept='.tif,.tiff,.asc,.bil,.dem,.xyz',
                                ),
                                html.Div(id='output-dem-upload'),
                                html.Hr(style={'marginTop': '12px', 'marginBottom': '8px'}),
                                html.Div(
                                    [
                                        html.Div('DEM download (WGS84 lon/lat bbox):', style={'fontWeight': '600', 'marginBottom': '6px'}),
                                        html.Div([
                                            html.Div([
                                                html.Label('Source', style={'fontSize': '12px'}),
                                                dcc.Dropdown(
                                                    id='dem-source',
                                                    options=[
                                                        {'label': 'OpenTopography (global)', 'value': 'opentopo'},
                                                        {'label': 'NCEI ETOPO 2022 (global GeoTIFF)', 'value': 'etopo'},
                                                    ],
                                                    value='opentopo',
                                                    clearable=False,
                                                )
                                            ], style={'width': '60%'}),
                                        ], style={'display': 'flex', 'gap': '10px', 'marginBottom': '8px'}),
                                        html.Div(
                                            [
                                                html.Label('OpenTopography API key', style={'fontSize': '12px'}),
                                                dcc.Input(
                                                    id='dem-api-key',
                                                    type='text',
                                                    value='',
                                                    placeholder='Paste API key (required for OpenTopography)',
                                                    list='dem-api-key-list',
                                                    className='form-control',
                                                    style={'width': '100%', 'borderRadius': '6px'}
                                                ),
                                                html.Datalist(id='dem-api-key-list'),
                                                dbc.Button(
                                                    'History ▼',
                                                    id='dem-api-key-history-toggle',
                                                    color='link',
                                                    size='sm',
                                                    style={'padding': '0', 'marginTop': '6px'}
                                                ),
                                                dbc.Collapse(
                                                    html.Div(
                                                        id='dem-api-key-history',
                                                        style={'marginTop': '6px'}
                                                    ),
                                                    id='dem-api-key-history-collapse',
                                                    is_open=False
                                                ),
                                            ],
                                            id='dem-api-key-container',
                                            style={'marginBottom': '8px'}
                                        ),
                                        html.Div([
                                            html.Div([
                                                html.Label('Min lon', style={'fontSize': '12px'}),
                                                dcc.Input(id='dem-bbox-minlon', type='number', placeholder='-180', debounce=True, style={'width': '100%'})
                                            ], style={'width': '24%'}),
                                            html.Div([
                                                html.Label('Min lat', style={'fontSize': '12px'}),
                                                dcc.Input(id='dem-bbox-minlat', type='number', placeholder='-90', debounce=True, style={'width': '100%'})
                                            ], style={'width': '24%'}),
                                            html.Div([
                                                html.Label('Max lon', style={'fontSize': '12px'}),
                                                dcc.Input(id='dem-bbox-maxlon', type='number', placeholder='180', debounce=True, style={'width': '100%'})
                                            ], style={'width': '24%'}),
                                            html.Div([
                                                html.Label('Max lat', style={'fontSize': '12px'}),
                                                dcc.Input(id='dem-bbox-maxlat', type='number', placeholder='90', debounce=True, style={'width': '100%'})
                                            ], style={'width': '24%'}),
                                        ], style={'display': 'flex', 'gap': '6px', 'marginBottom': '8px'}),
                                        html.Div(
                                            [
                                                dbc.Button('Use data extent', id='dem-bbox-from-data', color='secondary', outline=True, size='sm'),
                                            ],
                                            style={'marginBottom': '8px'}
                                        ),
                                        html.Div([
                                            html.Div([
                                                html.Label('Resolution', style={'fontSize': '12px'}),
                                                dcc.Dropdown(
                                                    id='dem-resolution',
                                                    options=[
                                                        {'label': 'Global Copernicus GLO-30 (~30 m)', 'value': 'opentopo_cop30'},
                                                        {'label': 'Global SRTMGL1 (~30 m)', 'value': 'opentopo_srtmgl1'},
                                                        {'label': 'Global SRTMGL3 (~90 m)', 'value': 'opentopo_srtmgl3'},
                                                        {'label': 'Global ALOS (~30 m)', 'value': 'opentopo_alos'},
                                                        {'label': 'ETOPO2022 30 arc-second (surface, global)', 'value': 'etopo_30s'},
                                                        {'label': 'ETOPO2022 60 arc-second (surface, global)', 'value': 'etopo_60s'},
                                                    ],
                                                    value='opentopo_cop30',
                                                    clearable=False,
                                                )
                                            ], style={'width': '60%'}),
                                            html.Div([
                                                dbc.Button(
                                                    'Download DEM',
                                                    id='download-dem',
                                                    color='primary',
                                                    style={'flex': '1', 'height': '42px'}
                                                ),
                                                dbc.Button(
                                                    'Save DEM + KML',
                                                    id='save-dem',
                                                    color='secondary',
                                                    outline=True,
                                                    disabled=True,
                                                    style={'flex': '1', 'height': '42px'}
                                                ),
                                            ], style={'width': '40%', 'display': 'flex', 'gap': '6px', 'marginTop': '18px', 'alignItems': 'flex-start'}),
                                        ], id='dem-resolution-container', style={'display': 'flex', 'gap': '10px', 'alignItems': 'flex-start'}),
                                        html.Div(
                                            [
                                                dbc.Button(
                                                    'Load DEM vs GPS',
                                                    id='load-dem-vs-gps',
                                                    color='secondary',
                                                    outline=False,
                                                    style={'width': '100%', 'backgroundColor': '#7B2CBF', 'borderColor': '#7B2CBF'}
                                                ),
                                            ],
                                            style={'marginTop': '8px'}
                                        ),
                                        html.Div(
                                            [
                                                dbc.Button(
                                                    'Restore GPS elevation',
                                                    id='restore-gps-elevation',
                                                    color='secondary',
                                                    outline=True,
                                                    style={'width': '100%'},
                                                    disabled=True
                                                ),
                                            ],
                                            style={'marginTop': '6px'}
                                        ),
                                        html.Div(id='output-dem-download', style={'marginTop': '6px'}),
                                        html.Div(id='output-dem-save', style={'marginTop': '6px'}),
                                        html.Div(id='output-dem-load', style={'marginTop': '6px'})
                                    ]
                                ),
                            ],
                            id='dem-upload-container',
                            style={'display': 'none', 'marginTop': '10px'}
                        ),
                    ],
                    id='dem-options-container',
                    style={'display': 'none'}
                ),
            html.Br(),
                html.Div(
                    [
                        dbc.Checkbox(
                            id='use-borehole',
                            value=False,
                            label='Use Borehole Data (optional)',
                            style={'marginLeft': '5px'}
                        ),
                        html.Div(
                            [
                                dcc.Upload(
                                    id='upload-borehole',
                                    children=html.Div([
                                        'Borehole: Drag and Drop .bor file or ',
                                        html.A('Select File')
                                    ], style={'height': '80px', 'lineHeight': '70px', 'textAlign': 'center'}),
                                    style={
                                        'borderWidth': '2px',
                                        'borderStyle': 'dashed',
                                        'borderRadius': '5px',
                                        'textAlign': 'center',
                                    },
                                    multiple=False,
                                    accept='.bor',
                                ),
                                html.Div(id='output-borehole-upload', style={'marginTop': '6px'}),
                            ],
                            id='borehole-upload-container',
                            style={'display': 'none', 'marginTop': '10px'}
                        ),
                    ],
                    id='borehole-options-container',
                    style={'display': 'none'}
                ),


        ],
        )
    
    def initialize(self):
        session_text = "### Recent sessions\n"
        if self.session_files is None or len(self.session_files) == 0:
            session_text += "no previous session:\n"
        else:
            for f in self.session_files:
                cfolder = f.strip().replace('\\', '/')
                session_text += f"- [{cfolder}](#load=\"{cfolder.replace(' ', '%20')}\")\n"
        session_text += "- [open session](#open_session)\n"
        return html.Div([
            dcc.Markdown("# Welcome to sea anemone", style={'textAlign': 'center'}),       
            dcc.Markdown("### Upload your data to get started."),
            self.render(),
            html.Div([
                html.Div(['Working directory: '], id="current-working-directory-label", style={"marginLeft":"10px", "marginTop": "10px", 'display': 'inline-block'}),
                html.A("Select directory", href="#change_working", id="current-working-directory", style={"cursor": "pointer", "color": "blue", "textDecoration": "underline", "marginLeft":"10px", "marginTop": "10px", 'display': 'inline-block'}, title='change directory')
            ]),
            dcc.Markdown("---"),
            dcc.Markdown(session_text),
            gear_maker(self.id)],
            style={'margin':'10px'}#,'height': 'calc(100%-30px)', 'overflow': 'hidden'} 
        )


# @nosj
# class TableSettings(PanelSettings):
#     max_rows: int = 50
#     visible_columns: list[bool] = None

#     def special_renders(self):
#         special_renders = super().special_renders()
#         vis_check = lambda key,prop: key == 'visible_columns'
#         def vis_render(key, prop):
#             checkbox_row = []
#             if hasattr(self, 'column_names'):
#                 col_names = self.column_names
#             else:
#                 col_names = [str(i) for i in range(self.visible_columns_len)]

#             for i, (val, name) in enumerate(zip(self.visible_columns, col_names)):
#                 checkbox_row.append(
#                     html.Div([
#                         html.Label(name, style={'fontSize': '12px', 'marginLeft': '5px'}),
#                         dbc.Checkbox(
#                             id={'type': f'settings-{self.id}', 'key': f'{key}-{i}'},
#                             #value=self.visible_columns[i] if i < len(self.visible_columns) else True,
#                             value=val,
#                             style={'margin': '5px', 'horizontalAlign': 'center', 'verticalAlign': 'middle'}
#                         ),
#                     ], style={'display': 'inline-block', 'marginRight': '15px', 'verticalAlign': 'top'})
#                 )
            
#             return html.Div([
#                 html.Br(),
#                 html.Div(checkbox_row, style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px'}),
#                 html.Br()])
        
#         special_renders.append((vis_check, vis_render))
#         return special_renders
    
# class Table(Panel):
#     def __init__(self, dataframe, **kwargs):
#         id = kwargs.pop('id', 'table')
#         settings = kwargs.pop('settings', TableSettings(id, visible_columns=[True for _ in dataframe.columns.tolist()]))
#         settings.column_names = dataframe.columns.tolist()
#         super().__init__(id=id, settings=settings, childname='children')
#         self.dataframe = dataframe
#         self.dashtable = None

#         for key, value in kwargs.items():
#             setattr(self, key, value)      

#     def render(self):
#         # colums = 
#         self.dashtable = dash_table.DataTable(
#             data=self.dataframe.to_dict('records'),
#             columns=[{"name": name, "id": name} for i,name in enumerate(self.dataframe.columns) if self.settings.visible_columns[i]],
#             page_size=self.settings.max_rows,
#             sort_action="native",
#             style_table={'height': '400px', 'overflowY': 'auto'},
#             style_cell={'textAlign': 'left', 'padding': '5px', 'fontSize': '12px'},
#             style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
#         )
#         # self.dashtable.SelectedCells = self.dashtable.SelectedCells if hasattr(self.dashtable, 'SelectedCells') else None
#         return html.Div(self.dashtable, id=self.id)
                
#     def initialize(self):
#         if hasattr(self, 'name'):
#             name = self.name
#         else:
#             name = self.id
#         return html.Div([
#             self.render(),
#             gear_maker(self.id)],
#             style={'margin':'10px'}#,'height': 'calc(100%-30px)', 'overflow': 'hidden'} 
#         )
   
    
import dash_bootstrap_components as dbc

class HotKeyReminder(Panel):
    javascript =     """
        function(id) {
            document.addEventListener("keydown", function(event) {
                // Check if focus is on an input element
                const activeElement = document.activeElement;
                const isInputFocused = activeElement && (
                    activeElement.tagName === 'INPUT' || 
                    activeElement.tagName === 'TEXTAREA' || 
                    activeElement.contentEditable === 'true'
                );
                
                if (event.ctrlKey) {
                    if (event.key == 'd') {
                        document.getElementById('disableButton').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }
                    if (event.key == 'e') {
                        document.getElementById('enableButton').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }
                    if (event.key == 'ArrowLeft') {
                        document.getElementById('prev-buffer').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }
                    if (event.key == 'ArrowRight') {
                        document.getElementById('next-buffer').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }                    
                    if (event.key == 'b') {
                        document.getElementById('beginning-buffer').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }   
                    if (event.key == 's') {
                        if (event.shiftKey) {
                            document.getElementById('saveAsButton').click()
                        } else {
                            document.getElementById('saveButton').click()
                        }
                        event.preventDefault()
                        event.stopPropagation()
                    }
                }
                
                // Arrow keys without Ctrl, but only if not typing in an input
                if (!isInputFocused) {
                    if (event.key == 'ArrowLeft') {
                        document.getElementById('highlight_prev').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }
                    if (event.key == 'ArrowRight') {
                        document.getElementById('highlight_next').click()
                        event.preventDefault()
                        event.stopPropagation()
                    }
                    if ((event.key == 'l' || event.key == 'L') && !event.ctrlKey && !event.metaKey) {
                        const drawButton = document.getElementById('map_drawline')
                        if (drawButton) drawButton.click()
                    }
                }
            });
            return window.dash_clientside.no_update       
        }
    """

    def __init__(self):
        super().__init__(id='processing_buttons')

    def initialize(self):
        x = html.Div([
            # dcc.Markdown(children='### buttons and hot keys'),
            html.Div(
                [
                    dbc.ButtonGroup([
                    dbc.Button("Disable [ctrl+d]", id='disableButton'),
                    html.Div(style={'width':'6px'}),
                    dbc.Button("Enable  [ctrl+e]", id='enableButton'),
                    ]),
                    dbc.ButtonGroup([
                        dbc.Button("Beginning [ctrl+b]", id='beginning-buffer', style={}),
                        html.Div(style={'width':'6px'}),
                        dbc.Button("Previous buffer [ctrl+<-]", id='prev-buffer', style={}),
                        html.Div(style={'width':'6px'}),
                        dbc.Button("Previous [<-]", id='highlight_prev', style={}),
                        html.Div(style={'width':'6px'}),
                        dbc.Button("Next [->]", id='highlight_next', style={}),
                        html.Div(style={'width':'6px'}),
                        dbc.Button("Next buffer [ctrl+->]", id='next-buffer', style={}),
                        html.Div(style={'width':'12px'}),
                        html.Div(
                            [
                                html.Small(
                                    "Buffer length:",
                                    style={
                                        "color": "#555",
                                        "fontSize": "12px",
                                    }, id="buffer-length-label"
                                ),
                                html.Div(style={'width':'6px'}),
                                dcc.Input(
                                    id='buffer-length-input',
                                    type='number',
                                    min=1,
                                    step=1,
                                    value=50,
                                    style={
                                        "width": "70px",
                                        "height": "32px",
                                        "fontSize": "13px"
                                    }
                                ),
                            html.Div(style={'width':'12px'}),
                            dbc.Progress(id="buffer-progress",value=0,max=100,style={"height": "18px", "marginTop": "10px"}),
                            html.Div(style={'width':'6px'}),
                            html.Div(id="buffer-progress-text", style={"fontSize": "14px"}),
                            ],
                            style={
                                "display": "flex",
                                "alignItems": "center",
                            }
                        )
                    ]),
                    html.Div(dbc.Toast(id="save-session-toast",header="Session Saved",is_open=False,dismissable=True,duration=8000,icon="success", 
                        style={"position": "fixed","top": "80px","right": "20px","width": 350,"zIndex": 9999})),
                    dbc.ButtonGroup([
                        dbc.Button("Save session [ctrl+s]", id='saveButton'),
                    ]),
                    html.Div(style={'width':'30px'}),
                    dbc.Tooltip("Save the current session to the default location or select a folder", target='saveButton', placement='top'),
                    dbc.Tooltip("Used to disable noisy data or data which cannot be fitted in inversions.", target='disableButton', placement='top'),
                    dbc.Tooltip("Used to enable previously disabled data.", target='enableButton', placement='top'),
                    dbc.Tooltip("Go to the first collected data site.", target='beginning-buffer', placement='top'),
                    dbc.Tooltip("Go to the previous buffer of sites.", target='prev-buffer', placement='top'),
                    dbc.Tooltip("Go to the next buffer of sites.", target='next-buffer', placement='top'),
                    dbc.Tooltip("Go to previous.", target='highlight_prev', placement='top'),
                    dbc.Tooltip("Go to next", target='highlight_next', placement='top'),
                ], style={'padding': '10px', 'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}
                ),
                dcc.Location(id='url_button'),
            ]
        , id='processing_buttons')
        return x
    
    def add_callbacks(self, app):
        super().add_callbacks(app)
        @app.callback(
            Output("buffer-progress", "value"),
            Output("buffer-progress-text", "children"),
            Input("data-buffer", "data"),
            Input("map", "figure"),   # ← triggers when upload completes
            Input({'type': 'settings-tTEM', 'key': 'x_axis'}, 'value'),  # sites are counted along the section axis
            prevent_initial_call=False
        )
        def update_buffer_progress(buffer_data, *_):
            from __main__ import sesh, buf

            if sesh.data is None or "site_id" not in sesh.data.columns:
                return 0, "No data loaded"

            # sites along the section x axis (fewer than all sites when it's a line)
            buffer_data = buf.store()
            total_sites = buffer_data['total']

            if total_sites == 0:
                return 0, "No sites"

            start = buffer_data.get("start_site", 0)
            length = buffer_data.get("length", 0)

            end = min(start + length, total_sites)
            percent = (end / total_sites) * 100

            return percent, f"{start+1}–{end} of {total_sites} sites"
        @app.callback(
            Output("save-session-toast", "is_open"),
            Output("save-session-toast", "children"),
            Input("session-save-complete", "data"),
            prevent_initial_call=True
        )
        def show_save_toast(save_data):
            if not save_data:
                raise PreventUpdate
            # from __main__ import sesh
            # save_dir = getattr(sesh, "session_path", "unknown")

            return True, f"Session saved to: {save_data.get('dir', 'unknown')}"
        @app.callback(
            Output("disableButton", "children"),
            Output("enableButton", "children"),

            Output("beginning-buffer", "style"),
            Output("prev-buffer", "style"),
            Output("next-buffer", "style"),
            # Output("highlight_prev", "style"),
            # Output("highlight_next", "style"),
            Output("highlight_prev", "children"),
            Output("highlight_next", "children"),
            Output("buffer-length-input", "style"),
            Output("buffer-progress", "style"),
            Output("buffer-progress-text", "style"),
            Output('buffer-length-label', 'style'),

            Input("interpret_layout", "color"),
            prevent_initial_call=True
        )
        def interpret_mode_ui(color):

            hidden = {"opacity": 0}
            shown = {"opacity": 1}


            if color != "primary":
                return (
                "Disable [ctrl+d]",
                "Enable [ctrl+e]",
                shown,  # beginning-buffer
                shown,  # prev-buffer
                shown,  # next-buffer
                'Previous',  # highlight_prev
                'Next',  # highlight_next
                {"width": "70px","height": "32px","fontSize": "13px"},  # buffer-length-input
                shown,  # buffer-progress
                shown,  # buffer-progress-text
                shown,  # buffer-length-label
            )
            return (
                "Delete",
                "Export",
                hidden,  # beginning-buffer
                hidden,  # prev-buffer
                hidden,  # next-buffer
                "Previous profile",  # highlight_prev
                "Next profile",  # highlight_next
                hidden,  # buffer-length-input
                hidden,  # buffer-progress
                hidden,  # buffer-progress-text
                hidden,  # buffer-length-label
            )
