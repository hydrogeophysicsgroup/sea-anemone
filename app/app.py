import sys, os
from tkinter import filedialog, Tk

fpath = os.path.dirname(os.path.abspath(__file__))
if fpath not in sys.path:
    sys.path.append(fpath)

import session
global sesh
sesh = None#session.Session.from_workbench(r"C:\\Users\\au646858\\OneDrive - Aarhus universitet\\Documents\\_repositories\\sea-anemone\\app\\Models\\Surround_MOD_dat.xyz")

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
dbdt1     = dbdtSounding(dataframe=sesh.data)
dbdt2     = dbdtSection(dataframe=sesh.data)
rhoa      = rhoaSounding(dataframe=sesh.data)
u1        = Upload(session_files=session_files)
mod1      = ModelGraph(   dataframe=sesh.models )
mod2      = ModelSection( dataframe=sesh.models )
Multi_inv = MultiInversion( dataframe=sesh.data )
Sing_inv  = Single_site( dataframe=sesh.data, rho=10 )
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
    
    dcc.Store(id="dem-applied", data=False),
    dcc.Store(id="dem-downloaded", data=False),

    dcc.Store(id="selected_ids_store", data=[]),
    dcc.Store(id="selected_sites_store", data=[]),
    dcc.Store(id="selected_sites_local", data=[]),

    dcc.Store(id="borehole-loaded", data=False),

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

@app.callback(
    [ 
        dbdt1.output, dbdt2.output, rhoa.output, mod1.output, mod2.output, m1.output,
        Output("data-buffer", "data", allow_duplicate=True),
        Output('buffer-length-input', 'value', allow_duplicate=True),
    ],
    [Input('map', 'selectedData')],
    prevent_initial_call=True
)
def handle_map_interactions(selected_data):
    print("Map interaction detected")
    if not selected_data:
        raise PreventUpdate
        
    if 'points' in selected_data:
        curve_number = m1._layers.index('sites')
        selected_sites = [point['pointNumber'] for point in selected_data['points'] if point['curveNumber']==curve_number]


    if selected_sites:
        selected_sites = list(set(selected_sites))
    else:
        raise PreventUpdate
    


    df_data = sesh.data.copy()
    new_df = df_data[df_data['site_id'].isin(selected_sites)]
    dbdt1.dataframe = new_df
    rhoa.dataframe  = new_df
    
    if sesh.models is not None:
        df_mod = sesh.models.copy()
        new_df = df_mod[df_mod['site_id'].isin(selected_sites)]
        mod1.dataframe = new_df
        mod1_patch = mod1.render()
    else:
        mod1_patch  = Patch()


    xmin,xmax = dbdt2.xlim(selected_sites)
    print(xmin, xmax)

    dbdt1_patch = dbdt1.render()
    dbdt2_patch = Patch()
    rhoa_patch  = rhoa.render()
    
    
    mod2_patch  = Patch()


    m1.buffer_sites = selected_sites
    m1_patch = m1.render()

    # m1_patch = Patch()
    # m1_patch["data"][0]["selected"]   = {"marker": {"size": int(m1.settings.markersize*1.5)}}
    # m1_patch["data"][0]["unselected"] = {"marker": {"opacity": 0.6}}
    
    mod2_patch["layout"]["xaxis"]["range"]  = [xmin, xmax]
    dbdt2_patch["layout"]["xaxis"]["range"] = [xmin, xmax]
    # dbdt2.xlim = [xmin, xmax]
    
    data_buffer = {"length": len(selected_sites), "start_site": min(selected_sites)}
    return dbdt1_patch, dbdt2_patch, rhoa_patch, mod1_patch, mod2_patch, m1_patch, data_buffer, len(selected_sites)

app.clientside_callback(
    hkr.javascript,
    Output("disableButton", "id"),
    Input("disableButton", "id")
)

