import os
import base64
import rasterio
import matplotlib.pyplot as plt
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.plot import reshape_as_image
from PIL import Image
import plotly.graph_objects as go
import plotly.express as px
from pyproj import Transformer
import pandas as pd
import numpy as np
import math
import re
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import plotly.colors as pc

from dataclasses_jsonschema import JsonSchemaMixin

import nosj

from dash import Dash, html, dcc, Input, Output, State, no_update, callback_context
from dash.dependencies import Input, Output, State, ALL, MATCH
from scipy.spatial import cKDTree
from pyproj import Geod

from basepanel import Panel, gear_maker, dcc, PanelSettings
# from temframe import TEMframe
import temframe


from panels import *

import io

# num_layers = 28         # number of interpreted layers for TESTING
# depth = 120       # number of depth samples per layer for TESTING

# # Sample dataframe for TESTING
# df = pd.DataFrame({
#     "latitude": [9.72, 9.70, 9.67, 9.69],
#     "longitude": [41.56, 41.58, 41.54, 41.55],
#     "value": [40.2, 50.8, 45.5, 47.9],
#     "Elevation": [1000.2, 1100.8, 1090.5, 1050.9],
#     "Resistivity" : [20, 38, 75, 1],
#     "ResModel":     [generate_res_model() for _ in range(4)],
#     "Depths":       [generate_depths() for _ in range(4)],
# })


# --------------------- Settings ---------------------
@nosj
class Settings(PanelSettings):
    png_crs : str = "EPSG:32637"
    vmin: float = 1.0
    vmax: float = 300.0
    log: bool = True
    cmap: str = 'turbo'
    Show_misfit : bool =True

    radius: int = 50 
    column_width: int = 6
    borehole_width : int = 50
    num_labels_colorbar: int = 4

settings = Settings('tmp_scattermap')



# ------------------------ COLORS -----------------------
def value_to_color(val, vmin, vmax, log=False, cmap="turbo"):
    if log:
        val = np.log10(val)
        vmin = np.log10(vmin)
        vmax = np.log10(vmax)

    # normalize 0–1
    t = (val - vmin) / (vmax - vmin)
    t = np.clip(t, 0, 1)

    # sample colorscale
    color = pc.sample_colorscale(cmap, [t])[0]
    return color

# ------------------------ BOREHOLES-----------------------
def load_borehole_file(file_path_or_content, from_string=False):

    if from_string:
        content = file_path_or_content
    else:
        with open(file_path_or_content, "r") as f:
            content = f.read()

    blocks = re.split(r"(?=BoreholeNo=)", content)
    blocks = [b.strip() for b in blocks if "BoreholeNo=" in b]

    all_boreholes = []

    for i, block in enumerate(blocks):
        def _get(field, text=block):
            m = re.search(f"{field}=(.*)", text)
            return m.group(1).strip() if m else None

        try:
            bh_id = _get("BoreholeNo")
            elev  = float(_get("Elevation"))
            utm_zone_raw = _get("UTMZone")
            datum_raw    = _get("Datum")

            # Auto-detect EPSG from UTMZone + Datum
            utm_zone = int(utm_zone_raw) if utm_zone_raw else 37
            datum    = (datum_raw or "WGS84").upper()
            if "WGS" in datum or "84" in datum:
                epsg = 32600 + utm_zone          # WGS-84 northern hemisphere
            else:
                epsg = 32600 + utm_zone          # fallback to WGS-84

            bh_metadata = {
                "bh_index": i,
                "id": bh_id,
                "x": float(_get("XUTM")),
                "y": float(_get("YUTM")),
                "elevation": elev,
                "utm_zone": utm_zone,
                "epsg": epsg,
            }
            print(bh_metadata)

            table_start = block.find("Top")
            if table_start == -1:
                continue

            table_lines = block[table_start:].strip().split("\n")
            if len(table_lines) < 2:
                continue

            data_rows = []
            for line in table_lines[1:]:
                parts = re.findall(r'(".*?"|\S+)', line)
                if len(parts) >= 2:
                    while len(parts) < 4:
                        parts.append("")
                    data_rows.append({
                        "Top": float(parts[0]),
                        "Bottom": float(parts[1]),
                        "LayerDescription": parts[2].replace('"', ''),
                        "RockType": parts[3],
                    })

            df_layers = pd.DataFrame(data_rows)
            if not df_layers.empty:
                df_layers["RockType"] = df_layers["RockType"].replace(
                    {"Nan": "Unspecified", "": "Unspecified"}
                )
                bh_metadata["layers"] = df_layers.to_dict("records")
                all_boreholes.append(bh_metadata)

        except Exception as e:
            print(f"Error parsing borehole {i}: {e}")

    # --- Global colour map ---
    all_rock_types = set()
    for bh in all_boreholes:
        for layer in bh["layers"]:
            rt = layer["LayerDescription"]
            if rt:
                all_rock_types.add(rt)

    sorted_rocks = sorted(all_rock_types)
    cmap = plt.get_cmap("tab20b")
    rock_color_map = {}
    if sorted_rocks:
        positions = np.linspace(0.1, 0.9, len(sorted_rocks))
        for idx, rock in enumerate(sorted_rocks):
            rock_color_map[rock] = mcolors.to_hex(cmap(positions[idx]))

    return all_boreholes, rock_color_map

def get_borehole_projections(boreholes, src_epsg=None):

    if isinstance(boreholes, dict):
        boreholes = [boreholes]

    projections = []
    _cache = {}                       # transformer cache keyed by epsg

    for bh in boreholes:
        epsg = src_epsg or bh.get("epsg", 32637)
        if epsg not in _cache:
            _cache[epsg] = Transformer.from_crs(
                f"EPSG:{epsg}", "EPSG:4326", always_xy=True
            )
        transformer = _cache[epsg]
        lon, lat = transformer.transform(bh["x"], bh["y"])

        projections.append({
            "id": bh["id"],
            "map_lon": lon,
            "map_lat": lat,
            "elev": bh["elevation"],
            "layers": bh["layers"],
        })

    return projections

