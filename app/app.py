import sys, os
from tkinter import filedialog, Tk

fpath = os.path.dirname(os.path.abspath(__file__))
if fpath not in sys.path:
    sys.path.append(fpath)

import session
global sesh
sesh =  None#session.Session.from_workbench("C:\\Users\\au646858\\Downloads\\tTEM_Aug_HM_MOD_inv.xyz")
#sesh.save("C:\\Users\\au646858\\Downloads\\tTEM_Aug_HM_MOD_inv_session\\")

if sesh is None:
    sesh = session.Session()

from tempfile import NamedTemporaryFile
with NamedTemporaryFile() as f:
    tempdir = os.path.dirname(f.name)
session_tracker = os.path.join(tempdir, 'anemone_projects.txt')


from panels import *
from inversion_panels import *
from dash import dcc
from dash import Dash, callback_context, ALL, Patch
from dash.exceptions import PreventUpdate
from dash import Input, Output, State, html, dcc, ctx
from dash_bootstrap_components import themes
import dash_bootstrap_components as dbc
from dash.dash import no_update
import numpy as np


import plotly.basedatatypes
plotly.basedatatypes.convert_to_base64 = lambda obj: None

import temframe


external_stylesheets = [themes.BOOTSTRAP]
app = Dash(__name__, suppress_callback_exceptions=True, assets_folder='assets',  external_stylesheets=external_stylesheets)
app.title = "Sea Anemone"

docs_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docs', 'build', 'html'))


if os.path.exists(session_tracker):
    with open(session_tracker, 'rt') as f:
        session_files = [x.strip() for x in f.readlines() if os.path.exists(x.strip())]
    session_files = list(set(session_files))

else:
    session_files = []

m1        = Map(data=sesh.overview)
dbdt1     = dbdtSounding(   dataframe=sesh.data)
dbdt2     = dbdtSection(    dataframe=sesh.data)
rhoa      = rhoaSounding(   dataframe=sesh.data)
mod1      = ModelGraph(     dataframe=sesh.models )
mod2      = ModelSection(   dataframe=sesh.models )
m1.res_panel = mod2
# window of sites the sections zoom to and the soundings show, plus the map selection; ordered along the tTEM section's x axis
buf = SiteBuffer(length=50)
buf.section = dbdt2
m1.buffer = dbdt2.buffer = mod2.buffer = buf
Multi_inv = MultiInversion( dataframe=sesh.data )
Multi_inv.map_panel = m1
Multi_inv.model_graph = mod1
Multi_inv.model_section = mod2
Sing_inv  = Single_site(    dataframe=sesh.data, rho=10 )
u1        = Upload(session_files=session_files)

hkr       = HotKeyReminder()

panels = [u1, m1, dbdt1, dbdt2, mod1, mod2, Multi_inv, Sing_inv, rhoa, hkr]
nodes = [node for panel in panels for node in panel.to_nodes()]


html_header = html.H1('Sea Anemone', style={'width': '100%'})

import layouts

flex_layout = dfl.FlexLayout(
            id="flex-layout",
            model=layouts.upload,
            children=nodes,
            useStateForModel=False,        
        )