@app.callback(m1.output,
    dbdt1.output, dbdt2.output, rhoa.output,

    Output("selected_ids_store", "data"),
    Output("selected_sites_store", "data"),
    Output("selected_sites_local", "data"),

    Input("disableButton", "n_clicks"),
    Input("enableButton", "n_clicks"),
    Input("tTEM", "selectedData"),    
    Input("sounding", "selectedData"), 
    Input("rhoa", "selectedData"),     
    
    State("selected_ids_store", "data"),
    State("selected_sites_store", "data"),
    State("selected_sites_local", "data"),
    State('interpret_layout', 'color'),
    prevent_initial_call=True,
)
def unified_handler(n1, n2, 
                    ttem_sel, sounding_sel, rhoa_sel, 
                    stored_data_ids, stored_site_ids, stored_site_ids_local,
                    layout_color):
    
    if layout_color == 'primary':
        raise PreventUpdate

    trigger = str(ctx.triggered_id)
    prop_id = ctx.triggered[0]["prop_id"]
    df_data = sesh.data
    
    active_site_ids_local = stored_site_ids_local or []
    active_data_ids = stored_data_ids or []

    if stored_site_ids:
        active_site_ids = stored_site_ids
    else:
        active_site_ids = df_data["site_id"].unique().tolist()
    
    # --- 1. SITE FILTERING ---
    # Determine which sites to display in the decay plots
    if trigger == "tTEM" and ttem_sel and ttem_sel.get('points'):
        active_site_ids = list(set(p['customdata'][2] for p in ttem_sel['points'] if 'customdata' in p))
        active_data_ids = list(set( int(p["customdata"][1]) for p in ttem_sel["points"] if "customdata" in p))

        map_site_ids = active_site_ids.copy()
        active_site_ids_local = []

    else:
        # Keep the sites that are currently loaded in the plots
        active_site_ids = stored_site_ids or dbdt1.dataframe['site_id'].unique().tolist()
        map_site_ids = active_site_ids.copy()

    if trigger in ["sounding", "rhoa"]:
            sel = sounding_sel if trigger == "sounding" else rhoa_sel
            if sel and sel.get("points"):
                active_data_ids = list(set( int(p["customdata"][1]) for p in sel["points"] if "customdata" in p))
                active_site_ids_local = list(set(df_data.loc[df_data["data_id"].isin(active_data_ids),"site_id"].tolist()))
                map_site_ids =  active_site_ids_local.copy()
    
    # 4. Button logic
    if trigger in ["disableButton", "enableButton"]:

        if active_data_ids:
            inuse = (trigger == "enableButton")
            df_data.loc[df_data["data_id"].isin(active_data_ids),"inuse_manual"] = inuse
            df_data["include"] = (df_data["inuse_manual"].fillna(df_data["inuse_auto"]).astype(bool))
            sesh.data = df_data
            
            active_site_ids_local = []
            active_data_ids = []
            map_site_ids = []
    
    # Double-click clear selections
    if ".relayoutData" in prop_id:
        relayout = ctx.triggered[0]["value"]

        if relayout and ( "autosize" in relayout or "xaxis.autorange" in relayout or "yaxis.autorange" in relayout):

            map_site_ids = []
            active_data_ids = []
            active_site_ids_local = []

    elif ".selectedData" in prop_id:
        sel = ctx.triggered[0]["value"]

        if sel is None:
            map_site_ids = []
            active_data_ids = []
            active_site_ids_local = []

    # 5. Apply site filtering
    dbdt1.dataframe = df_data[df_data["site_id"].isin(active_site_ids)]
    rhoa.dataframe = df_data[df_data["site_id"].isin(active_site_ids)]

    # keep full tTEM for re-selection
    dbdt2.dataframe = df_data
    
    if len(active_site_ids_local) != 0:
        if len(active_site_ids_local) < len(active_site_ids) or len(active_site_ids_local) == len(active_site_ids):
            m1.highlighted = active_site_ids_local.copy()
    else:
        m1.highlighted = map_site_ids
    
    highlight_clr = "#ffb835" #
    m1.settings.highlight_color = highlight_clr
    m1.settings.markersize = 8 # 14

    # 6. Render
    fig0 = m1.render()
    fig1 = dbdt1.render()
    fig2 = dbdt2.render()
    fig3 = rhoa.render()

    # preserve selection visuals
    for fig in [fig0, fig1, fig2, fig3]:
        if fig is not None:
            fig.update_layout(uirevision="constant",dragmode="select")

    # 7. Highlight selected points
    for fig, f_id in zip([fig1, fig2, fig3],["sounding", "tTEM", "rhoa"]):
        if not fig:
            continue

        # do not dim tTEM when it is source of site filter
        # if trigger == "tTEM" and f_id == "tTEM":
        #     for trace in fig.data:
        #         trace.selectedpoints = None
        #         trace.selected = {"marker": {"color": highlight_clr ,"opacity": 0.5,"size": 12}}
        #     continue

        for trace in fig.data:
            if getattr(trace, "mode", "") == "lines":
                continue

            cd = getattr(trace, "customdata", None)
            if cd is None:
                continue

            indices = [i for i, row in enumerate(cd)if int(row[1]) in active_data_ids]

            if indices:
                trace.selectedpoints = indices
                if trigger == "tTEM" and f_id == "tTEM":                  
                    trace.selected = {"marker": {"color": highlight_clr ,"opacity": 1,"size": 9}}
                    trace.unselected = {"marker": {"opacity": 0.1}}
                else:
                    trace.selected = {"marker": {"color": highlight_clr ,"opacity": 0.8,"size": 10}}
                    trace.unselected = {"marker": {"opacity": 0.1}}
            elif active_data_ids:
                trace.selectedpoints = []
                trace.unselected = {"marker": {"opacity": 0.1}}

            else:
                trace.selectedpoints = None
                trace.unselected = {"marker": {"opacity": 1}}

    return (fig0, fig1, fig2, fig3, active_data_ids, active_site_ids, active_site_ids_local)


