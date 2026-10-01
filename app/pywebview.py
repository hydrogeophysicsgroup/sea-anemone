

app.clientside_callback(
    """
        function(n_clicks) {
            if (n_clicks) {
                window.open(
                    '/help/index.html',
                    '_blank',
                    'width=1100,height=800,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes'
                );
            }
            return window.dash_clientside.no_update;
        }
    """,
    Output("help-fab", "title"),
    Input("help-fab", "n_clicks"),
    prevent_initial_call=True
)

# help button code:
# dbc.Button(
#     "?",
#     id='help-fab',
#     color='primary',
#     style={
#         'position': 'fixed',
#         'right': '24px',
#         'bottom': '24px',
#         'width': '56px',
#         'height': '56px',
#         'borderRadius': '50%',
#         'fontSize': '24px',
#         'zIndex': 3000,
#         'boxShadow': '0 6px 16px rgba(0,0,0,0.2)'
#     }
# ),
# html.Div(id='help-window')



@app.callback(
    Output('dem-options-container', 'style'),
    Output('borehole-options-container', 'style'),
    Input('upload-data', 'contents'),
    Input('url', 'hash'),
    prevent_initial_call=False
)
def toggle_dem_options(contents, url_hash):
    if sesh.data is None:
        return {'display': 'none'}, {'display': 'none'}
    return {'display': 'block'}, {'display': 'block'}

@app.callback(
    Output('dem-api-key-container', 'style'),
    Output('dem-resolution-container', 'style'),
    Output('dem-resolution', 'options'),
    Output('dem-resolution', 'value'),
    Input('dem-source', 'value'),
    State('dem-resolution', 'value'),
    prevent_initial_call=False
)
def toggle_dem_inputs(source, current_value):
    resolution_options_map = {
        'opentopo': [
            {'label': 'Global Copernicus GLO-30 (~30 m)', 'value': 'opentopo_cop30'},
            {'label': 'Global SRTMGL1 (~30 m)', 'value': 'opentopo_srtmgl1'},
            {'label': 'Global SRTMGL3 (~90 m)', 'value': 'opentopo_srtmgl3'},
            {'label': 'Global ALOS (~30 m)', 'value': 'opentopo_alos'},
        ],
        'etopo': [
            {'label': 'ETOPO2022 30 arc-second (surface, global)', 'value': 'etopo_30s'},
            {'label': 'ETOPO2022 60 arc-second (surface, global)', 'value': 'etopo_60s'},
        ],
    }

    options = resolution_options_map.get(source, [])
    valid_values = {opt['value'] for opt in options}
    default_value = options[0]['value'] if options else None
    value = current_value if current_value in valid_values else default_value

    if source == 'opentopo':
        return {'marginBottom': '8px'}, {'display': 'flex', 'gap': '10px'}, options, value
    return {'display': 'none'}, {'display': 'flex', 'gap': '10px'}, options, value

