import sys, os, time
from tkinter import filedialog, Tk

# The packaged exe has no console window (PyInstaller --noconsole), so
# print() output and callback tracebacks (Flask logs them to stderr) would
# vanish. Send both to a log file instead, so problems on a user's machine
# can be diagnosed afterwards: %LOCALAPPDATA%\SeaAnemone\logs\sea_anemone.log
# (overwritten on every start).
if getattr(sys, 'frozen', False):
    try:
        _log_dir = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'SeaAnemone', 'logs')
        os.makedirs(_log_dir, exist_ok=True)
        _log_file = open(os.path.join(_log_dir, 'sea_anemone.log'), 'w', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = _log_file
        print(f'Sea Anemone started {time.strftime("%Y-%m-%d %H:%M:%S")}')
    except OSError:
        pass

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
import pandas as pd
import plotly.io as pio
import simplekml
from PIL import Image
import io
from datetime import datetime

import temframe

from model3d_panel import Model3D
from report_panel import ReportPanel, REPORT_SETTING_STATES, report_settings_from_states

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

mod3d = Model3D( dataframe=sesh.models ) 

Simple_inv = SimpleInversion( dataframe=sesh.data )
Multi_inv = MultiInversion( dataframe=sesh.data )
Sing_inv  = Single_site( dataframe=sesh.data, rho=10 )
hkr       = HotKeyReminder()
table_overview = TableOverview( dataframe=sesh.overview )
report_panel = ReportPanel()

panels = [u1, m1, dbdt1, dbdt2, mod1, mod2, mod3d, Simple_inv, Multi_inv, Sing_inv, rhoa, hkr, table_overview, report_panel]
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

    dcc.Store(id="export-request", data=None),
    # Last camera (angle/azimuth/zoom) of the 3D Model view -- see
    # remember_3d_camera. Used by the report and the Interpret export.
    dcc.Store(id="model-3d-camera", data=None),

    dcc.Store(id="borehole-loaded", data=False),

    # Multi-file upload staging: pending-upload-store holds the raw zip
    # contents between file selection and confirmation; upload-action-store
    # is the sole trigger that actually processes them ('merge' onto the
    # current session, or 'fresh' to reset sesh first) -- see
    # stage_upload/process_upload below.
    dcc.Store(id="pending-upload-store", data=None),
    dcc.Store(id="upload-action-store", data=None),
    dbc.Modal(
        id="upload-confirm-modal", is_open=False, backdrop="static", keyboard=False,
        children=[
            dbc.ModalHeader("Confirm upload"),
            dbc.ModalBody(id="upload-confirm-modal-body"),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="upload-confirm-no-btn", color="secondary"),
                dbc.Button("Proceed", id="upload-confirm-yes-btn", color="primary"),
            ]),
        ],
    ),
    dbc.Modal(
        id="upload-fresh-modal", is_open=False, backdrop="static", keyboard=False,
        children=[
            dbc.ModalHeader("Start a new session?"),
            dbc.ModalBody(id="upload-fresh-modal-body"),
            dbc.ModalFooter([
                dbc.Button("Cancel upload", id="upload-fresh-no-btn", color="secondary"),
                dbc.Button("Start new session", id="upload-fresh-yes-btn", color="danger"),
            ]),
        ],
    ),

    dcc.Store(id="compare-click-store", data=None),
    dcc.Store(id="compare-window-store", data={"window_id": None, "items": []}),
    # Individual windows (Sections_plotting.create_draggable_window) are
    # only zIndex 1000 -- same as the top nav bar and the interpret
    # panels' floating x-axis/radius controls, so DOM order was deciding
    # the tie and losing. Giving the container itself a high zIndex (the
    # same fix used in the app_weiyang.py/GIS_profile_only.py reference
    # implementations of this feature) makes its children stack above
    # everything outside it regardless of the children's own z-index.
    html.Div(id="compare-window-container", children=[], style={"position": "relative", "zIndex": 9999}),

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
    dbc.Toast(
        "",
        id="export-toast",
        header="Export",
        is_open=False,
        dismissable=True,
        duration=8000,
        icon="success",
        style={"position": "fixed", "top": "70px", "right": "20px", "width": 350, "zIndex": 2000},
    ),
    dbc.Toast(
        "",
        id="session-load-toast",
        header="Session Loaded",
        is_open=False,
        dismissable=True,
        duration=6000,
        icon="success",
        style={"position": "fixed", "top": "70px", "right": "20px", "width": 350, "zIndex": 2000},
    ),
    dbc.Toast(
        "",
        id="dem-toast",
        header="DEM",
        is_open=False,
        dismissable=True,
        duration=6000,
        icon="success",
        style={"position": "fixed", "top": "70px", "right": "20px", "width": 350, "zIndex": 2000},
    ),
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
    html.Div(
        [flex_layout],
        style={
            'marginTop': '60px',
            # FlexLayout computes its panels' pixel sizes from this
            # container's own box, not from its content -- without an
            # explicit height here, this div only got as tall as "auto"
            # resolved to (which depends on the browser/screen/DPI, not
            # the actual window size), so on some machines FlexLayout had
            # too little room to work with and panels ended up clipped.
            # calc(100vh - 60px) is viewport-relative, so it doesn't rely
            # on the ancestor chain (html/body/#react-entry-point) having
            # explicit heights of their own -- vh always resolves.
            'height': 'calc(100vh - 60px)',
            'width': '100%',
            'overflow': 'hidden',
        },
    ),
    html.Div(id='output-click'),
], style={'height': '100vh', 'width': '100vw', 'margin': 0})

for panel in panels:
    panel.add_callbacks(app)

from compare_popups import register_compare_callbacks
register_compare_callbacks(app, mod2, dbdt2, dbdt1)

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
        # NOT reading point['customdata'] here -- confirmed elsewhere in
        # this app (see unified_handler's Model Section note) that this
        # Dash/Plotly build never actually includes customdata in the
        # selectedData payload, only curveNumber/pointNumber/x/y/lat/lon
        # (an earlier version of this fix assumed customdata WAS present,
        # which made box-select silently select nothing at all). Instead,
        # curveNumber is mapped to a layer name via m1._layers, then
        # pointNumber is looked up in m1._layer_site_ids[layer] -- a
        # point-index -> site_id list Map.render() builds server-side
        # from each trace's own customdata (reliable there, since it
        # never has to round-trip through the browser). This also covers
        # BOTH the normal site trace ('sites') and, in Enabled/Disabled
        # mode, the disabled-sites overlay ('disabled_sites') -- box-
        # selecting across both enabled and disabled markers together now
        # captures all of them, not just whichever trace is named 'sites'.
        layer_site_ids = getattr(m1, '_layer_site_ids', {})
        selected_sites = []
        for point in selected_data['points']:
            curve_number = point.get('curveNumber')
            point_number = point.get('pointNumber')
            if curve_number is None or point_number is None or curve_number >= len(m1._layers):
                continue
            site_ids_for_layer = layer_site_ids.get(m1._layers[curve_number])
            if site_ids_for_layer is not None and point_number < len(site_ids_for_layer):
                selected_sites.append(site_ids_for_layer[point_number])
    else:
        selected_sites = []

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
        # ModelGraph always plots by site_id -- give it the explicit
        # selection directly rather than relying on buffer_start/buffer_len,
        # which may currently be in a different axis's units (e.g. daytime
        # milliseconds) and would otherwise silently produce an empty/wrong
        # slice on top of the already-filtered dataframe above.
        mod1.buffer_sites = selected_sites
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
    # A fresh top-level uirevision on every render here, same reasoning
    # (and same fix) as unified_handler's own -- without one, Plotly tries
    # to carry over the in-progress box-select's own client-side
    # selectedpoints/dimming state onto this brand new figure instead of
    # using the clean, fully-opaque state this render actually produces,
    # which made the just-selected (and any other) markers -- most
    # noticeably the whole disabled-sites overlay -- appear to vanish
    # after selecting. legend.uirevision (set inside Map.render() itself)
    # is independent of this and keeps working regardless.
    m1_patch.update_layout(uirevision=f"rev-{time.time()!r}")

    # m1_patch = Patch()
    # m1_patch["data"][0]["selected"]   = {"marker": {"size": int(m1.settings.markersize*1.5)}}
    # m1_patch["data"][0]["unselected"] = {"marker": {"opacity": 0.6}}

    mod2_patch["layout"]["xaxis"]["range"]  = [xmin, xmax]
    dbdt2_patch["layout"]["xaxis"]["range"] = [xmin, xmax]
    # dbdt2.xlim = [xmin, xmax]

    # Keep the buffer window in the same units as the resolved transect
    # x-axis (site count / minutes / meters) -- xmin/xmax above already
    # come from dbdt2.xlim(), which resolves through the same axis logic.
    # A raw site count here would silently corrupt the window (and the
    # displayed "Buffer length") whenever the axis isn't site_id.
    if xmin is not None and xmax is not None:
        buffer_length = xmax - xmin
        buffer_start  = xmin
    else:
        buffer_length = len(selected_sites)
        buffer_start  = 0

    _, factor = dbdt2._buffer_unit()
    buffer_length_display = buffer_length / factor

    data_buffer = {"length": buffer_length, "start_site": buffer_start}
    return dbdt1_patch, dbdt2_patch, rhoa_patch, mod1_patch, mod2_patch, m1_patch, data_buffer, buffer_length_display

app.clientside_callback(
    hkr.javascript,
    Output("disableButton", "id"),
    Input("disableButton", "id")
)