# @app.callback(
#     mod2.output, dbdt2.output, dbdt1.output, m1.output, mod1.output, rhoa.output,
#     Input('data-buffer', 'data'),
#     prevent_initial_call=True
# )
# def update_model_section_from_buffer(buffer_data):
#     start  = buffer_data["start_site"]
#     length = buffer_data["length"]

#     # Update model section buffer
#     mod2.buffer_start = start
#     mod2.buffer_len   = length
#     mod1.buffer_start = start
#     mod1.buffer_len   = length
    

#     # Update tTEM buffer
#     dbdt2.buffer_start = start
#     dbdt2.buffer_len   = length


#     x_axis = dbdt2.settings.x_axis
#     df = dbdt2.dataframe

#     df_buf = dbdt2.dataframe.copy()
#     if x_axis == "site_id":
#         df_buf = df_buf[df_buf["site_id"] != -1]
#     x_vals = np.sort(df_buf[x_axis].dropna().unique())

#     x_slice = x_vals[start:start+length]

#     buffer_sites = (
#             df[
#                 (df[x_axis].isin(x_slice)) &
#                 (df["site_id"] != -1)
#             ]["site_id"]
#             .dropna()
#             .unique()
#         )


#     if buffer_data.get("source") == "buffer_button":
#         dbdt1.dataframe = sesh.data[sesh.data["site_id"].isin(buffer_sites)]
#         rhoa.dataframe  = sesh.data[sesh.data["site_id"].isin(buffer_sites)]
#     m1.buffer_sites = buffer_sites
#     m1.is_last_tab = False
#     # rhoa.dataframe = sesh.data[sesh.data["site_id"].isin(buffer_sites)]
#     # dbdt1.buffer_sites = buffer_sites
#     if buffer_data.get("source") == "buffer_button":
#         mod1.highlighted = None
#         mod2.highlighted = None
#         m1.highlighted = None
#         dbdt2.highlighted = None
#     return mod2.render(), dbdt2.render(), dbdt1.render(), m1.render(), mod1.render(), rhoa.render()

# @app.callback(
#     Output('data-buffer', 'data'),
#     Input('beginning-buffer', 'n_clicks'),
#     Input('next-buffer', 'n_clicks'),
#     Input('prev-buffer', 'n_clicks'),
#     State('data-buffer', 'data'),
#     prevent_initial_call=True
# )
# def update_buffer(next_clicks, prev_clicks, beginning_clicks, buffer_data):
#     if not ctx.triggered:
#         raise PreventUpdate

#     trigger = ctx.triggered_id

#     length = buffer_data["length"]
#     start  = buffer_data["start_site"]
#     # Get total number of sites from models (safer than tTEM)
#     if dbdt2.dataframe is None:
#         raise PreventUpdate

#     x_axis = dbdt2.settings.x_axis
#     df = dbdt2.dataframe

#     if x_axis == "site_id":
#         df = df[df["site_id"] != -1]