app.layout = html.Div([
    dcc.Location(id='url', refresh='callback-nav'),
    dcc.Interval(id= "inv-log-poll", interval=1000, n_intervals=0, disabled=True),  # Poll every 2 seconds
    dcc.Store(id="session-save-complete"),
    dcc.Store(id="starting-model", data={"rho": 10.0,"depth": np.cumsum(np.logspace(0, 1.3, 31)).tolist()}),
    dcc.Store(id='starting-model-selected',data=[]),
    dcc.Store(id='data-buffer',data={"length": 50, "start_site":0}),
    dcc.Store(id='map-hover-site', data=None),
    html.Div([dbc.Toast(
                    "⛔ Please Zoom or Pan in the map.",
                    id="zoom-toast",
                    header="Map Not Ready",
                    is_open=False,
                    dismissable=True,
                    duration=4000, # Disappears after 4 seconds
                    icon="danger",
                    style={"position": "fixed", "top": "50%", "left": "50%", "transform": "translate(-50%, -50%)", "width": 350, "zIndex": 9999,"textAlign": "center"},
                ),
            ], id="toast-container"),
    html.Div([
        dbc.ButtonGroup([
            dbc.Button("1. Load Data",  id="upload_layout",    color="primary"),
            dbc.Button("2. Process",    id="process_layout",   disabled=False,  color="secondary"),
            dbc.Button("3. Invert",     id="invert_layout",    disabled=False,  color="secondary"),
            dbc.Button("4. QC",         id="review_layout",    disabled=False,  color="secondary"),
            dbc.Button("5. Interpret",  id="interpret_layout", disabled=False, color="secondary"),
        ], style={'width': '100%'})
    ], style={
        'position': 'fixed',
        'top': '0',
        'left': '0',
        'right': '0',
        'height': '60px',
        'width': '100%',
        'background': '#f8f9fa',
        'borderBottom': '1px solid #ddd',
        'zIndex': '1000',
        'display': 'flex',
        'alignItems': 'center',
        'padding': '0 10px'
    }),
    html.Div([flex_layout], style={'marginTop': '60px'}),  # Push content below fixed header
    html.Div(id='output-click'),
])

for panel in panels:
    panel.add_callbacks(app)




def show_sites(site_ids):
    """the sounding panels and the 1D model graph show these sites"""
    if sesh.data is not None:
        dbdt1.dataframe = sesh.data[sesh.data['site_id'].isin(site_ids)].copy()
        rhoa.dataframe  = dbdt1.dataframe.copy()
    if sesh.models is not None:
        mod1.dataframe = sesh.models[sesh.models['site_id'].isin(site_ids)].copy()
        mod1.buffer_start, mod1.buffer_len = 0, max(len(site_ids), 1)


def select_sites(site_ids, move=True):
    """select sites everywhere: dotted boxes in the sections, highlight markers on the map, and the soundings / 1D model
    graph show them. A single site is also the highlighted site that Previous/Next step from. With move, the buffer
    window follows sites outside it (scrolling to a single site, centring on several)."""
    site_ids = list(site_ids)
    buf.selected = site_ids
    highlighted = site_ids[0] if len(site_ids) == 1 else None
    for panel in [m1, mod1, mod2, dbdt2]:
        panel.highlighted = highlighted
    if move and not set(site_ids) <= set(buf.window()):
        if len(site_ids) == 1:
            buf.scroll_to(site_ids[0])
        else:
            buf.center_on(site_ids)
    show_sites(site_ids)


def map_selection_patch():
    patch = Patch()
    for layer, site_ids in (('buffer', buf.window()), ('highlight', buf.selected)):
        trace_index = m1._layers.index(layer)
        sites = m1.dataframe.loc[m1.dataframe['site_id'].isin(site_ids)]
        patch['data'][trace_index]['lat'] = sites['latitude'].tolist()
        patch['data'][trace_index]['lon'] = sites['longitude'].tolist()
        patch['data'][trace_index]['customdata'] = [[site_id] for site_id in sites['site_id'].tolist()]
    return patch


def section_selection_patch(panel):
    if not hasattr(panel, '_site_buffer_site_x'):
        return no_update
    selection = go.Figure()
    x_range = apply_site_buffer(selection, panel._site_buffer_site_x, panel.buffer)
    patch = Patch()
    patch['layout']['shapes'] = (
        panel._site_buffer_static_shapes
        + [shape.to_plotly_json() for shape in selection.layout.shapes or ()]
    )
    if x_range is not None:
        patch['layout']['xaxis']['range'] = x_range
        patch['layout']['xaxis']['autorange'] = False
    return patch


@app.callback(
    dbdt1.output, dbdt2.output, rhoa.output, mod1.output, mod2.output, m1.output,
    Output("data-buffer", "data", allow_duplicate=True),
    Input('map', 'selectedData'),
    prevent_initial_call=True
)
def handle_map_interactions(selected_data):
    if not selected_data or 'points' not in selected_data:
        raise PreventUpdate
    curve_number = m1._layers.index('sites')
    selected_sites = sorted({point['customdata'][0] for point in selected_data['points'] if point['curveNumber']==curve_number and 'customdata' in point})
    if not selected_sites:
        raise PreventUpdate

    # sites already in the buffer window are just outlined in the sections; otherwise the window moves to centre on them
    select_sites(selected_sites)
    return (dbdt1.render(), section_selection_patch(dbdt2), rhoa.render(), mod1.render(),
            section_selection_patch(mod2), map_selection_patch(), buf.store())