def add_boreholes_to_map_fig(fig, bh_projections, bh_color="orange"):

    if not bh_projections:
        return fig

    lons  = [b["map_lon"] for b in bh_projections]
    lats  = [b["map_lat"] for b in bh_projections]
    names = [b["id"]      for b in bh_projections]

    # customdata carries [bh_id, 0, "borehole"] so Alt+click can identify type
    cdata = [[b["id"], 0, "borehole"] for b in bh_projections]

    fig.add_trace(go.Scattermap(
        lat=lats,
        lon=lons,
        mode="markers+text",
        marker=dict(size=14, color=bh_color, symbol="circle"),
        text=names,
        textposition="top right",
        customdata=cdata,
        name="Boreholes",
        showlegend=False,
        below="",
    ))
    return fig

def add_boreholes_to_section_fig(fig, bh_projections,rock_color_map, bar_width=settings.borehole_width):
    width_factor = float(bar_width) / 10.0 
    x_coords = [s['dist_x'] for s in bh_projections]

    # 2. Calculate the width based on spacing
    if len(bh_projections) > 1:
        avg_spacing = (max(x_coords) - min(x_coords)) / (len(bh_projections) )
        bar_width = avg_spacing * width_factor
    else:
        bar_width = 50.0 # Fallback for single borehole
    
    # print("bar width", bar_width)

    if not bh_projections:
        return fig

    for bh in bh_projections:
        bh_id = bh["id"]
        bh_x = bh.get("dist_x")
        if bh_x is None:
            continue

        for layer in bh["layers"]:
            z_top    = bh["elev"] - float(layer["Top"])
            z_bottom = bh["elev"] - float(layer["Bottom"])
            hw = bar_width / 2.0

            x_box = [bh_x - hw, bh_x + hw, bh_x + hw, bh_x - hw, bh_x - hw]
            y_box = [z_top, z_top, z_bottom, z_bottom, z_top]

            click_data = [bh['id'], bh_x,  "borehole"] * 5,

            rock  = layer.get("LayerDescription", "").strip()

            color = rock_color_map.get(rock, "lightgray")

            fig.add_trace(go.Scatter(
                x=x_box,
                y=y_box,
                fill="toself",
                fillcolor=color,
                mode="lines",
                line=dict(width=0.5, color="black"),
                name = rock,
                customdata=click_data,
                showlegend=False,
                hovertext=f"{bh['id']}: {rock}",
                hoverinfo="text",
            ))

        fig.add_annotation(
            x=bh_x,
            y=bh["elev"],
            text=f"<b>{bh['id']}</b>",
            showarrow=False,
            yshift=10,
            xanchor="center",
            yanchor="bottom",
            font=dict(size=10, color="black"),
        )

    return fig

def build_combined_borehole_figure(bh_ids, bh_projections, rock_color_map):
    fig = go.Figure()
    valid_indices = []

    for x_pos, target_id in enumerate(bh_ids):
        bh = next(
            (b for b in bh_projections
             if str(b.get("id")) == str(target_id)),
            None,
        )
        if not bh:
            continue
        valid_indices.append(x_pos)

        for layer in bh.get("layers", []):
            z_top    = bh["elev"] - float(layer["Top"])
            z_bottom = bh["elev"] - float(layer["Bottom"])
            w = 0.4
            x_box = [x_pos - w, x_pos + w, x_pos + w, x_pos - w, x_pos - w]
            y_box = [z_top, z_top, z_bottom, z_bottom, z_top]

            rock  = layer.get("LayerDescription", "").strip()
            color = rock_color_map.get(rock, "lightgray")

            fig.add_trace(go.Scatter(
                x=x_box, y=y_box,
                fill="toself",
                fillcolor=color,
                mode="lines",
                line=dict(width=0.8, color="black"),
                name=rock,
                showlegend=False,
                hovertext=(
                    f"<b>{bh['id']}</b><br>{rock}<br>"
                    f"Elev: {z_top:.1f} to {z_bottom:.1f}m"
                ),
                hoverinfo="text",
            ))

        fig.add_annotation(
            x=x_pos, y=bh["elev"],
            text=f"<b>{bh['id']}</b>",
            showarrow=False, yshift=15,
            font=dict(size=12),
        )

    x_min = (min(valid_indices) - 1) if valid_indices else -1
    x_max = (max(valid_indices) + 1) if valid_indices else  1

    fig.update_layout(
        template="plotly_white",
        showlegend=False,
        xaxis=dict(
            tickvals=list(range(len(bh_ids))),
            ticktext=bh_ids,
            title="Borehole ID",
            range=[x_min, x_max],
            showgrid=False,
            linecolor="black", mirror=True,
        ),
        yaxis=dict(
            title="Elevation (m.a.s.l.)",
            gridcolor="lightgray",
            linecolor="black", mirror=True,
        ),
        margin=dict(l=60, r=40, t=50, b=60),
    )
    return fig

bh_data = None 
rock_color_map = None

