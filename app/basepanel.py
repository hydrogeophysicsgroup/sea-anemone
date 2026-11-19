from typing import Literal
from nosj import nosj

import dash_bootstrap_components as dbc
from dash import  html, Output, Input, dcc, State,ALL, MATCH
from dash.exceptions import PreventUpdate

import dash_flexlayout as dfl

from dataclasses import dataclass
from dataclasses_jsonschema import JsonSchemaMixin

import plotly.express as px
import plotly.graph_objects as go

import numpy as np
import pandas as pd



def site_positions(df, x_axis):
    """x-position of each site along x_axis (indexed by site_id, sorted by position)"""
    if df is None or x_axis not in df.columns:
        return pd.Series(dtype=float)
    return df[df['site_id'] != -1].groupby('site_id')[x_axis].first().dropna().sort_values()


def site_lookup(df, x_axis):
    """x-position of each site along x_axis, stored in layout.meta so the browser can map a hovered x back to a site (map hover marker)."""
    site_x = site_positions(df, x_axis)
    return {'site_x': site_x.values.tolist(), 'site_id': site_x.index.tolist()}


class SiteBuffer:
    """The window of `length` consecutive sites that the section panels zoom to and the sounding panels show, plus the
    sites selected on the map. Shared by the panels and read when they render, so every render shows the current window.
    Sites are counted in the order they appear along the section x axis (site_id, daytime or distance along a line),
    taken from `section`'s settings."""
    def __init__(self, length=50):
        self.start = 0
        self.length = length
        self.selected = []
        self.section = None

    def sites(self):
        from __main__ import sesh
        df = sesh.data if sesh.data is not None else sesh.models
        if df is None or self.section is None:
            return np.array([], dtype=int)
        x_axis = self.section.settings.x_axis
        if x_axis not in df.columns:
            return np.array([], dtype=int)
        if x_axis.startswith('_line'):
            df = df.loc[np.abs(df[x_axis.replace('_x', '_y')]) < self.section.settings.radius]
        return site_positions(df, x_axis).index.to_numpy()

    def _clamp(self, n_sites):
        self.start = int(np.clip(self.start, 0, max(0, n_sites - self.length)))

    def window(self):
        sites = self.sites()
        self._clamp(len(sites))
        return sites[self.start:self.start + self.length]

    def reset(self):
        self.start = 0
        self.selected = []

    def step(self, n_windows):
        self.start += n_windows * self.length
        self._clamp(len(self.sites()))

    def center_on(self, site_ids):
        """centre the window on site_ids (the ones on the current axis); False if none of them are"""
        sites = self.sites()
        idx = np.flatnonzero(np.isin(sites, site_ids))
        if len(idx) == 0:
            return False
        self.start = int(round((idx.min() + idx.max()) / 2 - (self.length - 1) / 2))
        self._clamp(len(sites))
        return True

    def scroll_to(self, site_id, margin=5):
        """slide the window just far enough to show site_id with `margin` sites to spare"""
        sites = self.sites()
        idx = np.flatnonzero(sites == site_id)
        if len(idx) == 0:
            return
        i, margin = int(idx[0]), min(margin, (self.length - 1) // 2)
        if i < self.start + margin:
            self.start = i - margin
        elif i > self.start + self.length - 1 - margin:
            self.start = i - self.length + 1 + margin
        self._clamp(len(sites))

    def store(self):
        """state for the 'data-buffer' store (buffer progress bar)"""
        return {'length': self.length, 'start_site': self.start, 'total': len(self.sites())}


def half_spacing(site_x):
    if len(site_x) > 1:
        return site_x.diff().median() / 2
    return pd.Timedelta(seconds=30) if pd.api.types.is_datetime64_any_dtype(site_x) else 0.5


def apply_site_buffer(fig, site_x, buffer):
    """zoom a section figure to the buffer window and outline the selected sites (dotted, one box per run of
    neighbouring sites); site_x as from site_positions. Returns the x range, or None if no window sites are on the plot."""
    if buffer is None or len(site_x) == 0:
        return None
    dx = half_spacing(site_x)
    in_view = site_x[site_x.index.isin(buffer.window())]
    xrange = None
    if len(in_view):
        xrange = [in_view.iloc[0] - dx, in_view.iloc[-1] + dx]
        fig.update_xaxes(range=xrange, autorange=False)
    pos = np.flatnonzero(site_x.index.isin(buffer.selected))
    for run in np.split(pos, np.flatnonzero(np.diff(pos) > 1) + 1) if len(pos) else []:
        fig.add_shape(type='rect', xref='x', yref='paper', x0=site_x.iloc[run[0]] - dx, x1=site_x.iloc[run[-1]] + dx,
                      y0=0, y1=1, line=dict(color='black', width=1.5, dash='dot'), fillcolor='rgba(0,0,0,0)',
                      name='site-selection')
    return xrange


def site_buffer_static_shapes(fig):
    return [shape.to_plotly_json() for shape in fig.layout.shapes or () if shape.name != 'site-selection']


def axis_menu(target, options, value=None, live=True):
    """Menu shown when the user clicks an axis or colour bar title (assets/axismenu.js), stored in layout.meta['menus'].
    Picking an option sets `value` on the component `target`; options are (label, value) pairs or plain values.
    With live=True the browser lists the target's own options when it has them (they may be newer than the figure)."""
    options = [{'label': o[0], 'value': o[1]} if isinstance(o, tuple) else {'label': str(o), 'value': o} for o in options]
    return {'target': target, 'options': options, 'value': value, 'live': live}


def section_x_menu():
    """x-axis menu of the section plots: drives the model section's x-axis dropdown, which the tTEM section follows."""
    from __main__ import sesh
    options = ['site_id', 'daytime']
    if sesh.lines is not None:
        options = [f'line {line_id:0.0f}' for line_id in sesh.lines['line'].unique()] + options
    return axis_menu('model_section_axis', options)


def parse_mean_res(value):
    """mean-res interval from the map's interval dropdown: '0-5' -> ('depth', 0, 5) (m below ground),
    'elev 420 410' -> ('elevation', 420, 410) (top and bottom elevation of the slice)"""
    if value.startswith('elev '):
        top, bot = [float(v) for v in value.split()[1:]]
        return 'elevation', top, bot
    top, bot = [float(v) for v in value.split('-')]
    return 'depth', top, bot


def axis_label(x_axis):
    """'_line_1_x' -> 'line 1'"""
    return x_axis.replace('_x', '').replace('_', ' ').strip()


def gear_maker(id):
    gear = html.Div(
        html.Span(
            [html.Img(id=id+'_gear', src="./assets/settings.svg", style={'height': '0.5cm'})],
            style={'cursor': 'pointer', 'position': 'absolute', 'bottom': '0', 'right': '0'}
        ),
    )
    return gear

def find_tab_by_id(tabs, tab_id, path=None):
    if path is None: path = []

    if isinstance(tabs, dict):
        if 'id' in tabs and tabs['id'] == tab_id:
            return path
        for key, value in tabs.items():
            if isinstance(value, (dict, list)):
                new_path = find_tab_by_id(value, tab_id, path=path + [key])
                if new_path:  # If a valid path is found, return it
                    return new_path
    elif isinstance(tabs, list):
        for i, item in enumerate(tabs):
            new_path = find_tab_by_id(item, tab_id, path=path + [i])
            if new_path:  # If a valid path is found, return it
                return new_path
    return None

def update_tabset(json_data, target_tab_id, settings_tab_id, change_order=False):
    accessor_chain = find_tab_by_id(json_data, target_tab_id)
    accessor_string = ''
    for key in accessor_chain[:-1]:
        if isinstance(key, int):
            accessor_string += f'[{key}]'
        else:
            accessor_string += f'["{key}\"]'
    tablist = eval('json_data' + accessor_string)
    tabset = [x['id'] for x in eval('json_data' + accessor_string)]
    idx = tabset.index(target_tab_id)
    if settings_tab_id not in tabset:
        tablist.insert(idx+1, {
            'type': 'tab',
            'id': settings_tab_id,
            'name': target_tab_id.replace('tab-', '')+' settings',
            'component': 'text',
        })
        tabset.insert(idx+1, settings_tab_id)
    elif change_order:
        ctab = tablist.pop(tabset.index(settings_tab_id))
        tablist.insert(idx+1, ctab)

    accessor_string = ''
    for key in accessor_chain[:-2]:
        if isinstance(key, int):
            accessor_string += f'[{key}]'
        else:
            accessor_string += f'["{key}\"]'
    exec(f'json_data{accessor_string}[\'selected\'] = {tabset.index(settings_tab_id)}')
    return json_data

def close_settings(json_data, target_tab_id, settings_tab_id):
    accessor_chain = find_tab_by_id(json_data, settings_tab_id)
    accessor_string = ''
    for key in accessor_chain[:-1]:
        if isinstance(key, int):
            accessor_string += f'[{key}]'
        else:
            accessor_string += f'["{key}\"]'
    tablist = eval('json_data' + accessor_string)
    tabset = [x['id'] for x in eval('json_data' + accessor_string)]
    idx = tabset.index(settings_tab_id)
    tablist.pop(idx)
    tabset.pop(idx)

    accessor_string = ''
    for key in accessor_chain[:-2]:
        if isinstance(key, int):
            accessor_string += f'[{key}]'
        else:
            accessor_string += f'["{key}\"]'
    
    exec(f'json_data{accessor_string}[\'selected\'] = {tabset.index(target_tab_id)}')
    return json_data

def add_tabset(json_data, new_tab, target_tab_id, settings_tab_id, change_order=False):
    accessor_chain = find_tab_by_id(json_data, new_tab)
    accessor_string = ''
    for key in accessor_chain[:-1]:
        if isinstance(key, int):
            accessor_string += f'[{key}]'
        else:
            accessor_string += f'["{key}\"]'
    tablist = eval('json_data' + accessor_string)
    tabset = [x['id'] for x in eval('json_data' + accessor_string)]
    idx = tabset.index(new_tab)
    if new_tab not in tabset:
        tablist.insert(idx+1, {
            'type': 'tab',
            'id': settings_tab_id,
            'name': target_tab_id.replace('tab-', '')+' settings',
            'component': 'text',
        })
        tabset.insert(idx+1, settings_tab_id)
    elif change_order:
        ctab = tablist.pop(tabset.index(settings_tab_id))
        tablist.insert(idx+1, ctab)

    accessor_string = ''
    for key in accessor_chain[:-2]:
        if isinstance(key, int):
            accessor_string += f'[{key}]'
        else:
            accessor_string += f'["{key}\"]'
    exec(f'json_data{accessor_string}[\'selected\'] = {tabset.index(settings_tab_id)}')
    return json_data




@dataclass
class PanelSettings:
    id: str
    _settings_schema: dict = None
    title: str = None
    def __init__(self, id):
        self.id = id

    def __post_init__(self):
        for key in self.schema.get('properties', {}).keys():
            try:
                if self.schema['properties'][key]['type'] == 'array':
                    if eval(f'self.{key}') is not None:
                        exec(f'self.{key}_len = len(self.{key})')
                    else:
                        exec(f'self.{key}_len = 0')
            except KeyError:
                pass

    def initialize(self):
        # Main panel content (to be overridden by subclasses)
        return html.Div([html.H3(f"Panel: {self.id}")])

    def special_renders(self):
        color_check = lambda key,prop: 'color' in key.lower()
        def color_render(key, prop):
            return dbc.Input(
                type='color',
                id={'type': f'settings-{self.id}', 'key': key},
                value=eval(f'self.{key}'),
                style={'width':'50px', 'height':'30px'}
            )
        enum_check = lambda key, prop: 'enum' in prop
        def enum_render(key, prop):
            return dbc.Select(
                options=[{"label": v, "value": v} for v in prop['enum']],
                id={'type': f'settings-{self.id}', 'key': key},
                value=eval(f'self.{key}'),
                style={'margin': '5px'}
            )
        bool_check = lambda key,prop: prop.get('type') == 'boolean'
        def bool_render(key,prop):
            return dbc.Checkbox(
                        id={'type': f'settings-{self.id}', 'key': key},
                        value=eval(f'self.{key}'),
                        style={'marginLeft': '5px'}
                        )
        return [
            (enum_check,  enum_render),
            (bool_check, bool_render),
            (color_check, color_render)
        ]

    def render(self):
        # Render settings form based on JSON schema
        if self.schema is None:
            return html.Div("No settings available.")
        form_items = [dcc.Markdown(f'# {self.id} settings') if self.title is None else dcc.Markdown(f'# {self.title}')]

        special_renders = self.special_renders()
        n_special_renders = len(special_renders)

        for key, prop in self.schema.get('properties', {}).items():
            row_children = []
            row_children.append(dbc.Label(prop.get('title', key), style={'marginRight': '10px'}))

            n_render = 0
            for check, render in special_renders:
                if check(key, prop):
                    row_children.append(render(key, prop))
                    break
                else:
                    n_render += 1
            if n_render == n_special_renders:
                input_type = 'text'
                if prop.get('type') == 'number':
                    input_type = 'number'
                row_children.append(
                    dbc.Input(
                        type=input_type,
                        id={'type': f'settings-{self.id}', 'key': key},
                        value=eval(f'self.{key}'),
                        debounce=True,
                        style={'margin': '5px'}
                    )
                )
            form_items.append(dbc.Row(row_children, className='mb-2'))
        return html.Div([dbc.Form(form_items, style={'margin': '10px'}), 
                         gear_maker(self.id+'_settings')], style={'width':'95%'})

    def node(self):
        return dfl.Tab(id=f'tab-{self.id}_settings', children=[self.render()])
    
    def update_attributes(self, data_dict):
        for key, value in data_dict.items():
            if hasattr(self, key):
                # Convert numeric strings to floats if necessary
                if isinstance(value, str) and value.replace('.', '', 1).isdigit():
                    value = float(value)
                setattr(self, key, value)

    @classmethod
    def _create_schema(cls):
        class tmp(cls, JsonSchemaMixin):
            pass
        schema = tmp.json_schema()
        return schema
    
    @property
    def schema(self):
        if self._settings_schema is None:
            tmp = self.__class__._create_schema()
            tmp['properties'].pop('_settings_schema')
            tmp['properties'].pop('id')
            tmp['properties'].pop('title')  # Remove title if it exists
            self._settings_schema = tmp
        return self._settings_schema
    
    @property
    def settings(self):
        return {k: getattr(self, k) for k in self.schema.get('properties', {}).keys() if hasattr(self, k)}
    
    @property
    def layout_dict(self):
        return {
            'type': 'tab',
            'id': f'tab-{self.id}_settings',
            'name': f'{self.id.lower()} settings',
        }
    
    def add_callbacks(self, app):

        
        @app.callback(
            Output('flex-layout', 'model', allow_duplicate=True),
            Input(f'{self.id}_gear', 'n_clicks'),
            State('flex-layout', 'model'),
            prevent_initial_call=True
        )
        def show_settings(n_clicks, model):
            if n_clicks:
                return update_tabset(model, f'tab-{self.id}', f'tab-{self.id}_settings', change_order=True)
            else:
                raise PreventUpdate        
        
        @app.callback(
            Output('flex-layout', 'model', allow_duplicate=True),
            Input(self.id+'_settings_gear', 'n_clicks'),
            State('flex-layout', 'model'),
            prevent_initial_call=True
        )
        def hide_settings(n_clicks, model):
            if n_clicks:
                return close_settings(model, f'tab-{self.id}', f'tab-{self.id}_settings')
            else:
                raise PreventUpdate

    @property
    def flat_keys(self):
        all_keys = list(self.schema.get('properties', {}).keys())
        key_elements = []
        for key in all_keys:
            if self.schema['properties'][key].get('type') == 'array':
                all_keys.remove(key)  # Remove list types from callbacks
                key_elements += [key+'-'+ str(i) for i in range(eval(f'self.{key}_len'))]
        all_keys = all_keys + key_elements
        return all_keys

@dataclass
class Panel:
    id: str
    settings: PanelSettings = None
    childname: str = 'figure'
    change_count: int = 0

    def add_callbacks(self, app):
        if self.settings is not None:
            self.settings.add_callbacks(app)
            def update_render(*args):
                for key, arg in zip(self.settings.flat_keys, args):
                    if isinstance(arg, dict) and 'hex' in arg:
                        arg = arg['hex']
                    
                    if hasattr(self.settings, key):
                        if self.settings.schema['properties'][key].get('type')=='integer':
                            arg = int(arg)
                        elif self.settings.schema['properties'][key].get('type')=='number':
                            arg = float(arg)
                        elif self.settings.schema['properties'][key].get('type')=='boolean':
                            arg = (arg=='true' or arg is True)
                        setattr(self.settings, key, arg)
                    elif '-' in key:
                        basekey,index = key.split('-')
                        if hasattr(self.settings, basekey):
                            arg = (arg=='true' or arg is True)
                            exec(f'self.settings.{basekey}[{index}] = arg')
                return self.render()        
            update_render = app.callback(Output(self.id, self.childname),
                        [Input({'type': f'settings-{self.id}', 'key': x}, 'value') for x in self.settings.flat_keys])(update_render)

            
    def initialize(self):
        children = [dcc.Graph(figure=self.render(), id=self.id, mathjax=True, clear_on_unhover=True, style={'height':'98%', 'width': '98%', 'align': 'center'})]
        if self.settings is not None:
            children.append(gear_maker(self.id))
        return html.Div(children,
                        style={'height': '100%'})

    def message_render(self, message):
        """empty figure with a message in the middle; the axes stay, so their title menus still work"""
        fig = go.Figure()
        fig.add_annotation(text=message, x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False)
        fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=False)
        fig.update_yaxes(showticklabels=False, showgrid=False, zeroline=False)
        return fig

    def empty_render(self):
        fig = px.scatter(title='No data available', labels={'x': 'X-axis', 'y': 'Y-axis'})
        return fig

    def to_nodes(self):
        nodes = []
        if self.settings is not None:
            nodes.append(self.settings.node())
        nodes.append(dfl.Tab(id=f'tab-{self.id}', children=[self.initialize()]))
        return nodes
    
    @property
    def layout_dict(self):
        return {
            'type': 'tab',
            'id': f'tab-{self.id}',
            'name': f'{self.id.lower()}',
        }
     
    @property
    def output(self):
        return Output(self.id, self.childname, allow_duplicate=True)
        
        