app.clientside_callback(
    hkr.javascript,
    Output("disableButton", "id"),
    Input("disableButton", "id")
)

# Hovering the data/model section moves the map's 'hover' marker to the nearest site, entirely in the browser
# (Plotly.restyle on one trace), so the map is never re-rendered. Sections carry a site/x lookup in layout.meta.
map_hover_js = """
function(hoverData) {
    const mapGd = document.querySelector('#map .js-plotly-plot');
    if (!mapGd || !mapGd.data) return window.dash_clientside.no_update;
    const iHover = mapGd.data.findIndex(t => t.name === 'hover');
    if (iHover < 0) return window.dash_clientside.no_update;

    const num = v => (typeof v === 'number') ? v : Date.parse(v);
    let site = null;
    if (hoverData && hoverData.points && hoverData.points.length) {
        const srcId = window.dash_clientside.callback_context.triggered[0].prop_id.split('.')[0];
        const src = document.querySelector('#' + srcId + ' .js-plotly-plot');
        const meta = src && src.layout && src.layout.meta;
        const x = num(hoverData.points[0].x);
        if (meta && meta.site_x && !isNaN(x)) {
            let bestD = Infinity;
            for (let i = 0; i < meta.site_x.length; i++) {
                const d = Math.abs(num(meta.site_x[i]) - x);
                if (d < bestD) { bestD = d; site = meta.site_id[i]; }
            }
        }
    }
    // skip if unchanged; the length check catches the server re-rendering the map (which empties the trace)
    const shown = (mapGd.data[iHover].lat || []).length > 0;
    if (mapGd._hoverSite === site && shown === (site !== null)) return window.dash_clientside.no_update;
    mapGd._hoverSite = site;

    let lat = [], lon = [];
    if (site !== null) {
        for (const t of mapGd.data) {
            if (t.name === 'hover' || !t.customdata) continue;
            const j = t.customdata.findIndex(c => (Array.isArray(c) ? c[0] : c) === site);
            if (j >= 0) { lat = [t.lat[j]]; lon = [t.lon[j]]; break; }
        }
    }
    Plotly.restyle(mapGd, {lat: [lat], lon: [lon]}, [iHover]);
    return site;
}
"""
# one callback per section, since each section panel is only in some of the layouts
for section_id in [dbdt2.id, mod2.id]:
    app.clientside_callback(
        map_hover_js,
        Output('map-hover-site', 'data', allow_duplicate=True),
        Input(section_id, 'hoverData'),
        prevent_initial_call=True
    )

@app.callback(
    dbdt1.output, dbdt2.output, rhoa.output,
    Input("disableButton", "n_clicks"),
    Input("enableButton", "n_clicks"),
    State("tTEM", "selectedData"),
    State("sounding", "selectedData"),
    State("rhoa", "selectedData"),
    State('interpret_layout','color'),
    prevent_initial_call=True,
)
def show_value(n1, n2, ttem_selected, sounding_selected, rhoa_selected, interpret_layout_color):
    if interpret_layout_color == 'primary':
        raise PreventUpdate
    if str(ctx.triggered_id) == 'disableButton':
        inuse = False
    elif str(ctx.triggered_id) == 'enableButton':
        inuse = True

    if sounding_selected and len(sounding_selected['points'])>0:
        data_ids = [point['customdata'][1] for point in sounding_selected['points'] if 'customdata' in point]
    elif rhoa_selected and len(rhoa_selected['points'])>0:
        data_ids = [point['customdata'][1] for point in rhoa_selected['points'] if 'customdata' in point]        
    elif ttem_selected and len(ttem_selected['points'])>0:
        data_ids = [point['customdata'][1] for point in ttem_selected['points'] if 'customdata' in point]

    else:
        raise PreventUpdate
    

    # df_data = sesh.data
    
    for df_data in [sesh.data, dbdt1.dataframe, dbdt2.dataframe, rhoa.dataframe]:
        df_data.loc[df_data['data_id'].isin(data_ids), 'inuse_manual'] = inuse
        df_data['include'] = temframe.include_mask(df_data)

    return dbdt1.render(), dbdt2.render(), rhoa.render()