@app.callback(m1.output,
    dbdt1.output, dbdt2.output, rhoa.output, mod1.output, mod2.output,

    Output("selected_ids_store", "data", allow_duplicate=True),
    Output("selected_sites_store", "data", allow_duplicate=True),
    Output("selected_sites_local", "data", allow_duplicate=True),

    Input("disableButton", "n_clicks"),
    Input("enableButton", "n_clicks"),
    Input("clearSelectionButton", "n_clicks"),
    Input("tTEM", "selectedData"),
    Input("sounding", "selectedData"),
    Input("rhoa", "selectedData"),
    Input("model_section", "selectedData"),

    State("selected_ids_store", "data"),
    State("selected_sites_store", "data"),
    State("selected_sites_local", "data"),
    State('interpret_layout', 'color'),
    State('data-buffer', 'data'),
    prevent_initial_call=True,)

def unified_handler(n1, n2, n_clear,
                    ttem_sel, sounding_sel, rhoa_sel, model_section_sel,
                    stored_data_ids, stored_site_ids, stored_site_ids_local,
                    layout_color, buffer_data):
    
    if layout_color == 'primary':
        raise PreventUpdate

    trigger = str(ctx.triggered_id)
    prop_id = ctx.triggered[0]["prop_id"]
    df_data = sesh.data

    # Plotly fires its own selectedData=None/empty-points event whenever a
    # figure using dragmode='select' gets replaced -- and since tTEM,
    # Sounding, Apparent res and Model Section are all re-rendered as part
    # of nearly every cross-panel callback in this app, that happens
    # constantly, not just from a genuine user deselect click (confirmed
    # via a live debug trace). There's no reliable way to tell the two
    # apart from here. Explicitly clearing the highlight on this used to
    # wipe out a selection that had just been correctly set moments
    # earlier; falling through to the "no explicit selection" branch
    # below instead re-populated it with *every* currently-buffered site
    # (looking like everything was selected). Ignoring the event entirely
    # -- leaving whatever's currently highlighted alone -- is the only
    # option that isn't wrong in one direction or the other.
    selection_payloads = {"tTEM": ttem_sel, "sounding": sounding_sel, "rhoa": rhoa_sel, "model_section": model_section_sel}
    if trigger in selection_payloads and not (selection_payloads[trigger] and selection_payloads[trigger].get("points")):
        raise PreventUpdate

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

    elif trigger == "model_section" and model_section_sel and model_section_sel.get('points'):
        # Model Section's select-targets overlay trace (model.py) carries
        # customdata=[site_id, latitude, longitude] per marker, but -- like
        # clickData.points[i].data found earlier in this app --
        # selectedData.points[i] doesn't actually include customdata in
        # this Plotly build (confirmed via a live debug dump: points only
        # ever carried curveNumber/pointIndex/x/y). Falling back to 'x'
        # instead works reliably: QC mode always forces x_axis='site_id'
        # (see model.py's toggle_qc_vs_interpret), and the select-targets
        # markers are placed at x=<site_id> for that axis, so a selected
        # point's own x *is* its site_id directly -- no customdata needed.
        # There's no per-gate data_id here (this is a per-site resistivity
        # model, not gate-level decay data), so instead of picking out
        # specific gates, every data_id belonging to a selected site is
        # treated as "selected" -- since dbdt1/rhoa's dataframe gets
        # narrowed to exactly these sites below anyway, this makes every
        # point they show get the same orange "selected" styling the
        # highlight loop already applies elsewhere, rather than falling
        # through to no styling at all.
        active_site_ids = list(set(int(round(p['x'])) for p in model_section_sel['points'] if 'x' in p))
        active_data_ids = df_data.loc[df_data['site_id'].isin(active_site_ids), 'data_id'].tolist()
        map_site_ids = active_site_ids.copy()
        active_site_ids_local = []

    else:
        # Keep the sites that are currently loaded in the plots. Read this
        # from dbdt1.dataframe directly rather than the stored site-id list:
        # other callbacks (buffer navigation, map selection, arrow-key
        # navigation) can update dbdt1/rhoa's dataframe without going
        # through this store, so stored_site_ids can go stale and
        # re-narrow the plots back to an old selection on every sounding/
        # rhoa point pick.
        active_site_ids = dbdt1.dataframe['site_id'].unique().tolist()
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

    # Explicit "Clear Selection" button -- added because a genuine
    # double-click-to-deselect on tTEM/sounding/rhoa/model_section can't
    # be told apart from Plotly's own spurious selectedData=None events
    # (see the removed-branch note below), so those are ignored entirely
    # and a real click-to-clear silently did nothing outside the panel it
    # was clicked in. active_data_ids=[]/map_site_ids=[] makes step 7
    # below reset every panel's selectedpoints/opacity styling and
    # highlight back to normal. active_site_ids also needs recomputing
    # here, NOT left at the SITE FILTERING step's fallback above
    # (`dbdt1.dataframe['site_id'].unique()`) -- that reads back
    # dbdt1.dataframe itself, which is exactly what's currently narrowed
    # to the selection being cleared, so it would just re-apply the same
    # narrowing instead of undoing it. Recompute the actual buffer window
    # from data-buffer's start/length instead (the same source
    # update_model_section_from_buffer uses), which was never narrowed.
    elif trigger == "clearSelectionButton":
        if buffer_data:
            active_site_ids = list(compute_buffer_sites(buffer_data))
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

    # NOTE: there used to be an `elif ".selectedData" in prop_id: if sel is
    # None: clear everything` branch here, meant to support clicking away
    # from a selection to deselect it. Removed: Plotly fires its own
    # selectedData=None event whenever a figure with dragmode='select'
    # gets replaced -- entirely independent of uirevision or any explicit
    # clearing -- and since dbdt2 (tTEM) is re-rendered as part of nearly
    # every cross-panel callback in this app, that happens constantly, not
    # just on a genuine deselect click. Confirmed via a live debug trace:
    # after correctly setting m1.highlighted=[52,53,54] from a Model
    # Section selection, the very next event was trigger='tTEM' with
    # ttem_sel=None (no user action involved -- tTEM had just been
    # re-rendered as a side effect), and this branch wiped the highlight
    # right back to []. There's no reliable way from here to tell a real
    # deselect click apart from an incidental re-render resetting the
    # selection tool, so this is removed rather than made "smarter".

    # 5. Apply site filtering
    dbdt1.dataframe = df_data[df_data["site_id"].isin(active_site_ids)]
    rhoa.dataframe = df_data[df_data["site_id"].isin(active_site_ids)]

    # keep full tTEM for re-selection
    dbdt2.dataframe = df_data

    # Model Graph shows one resistivity profile line per site in
    # buffer_sites (see ModelGraph.render()) -- keep it in sync with
    # whatever selection narrowed active_site_ids too, whether that came
    # from Model Section, Transect view, Sounding, or Apparent res.
    mod1.buffer_sites = active_site_ids

    if len(active_site_ids_local) != 0:
        if len(active_site_ids_local) < len(active_site_ids) or len(active_site_ids_local) == len(active_site_ids):
            m1.highlighted = active_site_ids_local.copy()
    else:
        m1.highlighted = map_site_ids

    # Model Section draws a black-boundary rect per site in `highlighted`
    # (see ModelSection.render()) -- mirror whatever m1.highlighted just
    # resolved to above, so the two panels always agree on which sites are
    # selected regardless of which panel the selection actually came from.
    mod2.highlighted = m1.highlighted

    # 6. Render
    fig0 = m1.render()
    fig1 = dbdt1.render()
    fig2 = dbdt2.render()
    fig3 = rhoa.render()
    fig4 = mod1.render()
    fig5 = mod2.render()

    # Every render here already bakes in the correct selectedpoints/
    # selected styling explicitly (see the loop below), so there's nothing
    # that needs to be *preserved* from a prior render via uirevision --
    # give each render a guaranteed-unique tag so Plotly never tries to
    # blend in an older render's selection state (which caused stale
    # highlighting to survive across buffer navigation and selections).
    revision = f"rev-{time.time()!r}"
    for fig in [fig0, fig1, fig2, fig3, fig4, fig5]:
        if fig is not None:
            fig.update_layout(uirevision=revision, dragmode="select")

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
                    trace.selected = {"marker": {"color": m1.settings.highlight_color ,"opacity": 1,"size": 9}}
                    trace.unselected = {"marker": {"opacity": 0.1}}
                else:
                    trace.selected = {"marker": {"color": m1.settings.highlight_color ,"opacity": 0.8,"size": 10}}
                    trace.unselected = {"marker": {"opacity": 0.1}}
            elif active_data_ids:
                trace.selectedpoints = []
                trace.unselected = {"marker": {"opacity": 0.1}}

            else:
                trace.selectedpoints = None
                trace.unselected = {"marker": {"opacity": 1}}

    return (fig0, fig1, fig2, fig3, fig4, fig5, active_data_ids, active_site_ids, active_site_ids_local)