@app.callback(
    Output('output-dem-load', 'children'),
    Output('output-data-summary', 'children', allow_duplicate=True),
    Output('dem-applied', 'data'),
    Output('dem-toast', 'is_open', allow_duplicate=True),
    Output('dem-toast', 'children', allow_duplicate=True),
    Input('load-dem-vs-gps', 'n_clicks'),
    State('use-dem', 'value'),
    prevent_initial_call=True
)
def load_dem_vs_gps(n_clicks, use_dem):
    if not n_clicks:
        raise PreventUpdate
    if not use_dem:
        return html.Div("Enable 'Use DEM' first."), build_data_summary(), False, True, "Enable 'Use DEM' first."
    if not sesh.dem_path or not os.path.exists(sesh.dem_path):
        return html.Div("No DEM found. Please download or upload a DEM first."), build_data_summary(), False, True, "No DEM found. Please download or upload a DEM first."

    stats = build_gps_dem_summary()
    replace_error = None
    try:
        df = sesh.data
        if df is not None:
            if 'elevation_gps' not in df.columns:
                df['elevation_gps'] = df['elevation']
            if 'site_id' in df.columns:
                df_sites = df.loc[df['site_id'] != -1].drop_duplicates(subset=['site_id'])[['site_id', 'longitude', 'latitude', 'elevation']]
                lons = df_sites['longitude'].astype(float).to_numpy()
                lats = df_sites['latitude'].astype(float).to_numpy()
                valid_coords = np.isfinite(lons) & np.isfinite(lats)
                df_sites = df_sites.loc[valid_coords].reset_index(drop=True)
                lons = lons[valid_coords]
                lats = lats[valid_coords]

                if len(df_sites) > 0:
                    dem_vals = _sample_dem_at_points(lons, lats, sesh.dem_path)
                    valid_dem = np.isfinite(dem_vals)
                    if valid_dem.any():
                        dem_map = pd.Series(dem_vals[valid_dem], index=df_sites.loc[valid_dem, 'site_id']).to_dict()
                        dem_series = df['site_id'].map(dem_map)
                        df.loc[dem_series.notna(), 'elevation'] = dem_series
            else:
                lons = df['longitude'].astype(float).to_numpy()
                lats = df['latitude'].astype(float).to_numpy()
                valid_coords = np.isfinite(lons) & np.isfinite(lats)
                if valid_coords.any():
                    dem_vals = _sample_dem_at_points(lons[valid_coords], lats[valid_coords], sesh.dem_path)
                    valid_dem = np.isfinite(dem_vals)
                    idx = df.index[valid_coords]
                    df.loc[idx[valid_dem], 'elevation'] = dem_vals[valid_dem]

            sesh.data = df
            if dbdt1.dataframe is not None and 'site_id' in df.columns:
                dbdt1.dataframe = df[df['site_id'].isin(dbdt1.dataframe['site_id'].unique())]
            if dbdt2.dataframe is not None and 'site_id' in df.columns:
                dbdt2.dataframe = df[df['site_id'].isin(dbdt2.dataframe['site_id'].unique())]
    except Exception as exc:
        replace_error = exc

    message_children = [
        html.Div("DEM loaded. GPS vs DEM updated."),
        stats
    ]
    if replace_error is not None:
        message_children.append(html.Div(f"DEM elevation replace failed: {replace_error}"))

    dem_applied = replace_error is None
    toast_msg = "DEM loaded. GPS vs DEM updated." if replace_error is None else f"DEM elevation replace failed: {replace_error}"
    return html.Div(message_children), build_data_summary(), dem_applied, True, toast_msg