@app.callback(
    dbdt1.output, rhoa.output, m1.output, mod1.output, mod2.output, dbdt2.output,
    Input(dbdt2.id, 'selectedData'),
    prevent_initial_call=True,
)
def update_selection_from_section(selected_data):
    if not selected_data or 'points' not in selected_data or len(selected_data['points']) == 0:
        raise PreventUpdate

    site_ids = sorted({point['customdata'][2] for point in selected_data['points'] if 'customdata' in point} - {-1})
    if not site_ids:
        raise PreventUpdate
    select_sites(site_ids, move=False)
    return (dbdt1.render(), rhoa.render(), map_selection_patch(), mod1.render(),
            section_selection_patch(mod2), section_selection_patch(dbdt2))

@app.callback(
    m1.output, dbdt1.output, dbdt2.output, rhoa.output, mod1.output, mod2.output,
    Output('data-buffer', 'data', allow_duplicate=True),
    Input('beginning-buffer', 'n_clicks'),
    Input('prev-buffer', 'n_clicks'),
    Input('next-buffer', 'n_clicks'),
    Input('buffer-length-input', 'value'),
    prevent_initial_call=True
)
def move_buffer(beginning_clicks, prev_clicks, next_clicks, length):
    trigger = ctx.triggered_id
    if trigger == 'buffer-length-input':
        if not length or int(length) < 1:
            raise PreventUpdate
        # same start, new length; keeps the selection
        buf.length = int(length)
        buf.window()
        return (map_selection_patch(), no_update, section_selection_patch(dbdt2), no_update,
                no_update, section_selection_patch(mod2), buf.store())

    if trigger == 'beginning-buffer':
        buf.start = 0
    else:
        buf.step(-1 if trigger == 'prev-buffer' else 1)
    window = buf.window()
    buf.selected = []
    for panel in [m1, mod1, mod2, dbdt2]:
        panel.highlighted = None
    show_sites(window)
    return (map_selection_patch(), dbdt1.render(), section_selection_patch(dbdt2), rhoa.render(),
            mod1.render(), section_selection_patch(mod2), buf.store())

@app.callback(
    Output("model_section", "figure", allow_duplicate=True),
    Output("model_graph", "figure", allow_duplicate=True),
    Input("review_layout", "n_clicks"),
    State("invert_layout", "color"),
    prevent_initial_call=True
)
def update_model_on_review(_, invert_color):
    mod2.dataframe = sesh.models.copy() if sesh.models is not None else None
    mod1.dataframe = sesh.models.copy() if sesh.models is not None else None
    return mod2.render(), mod1.render()

@app.callback(
    Output("model_section", "figure", allow_duplicate=True),
    Input("interpret_layout", "n_clicks"),
    State("invert_layout", "color"),
    prevent_initial_call=True
)
def update_model_on_interpret(_, invert_color):
    mod2.dataframe = sesh.models.copy() if sesh.models is not None else None
    return mod2.render()


@app.callback(
    [Output('output-click', 'children', allow_duplicate=True),
    Output('session-save-complete', 'data', allow_duplicate=True),],
    Input('saveButton', 'n_clicks'),
    prevent_initial_call=True,
    allow_duplicate=True
)
def save_session(n1):
    if sesh.save_dir is None:
        root = Tk()
        root.withdraw()  # Hide the root window
        root.attributes('-topmost', True)
        root.lift()
        root.focus_force()
        root.update()
        folder_path = filedialog.askdirectory(title="Select Save Directory", parent=root)
        print(folder_path)
        root.destroy()  # Destroy the root window after selection
        if not folder_path:
            raise PreventUpdate
        sesh.save_dir = folder_path + '/' if not folder_path.endswith('/') else folder_path
    if sesh.save_dir not in u1.session_files:
        u1.session_files.append(sesh.save_dir)
        with open(session_tracker, 'w') as f:
            for item in u1.session_files:
                f.write(f"{item}\n")

    sesh.save(folder=sesh.save_dir)
    print(f'Session saved to {sesh.save_dir}')
    message = f"Session saved to {sesh.save_dir}"
    return message, {"dir": sesh.save_dir}