def haversine_distance(p1, p2):
    """Distance in metres between two [lon, lat] points."""
    lon1, lat1 = np.radians(p1)
    lon2, lat2 = np.radians(p2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * np.arcsin(np.sqrt(a))

def project_point_onto_polyline(station_pt, polyline_coords):
    """
    Project a [lon, lat] point onto a polyline.

    Returns (distance_along_line_m, perpendicular_distance_m).
    """
    best_x = 0
    min_dist = float("inf")
    cum_dist = 0
    for i in range(len(polyline_coords) - 1):
        A = np.array(polyline_coords[i])
        B = np.array(polyline_coords[i + 1])
        P = np.array(station_pt)
        seg_len = haversine_distance(A, B)
        if seg_len == 0:
            continue
        ab = B - A
        t = np.clip(np.dot(P - A, ab) / np.dot(ab, ab), 0, 1)
        closest = A + t * ab
        d = haversine_distance(P, closest)
        if d < min_dist:
            min_dist = d
            best_x = cum_dist + t * seg_len
        cum_dist += seg_len
    return best_x, min_dist

def get_boreholes_on_line(line_coords, bh_projections, search_radius_m=settings.radius):
    if not line_coords or len(line_coords) < 2:
        return []
    result = []
    for bh in bh_projections:
        pt = [bh["map_lon"], bh["map_lat"]]
        
        dist_along, dist_from = project_point_onto_polyline(pt, line_coords)
        if dist_from <= search_radius_m:
            entry = dict(bh)          # shallow copy
            entry["dist_x"] = dist_along
            result.append(entry)
    return sorted(result, key=lambda x: x["dist_x"])

def boreholes_to_dataframe(all_boreholes):
    print("sections plotting.py here - boreholes to df")
    """
    Converts the nested 'all_boreholes' list into a flat pandas DataFrame.
    """
    flat_data = []
    for bh in all_boreholes:
        # Extract metadata
        meta = {
            "bh_id": bh["id"],
            "bh_x": bh["x"],
            "bh_y": bh["y"],
            "bh_elev": bh["elevation"],
            "utm_zone": bh.get("utm_zone", 37),
            "epsg": bh.get("epsg", 32637)
        }
        
        # Add a row for every layer
        for layer in bh.get("layers", []):
            row = meta.copy()
            row.update({
                "layer_top": layer["Top"],
                "layer_bottom": layer["Bottom"],
                "layer_desc": layer["LayerDescription"],
                "layer_rock": layer["RockType"]
            })
            flat_data.append(row)
            
    return pd.DataFrame(flat_data)

def dataframe_to_boreholes(df):
    print("df to boreholes")
    """
    Reconstructs the nested borehole list from a flat DataFrame.
    """
    if df is None or df.empty:
        return []
        
    all_boreholes = []
    # Group by borehole ID to reconstruct metadata
    for bh_id, group in df.groupby("bh_id"):
        first_row = group.iloc[0]
        
        layers = []
        for _, row in group.iterrows():
            layers.append({
                "Top": row["layer_top"],
                "Bottom": row["layer_bottom"],
                "LayerDescription": row["layer_desc"],
                "RockType": row["layer_rock"]
            })
            
        all_boreholes.append({
            "id": bh_id,
            "x": first_row["bh_x"],
            "y": first_row["bh_y"],
            "elevation": first_row["bh_elev"],
            "utm_zone": first_row["utm_zone"],
            "epsg": first_row["epsg"],
            "layers": layers
        })
    return all_boreholes



# -------------------------------------------------------------
def preprocess_new_df(new_df):
    if new_df is None or not hasattr(new_df, 'columns'):
        # return pd.DataFrame(), {}, []
        empty_df = pd.DataFrame(columns=['site_id', 'latitude', 'longitude', 'Depths', 'resistivity'])
        return empty_df, {}, []

    attributes = ['date', 'daytime', 'elevation','misfit', 'doi', 'Number of Gates']
    color_master_map = {}

    # 2. Build the aggregation dictionary
    agg_dict = {
        'resistivity': lambda x: list(x),
        'top_depth': lambda x: list(x),
        'bottom_depth': lambda x: list(x),}
        
    
    groupby_cols = ['site_id', 'latitude', 'longitude', 'elevation']
    existing_attrs = [col for col in attributes if col in new_df.columns]
    # print("EXISTING ATTRS", existing_attrs)
    
    # For every attribute, just take the first occurrence in the group
    for col in existing_attrs:
        if col not in groupby_cols:
            agg_dict[col] = 'first'

    # 3. Group and aggregate
    df_wide = new_df.groupby(groupby_cols).agg(agg_dict).reset_index()

    # 4. Create the 'Depths' column
    def extract_depth_interfaces(row):
        return row['top_depth'] + [row['bottom_depth'][-1]]
    
    df_wide['Depths'] = df_wide.apply(extract_depth_interfaces, axis=1)

    for attr in existing_attrs:
            if not pd.api.types.is_numeric_dtype(new_df[attr]) or attr == 'date':
                unique_vals = sorted(new_df[attr].astype(str).str.replace(r'\.0$', '', regex=True).unique().tolist())
                palette = px.colors.qualitative.Light24
                color_master_map[attr] = {val: palette[i % len(palette)] for i, val in enumerate(unique_vals)}

    return df_wide, color_master_map, existing_attrs
   
def get_numeric_colors(values, vmin, vmax, log=False, cmap_name='jet'): 
    """Maps numbers to Hex strings using GLOBAL min/max."""
    try:
        vals = np.array(values, dtype=float)
        
        # 1. Use global limits instead of local np.nanmin/max
        # 2. Handle log scale if enabled in settings
        if log:
            # Shift values to avoid log(0)
            vals = np.maximum(vals, 1e-6) 
            norm = mcolors.LogNorm(vmin=max(vmin, 1e-6), vmax=vmax)
        else:
            norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
            
        cmap = plt.get_cmap(cmap_name)
        return [mcolors.to_hex(cmap(norm(v))) for v in vals]
    except:
        return ['grey'] * len(values)

def parse_polyline_path(path_str):
    """Regex to find x,y pairs and convert to float list of lists"""
    # Matches pairs like "0.5,0.2"
    matches = re.findall(r"([0-9.]+),([0-9.]+)", path_str)
    # Return as [[x1, y1], [x2, y2]]
    return [[float(x), float(y)] for x, y in matches]

def project_station_onto_polyline(station_pt, polyline_coords):
    """
    station_pt: [lon, lat]
    polyline_coords: [[lon1, lat1], [lon2, lat2], ...]
    Returns: (best_x_dist, min_dist_to_line_m)
    """
    best_x = 0
    min_dist_to_line = float('inf')
    cum_dist = 0
    
    for i in range(len(polyline_coords) - 1):
        A = np.array(polyline_coords[i])
        B = np.array(polyline_coords[i+1])
        P = np.array(station_pt)
        
        seg_len = haversine_distance(A, B)
        if seg_len == 0: continue
        
        # Vector math for projection
        # t is the fraction along the segment (0 to 1)
        ap = P - A
        ab = B - A
        t = np.dot(ap, ab) / np.dot(ab, ab)
        t = np.clip(t, 0, 1)
        
        # Closest point on this segment
        closest_pt = A + t * ab
        dist_to_seg = haversine_distance(P, closest_pt)
        
        if dist_to_seg < min_dist_to_line:
            min_dist_to_line = dist_to_seg
            best_x = cum_dist + (t * seg_len)
            
        cum_dist += seg_len
        
    return best_x, min_dist_to_line

def get_station_projections(polyline_coords, df, search_radius_m=settings.radius):
    stations_on_line = []
    
    for i, row in df.iterrows():
        s_pt = [row['longitude'], row['latitude']]
        
        # Use our new linear projection
        dist_x, dist_to_line = project_station_onto_polyline(s_pt, polyline_coords)
        
        if dist_to_line <= search_radius_m:
            stations_on_line.append({
                'df_index': i,
                'dist_x': dist_x,
                'elev': row['elevation'],
                'res': row['resistivity'],
                'misfit': row['misfit'],
                'doi': row['doi'],
                'id': row.get('site_id', i)
            })
            # print ("DOI ROW",row['doi'])
            
    # Sort by distance along path so the plot is ordered left-to-right
    # print ("stations on line for doi", stations_on_line)
    return sorted(stations_on_line, key=lambda x: x['dist_x'])

#-------------------------------------------
def interpolate_nearest(df, samples, radius=settings.radius):
    """
    Efficient spatial lookup for resistivity and elevation.
    samples: array of [lon, lat] pairs.
    """
    coords = df[["longitude", "latitude"]].values
    tree = cKDTree(coords)

    # Query nearest points --- Nearest-Neighbor interpolation.
    dists, idxs = tree.query(samples)

    res_models = []
    elevations = []
    dois = []

    for dist, idx in zip(dists, idxs):
        # radius is in degrees; roughly 0.001 deg ~ 111m
        if radius is not None and dist > radius:
            res_models.append(None) 
            elevations.append(np.nan)
            dois.append(0)
        else:
            res_models.append(df.iloc[idx]["resistivity"])
            elevations.append(df.iloc[idx]["elevation"]) 
            dois.append(df.iloc[idx].get("doi", 0))

    return res_models, elevations, dists, idxs, dois

def get_polyline_profile(coords, section_data, resolution_m=10.0):
    """
    Takes polyline points, generates equal-distance sample points in meters,
    and returns coords and distances for plotting.
    """
    all_x_coords = []
    all_lons = []
    all_lats = []
    total_dist = 0.0

    for i in range(len(coords) - 1):
        p_start, p_end = coords[i], coords[i+1]
        seg_length = haversine_distance(p_start, p_end)
        
        num_samples = max(2, int(seg_length / resolution_m))
        
        lons = np.linspace(p_start[0], p_end[0], num_samples)
        lats = np.linspace(p_start[1], p_end[1], num_samples)
        
        # Distance along this specific segment
        seg_dist = np.linspace(0, seg_length, num_samples) + total_dist
        
        # Filter duplicates at vertices
        start_idx = 1 if i > 0 else 0
        all_x_coords.extend(seg_dist[start_idx:])
        all_lons.extend(lons[start_idx:])
        all_lats.extend(lats[start_idx:])
        
        total_dist += seg_length
        
    return np.array(all_x_coords), np.array(all_lons), np.array(all_lats)

def extract_doi_value(val):
    """Safely extracts a number from float, tensor, or the string 'tensor(xxx)'."""
    if val is None:
        return 0.0
    # Handle actual torch tensor objects
    if hasattr(val, "item"):
        return float(val.item())
    # Handle the string representation: "tensor(174.1709, ...)"
    if isinstance(val, str) and "tensor(" in val:
        match = re.search(r"tensor\(([-+]?\d*\.\d+|\d+)", val)
        if match:
            return float(match.group(1))
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def create_blocky_polygons(stations_on_line, depths, vmin, vmax, log,show_misfit=settings.Show_misfit, bar_width=settings.column_width, show_borders=False):    
    width_factor = float(bar_width) / 10.0
    x_coords = [s['dist_x'] for s in stations_on_line]

    if len(stations_on_line) > 1:
        avg_spacing = (max(x_coords) - min(x_coords)) / (len(stations_on_line) - 1)
        # Use the converted float here
        bar_width = avg_spacing * width_factor
    else:
        bar_width = 50.0

    traces = []
    if not stations_on_line: return go.Figure()

    doi_line_x = []
    doi_line_y = []

    misfit_line_x = []
    misfit_line_y = []
    
    for s in stations_on_line:
        x_center = s['dist_x']
        surface = float(s.get('elev', 0))
        res_values = s['res']
        
        # Extract DOI for this station
        doi_depth = extract_doi_value(s.get("doi", 0))
        doi_elevation = surface - doi_depth
        doi_line_x.append(x_center)
        doi_line_y.append(doi_elevation)
        
        if show_misfit:
            misfit = extract_doi_value(s.get('misfit',0))
            misfit_line_x.append(x_center)
            misfit_line_y.append(misfit)

        # 1. Create the resistivity blocks
        for j in range(len(depths) - 1):
            val = res_values[j]
            top, bottom = surface - depths[j], surface - depths[j+1]
            color_str = value_to_color(val, vmin, vmax, log, cmap=settings.cmap)

            def add_block(y_top, y_bot, opacity):
                final_color = color_str
                if opacity < 1.0:
                    # Convert rgb to rgba or modify existing rgba
                    final_color = color_str.replace('rgb(', 'rgba(').replace(')', f', {opacity})')

                x_box = [x_center - bar_width/2, x_center + bar_width/2, 
                        x_center + bar_width/2, x_center - bar_width/2, x_center - bar_width/2]
                y_box = [y_top, y_top, y_bot, y_bot, y_top]
                
                # sounding_idx = s.get('df_index')
                sounding_idx = s.get('id')
                
                traces.append(go.Scatter(
                    x=x_box, y=y_box, 
                    fill="toself", 
                    fillcolor=final_color,
                    mode='lines', 
                    line=dict(width=0),
                    showlegend=False,                
                    customdata=[[sounding_idx, x_center]]* len(x_box),
                    name="", 
                    hoveron='fills',
                    text=f"Res {val:.1f} Ωm \nModel: {sounding_idx}",
                ))

            # LOGIC: Splitting the block based on DOI
            if top > doi_elevation > bottom:
                # Layer is split by DOI
                add_block(top, doi_elevation, 1.0,)      # Solid top
                add_block(doi_elevation, bottom, 0.3, )   # Transparent bottom
            elif top <= doi_elevation:
                # Entire layer is below DOI
                add_block(top, bottom, 0.3, )
            else:
                # Entire layer is above DOI
                add_block(top, bottom, 1.0, )

            if show_borders:
                # Find the bottom of the last layer
                total_bottom = surface - depths[-1]
                top, bottom = surface - depths[j], surface - depths[j+1]
                
                x_outline = [x_center - bar_width/2, x_center + bar_width/2, 
                            x_center + bar_width/2, x_center - bar_width/2, x_center - bar_width/2]
                y_box = [top, top, bottom, bottom, top]
                
                traces.append(go.Scatter(
                    x=x_outline, y=y_box,
                    mode='lines',
                    line=dict(color="black", width=0.3), # Your clean boundary
                    showlegend=False,
                    hoverinfo='skip' # Don't interfere with block tooltips
                ))

        # Add the misfit Line on top for visual clarity
    if show_misfit and misfit_line_x:
        traces.append(go.Scatter(
            x=misfit_line_x, y=misfit_line_y,
            yaxis="y2",
            mode="lines", 
            line=dict(color="red", width=1.5, ), #dash="dash"),
            name="Misfit", 
            showlegend=True,
            hoverinfo="skip",      # Tells Plotly to ignore this trace for tooltips
            hoveron="points",     # Ensures it doesn't behave like a "fill" click
            customdata=[None] * len(misfit_line_x)
        ))

    fig = go.Figure(data=traces)


    fig.update_layout(dragmode='pan', hovermode='closest')   

    # fig.update_layout(
    layout_dict = dict(
        template="plotly_white", # Sets initial white theme
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis_title="Distance [m]",
        yaxis_title="Elevation [m]",
        hovermode="x",
        showlegend=False,
        xaxis=dict(showgrid=True,gridcolor="lightgray",gridwidth=0.5,zeroline=False,
            showline=True,linecolor="black",mirror=True),
        yaxis=dict(showgrid=True,gridcolor="lightgray",gridwidth=0.5,
            zeroline=False,showline=True,linecolor="black",
            mirror=True, autorange=True ),
            )

        # yaxis2=dict(
    if show_misfit:

        # Enable the legend
        layout_dict["showlegend"] = True
        
        # Configure the legend appearance
        layout_dict["legend"] = dict(
            x=0.01, y=0.01,
            xanchor="left", yanchor="bottom",
            bgcolor="rgba(255, 255, 255, 0.5)",
            bordercolor="lightgray", borderwidth=1
        )

        layout_dict["yaxis2"] = dict(
                title="Misfit",
                tickfont=dict(color="red"),
                anchor="x",
                overlaying="y",
                side="right",
                # range=[0, max(misfit_line_y) * 1.2 if misfit_line_y else 1], 
                range=[0, 9],  
                showgrid=False, 
            )

        layout_dict["margin"] = dict(l=60, r=80, t=50, b=60)
    else:
        layout_dict["showlegend"] = False
        # Reset right margin if no second axis
        layout_dict["margin"] = dict(l=60, r=40, t=50, b=60)
    
    fig.update_layout(**layout_dict)
    return fig

def combine_sections_final(all_x, y_depth, vmin, vmax, log, res_models, elevations, stations_on_line, dois, show_misfit, bar_width=settings.column_width):
    blocky_fig = create_blocky_polygons(stations_on_line, y_depth, vmin, vmax, log, show_misfit, bar_width, show_borders=True)
    interp_fig = plot_section_topographic(all_x, y_depth, vmin, vmax, log, res_models, elev=elevations, dois=dois, title="Combined Section")
    
    combined_fig = go.Figure(layout=blocky_fig.layout)
    for trace in interp_fig.data:
        if trace.mode == 'lines' and trace.line.color == 'black':
            topo_trace = trace
            continue
        trace.opacity = 0.5
        combined_fig.add_trace(trace)

    for trace in blocky_fig.data:
        trace.opacity = 1
        combined_fig.add_trace(trace)

    if 'topo_trace' in locals():
        topo_trace.opacity = 1.0
        combined_fig.add_trace(topo_trace)

    return combined_fig

# ---------- for hover Marker -------------
def get_geo_at_distance(polyline, target_dist):
    """Finds [lon, lat] at target_dist meters from the start of the polyline."""
    cum_dist = 0
    for i in range(len(polyline) - 1):
        p1, p2 = polyline[i], polyline[i+1]
        seg_len = haversine_distance(p1, p2)
        
        if cum_dist + seg_len >= target_dist:
            # The point is on this segment
            remainder = target_dist - cum_dist
            fraction = remainder / seg_len
            
            lon = p1[0] + fraction * (p2[0] - p1[0])
            lat = p1[1] + fraction * (p2[1] - p1[1])
            return [lon, lat]
        
        cum_dist += seg_len
    return polyline[-1] # Fallback to end

def plot_section_topographic(x, y_depth, vmin, vmax, log, res_models, elev, dois, title="Resistivity Section"):
    fig = go.Figure()
    res_m = x[1] - x[0] if len(x) > 1 else 10
    doi_line_x = []
    doi_line_y = []
    # 1. Plot the "Background" Data as vertical columns
    for i in range(len(x)):
        x_center = x[i]

        if elev is not None:
            surface = elev[i]
        else: 
            return no_update
            
        res_values = res_models[i]

        doi_depth = extract_doi_value(dois[i])
        doi_elevation = surface - doi_depth
        doi_line_x.append(x_center)
        doi_line_y.append(doi_elevation)
        
        if res_values is None: continue

        for j in range(len(y_depth) - 1):
            val = res_values[j]
            
            color_str = value_to_color(val,vmin,vmax,log,cmap=settings.cmap)
             
            if val <= 0 or np.isnan(val): continue
            top = surface - y_depth[j]
            bottom = surface - y_depth[j+1]

            def add_block(y_top, y_bot, opacity):
                final_color = color_str
                if opacity < 1.0:
                    final_color = color_str.replace('rgb(', 'rgba(').replace(')', f', {opacity})')

                x_box = [x_center - res_m/2, x_center + res_m/2, 
                        x_center + res_m/2, x_center - res_m/2, x_center - res_m/2]
                y_box = [y_top, y_top, y_bot, y_bot, y_top]
                
                fig.add_trace(go.Scatter(
                    x=x_box, y=y_box, 
                    fill="toself", 
                    fillcolor=final_color,
                    mode='lines', 
                    line=dict(width=0),
                    showlegend=False,                
                    customdata=[x_center] * len(x_box),
                    # customdata=[[x_center]] * len(x_box),
                    hoveron='fills', hoverinfo="all", text=f"Res: {val:.1f} Ωm",
                ))

            if top > doi_elevation > bottom:
                add_block(top, doi_elevation, 1.0)      
                add_block(doi_elevation, bottom, 0.3)   
            elif top <= doi_elevation:
                add_block(top, bottom, 0.3)
            else:                
                add_block(top, bottom, 1.0)

    if doi_line_x:
        x_start_extended = doi_line_x[0] - res_m/2
        x_end_extended = doi_line_x[-1] + res_m/2

        extended_doi_x = [x_start_extended] + doi_line_x + [x_end_extended]
        extended_doi_y = [doi_line_y[0]] + doi_line_y + [doi_line_y[-1]]

        extended_elev = [elev[0]] + list(elev) + [elev[-1]]

        # add the topography
        fig.add_trace(go.Scatter(
                    x=extended_doi_x, y=extended_elev  ,
                    mode='lines',showlegend=False,
                    line=dict(color='black', width=2, shape='hv'), ))

    else:
    # 2. Add the Topography Line (The "Staircase")
        fig.add_trace(go.Scatter(
            x=x, y=elev,
            mode='lines',showlegend=False,
            line=dict(color='black', width=2, shape='hv'), ))

    fig.update_layout(
        template="plotly_white", 
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis_title="Distance along path (m)",
        yaxis_title="Elevation [m]",
        xaxis=dict(showgrid=True,gridcolor="lightgray",gridwidth=0.5,zeroline=False,showline=True,linecolor="black",mirror=True),
        yaxis=dict(showgrid=True,gridcolor="lightgray",gridwidth=0.5,zeroline=False,showline=True,linecolor="black",mirror=True,
                autorange=True), 
        margin=dict(l=60, r=40, t=50, b=60),)
    
    return fig

# ---------- STEP PLOT -------------
def generate_res_step_graph(row, row_index, label=None, step_color='red'):
    res = np.array(row.get('resistivity', [])).astype(float)
    top = np.array(row.get('top_depth', [])).astype(float)
    bottom = np.array(row.get('bottom_depth', [])).astype(float)
    
    doi = extract_doi_value(row.get("doi", 0))
    
    # --- 2. Validation ---
    valid = np.isfinite(res) & np.isfinite(top) & np.isfinite(bottom)
    res, top, bottom = res[valid], top[valid], bottom[valid]

    if len(res) == 0:
        return go.Figure().add_annotation(text="No valid layers", showarrow=False)

    # --- 3. Create the Figure ---
    fig = go.Figure()

    # Step-post logic: add last bottom and last res to close the polygon
    z_coords = np.append(top, bottom[-1])
    res_coords = np.append(res, res[-1])

    fig.add_trace(go.Scatter(
        x=res_coords,
        y=z_coords,
        mode='lines',
        line=dict(shape='hv', width=3, color=step_color),
        name=label or f"Sounding {row_index}"
    ))

    # Add DOI Line
    if pd.notnull(doi) and doi > 0:
        fig.add_hline(
            y=doi, 
            line_dash="dash", 
            line_color="gray", 
            # annotation_text=f"DOI ({doi:.1f}m)", 
            # annotation_position="bottom right"
        )

    # --- 4. Layout ---
    fig.update_layout(
        xaxis=dict(title="Resistivity (Ohm-m)", type="log", gridcolor='lightgray',
            linecolor='black',      # Color of the axis line
            linewidth=1,            # Thickness of the border
            mirror=True,            # Adds the line to the top as well, creating a box
            dtick=1,                # Ensures minor gridlines/labels are hidden
            minor=dict(showgrid=True, ticks=""),
            range=[0, 3]            # LOG LIMITS: 10^0 to 10^4 (i.e., 1 to 10,000 Ohm-m) change this to [0, 3] for 1 to 1,000 Ohm-m
        ),
        yaxis=dict(title="Depth (m)", autorange="reversed", gridcolor='lightgray',
            linecolor='black',
            linewidth=1,
            mirror=True,),
        template="plotly_white",
        margin=dict(l=50, r=40, t=50, b=50), # Slightly more margin for labels
        plot_bgcolor='white'
    )

    return fig

def generate_res_step_graph_elev(row, row_index, label=None, elevation=None,step_color='red'):
    res = np.array(row.get('resistivity', [])).astype(float)
    top = np.array(row.get('top_depth', [])).astype(float)
    bottom = np.array(row.get('bottom_depth', [])).astype(float)

    doi = extract_doi_value(row.get("doi", 0))
    valid = np.isfinite(res) & np.isfinite(top) & np.isfinite(bottom)
    res, top, bottom, = res[valid], top[valid], bottom[valid], 

    if len(res) == 0:
        return go.Figure().add_annotation(text="No valid layers", showarrow=False)

    # Calculate Z coordinates based on Depth or Elevation
    if elevation is not None:
        # Elevation = Surface Elevation - Depth
        z_coords = np.append(elevation - top, elevation - bottom[-1])
        y_range = [np.min(z_coords) - 5, np.max(z_coords) + 5 ]
        y_title = "Elevation"
        doi = elevation - doi
    else:
        z_coords = np.append(top, bottom[-1])
        y_range = [np.min(z_coords) - 5, np.max(z_coords) + 5]
        y_title = "Depth (m)"
        doi = doi

    res_coords = np.append(res, res[-1])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=res_coords,
        y= z_coords,
        mode='lines',
        line=dict(shape='hv', width=3, color=step_color),
        name=label or f"Sounding {row_index}"
    ))
    # DOI
    fig.add_hline(
        y=doi, 
        line_dash="dash", 
        line_color=step_color,
        line_width=2,
        )

    fig.update_layout(
        yaxis=dict(title=y_title, range=y_range, autorange=False),
        xaxis=dict(type="log", title="Resistivity (Ohm-m)", minor=dict(showgrid=False, ticks="")),
        showlegend=True,
        legend=dict(
            yanchor="bottom",
            y=0.02,             # Slightly above the bottom axis
            xanchor="left",
            x=0.02,             # Slightly to the right of the left axis
            bgcolor="rgba(255, 255, 255, 0.7)", # Semi-transparent white
            bordercolor="Black",
            borderwidth=1
        ),
        margin=dict(l=60, r=20, t=30, b=50)
    )
    return fig