#     x_vals = np.sort(df[x_axis].dropna().unique())
#     n_sites = len(x_vals)

#     if trigger == "next-buffer":
#         start += length
#     elif trigger == "prev-buffer":
#         start -= length
#     elif trigger == "beginning-buffer":
#         start = 0

#     # Clamp safely
#     start = max(0, min(start, max(0, n_sites - length)))

#     buffer_data["start_site"] = start
#     buffer_data['source'] = "buffer_button"
#     return buffer_data

# @app.callback(
#     Output('data-buffer', 'data', allow_duplicate=True),
#     Input('buffer-length-input', 'value'),
#     State('data-buffer', 'data'),
#     prevent_initial_call=True,
# )
# def update_buffer_length(new_length, buffer_data):
#     if new_length is None or new_length <= 0:
#         raise PreventUpdate

#     buffer_data["length"] = int(new_length)

#     # reset start if necessary to avoid overflow
#     buffer_data["start_site"] = max(0, buffer_data["start_site"])

#     return buffer_data

# @app.callback(
#     Output("model_section", "figure", allow_duplicate=True),
#     Output("model_graph", "figure", allow_duplicate=True),
#     Input("review_layout", "n_clicks"),
#     State("invert_layout", "color"),
#     prevent_initial_call=True
# )

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
    Output("data-buffer", "data", allow_duplicate=True),   # <-- ADD
    Input('highlight_prev', 'n_clicks'),
    Input('highlight_next', 'n_clicks'),
    State('invert_layout',  'color'),
    State('flex-layout', 'model'),
    State("data-buffer", "data"),                          # <-- ADD
    prevent_initial_call=True,
)
def highlight_change(n1, n2, invert_layout_color, model, buffer_data):
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
        raise PreventUpdate

    highlighted = highlighted + step

    # --- your existing updates ---
    df_data = sesh.data
    m1.highlighted = highlighted
    mod1.highlighted = highlighted
    mod2.highlighted = highlighted
    dbdt2.highlighted = highlighted
    dbdt1.dataframe = df_data[df_data['site_id'] == highlighted]
    rhoa.dataframe  = df_data[df_data['site_id'] == highlighted]
    # --- NEW: slide buffer only if highlight exits current buffer window ---
    new_buffer = no_update
    if buffer_data is not None and dbdt2.dataframe is not None:
        start  = buffer_data["start_site"]
        length = buffer_data["length"]

        x_axis = dbdt2.settings.x_axis
        df = dbdt2.dataframe

        # sorted axis positions
        # df_buf = dbdt2.dataframe.copy()
        if x_axis == "site_id":
            df_buf = df[df["site_id"] != -1]
        x_vals = np.sort(df[x_axis].dropna().unique())
        # x_vals = np.sort(df[x_axis].dropna().unique())

        # find index of highlighted site
        sel = df[df["site_id"] == highlighted]
        if not sel.empty:
            x_val = sel[x_axis].iloc[0]

            idx = np.where(x_vals == x_val)[0]
            if len(idx) > 0:
                idx = int(idx[0])

                # slide buffer when highlight exits window
                if idx-1 < start:
                    start = idx-5
                elif idx > start + length:
                    start = idx - length+4

                # clamp
                start = max(0, min(start, max(0, len(x_vals) - length)))

                buffer_data["start_site"] = start
                buffer_data["source"] = "site_nav"
                new_buffer = buffer_data
    m1.is_last_tab = False
    return (
        ctx.triggered_id,
        m1.render(),
        mod1.render(),
        dbdt1.render(),
        Multi_inv.render(),
        mod2.render(),
        dbdt2.render(),
        rhoa.render(),
        new_buffer,   # <-- return updated buffer only when needed
    )

from map import cdist