@app.callback(
    Output("output-click", "children", allow_duplicate=True),
    m1.output, mod1.output, dbdt1.output, Multi_inv.output, mod2.output, dbdt2.output, rhoa.output,
    Output("data-buffer", "data", allow_duplicate=True),
    Input('highlight_prev', 'n_clicks'),
    Input('highlight_next', 'n_clicks'),
    State('invert_layout',  'color'),
    State('flex-layout', 'model'),
    prevent_initial_call=True,
)
def highlight_change(n1, n2, invert_layout_color, model):
    if not ctx.triggered:
        raise PreventUpdate
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    highlighted = m1.highlighted
    if trigger_id == 'highlight_prev':
        step = -1
    elif trigger_id == 'highlight_next':
        step = 1
    else:
        raise PreventUpdate

    if highlighted is None:
        # with several sites selected, step from the first / last of them
        if not buf.selected:
            raise PreventUpdate
        order = [site for site in buf.sites() if site in buf.selected]
        highlighted = (order or buf.selected)[0 if step == -1 else -1]

    # step to the neighbouring site along the section x axis
    sites = buf.sites()
    idx = np.flatnonzero(sites == highlighted)
    if len(idx) == 0:
        highlighted = highlighted + step
    else:
        highlighted = sites[int(np.clip(idx[0] + step, 0, len(sites) - 1))]

    select_sites([highlighted])
    # slide the buffer window along when the highlight nears its edge
    buf.scroll_to(highlighted)
    m1.is_last_tab = False
    return (
        ctx.triggered_id,
        map_selection_patch(),
        mod1.render(),
        dbdt1.render(),
        Multi_inv.render(),
        section_selection_patch(mod2),
        section_selection_patch(dbdt2),
        rhoa.render(),
        buf.store(),
    )

from map import cdist

@app.callback(
    m1.output, mod1.output, dbdt1.output, mod2.output, dbdt2.output, rhoa.output,
    Output('data-buffer', 'data', allow_duplicate=True),
    Input('model_section', 'clickData'),
    Input('tTEM', 'clickData'),
    Input('map', 'clickData'),
    State('invert_layout',  'color'),
    State('review_layout', 'color'),
    State('interpret_layout', 'color'),
    prevent_initial_call=True
)
def cross_panel_click(model_click, ttem_click, map_click, invert_layout_color, review_layout_color, interpret_layout_color):
    if not ctx.triggered:
        raise PreventUpdate
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    click_data = ctx.triggered[0]['value']
    site_id = None

    if not click_data or 'points' not in click_data:
        raise PreventUpdate
    if trigger_id == 'tTEM':
        x_value = click_data['points'][0]['x']
        site_id = dbdt2.dataframe.query(f'{dbdt2.settings.x_axis} == @x_value')['site_id'].iloc[0]
    elif trigger_id == 'model_section':
        x_value = click_data['points'][0]['x']
        site_id = mod2.dataframe.query(f'{mod2.settings.x_axis} == @x_value')['site_id'].iloc[0]
    elif trigger_id == 'map':
        if m1._layers[click_data['points'][0]['curveNumber']] in ('buffer', 'sites', 'highlight'):
            x_value,y_value = click_data['points'][0]['lon'],click_data['points'][0]['lat']
            all_dist = cdist(m1.dataframe.latitude, m1.dataframe.longitude, y_value+0.00000002, x_value+0.000000002)
            site_id = m1.dataframe.loc[np.argmin(all_dist), 'site_id']
    if site_id is None:
        raise PreventUpdate

    # a site clicked on the map may be outside the buffer window
    select_sites([site_id])
    return (map_selection_patch(), mod1.render(), dbdt1.render(), section_selection_patch(mod2),
            section_selection_patch(dbdt2), rhoa.render(), buf.store())

