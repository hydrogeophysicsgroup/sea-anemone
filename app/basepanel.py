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

# Shared look for the small floating control boxes that sit directly on
# top of a plot (e.g. Map's plot-by/mean-res selects, Model Section's
# x-axis/radius controls) -- factored out here so every panel that has
# one gets the same background/padding/shadow instead of each panel
# hand-rolling its own slightly different box.
FLOATING_BOX_STYLE = {
    "position": "absolute",
    "display": "flex",
    "flexDirection": "column",
    "gap": "8px",
    "zIndex": 1000,
    "backgroundColor": "rgba(255,255,255,0.9)",
    "padding": "8px 10px",
    "borderRadius": "8px",
    "boxShadow": "0 1px 4px rgba(0,0,0,0.25)",
}

FLOATING_BOX_ROW_STYLE = {"display": "flex", "alignItems": "center", "gap": "8px"}

FLOATING_BOX_LABEL_STYLE = {"width": "90px", "textAlign": "right", "fontSize": "13px"}

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

def update_tabset(json_data, target_tab_id, settings_tab_id, change_order=False, name=None):
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
            # A caller-supplied name (e.g. a panel's settings.title) takes
            # priority; falls back to deriving one from the raw tab id
            # (e.g. 'tab-tTEM' -> 'tTEM settings') for panels that don't
            # set a nicer title.
            'name': name if name else target_tab_id.replace('tab-', '')+' settings',
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
    # Plain class attribute (no type annotation), NOT a dataclass field --
    # subclasses can override with a set of schema property names to omit
    # from the auto-generated gear form. Needed for internal/non-primitive
    # fields (e.g. a dict holding viewport state): the generic render()
    # fallback renders any field without a dedicated special_renders match
    # as a plain text dbc.Input, and update_render() (Panel.add_callbacks)
    # writes that Input's raw string value straight back via setattr on
    # every settings-form change (not just changes to that specific field,
    # since all settings inputs share one pattern-matching callback) --
    # silently corrupting a dict-typed field into a string the next time
    # any OTHER setting changes.
    hidden_settings = frozenset()
    # Plain class attribute (see hidden_settings above) -- subclasses can
    # override with {field_key: {enum_value: 'Nice Label'}} to give an
    # enum field's choices friendlier display text than their raw values.
    # dataclasses_jsonschema's field metadata only recognizes title/
    # description/examples/extensions/read_only/write_only, not a per-
    # choice label, so enum choice labels can't be set the same way
    # `metadata={'title': ...}` sets a field's own row label.
    enum_labels = {}
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
            labels = self.enum_labels.get(key, {})
            return dbc.Select(
                options=[{"label": labels.get(v, v), "value": v} for v in prop['enum']],
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
            if key in self.hidden_settings:
                continue
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
                step = None
                if prop.get('type') == 'number':
                    input_type = 'number'
                    # 'any': without it the browser's default step of 1
                    # marks decimals like 0.5 invalid and sends None.
                    step = 'any'
                elif prop.get('type') == 'integer':
                    input_type = 'number'
                    step = 1
                row_children.append(
                    dbc.Input(
                        type=input_type,
                        step=step,
                        id={'type': f'settings-{self.id}', 'key': key},
                        value=eval(f'self.{key}'),
                        # Send 0.6 s after the last change. debounce=True
                        # only sent on Enter/blur, so the up/down arrows
                        # changed the number on screen but never applied it.
                        debounce=600,
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
                return update_tabset(model, f'tab-{self.id}', f'tab-{self.id}_settings', change_order=True, name=self.title)
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
        all_keys = [k for k in self.schema.get('properties', {}).keys() if k not in self.hidden_settings]
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
        
        