def get_shown_site_locations(panel):
    """
    Return a DataFrame of (site_id, latitude, longitude) for the sites
    currently displayed by `panel` (a ModelSection), respecting its
    x-axis choice (site_id/daytime/line N) and current buffer window --
    mirrors the windowing ModelSection.render() itself applies. Rows are
    ordered by the resolved x-axis value, so a line drawn through them
    follows the same left-to-right order shown on screen.
    """
    empty = pd.DataFrame(columns=['site_id', 'latitude', 'longitude'])
    if panel.dataframe is None:
        return empty

    raw_x_axis = panel.settings.x_axis
    if raw_x_axis.startswith('line'):
        if sesh.models is None:
            return empty
        line_id = int(float(raw_x_axis.split(' ')[-1]))
        line_col = f'_line_{line_id:0.0f}_x'
        df = sesh.models.copy()
        df = df.loc[np.abs(df[line_col.replace('_x', '_y')]) < panel.settings.radius]
        x_col = line_col
    else:
        df, x_col = panel._prepare_x_axis(panel.dataframe.copy())
        x_vals = np.sort(df[x_col].dropna().unique())
        if len(x_vals) > 0:
            x_slice = x_vals[(x_vals >= panel.buffer_start) & (x_vals <= panel.buffer_start + panel.buffer_len)]
            if len(x_slice) > 0:
                df = df[df[x_col].isin(x_slice)]

    if df is None or df.empty:
        return empty

    return (
        df.dropna(subset=['latitude', 'longitude', x_col])
          .sort_values(x_col)
          .drop_duplicates('site_id')[['site_id', 'latitude', 'longitude']]
          .reset_index(drop=True)
    )