@app.callback(
    Output("starting-model", "data", allow_duplicate=True),
    Input("multi_inv", "relayoutData"),
    State("starting-model", "data"),
    prevent_initial_call=True
)
def update_starting_model_from_drag(relayout, model):
    if not relayout:
        raise PreventUpdate

    # Look for moved vertical line
    moved = [k for k in relayout if k.endswith(".x0")]
    if not moved:
        raise PreventUpdate

    new_rho = relayout[moved[0]]

    # Update starting model
    model["rho"] = float(new_rho)

    return model

@app.callback(
    Output("starting-model", "data", allow_duplicate=True),
    Input("inv-single", "relayoutData"),
    State("starting-model", "data"),
    prevent_initial_call=True
)
def update_starting_model_from_single_drag(relayout, model):
    if not relayout:
        raise PreventUpdate

    moved = [k for k in relayout if k.endswith(".x0")]
    if not moved:
        raise PreventUpdate

    model["rho"] = float(relayout[moved[0]])
    return model


@app.callback(
    Output("inv-log-poll", "n_intervals"),
    Input("invert_all_button", "n_clicks"),
    prevent_initial_call=True,
)
def reset_polling(n):
    return 0

@app.callback(
    [Output('output-data-upload', 'children'),

     m1.output, dbdt1.output, dbdt2.output, rhoa.output, 
     Multi_inv.output, Sing_inv.output,

     Output('output-data-summary', 'children', allow_duplicate=True),
     Output('upload-toast', 'is_open'),
     Output('upload-toast', 'children'),
     Output('process_layout', 'disabled', allow_duplicate=True),
     Output('invert_layout', 'disabled', allow_duplicate=True),
    ],
    Input('upload-data', 'contents'),
    running=[(Output("upload-data", "disabled"), True, False)],
    prevent_initial_call=True
)
def upload_file(contents):
    global sesh
    if contents is None:
        raise PreventUpdate
    if contents[0].startswith('data:application/json'):
        import base64
        codec,info = contents[0].split(';')[1].split(',')
        sesh_str = base64.b64decode(info).decode().replace('null', 'None')
        sesh_dict = dict(eval(sesh_str))
        filepath = sesh_dict['save_dir'].replace(' ', '%20')
        return [no_update]*5 + [html.Div(f'File: {sesh_dict['save_dir']}'), f"#load={filepath}"]
    warning_msg = None
    if sesh.save_dir is None:
        warning_msg = "No working directory selected. You can still explore data; choose Save to set one."
    if contents[0].startswith('data:application/x-zip') or contents[0].startswith('data:application/zip'):
        sesh.data, sesh.forwards = temframe.from_zip_content(contents[0])
    else:
        print(contents[0][:500])
        print('data upload failed')
        return [no_update]*7

        # except Exception as e:
        #     return (html.Div("Upload failed."),no_update,no_update,no_update,no_update,no_update,no_update,build_data_summary(),True,f"Upload failed: Only one geometry is supported at a time",True,True,no_update,no_update,no_update,no_update,no_update,{'display': 'block'}, {'display': 'block'})
    # sesh.site = sesh.overview
    sesh.data['include'] = temframe.include_mask(sesh.data)
    sesh.models          = None
    m1.dataframe    = sesh.overview.copy()
    
    
    mod1.dataframe  = sesh.models
    mod2.dataframe  = sesh.models
    dbdt2.dataframe = sesh.data.copy()          # keep full section view
    show_sites(buf.window())
    Multi_inv.dataframe = sesh.data.copy()
    Sing_inv.dataframe = sesh.data.copy()
    
    # t1.dataframe = TABLES['overview'].copy()
    new_process_clicks = no_update

    #return html.Div("File uploaded successfully."), False, False, new_process_clicks#, t1.render()
    if 'site_id' in sesh.data.columns:
        toast_count = int(sesh.data.loc[sesh.data['site_id'] != -1, 'site_id'].nunique())
    else:
        toast_count = int(len(sesh.data))
    toast_msg = f"Uploaded {toast_count} sites."
    upload_msg = "File uploaded successfully."
    if warning_msg:
        upload_msg = f"{upload_msg} {warning_msg}"

    return html.Div(upload_msg), m1.render(), dbdt1.render(), dbdt2.render(), rhoa.render(), Multi_inv.render(), Sing_inv.render(), 'data uploaded', True, toast_msg, False, False