def build_combined_step_figure(df, indices,use_elevation=True):
    fig = go.Figure()
    
    standard_colors = [c for c in px.colors.qualitative.Plotly if c.lower() != '#ef553b'] # #ef553b is Plotly Red
    colors = ['red'] + standard_colors

    for count, idx in enumerate(indices):
        try:
            # Convert idx to match the column type (usually int for site_id)
            search_val = int(idx) if str(idx).isdigit() else idx
            
            # Find the row where site_id matches our clicked index
            mask = df['site_id'] == search_val
            if mask.any():
                row = df[mask].iloc[0]
            else:
                print(f"Warning: Site ID {search_val} not found in current dataframe.")
                continue
        except Exception as e:
            print(f"Error locating Site {idx}: {e}")
            continue

        elev_val = row.get('elevation') if use_elevation else None

        chosen_color = colors[count % len(colors)]
        
        if elev_val is not None:
            one = generate_res_step_graph_elev(row, idx, elevation=elev_val, step_color=chosen_color)
        else:
            one = generate_res_step_graph(row, idx, step_color=chosen_color)

        for tr in one.data:
            if tr.name == "DOI":
                tr.showlegend = False
            else:
                tr.name = f"{idx}"
                tr.showlegend = True
            fig.add_trace(tr)
        if one.layout.shapes:
            for shape in one.layout.shapes:
                fig.add_shape(shape)

    fig.update_layout(
        # title="Combined step plots",
        legend_title="Station",
        xaxis=dict(title="Resistivity (Ohm-m)", type="log", 
                    gridcolor='lightgray',        
                    linecolor='black',
                    linewidth=1,
                    mirror = True,
                    dtick=1, 
                    minor = dict(showgrid=True, ticks=""),
                    range=[0,3]),
        yaxis=dict(title="Depth (m)", gridcolor='lightgray',
                   linecolor ='black',
                   linewidth = 1, 
                   mirror = True,
                   ),
                showlegend=True,
        legend=dict(
            yanchor="bottom",
            y=0.02,             # Slightly above the bottom axis
            xanchor="left",
            x=0.02,             # Slightly to the right of the left axis
            bgcolor="rgba(255, 255, 255, 0.7)", # Semi-transparent white
            bordercolor="Black",
            borderwidth=1),
        template="plotly_white",
        margin=dict(l=40, r=20, t=40, b=40),
        clickmode="event+select"

    )
    return fig