def export_interpret_view(export_3d=False, camera=None):
    """
    Export the current Interpret-tab view.

    Normal case: a combined PNG of the map and model section (stacked),
    and a KMZ containing that PNG plus a line/point marking the locations
    of the sites currently shown in the model section (clicking it in
    Google Earth pops up the image).

    export_3d=True: a combined PNG of the map and the 3D model view
    (stacked), named with a trailing "_3D", and no KMZ (there's no single
    section line to georeference a 3D view against). `camera` -- the
    scene.camera dict read straight off the live Plotly graph in the
    browser -- is applied to the 3D figure so the export matches whatever
    orientation the user rotated it to, rather than the default view.

    Saves into sesh.save_dir (or the working directory if unset). Returns
    (png_path, kmz_path, basemap_dropped) -- kmz_path is None when
    export_3d is True; basemap_dropped is True if the satellite background
    couldn't be downloaded and the map was exported without it.
    """
    save_dir = sesh.save_dir or os.getcwd()
    os.makedirs(save_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"interpret_export_{timestamp}" + ("_3D" if export_3d else "")
    png_path = os.path.join(save_dir, f"{base_name}.png")

    # Same map decorations (north arrow, scale bar, UTM tick labels) and
    # pixel size report.py uses for its own map figures, applied on top of
    # whatever plot_by/mean_res/view the Map panel is currently showing
    # live -- so this stays a "what you see is what you export" capture of
    # the current screen, just dressed up the same way a report figure is.
    import report
    has_colorbar = report._map_has_colorbar(m1)
    # The editable/erasable line shape is positioned in fixed paper
    # coordinates from the live browser's own pixel size -- rendering it
    # again at the export's PNG dimensions leaves it visibly offset from
    # the real line trace (a second, near-identical dashed line). It's a
    # drag-to-edit affordance only, so skip it for this static export.
    orig_suppress_line_shape = m1.suppress_line_shape_overlay
    m1.suppress_line_shape_overlay = True
    try:
        map_fig = report._add_map_decorations(m1.render(), m1.settings.view, has_colorbar=has_colorbar)
    finally:
        m1.suppress_line_shape_overlay = orig_suppress_line_shape
    # figure_to_png retries, and falls back to no satellite background if
    # the tiles won't download ("Error 525: Map error.") -- see report.py.
    map_png_bytes, basemap_dropped = report.figure_to_png(
        map_fig, report.REPORT_IMG_WIDTH, report.REPORT_IMG_HEIGHT, report.REPORT_IMG_SCALE)

    if export_3d:
        second_fig = mod3d.render()
        if camera:
            second_fig.update_layout(scene_camera=camera)
        second_width, second_height = 1200, 600
    else:
        # Same aspect ratio as Appendix A's line-profile figures in the
        # report (15.24 x 6.45cm) -- mod2.render() itself already reflects
        # whatever x-axis (line N/site_id/daytime) is currently selected.
        second_fig = mod2.render()
        second_width, second_height = report.PROFILE_IMG_WIDTH, report.PROFILE_IMG_HEIGHT
    second_png_bytes, _ = report.figure_to_png(second_fig, second_width, second_height)

    map_img    = Image.open(io.BytesIO(map_png_bytes)).convert('RGB')
    second_img = Image.open(io.BytesIO(second_png_bytes)).convert('RGB')

    width = max(map_img.width, second_img.width)
    combined = Image.new('RGB', (width, map_img.height + second_img.height), 'white')
    combined.paste(map_img, ((width - map_img.width) // 2, 0))
    combined.paste(second_img, ((width - second_img.width) // 2, map_img.height))
    combined.save(png_path)

    if export_3d:
        return png_path, None, basemap_dropped

    kmz_path = os.path.join(save_dir, f"{base_name}.kmz")
    locations = get_shown_site_locations(mod2)

    kml = simplekml.Kml()
    # addfile() stores the PNG inside the KMZ as files/<name>.png and
    # returns that path -- the balloon must reference it exactly, or
    # Google Earth shows an empty picture (it used the bare file name).
    png_in_kmz = kml.addfile(png_path)
    balloon = f'<![CDATA[<img src="{png_in_kmz}" width="1000" />]]>'
    if len(locations) >= 2:
        ls = kml.newlinestring(name="Interpret view")
        ls.coords = list(zip(locations['longitude'], locations['latitude']))
        ls.style.linestyle.width = 4
        ls.style.linestyle.color = simplekml.Color.red
        ls.description = balloon
    elif len(locations) == 1:
        pnt = kml.newpoint(
            name="Interpret view",
            coords=[(locations['longitude'].iloc[0], locations['latitude'].iloc[0])],
        )
        pnt.description = balloon

    kml.savekmz(kmz_path)

    return png_path, kmz_path, basemap_dropped


def session_name():
    """The session's folder name (e.g. LM_202610_Chad_Arkoum), or 'session' if it hasn't been saved yet."""
    if not sesh.save_dir:
        return 'session'
    name = os.path.basename(os.path.normpath(sesh.save_dir))
    return ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in name) or 'session'


def export_site_shapefiles(save_dir, name):
    """
    One point shapefile per map "Color by" mode, for QGIS, in WGS84
    (EPSG:4326), each with the sites and that mode's attribute:
      <name>_FromImport.shp       site attributes only
      <name>_EnabledDisabled.shp  + status ('Enabled'/'Disabled') and gates
                                  (number of data points in use)
      <name>_Misfit.shp           + misfit   (needs an inversion)
      <name>_DOI.shp              + doi      (needs an inversion)
    Every file also has site_id, date, daytime, latitude, longitude,
    elev, utm_x, utm_y and instrument. Existing files with the same name
    are overwritten. Field names are short because shapefile (dBase)
    fields are limited to 10 characters.

    Returns (written, skipped): a list of .shp paths, and the names of
    the files skipped because their attribute doesn't exist yet.
    """
    import geopandas as gpd

    site = sesh.site
    if site is None or site.empty:
        return [], []
    site = site[site['site_id'] != -1].dropna(subset=['latitude', 'longitude']).copy()
    base_cols = [c for c in ('site_id', 'date', 'daytime', 'latitude', 'longitude', 'elevation',
                             'utm_x', 'utm_y', 'instrument') if c in site.columns]

    # Enabled/disabled from the data's own in-use flags, with the same rule
    # as the map (a site is disabled when none of its data points is in
    # use) -- sesh.site's gates_used column only exists after an inversion.
    data = sesh.data[sesh.data['site_id'] != -1]
    # Manual flag wins where set, else the automatic one (same as the
    # Disable/Enable buttons' 'include' column).
    in_use = data['inuse_manual'].fillna(data['inuse_auto']).astype(bool)
    gates = in_use.groupby(data['site_id']).sum()
    site['gates'] = site['site_id'].map(gates).fillna(0).astype(int)
    site['status'] = np.where(site['gates'] > 0, 'Enabled', 'Disabled')

    layers = [
        ('FromImport', []),
        ('EnabledDisabled', ['status', 'gates']),
        ('Misfit', ['misfit']),
        ('DOI', ['doi']),
    ]
    written, skipped = [], []
    for suffix, extra in layers:
        if any(c not in site.columns for c in extra):
            skipped.append(suffix)
            continue
        table = site[base_cols + extra].rename(columns={'elevation': 'elev', 'instrument': 'instrumen'})
        gdf = gpd.GeoDataFrame(table, geometry=gpd.points_from_xy(table['longitude'], table['latitude']), crs='EPSG:4326')
        path = os.path.join(save_dir, f"{name}_{suffix}.shp")
        # Windows' 260-character path limit: GDAL can write such a file but
        # then can't reopen or replace it ("... .shp is not a directory").
        if len(os.path.abspath(path)) > 255:
            raise ValueError(f"the folder path is too long for Windows ({len(os.path.abspath(path))} characters "
                             "incl. file name, max ~255). Save the session in a shorter folder path and export again.")
        # Remove the previous export's files first, so re-exporting replaces them.
        stem = os.path.splitext(path)[0]
        for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            if os.path.exists(stem + ext):
                os.remove(stem + ext)
        gdf.to_file(path, driver='ESRI Shapefile', engine='pyogrio')
        written.append(path)
    return written, skipped


# The FlexLayout `model` prop tracks the whole layout tree (sizes, active
# borders, etc.), not just tab selection, and is a poor/unreliable signal
# for "which Interpret sub-tab is on screen right now". Instead, on the
# same click that triggers the export, read visibility straight off the
# DOM. This runs as a clientside callback so it resolves before the
# server-side export callback (chained off this Store, not off n_clicks
# directly) ever fires -- avoiding a race between two n_clicks-triggered
# callbacks. The camera orientation itself is read server-side instead,
# from model_3d's own `relayoutData` prop (see export_interpret_view_callback)
# -- that's a native Dash/Plotly prop Plotly already keeps in sync on every
# 3D drag, so there's no need to go digging through the DOM for it.
app.clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) { return window.dash_clientside.no_update; }
        var outer = document.getElementById('model_3d');
        var visible = false;
        if (outer) {
            var rect = outer.getBoundingClientRect();
            visible = outer.offsetParent !== null && rect.width > 0 && rect.height > 0;
        }
        return {n_clicks: n_clicks, export_3d: visible};
    }
    """,
    Output('export-request', 'data'),
    Input('enableButton', 'n_clicks'),
    prevent_initial_call=True,
)


@app.callback(
    Output('model-3d-camera', 'data'),
    Input('model_3d', 'relayoutData'),
    State('model-3d-camera', 'data'),
    prevent_initial_call=True,
)
def remember_3d_camera(relayout_data, camera):
    # relayoutData only holds the most recent event, and resizing the
    # graph (e.g. switching tabs) replaces the camera with
    # {'autosize': True}. Keep the last camera seen instead. Plotly sends
    # either the whole camera ('scene.camera') or single parts of it
    # ('scene.camera.eye', ...).
    if not relayout_data:
        raise PreventUpdate
    camera = dict(camera or {})
    changed = False
    for key, value in relayout_data.items():
        if key == 'scene.camera' and isinstance(value, dict):
            camera.update(value)
            changed = True
        elif key.startswith('scene.camera.'):
            camera[key[len('scene.camera.'):]] = value
            changed = True
    if not changed:
        raise PreventUpdate
    return camera


@app.callback(
    Output('export-toast', 'is_open'),
    Output('export-toast', 'children'),
    Output('export-toast', 'icon'),
    Input('export-request', 'data'),
    State('interpret_layout', 'color'),
    State('model-3d-camera', 'data'),
    prevent_initial_call=True,
)
def export_interpret_view_callback(export_request, interpret_layout_color, saved_camera):
    # The Enable/Export button is dual-purpose: unified_handler above
    # bails out immediately whenever the Interpret tab is active (color
    # == 'primary'), so this callback -- the mirror-image condition --
    # is the only one that ever acts on that click while on that tab.
    if interpret_layout_color != 'primary' or not export_request:
        raise PreventUpdate

    if sesh.data is None:
        return True, "No data loaded to export.", "warning"

    export_3d = bool(export_request.get('export_3d'))
    # Last camera of the 3D view (see remember_3d_camera); None if the
    # user never rotated it, which means the default view.
    camera = saved_camera if export_3d else None

    try:
        png_path, kmz_path, basemap_dropped = export_interpret_view(export_3d=export_3d, camera=camera)
    except Exception as e:
        print(f"Export failed: {e}")
        return True, f"Export failed: {e}", "danger"

    children = [html.Div(f"Saved {os.path.basename(png_path)}")]
    if kmz_path:
        children.append(html.Div(f"Saved {os.path.basename(kmz_path)}"))
    children.append(html.Div(f"in {os.path.dirname(png_path)}", style={"fontSize": "0.85rem", "color": "#6c757d"}))
    if basemap_dropped:
        children.append(html.Div("The satellite background couldn't be downloaded, so the map was "
                                 "exported without it. Check the internet connection and export again.",
                                 style={"fontSize": "0.85rem", "marginTop": "4px"}))

    return True, html.Div(children), ("warning" if basemap_dropped else "success")


@app.callback(
    Output('export-toast', 'is_open', allow_duplicate=True),
    Output('export-toast', 'children', allow_duplicate=True),
    Output('export-toast', 'icon', allow_duplicate=True),
    Input('exportShpButton', 'n_clicks'),
    prevent_initial_call=True,
)
def export_shapefile_callback(n_clicks):
    # "🗺️ Export to .shp" on the Interpret tab (see panels.py).
    if not n_clicks:
        raise PreventUpdate
    if sesh.data is None:
        return True, "No data loaded to export.", "warning"
    save_dir = sesh.save_dir or os.getcwd()
    os.makedirs(save_dir, exist_ok=True)
    try:
        written, skipped = export_site_shapefiles(save_dir, session_name())
    except Exception as e:
        print(f"Shapefile export failed: {e}")
        return True, f"Shapefile export failed: {e}", "danger"
    if not written:
        return True, "No sites to export.", "warning"
    children = [html.Div(f"Saved {os.path.basename(p)}") for p in written]
    if skipped:
        children.append(html.Div(f"Skipped {', '.join(skipped)}: run an inversion first.",
                                 style={"fontSize": "0.85rem", "marginTop": "4px"}))
    children.append(html.Div(f"in {save_dir}", style={"fontSize": "0.85rem", "color": "#6c757d"}))
    return True, html.Div(children), "success"


def refresh_dbdt2_for_line_mode():
    """
    dbdt2.dataframe can be a stale snapshot missing a just-drawn line's
    _line_N_x/_line_N_y projection columns (those only exist on the
    freshly-recomputed sesh.data). dbdtSection's own render()/
    observed_only()/xlim() already refresh from sesh.data before using
    'line N' as the x-axis; call this before any other dbdt2._prepare_x_axis
    call so it doesn't KeyError on the new column.
    """
    x_axis = dbdt2.settings.x_axis
    if x_axis.startswith('line'):
        line_id = int(float(x_axis.split(' ')[-1]))
        line_col = f'_line_{line_id:0.0f}_x'
        y_col = line_col.replace('_x', '_y')
        dbdt2.dataframe = sesh.data.copy()
        if y_col not in dbdt2.dataframe.columns:
            # The line's projection columns haven't made it onto sesh.data
            # yet -- e.g. a race with the line-drawing callback that
            # triggers sesh.update_site_table(), or a line that's since
            # been erased out from under this axis selection. This used to
            # KeyError here, which is disruptive since update_buffer_progress
            # (the only caller) fires on nearly every Map/Transect re-render.
            # Fall back to site_id, matching the same fallback the
            # line-eraser path already applies when a line disappears.
            dbdt2.settings.x_axis = 'site_id'
            return
        dbdt2.dataframe = dbdt2.dataframe.loc[np.abs(dbdt2.dataframe[y_col]) < dbdt2.settings.radius]


def compute_buffer_sites(buffer_data):
    """
    Resolve a {"start_site", "length"} buffer window (in whatever units
    dbdt2's current x-axis uses -- site count/minutes/meters/etc, not
    indices) into the actual site_id list it currently covers. Pulled out
    of update_model_section_from_buffer so unified_handler's "Clear
    Selection" button can restore the SAME full buffer window rather than
    re-deriving it from dbdt1.dataframe, which is itself narrowed to
    whatever selection is being cleared (that was the actual bug: reading
    "the current buffer" back from an already-narrowed dataframe just
    re-applies the narrowing instead of undoing it).
    """
    start = buffer_data["start_site"]
    length = buffer_data["length"]
    refresh_dbdt2_for_line_mode()
    df, x_axis, _ = dbdt2._prepare_x_axis(dbdt2.dataframe)
    df_buf = df
    if x_axis == "site_id":
        df_buf = df_buf[df_buf["site_id"] != -1]
    x_vals = np.sort(df_buf[x_axis].dropna().unique())
    x_slice = x_vals[(x_vals >= start) & (x_vals <= start + length)]
    return (
        df[(df[x_axis].isin(x_slice)) & (df["site_id"] != -1)]["site_id"]
        .dropna()
        .unique()
    )


@app.callback(
    mod2.output, dbdt2.output, dbdt1.output, m1.output, mod1.output, rhoa.output,
    Output("selected_ids_store", "data", allow_duplicate=True),
    Output("selected_sites_local", "data", allow_duplicate=True),
    Output("tTEM", "selectedData", allow_duplicate=True),
    Output("sounding", "selectedData", allow_duplicate=True),
    Output("rhoa", "selectedData", allow_duplicate=True),
    Input('data-buffer', 'data'),
    prevent_initial_call=True
)
def update_model_section_from_buffer(buffer_data):
    start  = buffer_data["start_site"]
    length = buffer_data["length"]

    # Update model section buffer
    mod2.buffer_start = start
    mod2.buffer_len   = length

    # Update tTEM buffer
    dbdt2.buffer_start = start
    dbdt2.buffer_len   = length

    # start/length are values in the same physical units as the resolved
    # x-axis column (site count / minutes / meters), not indices.
    buffer_sites = compute_buffer_sites(buffer_data)

    # ModelGraph always plots by site_id regardless of the transect's
    # x-axis unit, so hand it the resolved site list directly rather than
    # a start/length pair that could be in the wrong units.
    mod1.buffer_sites = buffer_sites

    if buffer_data.get("source") == "buffer_button":
        dbdt1.dataframe = sesh.data[sesh.data["site_id"].isin(buffer_sites)]
        rhoa.dataframe  = sesh.data[sesh.data["site_id"].isin(buffer_sites)]
    m1.buffer_sites = buffer_sites
    m1.is_last_tab = False
    if buffer_data.get("source") == "buffer_button":
        mod1.highlighted = None
        mod2.highlighted = None
        m1.highlighted = None
        dbdt2.highlighted = None

    figs = (mod2.render(), dbdt2.render(), dbdt1.render(), m1.render(), mod1.render(), rhoa.render())

    # Paging through the buffer changes which points/sites these figures
    # contain, so any point-level highlight left over from a previous
    # sounding/rhoa/tTEM selection (unified_handler) no longer corresponds
    # to the same data. Give each figure a guaranteed-unique uirevision so
    # Plotly never tries to carry the old selection's marker styling over
    # onto different points, and clear the stored selection so it can't
    # get silently reapplied by a later unrelated callback.
    revision = f"rev-{time.time()!r}"
    for fig in figs:
        if fig is not None:
            fig.update_layout(uirevision=revision)

    # Explicitly clear each graph's selectedData too. Otherwise the
    # browser's own reset of a stale selection (now pointing at different
    # data after the figure swap) fires as an independent, unordered event
    # -- if it lands after a selection you make right after paging the
    # buffer, it silently wipes out that selection instead of the old one.
    # Clearing it here, as part of this same update, makes the reset
    # deterministic instead of racy. (model_section's own selectedData is
    # deliberately NOT cleared here the same way -- doing that for
    # highlight_change's Next/Previous flow turned out to backfire: the
    # clearing write is itself a prop change, and unified_handler listens
    # to exactly these props, so it immediately re-fired, saw a None
    # selection, and wiped out the highlight this callback had just set.
    # This function still clears tTEM/sounding/rhoa's stale selection --
    # unlike Next/Previous, buffer paging is *supposed* to drop any
    # active highlight, so unified_handler re-firing and landing on
    # "nothing selected" here doesn't undo anything real.)
    return (*figs, [], [], None, None, None)

@app.callback(
    Output('data-buffer', 'data', allow_duplicate=True),
    Input('beginning-buffer', 'n_clicks'),
    Input('next-buffer', 'n_clicks'),
    Input('prev-buffer', 'n_clicks'),
    State('data-buffer', 'data'),
    prevent_initial_call=True)

def update_buffer(next_clicks, prev_clicks, beginning_clicks, buffer_data):
    if not ctx.triggered:
        raise PreventUpdate

    trigger = ctx.triggered_id

    length = buffer_data["length"]
    start  = buffer_data["start_site"]
    # Get total number of sites from models (safer than tTEM)
    if dbdt2.dataframe is None:
        raise PreventUpdate

    refresh_dbdt2_for_line_mode()
    df, x_axis, _ = dbdt2._prepare_x_axis(dbdt2.dataframe)

    if x_axis == "site_id":
        df = df[df["site_id"] != -1]

    x_vals = np.sort(df[x_axis].dropna().unique())
    if len(x_vals) == 0:
        raise PreventUpdate
    x_min, x_max = x_vals.min(), x_vals.max()

    if trigger == "next-buffer":
        start += length
        # If the window lands entirely in a gap (e.g. a multi-hour break
        # between sites when the axis is daytime), jump to the next point
        # that actually has data instead of leaving the button looking
        # unresponsive.
        if not np.any((x_vals >= start) & (x_vals <= start + length)):
            after = x_vals[x_vals > start]
            if len(after) > 0:
                start = after[0]
    elif trigger == "prev-buffer":
        start -= length
        if not np.any((x_vals >= start) & (x_vals <= start + length)):
            before = x_vals[x_vals < start + length]
            if len(before) > 0:
                start = before[-1] - length
    elif trigger == "beginning-buffer":
        start = x_min

    # Clamp safely, in the same units as x_axis
    start = max(x_min, min(start, max(x_min, x_max - length)))

    buffer_data["start_site"] = start
    buffer_data['source'] = "buffer_button"
    return buffer_data

@app.callback(
    Output('data-buffer', 'data', allow_duplicate=True),
    Input('buffer-length-input', 'value'),
    State('data-buffer', 'data'),
    prevent_initial_call=True,
)
def update_buffer_length(new_length, buffer_data):
    if new_length is None or new_length <= 0:
        raise PreventUpdate

    # The input is typed in the axis's display unit (sites / minutes / m);
    # convert to the raw units the resolved x-axis column uses internally.
    _, factor = dbdt2._buffer_unit()
    buffer_data["length"] = float(new_length) * factor

    # reset start if necessary to avoid overflow
    buffer_data["start_site"] = max(0, buffer_data["start_site"])

    return buffer_data

@app.callback(
    Output("model_section", "figure", allow_duplicate=True),
    Output("model_graph", "figure", allow_duplicate=True),
    Output("model_3d", "figure", allow_duplicate=True),
    Input("review_layout", "n_clicks"),
    State("invert_layout", "color"),
    prevent_initial_call=True
)
def update_model_on_review(_, invert_color):
    mod2.dataframe = sesh.models.copy() if sesh.models is not None else None
    mod1.dataframe = sesh.models.copy() if sesh.models is not None else None
    mod3d.dataframe = sesh.models.copy() if sesh.models is not None else None
    return mod2.render(), mod1.render(), mod3d.render()

@app.callback(
    Output("model_section", "figure", allow_duplicate=True),
    Output("model_3d", "figure", allow_duplicate=True),
    Input("interpret_layout", "n_clicks"),
    State("invert_layout", "color"),
    prevent_initial_call=True
)
def update_model_on_interpret(_, invert_color):
    mod2.dataframe = sesh.models.copy() if sesh.models is not None else None
    mod3d.dataframe = sesh.models.copy() if sesh.models is not None else None
    return mod2.render(), mod3d.render()


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
    Output('report-toast', 'is_open'),
    Output('report-toast', 'children'),
    Output('report-toast', 'icon'),
    Output('report-toast', 'header'),
    Input('generateReportButton', 'n_clicks'),
    Input('report-generate-button', 'n_clicks'),
    *REPORT_SETTING_STATES,
    State('model-3d-camera', 'data'),
    running=[
        (Output('generateReportButton', 'disabled'), True, False),
        (Output('report-generate-button', 'disabled'), True, False),
        (Output('report-progress-modal', 'is_open'), True, False),
        (Output('report-progress-poll', 'disabled'), False, True),
    ],
    prevent_initial_call=True,
)
def generate_report_button(n1, n2, section_order, markersize, zoom_offset, radius, camera):
    report_settings = report_settings_from_states(section_order, markersize, zoom_offset, radius)
    import report
    # Same "ask for a folder only if one isn't already chosen" flow as
    # save_session, so a report generated before any session save still
    # works, and one generated after just reuses the same folder.
    if sesh.save_dir is None:
        root = Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        root.lift()
        root.focus_force()
        root.update()
        folder_path = filedialog.askdirectory(title="Select Save Directory", parent=root)
        root.destroy()
        if not folder_path:
            raise PreventUpdate
        sesh.save_dir = folder_path + '/' if not folder_path.endswith('/') else folder_path

    save_path = os.path.join(sesh.save_dir, 'QC_report.docx')
    try:
        # Same settings and 3D camera as the Report tab's preview.
        basemaps_dropped = report.generate_report(save_path, options=report_settings, camera=camera)
    except Exception as e:
        print(f'Report generation failed: {e}')
        return True, f"Report generation failed: {e}", "danger", "Report Failed"

    print(f'Report saved to {save_path}')
    if basemaps_dropped:
        return (True, f"Report saved to {save_path}. {basemaps_dropped} map(s) are without the satellite "
                      "background because it couldn't be downloaded; check the internet connection and "
                      "generate again.", "warning", "Report Generated")
    return True, f"Report saved to {save_path}", "success", "Report Generated"


@app.callback(
    Output('report-progress-bar', 'value'),
    Output('report-progress-bar', 'label'),
    Output('report-progress-label', 'children'),
    Input('report-progress-poll', 'n_intervals'),
    prevent_initial_call=True,
)
def update_report_progress(n_intervals):
    # Reads report.REPORT_PROGRESS, written to by generate_report_button's
    # own callback while it's still running on another Flask worker thread
    # -- same live-polling-a-shared-dict pattern as inversion_panels.py's
    # update_misfit()/sesh.inv_status.
    import report
    p = report.REPORT_PROGRESS
    total = p['total']
    current = p['current']
    pct = int(100 * current / total) if total else 0
    bar_label = f"{current}/{total}" if total else ""
    return pct, bar_label, p['label']


@app.callback(
    Output('generateReportButton', 'style'),
    Input('interpret_layout', 'color'),
)
def toggle_generate_report_visibility(interpret_color):
    # This button lives in the shared processing_buttons bottom toolbar (a
    # FlexLayout border, so it's visible from every stage) -- show it only
    # on the Interpret tab, active exactly when interpret_layout's color
    # is 'primary' (same convention model.py's toggle_qc_vs_interpret uses).
    return {} if interpret_color == 'primary' else {'display': 'none'}


@app.callback(
    Output('clearSelectionButton', 'style'),
    Input('interpret_layout', 'color'),
)
def toggle_clear_selection_visibility(interpret_color):
    # Same idea in reverse -- hide Clear Selection on the Interpret tab.
    return {'display': 'none'} if interpret_color == 'primary' else {}


@app.server.route('/_beacon_save_session', methods=['POST'])
def beacon_save_session():
    """
    Hit by navigator.sendBeacon (see HotKeyReminder.javascript's
    beforeunload handler in panels.py) as a best-effort save when the
    browser tab/window is closing. A plain Flask route rather than a Dash
    callback -- sendBeacon can't drive a normal Dash callback round trip,
    and this needs to fire-and-forget in the tiny window browsers give an
    unload handler. Silently does nothing if no save directory has been
    chosen yet: that first-save flow needs a folder-picker dialog (see
    save_session above), which can't be shown while the page is
    unloading.
    """
    if sesh.save_dir:
        try:
            sesh.save(folder=sesh.save_dir)
        except Exception as e:
            print(f'beacon save failed: {e}')
    return ('', 204)


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

    # m1.highlighted is a scalar site_id from single-site navigation, but
    # a list/set whenever a multi-site selection (unified_handler) set it
    # last -- `highlighted + step` below assumes a scalar. Stepping from
    # an arbitrary element of that set (e.g. next(iter(...))) could land
    # back inside the selection itself (Next from {53, 54} picking 53 and
    # landing on 54 again) -- stepping from the boundary in the direction
    # of travel (max for Next, min for Previous) is what actually moves
    # past the whole selection.
    if isinstance(highlighted, (list, tuple, set, np.ndarray, pd.Series)):
        highlighted_list = list(highlighted)
        highlighted = (max(highlighted_list) if step > 0 else min(highlighted_list)) if highlighted_list else None

    if highlighted is None:
        raise PreventUpdate

    highlighted = highlighted + step

    # Skip over sites with no model -- a fully disabled site never gets a
    # row in sesh.models at all (see temframe.invert()), so landing on
    # one leaves Model Section/Model Graph blank while Sounding still
    # shows its (disabled) raw decay curve, an inconsistent, confusing
    # stop for what's meant to be inversion-result navigation. Keep
    # stepping in the same direction until a modeled site is found, or
    # stop (PreventUpdate) if the modeled range runs out first.
    if sesh.models is not None:
        modeled_site_ids = set(sesh.models['site_id'].unique().tolist())
        if modeled_site_ids:
            site_min, site_max = min(modeled_site_ids), max(modeled_site_ids)
            while highlighted not in modeled_site_ids and site_min <= highlighted <= site_max:
                highlighted += step
            if highlighted not in modeled_site_ids:
                raise PreventUpdate

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

    figs = (m1.render(), mod1.render(), dbdt1.render(), Multi_inv.render(), mod2.render(), dbdt2.render(), rhoa.render())

    # A selection box left over from before (e.g. a Model Section
    # multi-select) no longer corresponds to real data once these figures
    # are replaced. The first fix here explicitly cleared each panel's
    # selectedData via its own Output -- but that write is itself a prop
    # change, and unified_handler listens to exactly those props
    # (Input("sounding", "selectedData") etc.), so it immediately fired
    # again with the just-cleared value, saw "selectedData is None", and
    # wiped m1.highlighted right back out (confirmed via a live debug
    # trace: unified_handler re-fired with trigger='sounding',
    # sounding_sel=None straight after this callback resolved a new
    # highlighted site). A fresh uirevision instead tells Plotly this is
    # a clean new figure with nothing to reconcile, so it never attempts
    # to carry over (or reset-and-emit-an-event-about) the old selection
    # in the first place -- no explicit clearing, no re-trigger.
    revision = f"rev-{time.time()!r}"
    for fig in figs:
        if fig is not None:
            fig.update_layout(uirevision=revision)

    return (
        ctx.triggered_id,
        *figs,
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
        # Query by the resolved column (matches what's actually plotted),
        # not the raw settings.x_axis name -- for daytime that's the raw,
        # undecoded composite value, which never equals the clicked point's
        # x (the decoded/date-typed value), so the old exact-equality query
        # always came back empty and crashed this callback.
        point = click_data['points'][0]
        if 'x' not in point:
            raise PreventUpdate
        x_value = point['x']
        refresh_dbdt2_for_line_mode()
        df, x_col, _ = dbdt2._prepare_x_axis(dbdt2.dataframe)
        df = df[df['site_id'] != -1]
        if dbdt2.settings.x_axis == 'daytime':
            x_value = pd.Timestamp(x_value).value // 10**6
        site_id = df.loc[(df[x_col] - x_value).abs().idxmin(), 'site_id']
    elif trigger_id == 'model_section':
        # model_section overlays several non-heatmap traces (misfit line,
        # its dashed threshold, the "Below DOI" fill, boreholes) -- a click
        # landing on one of those doesn't always report an 'x', unlike a
        # click directly on a heatmap bar.
        point = click_data['points'][0]
        if 'x' not in point:
            raise PreventUpdate
        # A borehole click (tagged 'BH:<id>' -- see model.py's
        # add_boreholes_to_section_fig) isn't a site selection -- its x
        # position sits close to whichever site the borehole is nearest
        # to, so without this check it would highlight that (unrelated)
        # site's square frame as if it had been clicked instead.
        customdata = point.get('customdata')
        if isinstance(customdata, str) and customdata.startswith('BH:'):
            raise PreventUpdate
        x_value = point['x']
        df, x_col = mod2._prepare_x_axis(mod2.dataframe)
        df = df[df['site_id'] != -1]
        if mod2.settings.x_axis == 'daytime':
            x_value = pd.Timestamp(x_value).value // 10**6
        site_id = df.loc[(df[x_col] - x_value).abs().idxmin(), 'site_id']
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
    Output("starting-model", "data", allow_duplicate=True),
    Input("simple_inv", "relayoutData"),
    State("starting-model", "data"),
    prevent_initial_call=True
)
def update_starting_model_from_simple_drag(relayout, model):
    # Same as update_starting_model_from_drag, for the default "Inversion" tab.
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
    Input("invert_default_button", "n_clicks"),
    prevent_initial_call=True,
)
def reset_polling(n, n_default):
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
    mod3d.boreholes = boreholes     
    mod3d.rock_color_map = rock_color_map

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
    mod3d.boreholes = None;     mod3d.rock_color_map = None
    return {'display': 'none', 'marginTop': '10px'}, m1.render()

# --- Multi-file upload with confirmation flow -------------------------
#
# dcc.Upload(id='upload-data', multiple=True, ...) already lets the browser
# multi-select files, but a single upload can also arrive while a session
# already has data loaded -- either way we don't want to silently overwrite
# or (for a second file) collide site_id/system_id/data_id numbering, which
# temframe.from_sweeps_multi assigns fresh from 0 on every call. This is
# split into three stages: stage_upload (gatekeeper: stash + decide whether
# a confirmation is needed at all), the modal button callbacks, and
# process_upload (does the actual merge, via Session.merge_upload -- see
# session.py -- which handles the site_id/system_id offsetting).
@app.callback(
    Output('output-data-upload', 'children'),
    Output('url', 'hash', allow_duplicate=True),
    Output('pending-upload-store', 'data'),
    Output('upload-action-store', 'data', allow_duplicate=True),
    Output('upload-confirm-modal', 'is_open'),
    Output('upload-confirm-modal-body', 'children'),
    Output('upload-data', 'disabled', allow_duplicate=True),
    Input('upload-data', 'contents'),
    prevent_initial_call=True,
)
def stage_upload(contents):
    print("file upload here")
    if not contents:
        raise PreventUpdate

    if contents[0].startswith('data:application/json'):
        import base64
        codec, info = contents[0].split(';')[1].split(',')
        sesh_str = base64.b64decode(info).decode().replace('null', 'None')
        sesh_dict = dict(eval(sesh_str))
        filepath = sesh_dict['save_dir'].replace(' ', '%20')
        return (html.Div(f'File: {sesh_dict["save_dir"]}'), f"#load={filepath}",
                no_update, no_update, False, no_update, False)

    zip_contents = [c for c in contents if c.startswith('data:application/x-zip')]
    if not zip_contents:
        raise PreventUpdate

    pending = {'contents': zip_contents}

    if sesh.data is None:
        # Nothing at stake on a first upload -- skip the confirmation.
        return (no_update, no_update, pending, {'mode': 'merge', 'nonce': time.time()},
                False, no_update, True)

    session_label = (os.path.basename(os.path.normpath(sesh.save_dir))
                      if sesh.save_dir else "this session (not yet saved to disk)")
    modal_body = f'This data will be uploaded to "{session_label}". Do you want to proceed?'
    return no_update, no_update, pending, no_update, True, modal_body, True


@app.callback(
    Output('upload-action-store', 'data', allow_duplicate=True),
    Output('upload-confirm-modal', 'is_open', allow_duplicate=True),
    Input('upload-confirm-yes-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def confirm_merge_upload(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return {'mode': 'merge', 'nonce': time.time()}, False


@app.callback(
    Output('upload-confirm-modal', 'is_open', allow_duplicate=True),
    Output('upload-fresh-modal', 'is_open', allow_duplicate=True),
    Output('upload-fresh-modal-body', 'children'),
    Input('upload-confirm-no-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def decline_merge_upload(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return False, True, "Start a new session from scratch instead?"


@app.callback(
    Output('upload-action-store', 'data', allow_duplicate=True),
    Output('upload-fresh-modal', 'is_open', allow_duplicate=True),
    Input('upload-fresh-yes-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def confirm_fresh_upload(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return {'mode': 'fresh', 'nonce': time.time()}, False


@app.callback(
    Output('upload-fresh-modal', 'is_open', allow_duplicate=True),
    Output('pending-upload-store', 'data', allow_duplicate=True),
    Output('upload-data', 'disabled', allow_duplicate=True),
    Output('upload-toast', 'is_open', allow_duplicate=True),
    Output('upload-toast', 'children', allow_duplicate=True),
    Input('upload-fresh-no-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def cancel_upload(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return False, None, False, True, "Upload cancelled."


@app.callback(
    Output('output-data-upload', 'children', allow_duplicate=True),
    m1.output, dbdt1.output, dbdt2.output, rhoa.output,
    Multi_inv.output, Sing_inv.output, table_overview.output, Simple_inv.output,
    Output('upload-toast', 'is_open', allow_duplicate=True),
    Output('upload-toast', 'children', allow_duplicate=True),
    Output('process_layout', 'disabled', allow_duplicate=True),
    Output('invert_layout', 'disabled', allow_duplicate=True),
    Output('process_layout', 'n_clicks', allow_duplicate=True),
    Output('dem-bbox-minlon', 'value', allow_duplicate=True),
    Output('dem-bbox-minlat', 'value', allow_duplicate=True),
    Output('dem-bbox-maxlon', 'value', allow_duplicate=True),
    Output('dem-bbox-maxlat', 'value', allow_duplicate=True),
    Output('dem-options-container', 'style', allow_duplicate=True),
    Output('borehole-options-container', 'style', allow_duplicate=True),
    Output('pending-upload-store', 'data', allow_duplicate=True),
    Output('upload-data', 'disabled', allow_duplicate=True),
    Output('current-working-directory', 'children', allow_duplicate=True),
    Output('use-borehole', 'value', allow_duplicate=True),
    Output('use-borehole', 'label', allow_duplicate=True),
    Output('selected_ids_store', 'data', allow_duplicate=True),
    Output('selected_sites_store', 'data', allow_duplicate=True),
    Output('selected_sites_local', 'data', allow_duplicate=True),
    Output('compare-window-store', 'data', allow_duplicate=True),
    Output('starting-model-selected', 'data', allow_duplicate=True),
    Input('upload-action-store', 'data'),
    State('pending-upload-store', 'data'),
    prevent_initial_call=True,
)
def process_upload(action, pending):
    global sesh
    if not action or not pending or not pending.get('contents'):
        raise PreventUpdate

    # "Start fresh" reset outputs -- left as no_update unless mode=='fresh'.
    working_dir_out = no_update
    use_borehole_value_out = no_update
    use_borehole_label_out = no_update
    selected_ids_out = no_update
    selected_sites_out = no_update
    selected_sites_local_out = no_update
    compare_window_out = no_update
    starting_model_selected_out = no_update

    if action.get('mode') == 'fresh':
        sesh = session.Session()
        for panel in (m1, mod1, mod2, mod3d):
            panel.boreholes = None
            panel.rock_color_map = None
        m1.lines = None
        m1.buffer_sites = None
        mod1.buffer_sites = None
        for panel in (m1, mod1, mod2, mod3d, dbdt1, dbdt2, rhoa, Simple_inv, Multi_inv, Sing_inv, table_overview):
            panel.dataframe = None
        working_dir_out = "No working directory selected."
        use_borehole_value_out = False
        use_borehole_label_out = "Use Borehole Data (optional)"
        selected_ids_out = []
        selected_sites_out = []
        selected_sites_local_out = []
        compare_window_out = {"window_id": None, "items": []}
        starting_model_selected_out = []

    warning_msg = None
    if sesh.save_dir is None:
        warning_msg = "No working directory selected. You can still explore data; choose Save to set one."

    # 'Uploaded N sites' should describe what THIS upload actually added,
    # not sesh.data's running total (nunique() over the whole, now-merged
    # frame) -- that was only ever correct back when a session could hold
    # at most one uploaded file.
    if sesh.data is not None:
        sites_before = set(sesh.data.loc[sesh.data['site_id'] != -1, 'site_id'].unique())
    else:
        sites_before = set()

    for content in pending['contents']:
        sesh.merge_upload(*temframe.from_zip_content(content))

    sites_after = set(sesh.data.loc[sesh.data['site_id'] != -1, 'site_id'].unique())
    new_site_count = len(sites_after - sites_before)

    m1.dataframe = sesh.overview.copy()
    table_overview.dataframe = sesh.overview.copy()

    buffer_length = 50
    unique_sites = np.sort(sesh.site['site_id'].dropna().unique())
    initial_sites = unique_sites[:buffer_length]

    m1.buffer_sites = initial_sites.tolist()
    mod1.dataframe  = sesh.models
    mod1.buffer_sites = initial_sites.tolist()
    mod2.dataframe  = sesh.models

    mod3d.dataframe  = sesh.models

    full_df = sesh.data.copy()

    buffered_df = full_df[full_df['site_id'].isin(initial_sites)].copy()

    dbdt1.dataframe = buffered_df
    dbdt2.dataframe = full_df          # keep full section view
    rhoa.dataframe  = buffered_df
    Simple_inv.dataframe = sesh.data.copy()
    Multi_inv.dataframe = sesh.data.copy()
    Sing_inv.dataframe = sesh.data.copy()

    if 'site_id' in sesh.data.columns:
        toast_count = new_site_count
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

    return (
        html.Div(upload_msg), m1.render(), dbdt1.render(), dbdt2.render(), rhoa.render(),
        Multi_inv.render(), Sing_inv.render(), table_overview.render(), Simple_inv.render(), True, toast_msg, False, False, no_update,
        *bbox_vals, {'display': 'block'}, {'display': 'block'},
        None, False,
        working_dir_out, use_borehole_value_out, use_borehole_label_out,
        selected_ids_out, selected_sites_out, selected_sites_local_out,
        compare_window_out, starting_model_selected_out,
    )


# @app.callback(
#     Output('map', 'figure', allow_duplicate=True),
#     Input('flex-layout', 'model'),
#     prevent_initial_call=True

# )
# def print_flex_layout_model(model):
#     print(f"Flex layout model: {model}")
#     return m1.render()


BUFFER_LENGTH_UNIT_LABELS = {
    'daytime':   'Buffer length (min):',
    'longitude': 'Buffer length (m):',
    'latitude':  'Buffer length (m):',
    'distance':  'Buffer length (m):',
}

@app.callback(
    Output({'type': f'settings-{dbdt2.id}', 'key': 'x_axis'}, 'value'),
    Output('buffer-length-label', 'children'),
    Input({'type': f'settings-{mod2.id}', 'key': 'x_axis'}, 'value'),
    prevent_initial_call=True
)
def sync_x_axis(x_axis):
    if x_axis.startswith('line'):
        buffer_label = 'Buffer length (m):'
    else:
        buffer_label = BUFFER_LENGTH_UNIT_LABELS.get(x_axis, 'Buffer length:')
    return x_axis, buffer_label

@app.callback(
    Output('data-buffer', 'data', allow_duplicate=True),
    Output('buffer-length-input', 'value', allow_duplicate=True),
    dbdt2.output,
    Input('model_section_axis', 'value'),
    prevent_initial_call=True
)
def reset_buffer_on_axis_change(new_x_axis):
    if dbdt2.dataframe is None:
        raise PreventUpdate

    # Force the new axis now rather than waiting for the settings-sync
    # chain (this callback runs in parallel with it), so the buffer
    # window below is computed against the correct column immediately.
    # Otherwise a window left over from the previous axis (e.g. a
    # site-id-scale [0, 50]) won't overlap daytime's epoch-millisecond
    # values at all, and the transect view renders empty with every tick
    # collapsing onto a day boundary (all reading 00:00:00).
    #
    # dbdt2.output is included directly here too, rather than relying
    # solely on the settings-panel-proxy chain (sync_x_axis ->
    # dbdt2's own settings-triggered re-render) or on
    # update_model_section_from_buffer picking up the data-buffer change
    # below -- both of those are indirect, multi-hop paths, and this way
    # the transect view is guaranteed to reflect the new x-axis choice
    # immediately regardless of whether either of those also fires.
    dbdt2.settings.x_axis = new_x_axis
    refresh_dbdt2_for_line_mode()
    df, x_axis, _ = dbdt2._prepare_x_axis(dbdt2.dataframe)
    if x_axis == "site_id":
        df = df[df["site_id"] != -1]
    x_vals = df[x_axis].dropna().values
    if len(x_vals) == 0:
        # Nothing to compute a buffer window from, but the transect view
        # itself should still refresh (e.g. to show its own "no data"
        # placeholder for the new axis) rather than silently staying on
        # the old one.
        return no_update, no_update, dbdt2.render()

    x_min, x_max = x_vals.min(), x_vals.max()
    length = max(x_max - x_min, 0.0)

    _, factor = dbdt2._buffer_unit()
    buffer_length_display = length / factor if length > 0 else 0

    return {"length": length, "start_site": x_min}, buffer_length_display, dbdt2.render()

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
        m1.output,
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

    # suppress_highlight only takes visual effect the next time m1
    # renders -- switching tabs alone doesn't trigger a render, so without
    # forcing one here, a highlight set on a previous tab would keep
    # showing on Interpret (or vice versa) until some unrelated click
    # happened to re-render the map.
    if button_id == "upload_layout":
        m1.suppress_highlight = False
        return layouts.upload, *colors.values(), m1.render()

    elif button_id == "process_layout":
        m1.suppress_highlight = False
        return layouts.data, *colors.values(), m1.render()

    elif button_id == "invert_layout":
        m1.suppress_highlight = False
        return layouts.invert, *colors.values(), m1.render()

    elif button_id == "review_layout":
        m1.suppress_highlight = False
        return layouts.review, *colors.values(), m1.render()

    elif button_id == "interpret_layout":
        # m1.render() self-heals the mean-res grid (see Map._ensure_grid).
        m1.settings.legend=True
        m1.settings.dragmode='pan'
        m1.suppress_highlight = True
        return layouts.interpret, *colors.values(), m1.render()

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

        # Inserted here (rather than appended at the end) so the many
        # res[-1]..res[-5] references further down -- which all target
        # the trailing use-borehole/working-directory/url-hash outputs --
        # keep pointing at the same components without needing to change:
        # negative indexing only cares about position relative to the
        # list's end, and this insertion point sits before all of them.
        Output('session-load-toast', 'is_open', allow_duplicate=True),
        Output('session-load-toast', 'children', allow_duplicate=True),

        # Also inserted here rather than appended at the end, same reason
        # as the toast outputs above.
        table_overview.output,

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
        res[16] = True  # session-load-toast is_open
        res[17] = f"Session loaded from: {sesh.save_dir}"  # session-load-toast children

        # Opening a different session must not leave state from the
        # previous one behind -- reset the same per-panel caches
        # process_upload()'s "start fresh" path resets, before applying
        # whatever the newly loaded session actually provides below.
        # m1.lines/boreholes/rock_color_map in particular are plain
        # instance attributes the Map panel caches itself (unlike
        # sesh.lines, which model.py/panels.py read fresh from sesh on
        # every render), so nothing else here would otherwise clear them.
        for panel in (m1, mod1, mod2, mod3d):
            panel.boreholes = None
            panel.rock_color_map = None
        m1.lines = None
        # A drawn line's x_axis mode is tied to that specific (now gone)
        # session's lines -- even if the new session coincidentally also
        # has a "line 1", it's a different line, so this would otherwise
        # keep filtering/plotting against a stale, wrong selection.
        if str(mod2.settings.x_axis).startswith('line'):
            mod2.settings.x_axis = 'site_id'
        if str(dbdt2.settings.x_axis).startswith('line'):
            dbdt2.settings.x_axis = 'site_id'

        if hasattr(sesh, 'borehole_list') and sesh.borehole_list is not None:
            # Transfer data to the display models
            from Sections_plotting import get_borehole_projections
            m1.boreholes = get_borehole_projections(sesh.borehole_list)
            mod1.boreholes = get_borehole_projections(sesh.borehole_list)
            mod2.boreholes = get_borehole_projections(sesh.borehole_list)
            mod3d.boreholes = get_borehole_projections(sesh.borehole_list)
            
            # Transfer the color map
            if hasattr(sesh, 'rock_map') and sesh.rock_map is not None:
                m1.rock_color_map = sesh.rock_map
                mod1.rock_color_map = sesh.rock_map
                mod2.rock_color_map = sesh.rock_map
                mod3d.rock_color_map = sesh.rock_map
            
            res[-4] = True  # use-borehole value
            res[-3] = html.Span(["Use Borehole Data ", 
                    html.B("(Loaded from Session)", style={'color': '#28a745'}),
                    html.Br(), # Adds a line break to keep it tidy
                    html.Small("Upload a new .bor file below to overwrite existing data.", style={'color': '#6c757d', 'fontStyle': 'italic', 'fontSize': '0.85rem'})])
            res[-2] = {'display': 'block', 'marginTop': '10px'} # container style
            
            res[0] = m1.render()
        else:
            # If no boreholes, ensure UI reflects that -- but keep the
            # *outer* options container (the checkbox itself) visible so
            # there's still a way to opt in and upload a .bor file. Only
            # the checkbox's own value controls whether the inner
            # borehole-upload-container (the actual dropzone) is shown, via
            # toggle_borehole_upload.
            res[-4] = False
            res[-3] = "Use Borehole Data (optional)"
            res[-2] = {'display': 'block'}

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
            table_overview.dataframe = sesh.overview.copy()
            rhoa.dataframe  = sesh.data.copy()
            Simple_inv.dataframe = sesh.data.copy()
            Multi_inv.dataframe = sesh.data.copy()
            Sing_inv.dataframe = sesh.data.copy()
            res[0] = m1.render()
            res[1] = dbdt1.render()
            res[2] = dbdt2.render()
            res[3] = rhoa.render()
            res[18] = table_overview.render()
        
        if sesh.models is not None:
            mod1.dataframe  = sesh.models.copy()
            mod2.dataframe  = sesh.models.copy()
            mod3d.dataframe = sesh.models.copy()
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
        # Borehole markers tag themselves with a flat 'BH:<id>' string
        # customdata (see model.py's add_boreholes_to_section_fig), not
        # the heatmap's [site_id, lat, lon] tuple this callback expects --
        # skip it outright rather than unpacking its characters as
        # coordinates (data[1] on "BH:MJ-2" is 'H', not a latitude).
        if isinstance(data, str):
            return no_update
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

    return _map_with_hover_marker(current_fig, lat, lon)


def _map_with_hover_marker(current_fig, lat, lon):
    """The current map figure with a white/red target marker at lat/lon, replacing any previous one."""
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


@app.callback(
    Output(m1.id, 'figure', allow_duplicate=True),
    Input(mod3d.id, 'hoverData'),
    State(m1.id, 'figure'),
    prevent_initial_call=True
)
def sync_3d_hover_to_map(hoverData, current_fig):
    # Same marker as sync_hover_to_map, for the 3D view. 3D hover events
    # carry the hovered point's scene x/y, which are UTM easting/northing
    # here (see Model3D.render), so mark the nearest site.
    if not hoverData or not current_fig or mod3d.dataframe is None or mod3d.dataframe.empty:
        return no_update
    point = hoverData['points'][0]
    x, y = point.get('x'), point.get('y')
    if x is None or y is None:
        return no_update
    sites = mod3d.dataframe.drop_duplicates('site_id').dropna(subset=['latitude', 'longitude'])
    if sites.empty:
        return no_update
    utm_x, utm_y = mod3d._project_latlon(sites['latitude'].values, sites['longitude'].values)
    nearest = np.nanargmin((utm_x - float(x)) ** 2 + (utm_y - float(y)) ** 2)
    site = sites.iloc[nearest]
    return _map_with_hover_marker(current_fig, float(site['latitude']), float(site['longitude']))


# import signal
# @app.server.route("/shutdown", methods=["POST"])
# def shutdown():
#     print('closing app, saving data to zip...')
#     sesh.save()    
#     os.kill(os.getpid(), signal.SIGINT)  # Send a signal to the process to terminate


if __name__ == "__main__":
    import socket
    import webbrowser
    import threading

    def _find_free_port(preferred=8050):
        # sesh/m1/mod1/... are plain module-level globals -- there's no
        # per-user session isolation inside a single process, so two
        # windows sharing one server means they silently share (and
        # stomp on) each other's state. Since each launch of the app is
        # its own OS process, giving each one its own port is what
        # actually makes multiple open windows independent: try the
        # familiar default first (nice for the common single-window
        # case), and fall back to whatever free port the OS hands out if
        # another instance already holds it, rather than failing to bind
        # or (depending on how the app is launched) ending up pointed at
        # that other instance's already-running server.
        for port in (preferred, 0):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', port))
                    return s.getsockname()[1]
                except OSError:
                    continue
        raise RuntimeError('Could not find a free port to bind to')

    def _wait_for_server_then_open_browser(port, timeout=60):
        # Polls the port instead of guessing a fixed delay -- this app's
        # own startup imports (torch etc.) can take several seconds, and
        # a fixed delay short enough for a fast machine would open the
        # browser before the server is actually listening on a slower one.
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.3)
        webbrowser.open(f'http://127.0.0.1:{port}/')

    # use_reloader=False -- the reloader used to re-exec this entire
    # script in a second "worker" process on every launch (Werkzeug marks
    # that one with WERKZEUG_RUN_MAIN=true), which doubled every heavy
    # startup import (torch alone costs ~5s) for a feature -- auto-restart
    # on source file edits -- that only matters while actively developing
    # the app, not for a packaged/shipped build. debug=True is kept (still
    # gives an in-browser traceback if something crashes), just not the
    # process-doubling reloader. With no reloader, WERKZEUG_RUN_MAIN is
    # simply never set, so this still only picks a port / opens a browser
    # tab once per launch.
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        chosen_port = _find_free_port(8050)
        os.environ['SEA_ANEMONE_PORT'] = str(chosen_port)
        threading.Thread(target=_wait_for_server_then_open_browser, args=(chosen_port,), daemon=True).start()
    else:
        chosen_port = int(os.environ.get('SEA_ANEMONE_PORT', 8050))

    # Debug mode (Dash's dev-tools button and in-browser error pop-ups) is
    # for development only: on when running app.py from source, off in the
    # packaged exe (PyInstaller sets sys.frozen). Set SEA_ANEMONE_DEBUG=1
    # before starting the exe to turn it back on for troubleshooting.
    is_packaged = getattr(sys, 'frozen', False)
    debug_mode = (not is_packaged) or os.environ.get('SEA_ANEMONE_DEBUG') == '1'

    try:
        app.run(port=chosen_port, debug=debug_mode, use_reloader=False)
    except Exception as e:
        print(f"Error running app: {e}")
    finally:
        print('closing app, saving data to zip...')
        # sesh.save()
        # os.kill(os.getpid(), signal.SIGINT)  # Send a signal to the process to terminate