@app.callback(
    Output('output-dem-load', 'children', allow_duplicate=True),
    Output('output-data-summary', 'children', allow_duplicate=True),
    Output('dem-applied', 'data', allow_duplicate=True),
    Output('dem-toast', 'is_open', allow_duplicate=True),
    Output('dem-toast', 'children', allow_duplicate=True),
    Input('restore-gps-elevation', 'n_clicks'),
    prevent_initial_call=True
)
def restore_gps_elevation(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    if sesh.data is None:
        return html.Div("No data loaded."), build_data_summary(), False, True, "No data loaded."
    df = sesh.data
    if 'elevation_gps' not in df.columns:
        return html.Div("No GPS elevation backup found."), build_data_summary(), False, True, "No GPS elevation backup found."

    df['elevation'] = df['elevation_gps']
    sesh.data = df

    if dbdt1.dataframe is not None and 'site_id' in df.columns:
        dbdt1.dataframe = df[df['site_id'].isin(dbdt1.dataframe['site_id'].unique())]
    if dbdt2.dataframe is not None and 'site_id' in df.columns:
        dbdt2.dataframe = df[df['site_id'].isin(dbdt2.dataframe['site_id'].unique())]

    return html.Div("GPS elevation restored."), build_data_summary(), False, True, "GPS elevation restored."

@app.callback(
    Output('restore-gps-elevation', 'disabled'),
    Input('dem-applied', 'data'),
    Input('use-dem', 'value'),
    prevent_initial_call=False
)
def toggle_restore_button(dem_applied, use_dem):
    return not bool(dem_applied and use_dem)

@app.callback(
    Output('output-dem-upload', 'children'),
    Output('output-data-summary', 'children', allow_duplicate=True),
    Output('dem-downloaded', 'data', allow_duplicate=True),
    Output('dem-loaded', 'data', allow_duplicate=True),
    Output('dem-toast', 'is_open', allow_duplicate=True),
    Output('dem-toast', 'children', allow_duplicate=True),
    Input('upload-dem', 'contents'),
    State('upload-dem', 'filename'),
    State('use-dem', 'value'),
    running=[(Output("upload-dem", "disabled"), True, False)],
    prevent_initial_call=True
)
def upload_dem(contents, filename, use_dem):
    if contents is None:
        raise PreventUpdate
    if not use_dem:
        raise PreventUpdate

    content_type, content_string = contents.split(',', 1)
    decoded = base64.b64decode(content_string)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    dem_dir = os.path.join(base_dir, 'cache', 'dem')
    os.makedirs(dem_dir, exist_ok=True)

    if not filename:
        filename = 'uploaded_dem.tif'

    safe_name = _sanitize_filename(filename, fallback="uploaded_dem.tif")
    dem_path = os.path.join(dem_dir, safe_name)

    with open(dem_path, 'wb') as f:
        f.write(decoded)

    sesh.dem_path = dem_path
    sesh.dem_name = safe_name

    return html.Div(f"DEM uploaded: {safe_name}"), build_data_summary(), False, True, True, f"DEM uploaded: {safe_name}"

@app.callback(
    Output('output-dem-download', 'children'),
    Output('output-data-summary', 'children', allow_duplicate=True),
    Output('dem-downloaded', 'data', allow_duplicate=True),
    Output('dem-loaded', 'data', allow_duplicate=True),
    Output('dem-toast', 'is_open', allow_duplicate=True),
    Output('dem-toast', 'children', allow_duplicate=True),
    Input('download-dem', 'n_clicks'),
    State('use-dem', 'value'),
    State('dem-source', 'value'),
    State('dem-api-key', 'value'),
    State('dem-bbox-minlon', 'value'),
    State('dem-bbox-minlat', 'value'),
    State('dem-bbox-maxlon', 'value'),
    State('dem-bbox-maxlat', 'value'),
    State('dem-resolution', 'value'),
    running=[(Output("download-dem", "disabled"), True, False)],
    prevent_initial_call=True
)
def download_dem(n_clicks, use_dem, source, api_key, min_lon, min_lat, max_lon, max_lat, resolution):
    def _fail(message):
        return html.Div(message), build_data_summary(), False, False, True, message

    if not n_clicks:
        raise PreventUpdate
    if not use_dem:
        return _fail("Enable 'Use DEM' first.")

    if None in (min_lon, min_lat, max_lon, max_lat):
        return _fail("Please enter a complete bbox (min/max lon/lat).")
    if min_lon >= max_lon or min_lat >= max_lat:
        return _fail("Invalid bbox: min values must be less than max values.")

    download_url = None
    safe_name = None
    ot_params = None
    api_key_value = api_key

    if source == 'opentopo':
        demtype_map = {
            'opentopo_cop30': 'COP30',
            'opentopo_srtmgl1': 'SRTMGL1',
            'opentopo_srtmgl3': 'SRTMGL3',
            'opentopo_alos': 'ALOS',
        }
        demtype = demtype_map.get(resolution)
        if not demtype:
            return _fail("Please choose a global DEM resolution.")
        if not api_key_value:
            return _fail("OpenTopography requires an API key. Paste it above.")

        ot_params = {
            'demtype': demtype,
            'south': min_lat,
            'north': max_lat,
            'west': min_lon,
            'east': max_lon,
            'outputFormat': 'GTiff',
            'API_Key': api_key_value
        }
        download_url = 'https://portal.opentopography.org/API/globaldem'
        safe_name = _sanitize_filename(f"{demtype}_{min_lat:.6f}_{min_lon:.6f}_{max_lat:.6f}_{max_lon:.6f}.tif")
    elif source == 'etopo':
        etopo_map = {
            'etopo_30s': 'https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/30s/30s_surface_elev_gtif/ETOPO_2022_v1_30s_N90W180_surface.tif',
            'etopo_60s': 'https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/60s/60s_surface_elev_gtif/ETOPO_2022_v1_60s_N90W180_surface.tif',
        }
        download_url = etopo_map.get(resolution)
        if not download_url:
            return _fail("Please choose an ETOPO resolution.")

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        dem_dir = os.path.join(base_dir, 'cache', 'dem')
        os.makedirs(dem_dir, exist_ok=True)

        global_name = _sanitize_filename(download_url.split('/')[-1])
        global_path = os.path.join(dem_dir, global_name)
        if not os.path.exists(global_path):
            try:
                with requests.get(download_url, stream=True, timeout=180) as r:
                    r.raise_for_status()
                    with open(global_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
            except Exception as exc:
                return _fail(f"ETOPO download failed: {exc}")

        safe_name = _sanitize_filename(
            f"etopo_{resolution}_{min_lat:.6f}_{min_lon:.6f}_{max_lat:.6f}_{max_lon:.6f}.tif"
        )
        dem_path = os.path.join(dem_dir, safe_name)

        try:
            import rasterio
            from rasterio.windows import from_bounds

            with rasterio.open(global_path) as src:
                window = from_bounds(min_lon, min_lat, max_lon, max_lat, src.transform)
                window = window.round_offsets().round_lengths()
                data = src.read(1, window=window, boundless=True, fill_value=src.nodata)
                transform = src.window_transform(window)

                with rasterio.open(
                    dem_path,
                    'w',
                    driver='GTiff',
                    height=data.shape[0],
                    width=data.shape[1],
                    count=1,
                    dtype=data.dtype,
                    crs=src.crs,
                    transform=transform,
                    nodata=src.nodata,
                ) as dst:
                    dst.write(data, 1)
        except Exception as exc:
            return _fail(f"ETOPO clip failed: {exc}")

        sesh.dem_path = dem_path
        sesh.dem_name = safe_name

        msg = f"DEM downloaded: {safe_name}"
        return html.Div(msg), build_data_summary(), True, True, True, msg
    else:
        return _fail("Unknown DEM source.")

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    dem_dir = os.path.join(base_dir, 'cache', 'dem')
    os.makedirs(dem_dir, exist_ok=True)

    if not safe_name:
        safe_name = _sanitize_filename(download_url.split('?')[0])

    dem_path = os.path.join(dem_dir, safe_name)

    try:
        with requests.get(download_url, params=ot_params, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(dem_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
    except Exception as exc:
        return _fail(f"Download failed: {exc}")

    sesh.dem_path = dem_path
    sesh.dem_name = safe_name

    msg = f"DEM downloaded: {safe_name}"
    return html.Div(msg), build_data_summary(), True, True, True, msg

@app.callback(
    Output('save-dem', 'disabled'),
    Input('dem-downloaded', 'data'),
    Input('use-dem', 'value'),
    prevent_initial_call=False
)
def toggle_save_dem_button(dem_downloaded, use_dem):
    return not bool(dem_downloaded and use_dem)

@app.callback(
    Output('dem-downloaded', 'data', allow_duplicate=True),
    Input('use-dem', 'value'),
    prevent_initial_call=True
)
def reset_dem_downloaded(use_dem):
    if use_dem:
        raise PreventUpdate
    return False

@app.callback(
    Output('output-dem-save', 'children'),
    Output('dem-toast', 'is_open', allow_duplicate=True),
    Output('dem-toast', 'children', allow_duplicate=True),
    Input('save-dem', 'n_clicks'),
    State('dem-downloaded', 'data'),
    State('use-dem', 'value'),
    prevent_initial_call=True
)
def save_dem(n_clicks, dem_downloaded, use_dem):
    def _fail(message):
        return html.Div(message), True, message

    if not n_clicks:
        raise PreventUpdate
    if not use_dem:
        return _fail("Enable 'Use DEM' first.")
    if not dem_downloaded:
        return _fail("Please download a DEM first.")
    if not sesh.dem_path or not os.path.exists(sesh.dem_path):
        return _fail("No DEM file found to save.")
    filename = sesh.dem_name or os.path.basename(sesh.dem_path)
    filename = os.path.splitext(filename)[0]

    _configure_tk_dpi_awareness()
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    root.lift()
    root.focus_force()
    root.update()
    save_path = filedialog.asksaveasfilename(
        title="Save DEM",
        initialfile=filename,
        parent=root
    )
    root.destroy()

    if not save_path:
        raise PreventUpdate

    try:
        save_path_effective = save_path
        valid_exts = {".tif", ".tiff", ".asc", ".bil", ".dem", ".xyz"}
        ext = os.path.splitext(save_path_effective)[1].lower()
        if ext not in valid_exts:
            save_path_effective = save_path_effective + ".tif"
        shutil.copy2(sesh.dem_path, save_path_effective)
    except Exception as exc:
        return _fail(f"DEM save failed: {exc}")

    kml_msg = None
    kml_path = None
    try:
        if sesh.data is not None:
            kml_path = os.path.splitext(save_path_effective)[0] + ".kml"
            kml_msg = _export_kml_points(sesh.data, kml_path)
    except Exception as exc:
        kml_msg = f"KML export failed: {exc}"

    if kml_path and kml_msg and not kml_msg.startswith("KML export failed"):
        return html.Div([
            html.Div("DEM(tiff) and KML exported:"),
            html.Ul([
                html.Li(save_path_effective),
                html.Li(kml_path),
            ])
        ]), True, "DEM and KML exported."
    if kml_msg:
        return html.Div([
            html.Div("DEM saved:"),
            html.Ul([html.Li(save_path_effective)]),
            html.Div(kml_msg)
        ]), True, f"DEM saved. {kml_msg}"
    return html.Div([
        html.Div("DEM saved:"),
        html.Ul([html.Li(save_path_effective)])
    ]), True, "DEM saved."

@app.callback(
    Output('dem-api-key-list', 'children'),
    Output('dem-api-key-history', 'children'),
    Input('dem-api-keys', 'data'),
    prevent_initial_call=False
)
def sync_api_key_options(api_keys):
    keys = api_keys or []
    datalist_options = [html.Option(value=key) for key in keys]
    history_rows = []
    for key in keys:
        history_rows.append(
            html.Div(
                [
                    html.Button(
                        key,
                        id={'type': 'dem-api-key-select', 'index': key},
                        n_clicks=0,
                        style={
                            'border': 'none',
                            'background': 'transparent',
                            'padding': '0',
                            'textAlign': 'left',
                            'color': '#0d6efd',
                            'cursor': 'pointer',
                            'whiteSpace': 'nowrap'
                        }
                    ),
                    html.Button(
                        '❌',
                        id={'type': 'dem-api-key-delete', 'index': key},
                        n_clicks=0,
                        title='Remove from history',
                        style={
                            'border': 'none',
                            'background': 'transparent',
                            'cursor': 'pointer',
                            'padding': '0',
                            'marginLeft': '6px'
                        }
                    ),
                ],
                style={'display': 'flex', 'alignItems': 'center'}
            )
        )
    history_container = html.Div(
        history_rows,
        style={'display': 'flex', 'flexDirection': 'column', 'gap': '4px'}
    ) if history_rows else html.Div("No history yet.", style={'color': '#6c757d', 'fontSize': '12px'})
    return datalist_options, history_container

@app.callback(
    Output('dem-api-key-history-collapse', 'is_open'),
    Input('dem-api-key-history-toggle', 'n_clicks'),
    State('dem-api-key-history-collapse', 'is_open'),
    prevent_initial_call=True
)
def toggle_api_key_history(n_clicks, is_open):
    if not n_clicks:
        raise PreventUpdate
    return not is_open

@app.callback(
    Output('dem-api-key', 'value'),
    Output('dem-api-keys', 'data', allow_duplicate=True),
    Input({'type': 'dem-api-key-select', 'index': ALL}, 'n_clicks'),
    Input({'type': 'dem-api-key-delete', 'index': ALL}, 'n_clicks'),
    State('dem-api-keys', 'data'),
    prevent_initial_call=True
)
def handle_api_key_history(select_clicks, delete_clicks, api_keys):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    trigger = ctx.triggered_id
    keys = list(api_keys or [])

    if isinstance(trigger, dict) and trigger.get('type') == 'dem-api-key-select':
        key = trigger.get('index')
        return key, no_update

    if isinstance(trigger, dict) and trigger.get('type') == 'dem-api-key-delete':
        key = trigger.get('index')
        keys = [k for k in keys if k != key]
        return no_update, keys

    raise PreventUpdate

@app.callback(
    Output('dem-api-keys', 'data', allow_duplicate=True),
    Input('dem-downloaded', 'data'),
    State('dem-api-key', 'value'),
    State('dem-api-keys', 'data'),
    prevent_initial_call=True
)
def remember_api_key_on_download(dem_downloaded, api_key, api_keys):
    if not dem_downloaded:
        raise PreventUpdate
    if not api_key:
        raise PreventUpdate

    keys = list(api_keys or [])
    if api_key in keys:
        keys = [k for k in keys if k != api_key]
    keys.insert(0, api_key)
    return keys[:20]



@app.callback(
    Output('dem-upload-container', 'style'),
    Input('use-dem', 'value'),
    prevent_initial_call=False
)
def toggle_dem_upload(use_dem):
    if use_dem:
        return {'display': 'block', 'marginTop': '10px'}
    sesh.dem_path = None
    sesh.dem_name = None
    return {'display': 'none', 'marginTop': '10px'}