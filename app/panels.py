from dataclasses import field
from basepanel import *
from map import Map, MapSettings
from inversion_panels import MultiInversion, MultiInversionSettings, Single_site, SinglesiteSettings
from model import ModelGraph, ModelGraphSettings, ModelSection, ModelSectionSettings, _no_data_figure

from dash import dash_table, ctx, no_update
import plotly.io as pio

import numpy as np
import pandas as pd
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


def _synthetic_observed_line_traces(df, x, y, line_group, lm_color, hm_color, custom_data):
    """
    Split a line trace into synthetic (dotted) and observed (solid)
    segments, based on the caller's 'is_synthetic' column, so a model-fit
    line is visually distinguishable from an observed-data fallback line
    (used for not-yet-inverted sites -- see compare_synthetic() on
    dbdtSounding/rhoaSounding/dbdtSection) even though both draw from the
    same y column. color_discrete_map is used rather than
    color_discrete_sequence since either subset can legitimately contain
    only one of 'lm'/'hm' (e.g. a buffer window with only synthetic HM
    data), and a plain sequence would then mis-assign whichever color
    happens to be first.
    """
    color_map = {'lm': lm_color, 'hm': hm_color}
    traces = []
    for is_synthetic, dash in ((True, 'dot'), (False, 'solid')):
        subset = df[df['is_synthetic'] == is_synthetic]
        if subset.empty:
            continue
        line_fig = px.line(
            subset, x=x, y=y, color="system_id", line_group=line_group,
            color_discrete_map=color_map, custom_data=custom_data,
        )
        line_fig.update_traces(line_dash=dash)
        traces.extend(line_fig.data)
    return traces


@nosj
class dbdtSoundingSettings(PanelSettings):
    # Shared by both Sounding (dbdt1) and Apparent Resistivity (rhoa) --
    # order here drives the gear-icon settings form's order for both.
    lm_factor: float = field(default=20.0, metadata={'title': 'LM factor'})
    hm_factor: float = field(default=1.0, metadata={'title': 'HM factor'})
    plot_error: bool = field(default=False, metadata={'title': 'plot_error'})
    x_axis: Literal['time', 'gate_id'] = field(default='time', metadata={'title': 'x axis'})  # or 'site_id', 'longitude', 'latitude'
    dbdt_min: float = field(default=-12, metadata={'title': 'dbdt min'})
    dbdt_max: float = field(default=-3, metadata={'title': 'dbdt max'})
    lm_color: str = field(default='#2D81FF', metadata={'title': 'LM color'})
    hm_color: str = field(default='#ff0000', metadata={'title': 'HM color'})