# @app.callback(
#     Output('map', 'figure', allow_duplicate=True),
#     Input('flex-layout', 'model'),
#     prevent_initial_call=True

# )
# def print_flex_layout_model(model):
#     print(f"Flex layout model: {model}")
#     return m1.render()
@app.callback(
    Output({'type': f'settings-{dbdt2.id}', 'key': 'x_axis'}, 'value'),
    Input({'type': f'settings-{mod2.id}', 'key': 'x_axis'}, 'value'),
    prevent_initial_call=True
)
def sync_x_axis(x_axis):
    return x_axis

@app.callback(
    Output({'type': f'settings-{dbdt2.id}', 'key': 'radius'}, 'value'),
    Input({'type': f'settings-{mod2.id}', 'key': 'radius'}, 'value'),
    prevent_initial_call=True
)
def sync_radius(radius):
    return radius

@app.callback(
    m1.output,
    Input({'type': f'settings-{mod2.id}', 'key': 'vmin'}, 'value'),
    Input({'type': f'settings-{mod2.id}', 'key': 'vmax'}, 'value'),
    prevent_initial_call=True
)
def sync_mean_res_range(vmin, vmax):
    # the mean-res map uses the model section's colour range (m1.res_panel); set it here too, as this may run before mod2's own settings callback
    if m1.settings.plot_by != 'mean-res':
        raise PreventUpdate
    mod2.settings.vmin, mod2.settings.vmax = float(vmin), float(vmax)
    return m1.render()



@app.callback(
    [
        Output('flex-layout', 'model'),
        Output('upload_layout', 'color'),
        Output('process_layout', 'color'),
        Output('invert_layout', 'color'),
        Output('review_layout', 'color'),
        Output('interpret_layout', 'color'),
    ],
    [
        State('flex-layout', 'model'),
        Input("upload_layout", 'n_clicks'),
        Input("process_layout", 'n_clicks'),
        Input("invert_layout", 'n_clicks'),
        Input("review_layout", 'n_clicks'),
        Input("interpret_layout", 'n_clicks'),
    ],
    prevent_initial_call=True
)
def update_layout(model,
                  load_clicks, process_clicks,
                  invert_clicks, review_clicks, interpret_clicks):

    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    is_interpret = (button_id == 'interpret_layout')

    colors = {
        "upload_layout":    'secondary',
        "process_layout":   'secondary',
        "invert_layout":    'secondary',
        "review_layout":    'secondary',
        "interpret_layout": 'secondary'
    }
    colors[button_id] = 'primary'

    if button_id == "upload_layout":
        return layouts.upload, *colors.values()

    elif button_id == "process_layout":
        return layouts.data, *colors.values()

    elif button_id == "invert_layout":
        return layouts.invert, *colors.values()

    elif button_id == "review_layout":
        return layouts.review, *colors.values()

    elif button_id == "interpret_layout":
        m1.settings.legend=True
        m1.settings.dragmode='pan'
        return layouts.interpret, *colors.values()


layout_output_list = [
        m1.output, dbdt1.output, dbdt2.output, rhoa.output, Multi_inv.output, Sing_inv.output, mod2.output,
        
        Output('flex-layout',    'model', allow_duplicate=True),

        Output('upload_layout',  'color',  allow_duplicate=True),
        Output('process_layout', 'color', allow_duplicate=True),
        Output('invert_layout',  'color', allow_duplicate=True),
        Output('review_layout',  'color', allow_duplicate=True), #Output('review_layout', 'disabled', allow_duplicate=True)
        Output('interpret_layout',  'color', allow_duplicate=True),
        
        Output('upload_layout',  'disabled',  allow_duplicate=True),
        Output('process_layout', 'disabled', allow_duplicate=True),
        Output('invert_layout',  'disabled', allow_duplicate=True),
        Output('review_layout',  'disabled', allow_duplicate=True), #Output
        Output('interpret_layout',  'disabled', allow_duplicate=True),
        Output("current-working-directory", "children", allow_duplicate=True),

        Output('use-borehole', 'value', allow_duplicate=True),
        Output('use-borehole', 'label', allow_duplicate=True),
        Output('borehole-options-container', 'style', allow_duplicate=True),


        Output('url', 'hash', allow_duplicate=True),
]