# ---------- inversion vs real data plot -------------

def generate_dbdt_graph(dbdt_df, site_id):
    target_site = int(site_id) 

    site_data = dbdt_df[dbdt_df['site_id'] == target_site].dropna(subset=['dbdt', 'time'])
    
    if site_data.empty:
        return go.Figure().add_annotation(text=f"No data for Site {target_site}", showarrow=False)

    d_obs = site_data.dbdt.values
    d_err = site_data.error.values
    time = site_data.time.values
    
    d_syn = site_data['dbdt_syn'].values 
    
    e = d_err / 100
    err_plus  = d_obs * e
    err_minus = d_obs * e / (1 + e)

    fig = go.Figure()

    # Trace 1: Model/Forward
    fig.add_trace(go.Scatter(
        x=time, y=d_syn,
        mode="lines",
        line=dict(color="#EF553B"), 
        name="Model Response"
    ))

    # Trace 2: Observed Markers
    fig.add_trace(go.Scatter(
        x=time, y=d_obs,
        # mode="markers",
        mode="lines+markers",
        name="Observed dB/dt",
        marker=dict(color="black", size=6),
        line=dict(color="black", width=1, dash='dash'),
        error_y=dict(type="data", array=err_plus, arrayminus=err_minus, visible=True, thickness=1, width=0)
    ))


    fig.update_layout(
        xaxis=dict(title="Time (s)", type="log", gridcolor='lightgray',
            linecolor='black',      # Color of the axis line
            linewidth=1,            # Thickness of the border
            mirror=True,            # Adds the line to the top as well, creating a box
            dtick=1,                # Ensures minor gridlines/labels are hidden
            minor=dict(showgrid=True, ticks=""),
            range=[-5.1, -2.3]            # LOG LIMITS: 10^0 to 10^4 (i.e., 1 to 10,000 Ohm-m) change this to [0, 3] for 1 to 1,000 Ohm-m
        ),
        yaxis=dict(title="dB/dt [V / m²]",  type="log", gridcolor='lightgray',
            linecolor='black',
            linewidth=1,
            mirror=True,
            dtick=1,
            minor=dict(showgrid=True, ticks=""),),
        legend=dict(
            yanchor="top",
            y=0.98,        # Slightly offset from the very top border
            xanchor="right",
            x=0.98,        # Slightly offset from the very right border
            bgcolor="rgba(255, 255, 255, 0.5)", # Semi-transparent background
            bordercolor="Black",
            borderwidth=1
        ),
        template="plotly_white",
        margin=dict(l=50, r=40, t=50, b=50), # Slightly more margin for labels
        plot_bgcolor='white'
    )
    
    return fig