@app.callback(
    m1.output, mod1.output, dbdt1.output, mod2.output, dbdt2.output, rhoa.output,
    Input('model_section', 'clickData'),
    Input('tTEM', 'clickData'),
    Input('map', 'clickData'),
    State('invert_layout',  'color'),
    State('review_layout', 'color'),
    State('interpret_layout', 'color'),
    State('data-buffer', 'data'),
    prevent_initial_call=True
)
def cross_panel_click(model_click, ttem_click, map_click, invert_layout_color, review_layout_color, interpret_layout_color, buffer_data):
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
        if click_data['points'][0]['curveNumber'] < 2:
            x_value,y_value = click_data['points'][0]['lon'],click_data['points'][0]['lat']
            all_dist = cdist(m1.dataframe.latitude, m1.dataframe.longitude, y_value+0.00000002, x_value+0.000000002)
            site_id = m1.dataframe.loc[np.argmin(all_dist), 'site_id']
    if site_id is None:
        raise PreventUpdate

    df_data = sesh.data
    m1.highlighted    = site_id
    mod1.highlighted  = site_id
    mod2.highlighted  = site_id
    dbdt2.highlighted = site_id
    dbdt1.dataframe   = df_data[df_data['site_id'] == site_id]
    rhoa.dataframe    = df_data[df_data['site_id'] == site_id]
    return m1.render(), mod1.render(), dbdt1.render(), mod2.render(), dbdt2.render(), rhoa.render()

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


# ── Borehole upload callback ───────────────────────────────────────────────────
@app.callback(
    Output('output-borehole-upload', 'children'),
    Output('borehole-loaded', 'data'),
    m1.output,
    Output('upload-toast', 'is_open', allow_duplicate=True),
    Output('upload-toast', 'children', allow_duplicate=True),
    Input('upload-borehole', 'contents'),
    State('upload-borehole', 'filename'),
    running=[(Output('upload-borehole', 'disabled'), True, False)],
    prevent_initial_call=True
)
def upload_borehole(contents, filename):
    import base64
    from Sections_plotting import load_borehole_file, get_borehole_projections, boreholes_to_dataframe
    if contents is None:
        raise PreventUpdate

    content_type, content_string = contents.split(',', 1)
    decoded = base64.b64decode(content_string)
    text = decoded.decode('utf-8', errors='replace')

    try:
        bh_data, rock_color_map = load_borehole_file(text, from_string=True)
    except Exception as e:
        return html.Div(f"Error parsing borehole file: {e}"), False, no_update, True, f"Borehole upload failed: {e}"

    if not bh_data:
        return html.Div("No boreholes found in file."), False, no_update, True, "No boreholes found."

    boreholes = get_borehole_projections(bh_data)
    sesh.borehole_list = boreholes
    sesh.rock_map = rock_color_map
    sesh.boreholes = boreholes_to_dataframe(bh_data)
   
    m1.boreholes = boreholes


    m1.rock_color_map = rock_color_map
    mod2.boreholes = boreholes
    mod2.rock_color_map = rock_color_map
    mod1.boreholes = boreholes
    mod1.rock_color_map = rock_color_map

    n_bh = len(bh_data)
    bh_ids = ', '.join(b['id'] for b in bh_data)
    return html.Div(f"Loaded {n_bh} borehole(s): {bh_ids}"), True, m1.render(), True, f"Loaded {n_bh} borehole(s)"

# ── Toggle borehole upload visibility ─────────────────────────────────────────
@app.callback(
    Output('borehole-upload-container', 'style'),
    m1.output,
    Input('use-borehole', 'value'),
    prevent_initial_call=True
)
def toggle_borehole_upload(use_borehole):
    if use_borehole:
        return {'display': 'block', 'marginTop': '10px'}, no_update
    m1.boreholes = None;        m1.rock_color_map = None
    mod2.boreholes = None;      mod2.rock_color_map = None
    mod1.boreholes = None;      mod1.rock_color_map = None
    return {'display': 'none', 'marginTop': '10px'}, m1.render()

