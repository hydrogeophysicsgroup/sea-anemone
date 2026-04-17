import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.express as px

def create(df, id='map'):
    from plotly.express import scatter_map
    from dash.dcc import Graph

    map = scatter_map(df, lat="latitude", lon="longitude", zoom=14,  color_discrete_sequence=['red'])
    map.update_layout(map_style="white-bg",
        map_layers=[
            {
                "below": 'traces',
                "sourcetype": "raster",
                "sourceattribution": "Google Earth (C)",
                "source": ['https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}']
            }])
    map.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    return Graph(figure=map, id=id)

class Panel:
    def __init__(self, id, data=None, settings_schema=None, settings=None):
        self.id = id
        self.data = data
        self.settings_schema = settings_schema or {}
        self.settings = settings or {}

    def render(self):
        # Main panel content (to be overridden by subclasses)
        return html.Div([html.H3(f"Panel: {self.id}")])

    def render_settings(self):
        # Render settings form based on JSON schema
        if not self.settings_schema:
            return html.Div("No settings available.")
        form_items = []
        for key, prop in self.settings_schema.get('properties', {}).items():
            row_children = []
            row_children.append(dbc.Label(prop.get('title', key), style={'marginRight': '10px'}))
            # Use Dash DAQ ColorPicker if the key or title suggests a color
            if 'color' in key.lower():
                import dash_daq as daq
                row_children.append(
                    daq.ColorPicker(
                        id={'type': f'settings-{self.id}', 'key': key},
                        label=key.lower(),
                        value={'hex': self.settings.get(key, prop.get('default', '#ff0000'))},
                        size=164,
                        style={'margin': '5px'}
                    )
                )
            elif 'enum' in prop:
                row_children.append(
                    dbc.Select(
                        options=[{"label": v, "value": v} for v in prop['enum']],
                        id={'type': f'settings-{self.id}', 'key': key},
                        value=self.settings.get(key, prop.get('default', '')),
                        style={'margin': '5px'}
                    )
                )
            else:
                input_type = 'text'
                if prop.get('type') == 'number':
                    input_type = 'number'
                elif prop.get('type') == 'boolean':
                    input_type = 'checkbox'
                row_children.append(
                    dbc.Input(
                        type=input_type,
                        id={'type': f'settings-{self.id}', 'key': key},
                        value=self.settings.get(key, prop.get('default', '')),
                        style={'margin': '5px'}
                    )
                )
            form_items.append(dbc.Row(row_children, className='mb-2'))
        return dbc.Form(form_items)

    def to_nodes(self):
        # Returns a layout with panel and settings tab
        return dbc.Tabs([
            dbc.Tab(self.render(), label="Panel"),
            dbc.Tab(self.render_settings(), label="Settings")
        ])

# Example subclass for a map panel
class MapPanel(Panel):
    def render(self):
        zoom  = self.settings.get('zoom', 14)
        #color = self.settings.get('color', {'hex':"#ff0000"})['hex']
        #color = self.settings.get('color', 'red')

        fig = px.scatter_mapbox(self.data, lat="latitude", lon="longitude", zoom=zoom, color_discrete_sequence=['red'])
        fig.update_layout(map_style="white-bg",
            map_layers=[
                {
                    "below": 'traces',
                    "sourcetype": "raster",
                    "sourceattribution": "Google Earth (C)",
                    "source": ['https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}']
                }])
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
        return dcc.Graph(figure=fig, id=self.id)

from dataclasses import dataclass, field
from typing import Literal

@dataclass
class MapSettings:
    zoom: int = 14
    color: Literal["red", "blue", "green", "orange"] = "red"

from dataclasses_jsonschema import JsonSchemaMixin



class MapSettingsSchema(MapSettings, JsonSchemaMixin):
    pass

settings_schema = MapSettingsSchema.json_schema()



# # Example usage:
# settings_schema = {
#     "type": "object",
#     "properties": {
#         "zoom":  {"type": "number", "title": "Zoom Level", "default": 14},
#         "color": {
#             "type": "string",
#             "title": "Marker Color",
#             "default": "red",
#             "enum": ["red", "blue", "green", "orange"]
#         }
#     }
# }
# panel = MapPanel("map1", data=df, settings_schema=settings_schema)
# app.layout = panel.to_nodes()

