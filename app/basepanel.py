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
                    if arg is None:
                        continue
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
        children = [dcc.Graph(figure=self.render(), id=self.id, mathjax=True, style={'height':'98%', 'width': '98%', 'align': 'center'})]
        if self.settings is not None:
            children.append(gear_maker(self.id))
        return html.Div(children,
                        style={'height': '100%'})

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
        
        