class dbdtSounding(Panel):
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

        df_tmp                                             = self.dataframe.sort_values(['site_id', 'system_id',  self.settings.x_axis])
        df_tmp['include'] = df_tmp['inuse_manual'].astype(bool, copy=True).fillna(df_tmp['inuse_auto'])
        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor

        # dbdt_syn is a column on sesh.data as a whole once ANY site has
        # ever been inverted in this session -- it isn't necessarily
        # populated for every site (e.g. sites merged in from a later
        # upload, not yet inverted). Fall back to the observed value
        # per-site rather than per-dataframe, so the colored LM/HM line
        # always has something to draw: observed pre-inversion, synthetic
        # once that specific site has been inverted.
        if 'dbdt_syn' not in df_tmp.columns:
            df_tmp['dbdt_syn'] = np.nan

        df_tmp.loc[df_tmp['system_id'] % 2 == 0, 'dbdt_syn']  *= lm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 1, 'dbdt_syn']  *= hm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 1, 'dbdt']      *= hm_factor
        df_tmp.loc[df_tmp['site_id'] == -1, 'include']  = False
        df_tmp.loc[df_tmp['dbdt']<=0, 'dbdt'] = np.nan

        df_tmp['dbdt_line'] = df_tmp['dbdt_syn'].where(df_tmp['dbdt_syn'].notna(), df_tmp['dbdt'])
        df_tmp['is_synthetic'] = df_tmp['dbdt_syn'].notna()

        df_tmp['system_id']                                = np.where(df_tmp['system_id'] % 2 == 0, 'lm', 'hm')

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
        df_tmp.loc[(~df_tmp['include']), 'dbdt_line']  = np.nan



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

        line_traces = _synthetic_observed_line_traces(
            df_tmp, self.settings.x_axis, 'dbdt_line', 'site_id',
            self.settings.lm_color, self.settings.hm_color,
            ["system_id", "data_id", "site_id"],
        )

        for trace in fig3.data:
            fig.add_trace(trace)

        for trace in line_traces:
            trace.line.width = 2
            fig.add_trace(trace)

        # fig.update_layout(yaxis_range=[self.settings.dbdt_min, self.settings.dbdt_max])


        return fig

    def render(self):
        if self.dataframe is None: return self.empty_render()

        fig = self.compare_synthetic()

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


    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', dbdtSoundingSettings(id='rhoa', title='App. Res. settings'))
        super().__init__(id='rhoa', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.settings.dbdt_min = 0
        self.settings.dbdt_max = 3


    def compare_synthetic(self):

        df_tmp                                             = self.dataframe.sort_values(['site_id', 'system_id',  self.settings.x_axis])
        df_tmp['rhoa'] = self.to_rhoa(df_tmp['time'].values, np.abs(df_tmp['dbdt'].values))

        # dbdt_syn is a column on sesh.data as a whole once ANY site has
        # ever been inverted in this session -- it isn't necessarily
        # populated for every site (e.g. sites merged in from a later
        # upload, not yet inverted). Fall back to the observed rhoa
        # per-site rather than per-dataframe, so the colored LM/HM line
        # always has something to draw: observed pre-inversion, synthetic
        # once that specific site has been inverted.
        if 'dbdt_syn' not in df_tmp.columns:
            df_tmp['dbdt_syn'] = np.nan
        df_tmp['rhoa_syn'] = self.to_rhoa(df_tmp['time'].values, np.abs(df_tmp['dbdt_syn'].values))
        df_tmp['rhoa_line'] = df_tmp['rhoa_syn'].where(df_tmp['rhoa_syn'].notna(), df_tmp['rhoa'])
        df_tmp['is_synthetic'] = df_tmp['dbdt_syn'].notna()

        df_tmp['include'] = df_tmp['inuse_manual'].astype(bool, copy=False).fillna(df_tmp['inuse_auto'])
        df_tmp.loc[df_tmp['site_id'] == -1, 'include']  = False


        df_tmp['system_id']                                = np.where(df_tmp['system_id'] % 2 == 0, 'lm', 'hm')

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
        df_tmp.loc[(~df_tmp['include']), 'rhoa_line']  = np.nan



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

        line_traces = _synthetic_observed_line_traces(
            df_tmp, self.settings.x_axis, 'rhoa_line', 'site_id',
            self.settings.lm_color, self.settings.hm_color,
            ["system_id", "data_id", "site_id"],
        )

        for trace in fig3.data:
            fig.add_trace(trace)

        for trace in line_traces:
            trace.line.width = 2
            fig.add_trace(trace)

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
        return fig

@nosj
class dbdtSectionSettings(PanelSettings):
    # Order here drives the gear-icon settings form's order.
    x_axis: Literal['daytime', 'site_id', 'longitude', 'latitude', 'distance'] = field(default='site_id', metadata={'title': 'x axis'})
    y_axis: str = field(default='dbdt_syn', metadata={'title': 'y axis'})
    lm_factor: float = field(default=20.0, metadata={'title': 'LM factor'})
    hm_factor: float = field(default=1.0, metadata={'title': 'HM factor'})
    plot_disabled: bool = field(default=True, metadata={'title': 'Plot Disabled'})
    dbdt_min: float = field(default=-12, metadata={'title': 'dbdt min'})
    dbdt_max: float = field(default=-3, metadata={'title': 'dbdt max'})
    lm_color: str = field(default='#2D81FF', metadata={'title': 'LM color'})
    hm_color: str = field(default='#ff0000', metadata={'title': 'HM color'})
    radius: float = 100.

class dbdtSection(Panel):
    dataframe = None
    highlighted: int = None
    buffer_start: int = 0
    buffer_len: int = 50

    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', dbdtSectionSettings(id='tTEM', title='Transect View Settings'))
        super().__init__(id='tTEM', settings=settings)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _prepare_x_axis(self, df):
        """
        Resolve the configured x-axis to a plottable column and axis label.
        site_id is left as-is; daytime is encoded as `date*100 + decimal_hour`
        (see temframe._sweeps_to_df: `daytime = date*100 + daytime`, where
        date is YYYYMMDD), so it's decoded back into a real timestamp
        (milliseconds since epoch) so Plotly can render it on a real date
        axis (see render(), which sets xaxis type='date' +
        tickformat='%H:%M:%S' for this case); longitude/latitude/distance
        are shown in meters (via the UTM-projected utm_x/utm_y/distance
        columns) rather than raw degrees. Falls back to the raw column if
        the meters-column isn't available (e.g. older sessions saved
        without utm_x/utm_y).
        """
        x_axis = self.settings.x_axis

        if x_axis.startswith('line'):
            line_id = int(float(x_axis.split(' ')[-1]))
            return df, f'_line_{line_id:0.0f}_x', x_axis

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
            return df, '_daytime_ms', 'Daytime'

        if x_axis == 'longitude' and 'utm_x' in df.columns:
            return df, 'utm_x', 'Longitude [m]'

        if x_axis == 'latitude' and 'utm_y' in df.columns:
            return df, 'utm_y', 'Latitude [m]'

        if x_axis == 'distance' and 'distance' in df.columns:
            return df, 'distance', 'Distance [m]'

        return df, x_axis, x_axis

    def _buffer_unit(self):
        """
        Map the user-facing "Buffer length" number to the raw units of the
        resolved x-axis column: site_id -> sites (factor 1), daytime ->
        minutes (the column is in milliseconds, so factor = 60_000),
        longitude/latitude/distance/line -> meters (factor 1).
        """
        x_axis = self.settings.x_axis
        if x_axis == 'daytime':
            return 'minutes', 60_000.0
        if x_axis in ('longitude', 'latitude', 'distance') or x_axis.startswith('line'):
            return 'm', 1.0
        return 'sites', 1.0

    def xlim(self, site_ids):

        x_axis = self.settings.x_axis
        if x_axis.startswith('line'):
            line_id = int(float(x_axis.split(' ')[-1]))
            line_col = f'_line_{line_id:0.0f}_x'

            from __main__ import sesh
            self.dataframe = sesh.data.copy()
            self.dataframe = self.dataframe.loc[np.abs(self.dataframe[line_col.replace('_x', '_y')])<self.settings.radius]

        df, x_col, _ = self._prepare_x_axis(self.dataframe)
        new_df = df[df['site_id'].isin(site_ids)][x_col].values
        if len(new_df) == 0:
            return None, None
        xmin, xmax = new_df.min(), new_df.max()
        dx = xmax-xmin
        xmax+= 0.1*dx
        xmin-= 0.1*dx
        return xmin,xmax

    def compare_synthetic(self):
        y_axis                                             = self.settings.y_axis
        df_tmp, x_axis, _ = self._prepare_x_axis(self.dataframe.copy())
        df_tmp                                             = df_tmp.sort_values(['gate_id', x_axis])
        df_tmp['include'] = df_tmp['inuse_manual'].astype(bool, copy=False).fillna(df_tmp['inuse_auto'])

        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor

        # dbdt_syn is a column on sesh.data as a whole once ANY site has
        # ever been inverted in this session -- it isn't necessarily
        # populated for every site (e.g. sites merged in from a later
        # upload, not yet inverted). Fall back to the observed value
        # per-site rather than per-dataframe, so the colored LM/HM line
        # always has something to draw: observed pre-inversion, synthetic
        # once that specific site has been inverted.
        if 'dbdt_syn' not in df_tmp.columns:
            df_tmp['dbdt_syn'] = np.nan

        df_tmp.loc[df_tmp['system_id'] % 2 == 0, 'dbdt_syn']  *= lm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 1, 'dbdt_syn']  *= hm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 1, 'dbdt']      *= hm_factor

        df_tmp['dbdt_line'] = df_tmp['dbdt_syn'].where(df_tmp['dbdt_syn'].notna(), df_tmp['dbdt'])
        df_tmp['is_synthetic'] = df_tmp['dbdt_syn'].notna()

        df_tmp['system_id']                                = np.where(df_tmp['system_id'] % 2 == 0, 'lm', 'hm')

        x_vals = np.sort(df_tmp[x_axis].unique())

        if x_axis == 'site_id':
            x_vals = x_vals[x_vals > -1]

        # buffer_start/buffer_len are in the same physical units as the
        # resolved x-axis column (site count / minutes / meters) -- zoom
        # into that window, same as observed_only(). This method renders
        # instead of observed_only() once dbdt_syn exists (e.g. after
        # running an inversion), so without this the buffer stops syncing
        # the moment that happens.
        buffer_start = self.buffer_start
        buffer_len   = self.buffer_len

        x_slice = x_vals[(x_vals >= buffer_start) & (x_vals <= buffer_start + buffer_len)]

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
        df_tmp.loc[(~df_tmp['include']), 'dbdt_line'] = np.nan



        fig3 = px.scatter(
            df_tmp,
            x=x_axis,
            y='dbdt',
            color_discrete_sequence=["black", "black"],
            color="system_id",
            error_y=error_ub,
            error_y_minus=error_lb,
        )

        line_traces = _synthetic_observed_line_traces(
            df_tmp, x_axis, 'dbdt_line', 'gate_id',
            self.settings.lm_color, self.settings.hm_color,
            ["system_id", "data_id", "site_id"],
        )

        for trace in fig3.data:
            fig.add_trace(trace)

        for trace in line_traces:
            trace.line.width = 1.5
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
        fig.update_layout(legend_title_text=None)
        fig.update_xaxes(range=[xmin-0.01*dx, xmax+0.01*dx])

        return fig

    def observed_by_gate_id(self):
        y_axis                                             = self.settings.y_axis
        df_tmp, x_axis, _ = self._prepare_x_axis(self.dataframe.copy())
        df_tmp                                             = df_tmp.sort_values(['gate_id', x_axis])
        df_tmp['include'] = df_tmp['inuse_manual'].astype(bool, copy=False).fillna(df_tmp['inuse_auto']).astype(bool)
        # lm_factor = compute_lm_scaling(self.dataframe, self.settings.lm_factor)
        lm_factor = self.settings.lm_factor
        hm_factor = self.settings.hm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 0, 'dbdt']      *= lm_factor
        df_tmp.loc[df_tmp['system_id'] % 2 == 1, 'dbdt']      *= hm_factor
        df_tmp.loc[df_tmp['site_id'] ==  -1, 'include']  = False
        df_tmp['system_id']                                = np.where(df_tmp['system_id'] % 2 == 0, 'lm', 'hm')

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
        if x_axis.startswith('line'):
            line_id = int(float(x_axis.split(' ')[-1]))
            x_axis = f'_line_{line_id:0.0f}_x'
            from __main__ import sesh
            self.dataframe = sesh.data.copy()
            self.dataframe = self.dataframe.loc[np.abs(self.dataframe[x_axis.replace('_x', '_y')])<self.settings.radius]
            if self.dataframe.empty:
                # No TEM data within the drawn line's radius -- compare_synthetic()
                # (and observed_by_gate_id()) both assume non-empty data and crash
                # (e.g. .min() on a zero-size array) otherwise. This panel (the
                # Transect/dB-dt view) never plots boreholes, unlike
                # ModelSection, so the message is unconditional here.
                return _no_data_figure("No TEM models and Boreholes in the search radius")
            x_min = 0
            x_max = sesh.lines[sesh.lines.line==line_id].total_length.max()
        # elif hasattr(self, 'xlim'):
        #     x_min,x_max = self.xlim
        else:
            x_min = None
            x_max = None

        if self.settings.y_axis=='gate_id':
            return self.observed_by_gate_id()

        fig = self.compare_synthetic()

        df_full, x_axis, x_label = self._prepare_x_axis(self.dataframe)

        if self.highlighted is not None and self.dataframe is not None:

            # self.highlighted is a scalar from single-site callbacks but a
            # list from multi-select ones (unified_handler) -- this draws
            # one highlight rect, so use the first site either way rather
            # than crashing on `series == a_list`.
            highlighted = self.highlighted
            if isinstance(highlighted, (list, tuple, set, np.ndarray, pd.Series)):
                highlighted = next(iter(highlighted), None)

            selected_df = df_full[df_full["site_id"] == highlighted]

            if not selected_df.empty:

                x_value = selected_df[x_axis].iloc[0]

                # Compute spacing dynamically
                x_vals = np.sort(df_full[x_axis].dropna().unique())

                if len(x_vals) > 1:
                    diffs = np.diff(x_vals)
                    dx = np.median(diffs) * 0.5
                else:
                    dx = 0.5

                fig.add_shape(
                    type="rect",
                    x0=x_value - dx,
                    x1=x_value + dx,
                    y0=self.dataframe["dbdt"].abs().min() * 0.5,
                    y1=self.dataframe["dbdt"].max()*self.settings.lm_factor *4,
                    line=dict(color="rgba(0,0,0,0.8)", width=1.5),
                    fillcolor="rgba(0,0,0,0.0)",
                )
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

        xaxis_kwargs = dict(
            showline=True,
            mirror=True,
            linewidth=1,
            linecolor="black"
        )
        if self.settings.x_axis == 'daytime':
            # daytime is plotted as milliseconds-since-epoch (see
            # _prepare_x_axis) so Plotly's date axis can render real
            # hh:mm:ss tick labels instead of a raw timestamp number.
            # Use tickformatstops rather than a flat tickformat so a
            # multi-day view doesn't show "00:00:00" on every tick (day
            # boundaries) with no way to tell the days apart.
            day_ms = 1000 * 60 * 60 * 24
            xaxis_kwargs.update(
                type='date',
                tickformatstops=[
                    dict(dtickrange=[None, day_ms], value='%H:%M:%S'),
                    dict(dtickrange=[day_ms, None], value='%Y-%m-%d %H:%M'),
                ],
            )

        fig.update_layout(
            yaxis_type="log",
            yaxis_range=[self.settings.dbdt_min, self.settings.dbdt_max],
            xaxis_title=x_label,
            yaxis_title="dB/dt [V / m²]",
            margin={"l": 55, "r": 40, "t": 10, "b": 50},
            dragmode='select',
            xaxis=xaxis_kwargs,
            yaxis=dict(
                showline=True,
                mirror=True,
                linewidth=1,
                linecolor="black"
            ))
        fig.update_layout(
            legend=dict(x=0.95, y=0.95,xanchor="right",yanchor="top",bgcolor="rgba(255,255,255,0.8)"),
            modebar=dict(add=['lasso'], remove=['zoomIn', 'zoomOut', 'toImage', 'plotly-logomark', 'autoScale', 'resetScale2d', 'pan2d'])
        )
        if x_min is not None and x_max is not None:
            fig.update_xaxes(range=[x_min, x_max], autorange=False)
        else:
            fig.update_xaxes(autorange=False)
        return fig    

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
                                                    '💾 Save DEM + KML',
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
        session_text += "- [📁 open session](#open_session)\n"
        return html.Div([
            dcc.Markdown("# Welcome to sea anemone", style={'textAlign': 'center'}),       
            dcc.Markdown("### Upload your data to get started."),
            self.render(),
            html.Div([
                html.Div(['Working directory: '], id="current-working-directory-label", style={"marginLeft":"10px", "marginTop": "10px", 'display': 'inline-block'}),
                html.A("📁 Select directory", href="#change_working", id="current-working-directory", style={"cursor": "pointer", "color": "blue", "textDecoration": "underline", "marginLeft":"10px", "marginTop": "10px", 'display': 'inline-block'}, title='change directory')
            ]),
            dcc.Markdown("---"),
            dcc.Markdown(session_text),
            html.Div(
                "Developed by HydroGeophysics Group, Aarhus University",
                style={
                    'position': 'absolute', 'bottom': '4px', 'left': '12px',
                    'fontSize': '11px', 'color': '#888',
                }
            ),
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
            // TEMPORARY DEBUG -- tracking down the disabled-overlay/
            // legend visibility bug. Piggybacked onto this callback (a
            // standalone Output('map','id')/Input('map','id')
            // clientside_callback in app.py never actually fired --
            // likely something about how dash_flexlayout mounts the map
            // tab's contents), since THIS one is already confirmed to
            // run reliably. Attaches Plotly.js event listeners to the
            // map's graph div and console.logs what Plotly actually does
            // with trace visibility on legend clicks and redraws.
            // Compare against the matching "[map.render DEBUG]" print in
            // map.py's Map.render() (what the server thinks it sent).
            // Remove once the bug's root cause is confirmed.
            (function attachMapDebugListeners(attempt) {
                attempt = attempt || 0;
                // dcc.Graph's id lands on a WRAPPER div in this Dash
                // version -- the actual Plotly-managed element (the one
                // with .on()/.data/.layout) is a descendant carrying the
                // js-plotly-plot/plotly-graph-div classes Plotly.js
                // always adds to whatever div it draws into. Trying
                // getElementById('map') directly here first (in case
                // some other Dash version puts it right on that element)
                // and falling back to searching inside it is what a
                // first attempt at this got silently stuck on forever --
                // logging every ~5s below so that's visible if it's
                // STILL not finding it.
                var container = document.getElementById('map');
                var gd = (container && typeof container.on === 'function')
                    ? container
                    : (container && (container.querySelector('.js-plotly-plot') || container.querySelector('.plotly-graph-div')));
                if (!gd || typeof gd.on !== 'function') {
                    if (attempt % 10 === 0) {
                        console.log('[map DEBUG] still looking for the plot div (attempt ' + attempt + '), container found=' + !!container);
                    }
                    setTimeout(function() { attachMapDebugListeners(attempt + 1); }, 500);
                    return;
                }
                if (gd._debugListenersAttached) { return; }
                gd._debugListenersAttached = true;
                console.log('[map DEBUG] listeners attached to #map');

                gd.on('plotly_legendclick', function(evt) {
                    var trace = gd.data[evt.curveNumber];
                    console.log('[map DEBUG] legendclick curveNumber=' + evt.curveNumber +
                        ' name=' + trace.name + ' uid=' + trace.uid +
                        ' legendgroup=' + trace.legendgroup +
                        ' visible(before-click)=' + trace.visible);
                });
                gd.on('plotly_restyle', function(evt) {
                    console.log('[map DEBUG] restyle event=' + JSON.stringify(evt));
                });
                gd.on('plotly_afterplot', function() {
                    var summary = gd.data.map(function(t) {
                        return {
                            name: t.name, uid: t.uid, legendgroup: t.legendgroup,
                            visible: t.visible, n: (t.lat || []).length,
                        };
                    });
                    console.log('[map DEBUG] afterplot layout.uirevision=' + gd.layout.uirevision +
                        ' legend.uirevision=' + (gd.layout.legend ? gd.layout.legend.uirevision : undefined) +
                        ' traces=' + JSON.stringify(summary));
                });
            })();

            window.addEventListener('beforeunload', function(event) {
                // Best-effort silent save -- sendBeacon (not fetch/XHR)
                // since a normal request isn't guaranteed to complete in
                // the tiny window browsers give an unload handler. See
                // beacon_save_session in app.py: it silently no-ops if no
                // save directory has been chosen yet.
                navigator.sendBeacon('/_beacon_save_session');
                // Standard "Leave site? Changes may not be saved" browser
                // dialog -- browsers ignore any custom message text for
                // security reasons, this is just how you trigger their
                // own built-in one.
                event.preventDefault();
                event.returnValue = '';
            });
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
                
                // Arrow keys without Ctrl, but only if not typing in an
                // input. The comment always said "without Ctrl" but the
                // check itself never actually excluded it -- so
                // Ctrl+ArrowLeft/Right (meant only for Previous/Next
                // buffer, handled above) was *also* firing
                // highlight_prev/highlight_next at the same time, racing
                // two conflicting callbacks against each other.
                if (!isInputFocused && !event.ctrlKey) {
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
                    if (event.key == 'Escape') {
                        document.getElementById('clearSelectionButton').click()
                        event.preventDefault()
                        event.stopPropagation()
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
                    html.Div(style={'width':'6px'}, id='disable-enable-spacer'),
                    dbc.Button("Enable  [ctrl+e]", id='enableButton'),
                    html.Div(style={'width':'6px'}),
                    dbc.Button("Clear Selection [Esc]", id='clearSelectionButton'),
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
                                    step='any',
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
                    html.Div(dbc.Toast(id="report-toast",header="Report Generated",is_open=False,dismissable=True,duration=8000,icon="success",
                        style={"position": "fixed","top": "140px","right": "20px","width": 350,"zIndex": 9999})),
                    # Progress popup for report generation -- backdrop='static'/keyboard=False
                    # so it can't be dismissed mid-render (the button click callback is still
                    # running synchronously; closing this early wouldn't stop it). Polled by
                    # report-progress-poll while report.generate_report() runs -- see
                    # report.REPORT_PROGRESS and app.py's update_report_progress callback.
                    dbc.Modal([
                        dbc.ModalHeader(dbc.ModalTitle("Generating Report")),
                        dbc.ModalBody([
                            html.Div(id="report-progress-label", children="Preparing figures..."),
                            html.Div(style={'height': '10px'}),
                            dbc.Progress(id="report-progress-bar", value=0, max=100, striped=True, animated=True, style={"height": "18px"}),
                        ]),
                    ], id="report-progress-modal", is_open=False, backdrop='static', keyboard=False),
                    dcc.Interval(id="report-progress-poll", interval=600, n_intervals=0, disabled=True),
                    dbc.ButtonGroup([
                        dbc.Button("💾 Save session [ctrl+s]", id='saveButton'),
                        html.Div(style={'width':'6px'}),
                        dbc.Button("📄 Generate report", id='generateReportButton'),
                    ]),
                    html.Div(style={'width':'30px'}),
                    dbc.Tooltip("Save the current session to the default location or select a folder", target='saveButton', placement='top'),
                    dbc.Tooltip("Generate a QC report (.docx) into the session's save folder.", target='generateReportButton', placement='top'),
                    dbc.Tooltip("Used to disable noisy data or data which cannot be fitted in inversions.", target='disableButton', placement='top'),
                    dbc.Tooltip("Used to enable previously disabled data.", target='enableButton', placement='top'),
                    dbc.Tooltip("Clear the current selection across all panels.", target='clearSelectionButton', placement='top'),
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
            Input("tTEM", "figure"),  # ← triggers immediately when the transect x-axis (or any other setting) changes
            prevent_initial_call=False
        )
        def update_buffer_progress(buffer_data, _, __):
            from __main__ import sesh, dbdt2, refresh_dbdt2_for_line_mode

            if sesh.data is None or "site_id" not in sesh.data.columns:
                return 0, "No data loaded"

            if dbdt2.dataframe is None:
                return 0, "No data loaded"

            refresh_dbdt2_for_line_mode()
            df, x_axis, _label = dbdt2._prepare_x_axis(dbdt2.dataframe)
            if x_axis == "site_id":
                df = df[df["site_id"] != -1]
            x_vals = df[x_axis].dropna().values

            if len(x_vals) == 0:
                return 0, "No sites"

            unit, factor = dbdt2._buffer_unit()

            x_min, x_max = x_vals.min(), x_vals.max()
            total_span = max(x_max - x_min, 1e-9)

            start  = buffer_data.get("start_site", x_min)
            length = buffer_data.get("length", 0)

            # Report *position* within the dataset (elapsed from the start
            # up to the end of the current window), not just the window's
            # width -- otherwise this never changes as you page through,
            # since the width stays ~constant at the configured length.
            elapsed_start = max(0.0, max(start, x_min) - x_min)
            elapsed_end   = max(0.0, min(start + length, x_max) - x_min)
            percent = (elapsed_end / total_span) * 100

            fmt = (lambda v: f"{v:.0f}") if unit == "sites" else (lambda v: f"{v:.1f}")

            return percent, f"{fmt(elapsed_start / factor)}–{fmt(elapsed_end / factor)} of {fmt(total_span / factor)} {unit}"
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
            Output("disableButton", "style"),
            Output("disable-enable-spacer", "style"),

            Output("beginning-buffer", "style"),
            Output("prev-buffer", "style"),
            Output("next-buffer", "style"),
            Output("highlight_prev", "style"),
            Output("highlight_next", "style"),
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
                {},  # disableButton -- shown (QC tab: still a working Disable button)
                {"width": "6px"},  # disable-enable-spacer
                shown,  # beginning-buffer
                shown,  # prev-buffer
                shown,  # next-buffer
                shown,  # highlight_prev
                shown,  # highlight_next
                'Previous',  # highlight_prev children
                'Next',  # highlight_next children
                {"width": "70px","height": "32px","fontSize": "13px"},  # buffer-length-input
                shown,  # buffer-progress
                shown,  # buffer-progress-text
                shown,  # buffer-length-label
            )
            return (
                "Delete",
                "📤 Export",
                {"display": "none"},  # disableButton -- Interpret tab: no longer wired to anything, remove it
                {"display": "none"},  # disable-enable-spacer
                hidden,  # beginning-buffer
                hidden,  # prev-buffer
                hidden,  # next-buffer
                hidden,  # highlight_prev -- Previous/Next profile no longer used on this tab
                hidden,  # highlight_next
                "Previous profile",  # highlight_prev children
                "Next profile",  # highlight_next children
                hidden,  # buffer-length-input
                hidden,  # buffer-progress
                hidden,  # buffer-progress-text
                hidden,  # buffer-length-label
            )


@nosj
class TableOverviewSettings(PanelSettings):
    max_rows: int = 100


class TableOverview(Panel):
    """
    QC tab's "Table Overview" -- a plain, sortable/filterable per-site
    summary table (id='table_overview'). layouts.py's `review` layout
    already references a 'tab-table_overview' tab, but no panel with that
    id was ever registered in app.py's `panels` list, so the tab rendered
    completely empty. Mirrors sesh.overview (the same per-site table Map
    itself is seeded from), set via app.py wherever m1.dataframe is
    refreshed from sesh.overview.
    """
    dataframe = None

    def __init__(self, **kwargs):
        settings = kwargs.pop('settings', TableOverviewSettings(id='table_overview'))
        super().__init__(id='table_overview', settings=settings, childname='children')
        for key, value in kwargs.items():
            setattr(self, key, value)

    def render(self):
        if self.dataframe is None or self.dataframe.empty:
            return html.Div("No data loaded yet.", style={'padding': '20px', 'color': '#888'})
        # Internal 'line N' projection columns (added once a line is drawn
        # on the map, see session.py's line_update) aren't meaningful in a
        # flat overview table -- leave them out.
        columns = [c for c in self.dataframe.columns if not c.startswith('_')]
        return dash_table.DataTable(
            data=self.dataframe[columns].to_dict('records'),
            columns=[{"name": c, "id": c} for c in columns],
            page_size=self.settings.max_rows,
            sort_action="native",
            filter_action="native",
            style_table={'overflowX': 'auto', 'height': '100%'},
            style_cell={'textAlign': 'left', 'padding': '5px', 'fontSize': '12px'},
            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
        )

    def initialize(self):
        return html.Div(
            [
                html.Div(self.render(), id=self.id, style={'height': '100%', 'overflow': 'auto'}),
                gear_maker(self.id),
            ],
            style={'height': '100%', 'position': 'relative', 'margin': '4px'}
        )