def build_combined_dbdt_figure(dbdt_df, indices):
    fig = go.Figure()
    
    # 1. Define custom color list (Red first, then standard palette)
    standard_colors = [c for c in px.colors.qualitative.Plotly if c.lower() != '#ef553b']
    colors = ['red'] + standard_colors
    
    for count, idx in enumerate(indices):
        # Filter for the specific site
        target_site = int(idx)
        site_data = dbdt_df[dbdt_df['site_id'] == target_site].dropna(subset=['dbdt', 'time'])
        
        if site_data.empty:
            continue

        chosen_color = colors[count % len(colors)]
        
        time = site_data['time'].values
        d_obs = site_data['dbdt'].values
        d_syn = site_data['dbdt_syn'].values if 'dbdt_syn' in site_data.columns else None
        
        # Error calculation
        e = site_data['error'].values / 100
        err_plus = d_obs * e
        err_minus = d_obs * e / (1 + e)

        # Trace 1: Model Response (Line)
        if d_syn is not None:
            fig.add_trace(go.Scatter(
                x=time, y=d_syn,
                mode="lines",
                line=dict(color=chosen_color, width=2),
                name=f"Model {idx}",
                legendgroup=f"group{idx}",
                showlegend=True
            ))

        # Trace 2: Observed Data (Markers)
        fig.add_trace(go.Scatter(
            x=time, y=d_obs,
            # mode="markers",
            mode="lines+markers",
            marker=dict(color=chosen_color, size=5, symbol='circle-open'),
            line=dict(color=chosen_color, width=1, dash='dash'),
            name=f"Observed {idx}",
            legendgroup=f"group{idx}",
            showlegend=False, # Hide from legend to prevent clutter
            error_y=dict(type="data", array=err_plus, arrayminus=err_minus, 
                         visible=True, thickness=0.8, width=0)
        ))

    # 2. Layout Logic (Log-Log)
    fig.update_layout(
        xaxis=dict(
            title="Time (s)", type="log", gridcolor='lightgray',
            linecolor='black', linewidth=1, mirror=True,
            range=[-5.1, -2.3]
        ),
        yaxis=dict(
            title="dB/dt [V / m²]", type="log", gridcolor='lightgray',
            linecolor='black', linewidth=1, mirror=True
        ),
        legend=dict(
            yanchor="top", y=0.98,
            xanchor="right", x=0.98,
            bgcolor="rgba(255, 255, 255, 0.7)",
            bordercolor="Black", borderwidth=1,
            title="Stations"
        ),
        template="plotly_white",
        margin=dict(l=50, r=40, t=50, b=50),
        plot_bgcolor='white'
    )
    
    return fig

