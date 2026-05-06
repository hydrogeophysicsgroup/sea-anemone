
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


class Popups(Panel):
    def add_callbacks(self, app):
        super().add_callbacks(app)
# # --------------------- #  MAP + PROFILE PLOT ---------------------
# # --------------------- #  GOOD CALLBACK FOR ALT+LEFT CLICK + CTRL FOR click on models ---------------------
        @app.callback(
            Output("window-container", "children"),
            Output("combined-window-store", "data"),
            Input("right-click-index-store", "data"),
            Input({"type": "close-window", "index": ALL}, "n_clicks"),
            State("window-container", "children"),
            State("combined-window-store", "data"),
            State("line-final-store", "data"),        # To get current line geometry
            State("selected-line-index", "data"),     # To know which line is active
            prevent_initial_call=True
        )

        def manage_windows(click_data, n_closes, current_windows, combined_state,all_lines, selected_idx):

            ctx = callback_context
            if not ctx.triggered:
                return no_update, no_update
            
            profile.dataframe = sesh.models
            df_up_map, color_master_map, existing_attrs = preprocess_new_df(profile.dataframe)
            
            dbdt_df = sesh.data

            trigger = ctx.triggered[0]["prop_id"]
            windows = list(current_windows or [])
            # combined_state stores: {"window_id": str, "items": [[id, type], ...]}
            combined_state = combined_state or {"window_id": None, "items": []}
            width_step = "550px"
            height_step ="900px"
        

            all_bhs = m1.boreholes or []
            line_bhs = []

            if all_lines and selected_idx is not None:
                try:
                    current_line = all_lines[selected_idx]
                    if all_bhs:
                        line_bhs = get_boreholes_on_line(current_line,all_bhs,search_radius_m=Settings.radius)
                except Exception as e:
                    print(f"⚠️ Borehole Projection Error: {e}")


            # --- 1. HANDLE NEW CLICKS (ALT or CTRL+ALT) ---
            if "right-click-index-store" in trigger:
                if not click_data:
                    return no_update, no_update

                idx = click_data.get("index")
                item_type = click_data.get("type", "tem") # 'tem' or 'borehole'
                is_combined = bool(click_data.get("multi"))
                ts = click_data.get("timestamp")

                # A) ALT-ONLY: Create a new independent window
                if not is_combined:
                    if idx is None:  # Safety check for empty clicks
                        return no_update, no_update
                    
                    new_id = f"win-{idx}-{ts}"
                    if item_type == "borehole":
                        fig = build_combined_borehole_figure([idx], all_bhs, m1.rock_color_map)
                        title = f"Borehole Log: {idx}"
                        content = html.Div([dcc.Graph(figure=fig, 
                                            style={"height": "750px"},
                                            config={'displayModeBar': False})]
                                    , style={"height": "100%", "padding": "10px"})                    
                    else:
                        try:
                            row_data = None
                            # Convert idx to match the column type (usually int for site_id)
                            search_val = int(idx) if str(idx).isdigit() else idx
                            print("idx for alt",idx)
                            
                            # Find the row where site_id matches our clicked index
                            mask = df_up_map['site_id'] == search_val
                            if mask.any():
                                row_data = df_up_map[mask].iloc[0]

                        except (ValueError, TypeError):
                            row_data = None

                        if row_data is not None:
                            fig_step = generate_res_step_graph(row_data, idx)            
                            fig_dbdt = generate_dbdt_graph(dbdt_df, idx)
                            
                            # 3. Create Tabs
                            tab_content = dcc.Tabs([
                                dcc.Tab(label='Res Step Plot', children=[
                                    dcc.Graph(figure=fig_step, style={"height": "750px"})
                                ]),
                                dcc.Tab(label='Data (dB/dt)', children=[
                                    dcc.Graph(figure=fig_dbdt, style={"height": "750px"})
                                ])
                            ], style={"height": "50px"})
                            
                            content = html.Div([tab_content], style={"height": "100%"})
                            title = f"TEM Sounding: {idx}"
                        else:
                            return no_update, no_update
                    
                    windows.append(create_draggable_window(new_id, title, content, width=width_step, height=height_step))
                    return windows, combined_state
                
                # B) CTRL+ALT: Add to Comparison Window
                else:
                    if not combined_state.get("window_id"):
                        combined_state["window_id"] = f"win-comparison-{ts}"
                        combined_state["items"] = []

                    # Add to list if not already there
                    if [idx, item_type] not in combined_state["items"]:
                        combined_state["items"].append([idx, item_type])

                    items = combined_state["items"]
                    tem_ids = [it[0] for it in items if it[1] == "tem"]
                    bh_ids = [it[0] for it in items if it[1] == "borehole"]

                    if len(bh_ids) == 0:
                        # 1. Build the combined Resistivity plot
                        print(tem_ids)
                        fig_combined_step = build_combined_step_figure(df_up_map, tem_ids, use_elevation=True)
                        
                        # 2. Build the combined dB/dt plot
                        fig_combined_dbdt = build_combined_dbdt_figure(sesh.data, tem_ids)
                        
                        # 3. Use Tabs for the content
                        content = html.Div([
                            dcc.Tabs([
                                dcc.Tab(label=f'Combined Models ({len(tem_ids)})', children=[
                                    dcc.Graph(figure=fig_combined_step, style={"height": "750px"})
                                ]),
                                dcc.Tab(label=f'Combined Data Fit', children=[
                                    dcc.Graph(figure=fig_combined_dbdt, style={"height": "750px"})
                                ])
                            ])
                        ], style={"height": "100%"})
                        
                        title = f"Comparison: {len(tem_ids)} Sites"
                        width_step = "900px"

                    # Scenario: Only Boreholes selected -> Side-by-Side Logs
                    elif len(tem_ids) == 0:
                        fig = build_combined_borehole_figure(bh_ids, all_bhs, m1.rock_color_map)
                        content = dcc.Graph(figure=fig, style={"height": "100%"})
                        title = f"Borehole Comparison ({len(bh_ids)})"

                    else:
                        # 1. Generate all three figures
                        tem_fig = build_combined_step_figure(df_up_map, tem_ids, use_elevation=True)
                        bh_fig = build_combined_borehole_figure(bh_ids, all_bhs, m1.rock_color_map)
                        dbdt_fig = build_combined_dbdt_figure(sesh.data, tem_ids) # The new combined function
                        
                        # 2. Align Y-Axes for TEM and Borehole (Correlation Tab)
                        all_z = []
                        for idx in tem_ids:
                            row = df_up_map.loc[idx]
                            all_z.extend(row['elevation'] - row['bottom_depth'])
                            all_z.append(row['elevation'])
                        for bh in all_bhs:
                            if bh['id'] in bh_ids:
                                all_z.append(bh['elev'])
                                all_z.append(bh['elev'] - max([l['Bottom'] for l in bh['layers']]))

                        z_min, z_max = min(all_z) - 5, max(all_z) + 5
                        tem_fig.update_layout(yaxis=dict(range=[z_min, z_max], autorange=False))
                        bh_fig.update_layout(yaxis=dict(range=[z_min, z_max], autorange=False))

                        # 3. Define the Correlation Content (Side-by-Side)
                        correlation_content = html.Div([
                            html.Div(dcc.Graph(figure=tem_fig, responsive=True, style={"width": "100%", "height": "100%"}), 
                                    style={"display": "flex", "width": "100%", "height": "100%"}),
                            html.Div(dcc.Graph(figure=bh_fig, responsive=True, style={"width": "100%", "height": "100%"}), 
                                    style={"display": "flex", "width": "100%", "height": "100%"})
                        ], style={"display": "flex", "flexDirection": "row", "height": "800px", "width": "100%","gap": "0px"})

                        # 4. Wrap everything in Tabs
                        content = html.Div([
                            dcc.Tabs([
                                dcc.Tab(label="Model Correlation (TEM vs BH)", children=[
                                    correlation_content
                                ]),
                                dcc.Tab(label="Combined Data Fit (dB/dt)", children=[
                                    dcc.Graph(figure=dbdt_fig, style={"height": "800px"})
                                ])
                            ])
                        ], style={"height": "100%"})

                        title = "TEM vs. Borehole Correlation"
                        width_step = "900px" # Widened slightly for better side-by-side visibility

                    # Update Window list
                    comp_id = combined_state["window_id"]
                    windows = [w for w in windows if w["props"]["id"] != comp_id]
                    windows.append(create_draggable_window(comp_id, title, content, width=width_step,height=height_step))
                    
                    return windows, combined_state

            # --- 2. HANDLE CLOSE BUTTON ---
            if "close-window" in trigger:
                try:
                    prop_dict = json.loads(trigger.split(".")[0])
                    closed_id = prop_dict.get("index")

                    windows = [w for w in windows if w["props"]["id"] != closed_id]

                    # Reset state if the comparison window was the one closed
                    if combined_state.get("window_id") == closed_id:
                        combined_state = {"window_id": None, "items": []}
                
                    return windows, combined_state
                
                except Exception as e:
                    print(f"Error closing window: {e}")

            return no_update, no_update



        # CALLBACK FOR ALT+LEFT CLICK + CTRL
        app.clientside_callback(
            """
            function(clickData){ 
                // 3. Only trigger if Alt is held down
                if (!window._keyTracker.alt) {
                    return window.dash_clientside.no_update;
                }

                // 4. Extract Data from Click Point
                const pt = clickData.points[0];
                let cd = pt.customdata;
                
                let extractedId = null;
                let extractedType = "tem"; // Default type

                // 5. Robust Extraction Logic
                // We drill down through arrays because Plotly structures customdata differently 
                // for points vs. fills (Scatter 'toself')
                if (cd !== undefined && cd !== null) {
                    let dataArray = cd;
                    
                    // If it's a nested array (e.g., [[id, dist, type]]), grab the inner one
                    if (Array.isArray(dataArray) && Array.isArray(dataArray[0])) {
                        dataArray = dataArray[0];
                    }

                    // At this point, dataArray should be [id, dist, type] or [id]
                    if (Array.isArray(dataArray)) {
                        extractedId = dataArray[0];
                        
                        // If the 3rd element is "borehole", update the type
                        if (dataArray.length >= 3 && dataArray[2] === "borehole") {
                            extractedType = "borehole";
                        }
                    } else {
                        // Fallback for simple single-value customdata
                        extractedId = dataArray;
                    }
                }

                // 6. Final Debug Log (Check your Browser Console with F12)
                console.log("🎯 Alt+Click Detected:", {
                    id: extractedId,
                    type: extractedType,
                    multi: window._keyTracker.ctrl
                });

                // 7. Return to Python Store
                return {
                    "index": extractedId,
                    "type": extractedType,
                    "multi": window._keyTracker.ctrl,
                    "timestamp": Date.now()
                };
            }
            """,
            Output("right-click-index-store", "data"),
            Input("profile_plot_main", "clickData"),
            prevent_initial_call=True
        )


        # DRAGGABLE WINDOW FOR CTRL + ALT + LEFT CLICK
        app.clientside_callback(
            """
            function(children) {
                if (!children) return window.dash_clientside.no_update;

                // Wait a tiny bit for the DOM to render the new window
                setTimeout(() => {
                    const windows = document.getElementsByClassName("draggable-window");
                    
                    Array.from(windows).forEach(win => {
                        const header = win.querySelector('.window-header');
                        if (!header || header.dataset.listener === 'true') return;

                        let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
                        header.dataset.listener = 'true'; // Prevent double-attaching
                        header.onmousedown = dragMouseDown;

                        function dragMouseDown(e) {
                            e.preventDefault();
                            pos3 = e.clientX;
                            pos4 = e.clientY;
                            document.onmouseup = closeDragElement;
                            document.onmousemove = elementDrag;
                        }

                        function elementDrag(e) {
                            e.preventDefault();
                            pos1 = pos3 - e.clientX;
                            pos2 = pos4 - e.clientY;
                            pos3 = e.clientX;
                            pos4 = e.clientY;
                            win.style.top = (win.offsetTop - pos2) + "px";
                            win.style.left = (win.offsetLeft - pos1) + "px";
                        }

                        function closeDragElement() {
                            document.onmouseup = null;
                            document.onmousemove = null;
                        }
                    });
                }, 100);

                return window.dash_clientside.no_update;
            }
            """,
            Output("window-container", "className"), # Dummy output
            Input("window-container", "children"),   # Triggers whenever a window is added/removed
            prevent_initial_call=True
        )