def no_update_factory(n):
    return [no_update for _ in range(n)]

@app.callback(
    layout_output_list,     
    Input('url', 'hash'),
    State('flex-layout', 'model'),
    prevent_initial_call=True,
    
)
def handle_url_hash(url_hash, model):
    global sesh
    res = no_update_factory(len(layout_output_list))
    res[-1] = ''
    layout=model
    print(f'url hash: {url_hash}')
    if url_hash.startswith('#open_session'):
        root = Tk()
        root.withdraw()  # Hide the root window
        root.attributes('-topmost', True)
        root.lift()
        root.focus_force()
        root.update()
        folder_path = filedialog.askdirectory(title="Select Working Directory", parent=root)
        url_hash = '#load='+folder_path+'/'
    
    if url_hash.startswith('#change_working'):
        root = Tk()
        root.withdraw()  # Hide the root window
        root.attributes('-topmost', True)
        root.lift()
        root.focus_force()
        root.update()
        folder_path = filedialog.askdirectory(title="Select Working Directory", parent=root)
        print(folder_path)
        root.destroy()  # Destroy the root window after selection
        if folder_path:
            sesh.save_dir = folder_path + '/' if not folder_path.endswith('/') else folder_path
            print(f'Working directory changed to: {sesh.save_dir}')
            res[-5] = sesh.save_dir

    if url_hash.startswith('#load'):
        folder = url_hash.split('=')[1].replace('%20', ' ').replace('%22', '')
        print(f'loading session from folder: {folder}')
        sesh = session.Session.from_folder(folder)
        res[-5] = sesh.save_dir

        # drop what the panels still hold from the previous session
        m1.lines = sesh.lines.copy() if sesh.lines is not None else None
        m1.settings.view = None
        for panel in [m1, mod1, mod2, dbdt2]:
            panel.highlighted = None

        if sesh.data is not None:
            m1.dataframe    = sesh.overview.copy()
            dbdt2.dataframe = sesh.data.copy()          # keep full section view
            buf.reset()
            show_sites(buf.window())

            Multi_inv.dataframe = sesh.data.copy()
            Sing_inv.dataframe = sesh.data.copy()
            res[0] = m1.render()
            res[1] = dbdt1.render()
            res[2] = dbdt2.render()
            res[3] = rhoa.render()
            res[4] = Multi_inv.render()
            res[5] = Sing_inv.render()
        
        if sesh.models is not None:
            mod2.dataframe  = sesh.models.copy()
            show_sites(buf.window())
            res[6] = mod2.render()

            res[8]   = 'secondary'
            res[9]   = 'secondary'
            res[10]   = 'secondary'
            res[11]   = 'success'
            res[12]  = 'secondary'
            res[13]  = False
            res[14]  = False
            res[15]  = False
            res[16]  = False
            res[17]  = False
        else:

            res[8]   = 'success'
            res[9]   = 'secondary'
            res[10]   = 'secondary'
            res[11]   = 'secondary'
            res[12]   = 'secondary'

            res[13]  = False
            res[14]  = False
            res[15]  = False
            res[16]  = True
            res[17]  = True
            
    res[-1] = ''
    return res

# import signal
# @app.server.route("/shutdown", methods=["POST"])
# def shutdown():
#     print('closing app, saving data to zip...')
#     sesh.save()    
#     os.kill(os.getpid(), signal.SIGINT)  # Send a signal to the process to terminate


if __name__ == "__main__":
    try:
        app.run(port=8050, debug=True, dev_tools_hot_reload=True)
    except Exception as e:
        print(f"Error running app: {e}")
    finally:
        print('closing app, saving data to zip...')
        # sesh.save()
        # os.kill(os.getpid(), signal.SIGINT)  # Send a signal to the process to terminate

#start msedge --app=http://127.0.0.1:8050/