@app.callback(
    [Output('output-data-upload', 'children'),

     m1.output, dbdt1.output, dbdt2.output, rhoa.output, 
     Multi_inv.output, Sing_inv.output,

     Output('upload-toast', 'is_open'),
     Output('upload-toast', 'children'),
     Output('process_layout', 'disabled', allow_duplicate=True),
     Output('invert_layout', 'disabled', allow_duplicate=True),
     Output('process_layout', 'n_clicks', allow_duplicate=True),
     Output('dem-bbox-minlon', 'value', allow_duplicate=True),
     Output('dem-bbox-minlat', 'value', allow_duplicate=True),
     Output('dem-bbox-maxlon', 'value', allow_duplicate=True),
     Output('dem-bbox-maxlat', 'value', allow_duplicate=True),
     Output('dem-options-container', 'style', allow_duplicate=True),
     Output('borehole-options-container', 'style', allow_duplicate=True),
    ],
    Input('upload-data', 'contents'),
    running=[(Output("upload-data", "disabled"), True, False)],
    prevent_initial_call=True
)
def upload_file(contents):
    print("file upload here")
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
    if contents[0].startswith('data:application/x-zip'):
        # try:
        sesh.data, sesh.forwards = temframe.from_zip_content(contents[0])
        # except Exception as e:
        #     return (html.Div("Upload failed."),no_update,no_update,no_update,no_update,no_update,no_update,build_data_summary(),True,f"Upload failed: Only one geometry is supported at a time",True,True,no_update,no_update,no_update,no_update,no_update,{'display': 'block'}, {'display': 'block'})
    # sesh.site = sesh.overview
    sesh.data['include'] = sesh.data['inuse_manual'].astype(bool, copy=True).fillna(sesh.data['inuse_auto'])
    sesh.models          = None
    m1.dataframe    = sesh.overview.copy()
    
    
    buffer_length = 50
    # unique_sites = np.sort(sesh.data['site_id'].unique())
    # unique_sites = np.sort(sesh.data.loc[sesh.data['site_id'] != -1, 'site_id'].unique())
    unique_sites = np.sort(sesh.site['site_id'].dropna().unique())
    unique_sites = unique_sites#[unique_sites != -1]
    initial_sites = unique_sites[:buffer_length]

    m1.buffer_sites = initial_sites.tolist()
    mod1.dataframe  = sesh.models
    mod1.buffer_sites = initial_sites.tolist()
    mod2.dataframe  = sesh.models

    full_df = sesh.data.copy()

    buffered_df = full_df[full_df['site_id'].isin(initial_sites)].copy()

    dbdt1.dataframe = buffered_df
    dbdt2.dataframe = full_df          # keep full section view
    rhoa.dataframe  = buffered_df
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
    
    bbox_vals = (no_update, no_update, no_update, no_update)
    if 'longitude' in sesh.data.columns and 'latitude' in sesh.data.columns:
        min_lon = float(sesh.data['longitude'].min())
        max_lon = float(sesh.data['longitude'].max())
        min_lat = float(sesh.data['latitude'].min())
        max_lat = float(sesh.data['latitude'].max())
        pad = 0.01
        bbox_vals = (min_lon - pad, min_lat - pad, max_lon + pad, max_lat + pad)
    
    # return html.Div(upload_msg), m1.render(), dbdt1.render(), dbdt2.render(), rhoa.render(), Multi_inv.render(), Sing_inv.render(), 'data uploaded', True, toast_msg, False, False
    return html.Div(upload_msg), m1.render(), dbdt1.render(), dbdt2.render(), rhoa.render(), Multi_inv.render(), Sing_inv.render(), True, toast_msg, False, False, no_update, *bbox_vals, {'display': 'block'}, {'display': 'block'}


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
    Output({'type': f'settings-{dbdt2.id}', 'key': 'Borehole_radius'}, 'value'),
    Input({'type': f'settings-{mod2.id}', 'key': 'Borehole_radius'}, 'value'),
    prevent_initial_call=True
)
def sync_radius(bh_radius):
    return bh_radius


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
        return layouts.upload, *colors.values(), 

    elif button_id == "process_layout":
        return layouts.data, *colors.values(), 

    elif button_id == "invert_layout":
        return layouts.invert, *colors.values(), 

    elif button_id == "review_layout":
        return layouts.review, *colors.values(), 

    elif button_id == "interpret_layout":
        m1.make_grid()
        m1.settings.legend=True
        m1.settings.dragmode='pan'
        return layouts.interpret, *colors.values(), 