# ------------------- draggable_window -------------------
def create_draggable_window(win_id, title, content, width="400px",height="700px"):
    if hasattr(content, 'layout'):
        body = dcc.Graph(
            figure=content, 
            style={"height": "100%", "width": "100%"}, 
            config={'responsive': True, 'displayModeBar': True}
        )
    else:
        body = content

    return html.Div(
        id=win_id, 
        className="draggable-window",
        style={
            "position": "fixed", "top": "150px", "left": "200px",
            "width": width, "height": height, "backgroundColor": "white",
            "border": "2px solid #333", "zIndex": 1000, "resize": "both", 
            "overflow": "hidden", "display": "flex", "flexDirection": "column",
            "boxShadow": "8px 8px 20px rgba(0,0,0,0.4)"
        },
        children=[
            html.Div([
                html.Span(title, style={"fontWeight": "bold", "marginLeft": "10px"}),
                # This button uses a DICTIONARY index
                html.Button("✕", id={"type": "close-window", "index": win_id}, 
                           style={"float": "right", "cursor": "pointer", "color": "white", "border":"none", "background":"none"})], 
            className="window-header", 
            style={"background": "#2c3e50", "color": "white", "padding": "5px", "height": "30px", "cursor": "move"}),
            
            html.Div(body, style={"flex": "1 1 auto", "minHeight": "0", "width": "100%"}),
        ]
    )