layout_output_list = [
        m1.output, dbdt1.output, dbdt2.output, rhoa.output, mod2.output,
        
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
        # _configure_tk_dpi_awareness()
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
        # res[-2] = sesh.save_dir
        res[-5] = sesh.save_dir


        if hasattr(sesh, 'borehole_list') and sesh.borehole_list is not None:
            # Transfer data to the display models
            from Sections_plotting import get_borehole_projections
            m1.boreholes = get_borehole_projections(sesh.borehole_list)
            mod1.boreholes = get_borehole_projections(sesh.borehole_list)
            mod2.boreholes = get_borehole_projections(sesh.borehole_list)
            
            # Transfer the color map
            if hasattr(sesh, 'rock_map') and sesh.rock_map is not None:
                m1.rock_color_map = sesh.rock_map
                mod1.rock_color_map = sesh.rock_map
                mod2.rock_color_map = sesh.rock_map
            
            res[-4] = True  # use-borehole value
            res[-3] = html.Span(["Use Borehole Data ", 
                    html.B("(Loaded from Session)", style={'color': '#28a745'}),
                    html.Br(), # Adds a line break to keep it tidy
                    html.Small("Upload a new .bor file below to overwrite existing data.", style={'color': '#6c757d', 'fontStyle': 'italic', 'fontSize': '0.85rem'})])
            res[-2] = {'display': 'block', 'marginTop': '10px'} # container style
            
            res[0] = m1.render()
        else:
            # If no boreholes, ensure UI reflects that
            res[-4] = False
            res[-3] = "Use Borehole Data (optional)"
            res[-2] = {'display': 'none'}

        if sesh.lines is not None:
            m1.lines = sesh.lines.copy()
            
        if sesh.data is not None:
            buffer_length = 50
            unique_sites = np.sort(sesh.site['site_id'].dropna().unique())
            initial_sites = unique_sites[:buffer_length].tolist()

            m1.buffer_sites = initial_sites        # <-- add this
            mod1.buffer_sites = initial_sites  

            dbdt1.dataframe = sesh.data.copy()    
            dbdt2.dataframe = sesh.data.copy()    
            m1.dataframe    = sesh.overview.copy()
            rhoa.dataframe  = sesh.data.copy()    
            Multi_inv.dataframe = sesh.data.copy()
            Sing_inv.dataframe = sesh.data.copy()
            res[0] = m1.render()
            res[1] = dbdt1.render()
            res[2] = dbdt2.render()
            res[3] = rhoa.render()
        
        if sesh.models is not None:
            mod1.dataframe  = sesh.models.copy()
            mod2.dataframe  = sesh.models.copy()
            res[4] = mod2.render()

            res[6]   = 'secondary'
            res[7]   = 'secondary'
            res[8]   = 'secondary'
            res[9]   = 'success'
            res[10]  = 'secondary'
            res[11]  = False
            res[12]  = False
            res[13]  = False
            res[14]  = False
            res[15]  = False
        else:

            res[6]   = 'success'
            res[7]   = 'secondary'
            res[8]   = 'secondary'
            res[9]   = 'secondary'
            res[10]   = 'secondary'

            res[11]  = False
            res[12]  = False
            res[13]  = False
            res[14]  = True
            res[15]  = True
            

    return res



@app.callback(
    Output(m1.id, 'figure', allow_duplicate=True),
    Input(mod2.id, 'hoverData'), 
    State(m1.id, 'figure'),
    prevent_initial_call=True
)
def sync_hover_to_map(hoverData, current_fig):
    if not hoverData or not current_fig:
        return no_update
    try:
        # For Heatmaps, customdata is returned via the 'points' list
        data = hoverData['points'][0].get('customdata')
        if data is None or len(data) < 3:
            return no_update
        
        if isinstance(data, dict):
            site_id = data.get('0')
            lat = float(data.get('1'))
            lon = float(data.get('2'))
        else:
            site_id = data[0]
            lat = float(data[1])
            lon = float(data[2])

        # If the ID is 'nan' (string), skip it
        if site_id == "nan":
            return no_update
    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"Hover Unpack Error: {e}")
        return no_update

    # Update the Map Figure
    fig = go.Figure(current_fig)
    
    # 1. Clear previous highlights
    fig.data = [t for t in fig.data if t.name != 'hover-highlight']
    
    # 2. Add the new pinpoint
    fig.add_trace(go.Scattermap(
        lat=[lat],
        lon=[lon],
        mode='markers',
        marker=dict(size=20,color='white',symbol='circle'),
        name='hover-highlight',
        showlegend=False
    ))
    
    # Add a second smaller dot inside for a 'target' look
    fig.add_trace(go.Scattermap(
        lat=[lat], lon=[lon],
        mode='markers',
        marker=dict(size=8, color='red'),
        name='hover-highlight',
        showlegend=False
    ))

    return fig


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