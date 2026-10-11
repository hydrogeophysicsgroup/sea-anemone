"""
QC report generator: assembles a .docx covering the same figures/structure
as the reference PDF report shared for this feature -- survey overview,
enabled/disabled, data residual (misfit), and DOI maps, followed by a
per-drawn-line resistivity profile appendix and a per-depth-band mean
resistivity map appendix.

Every figure here is produced by the exact same Map/ModelSection render()
methods the live GUI uses (just with different settings), rather than any
separate plotting code, so the report always looks like what's on screen
(model_section colors etc.) modulo the few report-specific overrides below
(dot size, zoom, disabled-overlay/lines visibility) that don't apply on
screen.

Figures are rasterized to PNG via kaleido, but NOT one at a time --
generate_report() collects every figure for the whole report first (each
behind a placeholder paragraph already in the right place in the
document), then exports all of them in a single plotly.io.write_images()
batch call at the end (see _flush_pending_images). Kaleido v1 pays a
real, fixed per-call startup cost for spinning up its browser session;
paying that once for the whole report instead of once per figure (a
report can easily have 30-40 map figures, each also loading live
satellite tiles) was close to a 5x speedup in local testing.
"""
import asyncio
import io
import math
import os
import shutil
import tempfile
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Report figures are exported at a fixed resolution/marker size rather than
# whatever's currently live on screen -- the live markersize is tuned for
# an interactive map that could be rendered at almost any pixel footprint,
# but a report figure is always ~6in wide on the page, and reusing the
# on-screen size (default 14) made dots look oversized once shrunk into a
# print figure. Zoom-fit math below is aspect-ratio-aware against these
# same dimensions.
REPORT_MARKERSIZE = 8
REPORT_IMG_WIDTH = 1200
REPORT_IMG_HEIGHT = 800
# 1200px wide already gives 200 DPI at the 6in width _add_figure/
# _queue_figure embed images at -- comfortably print-quality. scale=2
# (400 DPI) also makes kaleido/MapLibre fetch higher-resolution basemap
# tiles over the network for every map figure, which measurably slowed
# report generation for no visible benefit at normal viewing/printing
# sizes; dropping to 1 cut a 16-figure synthetic report from 88s to 61s
# and roughly a third of the .docx file size, on top of the batched-
# export speedup from _flush_pending_images.
REPORT_IMG_SCALE = 1

# Model Section's resistivity-profile figures (Appendix A's "b" images)
# aren't maps and don't share the map's aspect ratio -- a transect is wide
# and comparatively short, so reusing REPORT_IMG_HEIGHT made them far
# taller than needed. Sized here for a printed 15.24 x 6.45 cm image at
# the same REPORT_IMG_WIDTH (15.24cm = 6in exactly, the width _add_figure
# embeds at by default).
PROFILE_IMG_WIDTH = REPORT_IMG_WIDTH
PROFILE_IMG_HEIGHT = round(REPORT_IMG_WIDTH * 6.45 / 15.24)

# Map.render() itself sets margin={"l":0,"r":0,"t":0,"b":0} -- fine for the
# live GUI, which has no tick labels to make room for, but the top/left
# tick-label annotations _add_map_decorations places outside the [0,1]
# plot area (above the top edge, left of the left edge) get clipped by the
# canvas boundary with zero margin, since there's no reserved space for
# them. MAP_MARGIN is applied on top of the map's own render() (see
# _add_map_decorations), and MAP_PLOT_WIDTH/HEIGHT (the plot area actually
# available for the map itself, canvas size minus margins) are what the
# zoom-fit and viewport math need to use -- MapLibre's zoom/pan is
# relative to the plot area, not the full canvas, so using the full
# canvas size there once margins are non-zero would make the "requested"
# framing drift from what actually renders.
#
# The scale bar is NOT in this margin -- it's drawn directly on the
# basemap, inside the plot area (see SCALE_ZONE_FRAC/BOTTOM_RESERVE_FRAC
# below), the same way a printed/GIS map's scale bar normally sits on top
# of the map image itself. b only needs to be big enough for the misfit/
# doi/mean-res colorbar (map.py, not here) on the figures that have one --
# there are still two margins/plot sizes (one with, one without) for the
# same reason as before: reusing the same view (center/zoom) across
# figures with different plot heights would make the same "fit" render a
# different effective viewport depending on plot_by/mean_res, risking
# cropped data. Every _fit_view()/_add_map_decorations() call takes an
# explicit has_colorbar flag and uses the matching margin/plot size
# throughout, so a view is only ever rendered at the plot size it was
# actually fitted for.
COLORBAR_MARGIN_PX = 60
MAP_MARGIN = dict(l=55, r=15, t=32, b=15)
MAP_MARGIN_COLORBAR = dict(l=55, r=15, t=32, b=COLORBAR_MARGIN_PX)
MAP_PLOT_WIDTH = REPORT_IMG_WIDTH - MAP_MARGIN['l'] - MAP_MARGIN['r']
MAP_PLOT_HEIGHT = REPORT_IMG_HEIGHT - MAP_MARGIN['t'] - MAP_MARGIN['b']
MAP_PLOT_HEIGHT_COLORBAR = REPORT_IMG_HEIGHT - MAP_MARGIN_COLORBAR['t'] - MAP_MARGIN_COLORBAR['b']

# SCALE_ZONE_FRAC: the bottom slice of the PLOT itself (paper y in
# [0, SCALE_ZONE_FRAC]) reserved for drawing the scale-bar cluster
# (backing panel + bar + ticks + label) directly on the basemap.
# BOTTOM_RESERVE_FRAC: how much extra room _fit_view() carves out on the
# south side only (on top of its normal symmetric padding) when fitting
# the data's bounding box, so the data itself never extends into that
# bottom slice -- see _zoom_and_center_for_bounds. Expressed as a fraction
# of the data's own north-south mercator span (same units as padding_frac)
# rather than a pixel/paper fraction directly, because the actual on-
# screen fraction it produces depends on which axis (lon or lat) ends up
# the binding zoom constraint; 0.25 was picked empirically (see
# test_map_decorations.py) to reserve roughly SCALE_ZONE_FRAC + some
# buffer even in the worst case (latitude-bound, i.e. no pre-existing
# slack on that axis to eat into).
SCALE_ZONE_FRAC = 0.14
BOTTOM_RESERVE_FRAC = 0.25

# The mean-res grid's default buffer (Map.grid_buffer_pixel=4, ~100m at the
# default grid_pixel_size=25m) is tuned for the live GUI's usual zoomed-in
# view -- at Appendix B's zoomed-out, whole-survey framing, that buffer is
# imperceptibly small. Report figures use a much larger one instead so the
# colored patches are actually visible on the page.
REPORT_GRID_BUFFER_PIXEL = 8

_COMPASS_DIRS = ['North', 'North-East', 'East', 'South-East', 'South', 'South-West', 'West', 'North-West']
_COMPASS_OPPOSITE = {
    'North': 'South', 'South': 'North', 'East': 'West', 'West': 'East',
    'North-East': 'South-West', 'South-West': 'North-East',
    'North-West': 'South-East', 'South-East': 'North-West',
}

# Polled by app.py's report-progress-poll Interval while generate_report()
# runs (same pattern as sesh.inv_status/inv-log-poll for the inversion
# progress log -- generate_report() itself runs synchronously inside the
# button-click callback and just blocks that one Flask worker thread; the
# Interval's own callback is served by a different thread, so it can read
# this dict live). Not thread-safe against overlapping report generations,
# but only one can ever be in flight (the button disables itself while
# running).
REPORT_PROGRESS = {'current': 0, 'total': 0, 'label': '', 'done': True, 'error': None}

# _flush_pending_images renders in chunks rather than one pio.write_images()
# call for the whole report, so REPORT_PROGRESS can advance visibly instead
# of jumping straight from 0 to done -- purely for progress-bar granularity.
# Smaller chunks give smoother progress but pay kaleido's per-call browser
# startup cost more often (see the module docstring/REPORT_IMG_SCALE
# comment for why that cost matters). Measured on a real 43-figure report:
# chunk size 6 (8 chunks) added ~2 minutes over the unchunked baseline --
# real map figures each fetch their own basemap tiles over the network, so
# the per-chunk cost is much higher than the plain-figure kaleido benchmark
# this was first tuned against. 15 keeps a real, if coarser, progress bar
# (updates roughly 3 times over a 43-figure report) while giving most of
# the batching speedup back.
FLUSH_CHUNK_SIZE = 15


def _queue_figure(doc, pending, fig, caption, width_in=6.0, width_px=REPORT_IMG_WIDTH, height_px=REPORT_IMG_HEIGHT, scale=REPORT_IMG_SCALE):
    """
    Adds the caption and a blank centered placeholder paragraph for `fig`
    at the correct position in the document, and queues fig for later
    batch export -- see _flush_pending_images, called once at the end of
    generate_report() to actually render every queued figure to PNG in a
    single pio.write_images() call and drop each into its placeholder.
    """
    placeholder = doc.add_paragraph()
    placeholder.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cap.add_run(caption)
    run.italic = True
    run.font.size = Pt(9)
    pending.append(dict(fig=fig, paragraph=placeholder, width_px=width_px, height_px=height_px, scale=scale, width_in=width_in))


def _has_basemap(fig):
    """True for a map figure with raster background layers (the satellite tiles)."""
    try:
        return bool(fig.layout.map.layers)
    except AttributeError:
        return False


# Errors a kaleido render can end with. When one figure in a batch fails,
# kaleido cancels the rest and the call ends with asyncio.CancelledError,
# which is NOT a subclass of Exception (it derives from BaseException), so
# a plain `except Exception` lets it crash the whole report.
RENDER_ERRORS = (Exception, asyncio.CancelledError)


def figure_to_png(fig, width, height, scale=1, retries=2):
    """
    PNG bytes for one figure, robust to basemap download failures.

    Map figures fetch their satellite background tiles over the internet
    while kaleido renders them; a single tile that fails or times out makes
    plotly.js abort the whole image ("Error 525: Map error."). So try a
    few times, and if it still fails, render without the satellite
    background rather than not at all.

    Returns (png_bytes, basemap_dropped).
    """
    last_error = None
    for _ in range(retries + 1):
        try:
            return pio.to_image(fig, format='png', width=width, height=height, scale=scale), False
        except RENDER_ERRORS as e:
            last_error = e
            print(f'[export] image render failed, retrying: {e}')
    if _has_basemap(fig):
        no_basemap = go.Figure(fig)
        # Direct assignment: update_layout(map_layers=[]) leaves existing layers in place.
        no_basemap.layout.map.layers = []
        print('[export] rendering without the satellite background')
        return pio.to_image(no_basemap, format='png', width=width, height=height, scale=scale), True
    raise last_error


def _flush_pending_images(pending):
    """
    Batch-export every queued figure in chunks of FLUSH_CHUNK_SIZE (see
    module docstring for why batching at all; chunking trades a little of
    that speedup for a REPORT_PROGRESS update after each chunk), then
    insert each into its placeholder paragraph.

    If a batch fails (usually one map whose satellite tiles didn't
    download), that chunk is rendered figure by figure via figure_to_png,
    so one bad tile doesn't sink the whole report. Returns the number of
    maps that had to be rendered without their satellite background.
    """
    if not pending:
        return 0
    tmpdir = tempfile.mkdtemp(prefix='sea_anemone_report_')
    basemaps_dropped = 0
    try:
        total = len(pending)
        REPORT_PROGRESS['total'] = total
        for start in range(0, total, FLUSH_CHUNK_SIZE):
            chunk = pending[start:start + FLUSH_CHUNK_SIZE]
            files = [os.path.join(tmpdir, f"fig_{start + i}.png") for i in range(len(chunk))]
            try:
                pio.write_images(
                    [p['fig'] for p in chunk], files, format='png',
                    width=[p['width_px'] for p in chunk],
                    height=[p['height_px'] for p in chunk],
                    scale=[p['scale'] for p in chunk],
                )
            except RENDER_ERRORS as e:
                print(f'[report] batch render failed ({e!r}); rendering this chunk one figure at a time')
                for p, path in zip(chunk, files):
                    png, dropped = figure_to_png(p['fig'], p['width_px'], p['height_px'], p['scale'])
                    basemaps_dropped += dropped
                    with open(path, 'wb') as f:
                        f.write(png)
            for p, path in zip(chunk, files):
                run = p['paragraph'].add_run()
                run.add_picture(path, width=Inches(p['width_in']))
            REPORT_PROGRESS['current'] = start + len(chunk)
            REPORT_PROGRESS['label'] = f"Rendering figure {REPORT_PROGRESS['current']}/{total}..."
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return basemaps_dropped


# MapLibre GL (which go.Scattermap/Choroplethmap render through, like
# Mapbox GL) defines zoom level 0 as the whole world fitting in a single
# 512px tile -- the classic web-tile convention (Leaflet/OSM/Google Static
# Maps) uses 256 instead. Every zoom/pixel/geo conversion below (fitting
# bounds, computing the actual rendered viewport, the scale bar) has to
# agree on this or they drift out of sync with each other and with what
# actually gets rendered.
MAPLIBRE_TILE_SIZE = 512
EARTH_CIRCUMFERENCE_M = 40_075_016.686


def _merc_y(lat):
    lat = max(min(lat, 89.9), -89.9)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _merc_y_inv(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def _zoom_and_center_for_bounds(lat0, lat1, lon0, lon1, img_width=MAP_PLOT_WIDTH, img_height=MAP_PLOT_HEIGHT, padding_frac=0.08, bottom_reserve_frac=0.0):
    """
    Web-mercator zoom-to-fit AND center for a lat/lon bounding box,
    accounting for the export image's own aspect ratio and for Mercator's
    latitude distortion (a naive equirectangular "degrees span" estimate
    gets the wrong zoom for anything away from the equator). Returns
    (zoom, center_lat, center_lon).

    padding_frac adds a symmetric margin around the data extent on every
    side (0.08 = 8%). bottom_reserve_frac adds EXTRA room on the south
    side only, on top of that -- both are expressed as a fraction of the
    data's own (unpadded) north-south mercator span. Since zoom = min(
    zoom_lon, zoom_lat), asymmetric south padding can't change the zoom
    level at all when longitude is the binding constraint (there's
    already slack on the latitude axis to absorb it into, which just
    shifts the returned center north instead) -- but when latitude IS the
    binding constraint, it forces a very slightly wider (more zoomed out)
    fit so the reserve is still guaranteed. Either way the result is a
    view whose southern edge always has that extra clear strip, which is
    what lets _add_map_decorations draw the scale bar directly on the
    basemap there (SCALE_ZONE_FRAC) instead of in a separate margin.
    """
    lon_diff = max(abs(lon1 - lon0), 1e-6) * (1 + 2 * padding_frac)

    merc0, merc1 = _merc_y(lat0), _merc_y(lat1)
    merc_diff_data = max(merc1 - merc0, 1e-6)
    merc_top = merc1 + padding_frac * merc_diff_data
    merc_bottom = merc0 - (padding_frac + bottom_reserve_frac) * merc_diff_data
    merc_diff = merc_top - merc_bottom

    zoom_lon = math.log2(img_width * 360.0 / (lon_diff * MAPLIBRE_TILE_SIZE))
    zoom_lat = math.log2(img_height * 2 * math.pi / (merc_diff * MAPLIBRE_TILE_SIZE))
    zoom = float(np.clip(min(zoom_lon, zoom_lat), 2, 18))

    center_lat = _merc_y_inv((merc_top + merc_bottom) / 2)
    center_lon = (lon0 + lon1) / 2
    return zoom, center_lat, center_lon


def _viewport_bounds(view, img_width=MAP_PLOT_WIDTH, img_height=MAP_PLOT_HEIGHT):
    """
    The ACTUAL lat/lon extent a rendered map covers for a given
    {'map.center', 'map.zoom'} view dict and export image size -- NOT the
    same as the raw data bounding box _fit_view() was computed from, since
    whichever axis wasn't the tighter constraint in _zoom_and_center_for_bounds
    ends up showing more area than that box (that's the "extra slack" that
    made zoom-fit padding only affect one axis in practice). Needed to
    place tick labels/scale bar/north arrow against what's really on
    screen rather than the pre-padding data extent.
    """
    zoom = view['map.zoom']
    clat, clon = view['map.center']['lat'], view['map.center']['lon']
    world_px = MAPLIBRE_TILE_SIZE * 2 ** zoom
    lon_per_px = 360.0 / world_px
    merc_per_px = (2 * math.pi) / world_px
    lon0 = clon - (img_width / 2) * lon_per_px
    lon1 = clon + (img_width / 2) * lon_per_px
    cy = _merc_y(clat)
    lat0 = _merc_y_inv(cy - (img_height / 2) * merc_per_px)
    lat1 = _merc_y_inv(cy + (img_height / 2) * merc_per_px)
    return lat0, lat1, lon0, lon1


def _nice_scale_length_m(target_m):
    """Round a target scale-bar length to a conventional 1/2/5-per-decade value."""
    if target_m <= 0:
        return 100.0
    magnitude = 10 ** math.floor(math.log10(target_m))
    for mult in (1, 2, 5, 10):
        candidate = mult * magnitude
        if candidate >= target_m:
            return float(candidate)
    return float(10 * magnitude)


def _add_map_decorations(fig, view, img_width=MAP_PLOT_WIDTH, img_height=None, n_xticks=8, n_yticks=5, has_colorbar=False):
    """
    North arrow, scale bar, and UTM easting/northing tick labels along the
    top/left edges. Plotly's Mapbox/MapLibre-based map traces have none of
    this natively (no axis-tick frame, no built-in map furniture) -- all
    three are hand-drawn as plain paper-coordinate annotations/shapes
    positioned from the actual rendered viewport (_viewport_bounds), which
    always matches the current view exactly since these figures are static
    kaleido exports, not an interactive map a user could have since panned.

    Applies MAP_MARGIN (or MAP_MARGIN_COLORBAR, if has_colorbar) on top of
    Map.render()'s own zero margins -- the top/left tick labels sit
    outside the [0,1] plot area (above y=1, left of x=0), which needs real
    reserved canvas space or they get clipped at the image boundary.
    has_colorbar reserves room in that bottom margin for the misfit/doi/
    mean-res colorbar (added by map.py, not here) -- the caller
    (_render_map) must pass has_colorbar=True exactly when the figure it
    built actually has one, and the view passed in must have been fitted
    (_fit_view) with the same has_colorbar value, or the framing won't
    match the plot size actually used here.

    The scale bar, unlike the ticks, is drawn INSIDE the plot area (paper
    y in [0, SCALE_ZONE_FRAC]), directly on the basemap, the same way a
    printed/GIS map's scale bar normally sits on top of the map image --
    not in a separate blank margin below it. That's safe from overlapping
    actual data because the view was fitted with BOTTOM_RESERVE_FRAC
    (_fit_view -> _zoom_and_center_for_bounds), which keeps that bottom
    slice of the rendered map clear of data in the first place.
    """
    if view is None:
        return fig
    import utm

    margin = MAP_MARGIN_COLORBAR if has_colorbar else MAP_MARGIN
    if img_height is None:
        img_height = MAP_PLOT_HEIGHT_COLORBAR if has_colorbar else MAP_PLOT_HEIGHT
    fig.update_layout(margin=margin)

    lat0, lat1, lon0, lon1 = _viewport_bounds(view, img_width, img_height)
    mean_lat = (lat0 + lat1) / 2
    mean_lon = (lon0 + lon1) / 2
    _, _, zone, letter = utm.from_latlon(mean_lat, mean_lon)

    # North arrow -- always straight up, since this app never rotates the
    # map (Map.paper2latlon/latlon2paper explicitly require bearing=0).
    fig.add_annotation(
        text="N<br>&#9650;", x=0.97, y=0.95, xref='paper', yref='paper',
        showarrow=False, align='center', font=dict(size=20, color='black'),
        bgcolor='rgba(255,255,255,0.75)', borderpad=5,
    )

    # Scale bar: a round-number ground distance close to 25% of the
    # viewport's east-west span at its mean latitude. Positioned inside
    # the plot's own bottom slice (paper y in [0, SCALE_ZONE_FRAC]) --
    # see the docstring above for why that's safe from overlapping data.
    x0_utm, _, _, _ = utm.from_latlon(mean_lat, lon0, force_zone_number=zone, force_zone_letter=letter)
    x1_utm, _, _, _ = utm.from_latlon(mean_lat, lon1, force_zone_number=zone, force_zone_letter=letter)
    span_m = max(abs(x1_utm - x0_utm), 1.0)
    bar_m = _nice_scale_length_m(span_m * 0.25)
    bar_frac = min(bar_m / span_m, 0.4)
    x_end = 0.95
    x_start = x_end - bar_frac

    # Fractions within the reserved zone (0 = right at the data boundary,
    # 1 = right at the image's bottom edge) mirrored into paper-y, so
    # f=0.08 (near the data boundary) lands close to SCALE_ZONE_FRAC and
    # f=0.95 (near the image edge) lands close to 0.
    def in_zone(f):
        return SCALE_ZONE_FRAC * (1 - f)

    panel_y_top = in_zone(0.08)
    y_bar = in_zone(0.35)
    y_label = in_zone(0.72)
    panel_y_bottom = in_zone(0.85) #0.95
    tick_half = SCALE_ZONE_FRAC * 0.08

    # Backing panel, added first (so it renders behind the bar/ticks/
    # label added after it) -- the plain black bar/text had no contrast
    # boost of their own, so they could disappear against a dark patch of
    # basemap or resistivity color.
    fig.add_shape(type='rect', x0=x_start - 0.015, x1=x_end + 0.015, y0=panel_y_bottom, y1=panel_y_top,
                  xref='paper', yref='paper', fillcolor='rgba(255,255,255,0.85)', line=dict(width=0))

    fig.add_shape(type='line', x0=x_start, x1=x_end, y0=y_bar, y1=y_bar,
                  xref='paper', yref='paper', line=dict(color='black', width=3))
    for x_tick in (x_start, x_end):
        fig.add_shape(type='line', x0=x_tick, x1=x_tick, y0=y_bar - tick_half, y1=y_bar + tick_half,
                      xref='paper', yref='paper', line=dict(color='black', width=2))
    label = f"{bar_m / 1000:.1f} km" if bar_m >= 1000 else f"{bar_m:.0f} m"
    fig.add_annotation(x=(x_start + x_end) / 2, y=y_label, xref='paper', yref='paper',
                       xanchor='center', text=label, showarrow=False, font=dict(size=12, color='black'))

    # X ticks (Easting), along the TOP edge -- Mercator's X is linear in
    # longitude, so evenly spaced longitudes give evenly spaced screen
    # positions. Labeled with UTM easting at the viewport's mean latitude.
    for i in range(n_xticks):
        frac = i / (n_xticks - 1)
        lon = lon0 + frac * (lon1 - lon0)
        easting, _, _, _ = utm.from_latlon(mean_lat, lon, force_zone_number=zone, force_zone_letter=letter)
        fig.add_annotation(x=frac, y=1.0, xref='paper', yref='paper', yanchor='bottom', yshift=4,
                           text=f"{easting:.0f}", showarrow=False, font=dict(size=12, color='black'),
                           bgcolor='rgba(255,255,255,0.6)')

    # Y ticks (Northing), along the LEFT edge -- evenly spaced in
    # MERCATOR Y, not raw latitude (Mercator Y is a nonlinear function of
    # latitude -- equal-latitude steps are NOT equally spaced on screen).
    # Labeled with UTM northing at the viewport's mean longitude.
    y0m, y1m = _merc_y(lat0), _merc_y(lat1)
    for i in range(n_yticks):
        frac = i / (n_yticks - 1)
        lat = _merc_y_inv(y0m + frac * (y1m - y0m))
        _, northing, _, _ = utm.from_latlon(lat, mean_lon, force_zone_number=zone, force_zone_letter=letter)
        fig.add_annotation(x=0.0, y=frac, xref='paper', yref='paper', xanchor='right', xshift=-4,
                           text=f"{northing:.0f}", showarrow=False, font=dict(size=12, color='black'),
                           bgcolor='rgba(255,255,255,0.6)', textangle=-90)

    return fig


def _fit_view(lat, lon, has_colorbar=False, zoom_offset=0.0):
    """
    A settings.view dict ({'map.center', 'map.zoom'}) that fits the given
    lat/lon points, with 8% padding plus BOTTOM_RESERVE_FRAC extra room on
    the south side for the scale bar (see _zoom_and_center_for_bounds).
    has_colorbar must match whatever is later passed to
    _add_map_decorations() for the figure(s) this view is used on -- the
    two margins have different plot heights, and a zoom fitted for one
    would show a different (potentially cropped) vertical extent than
    intended if rendered at the other's plot size.

    zoom_offset (the report setting "Map zoom") is added on top of the
    fitted zoom: 0 = fit to the data, positive zooms in, negative zooms
    out. The decorations follow automatically since they're computed from
    the final view.
    """
    lat0, lat1 = lat.min(), lat.max()
    lon0, lon1 = lon.min(), lon.max()
    img_height = MAP_PLOT_HEIGHT_COLORBAR if has_colorbar else MAP_PLOT_HEIGHT
    zoom, center_lat, center_lon = _zoom_and_center_for_bounds(
        lat0, lat1, lon0, lon1, img_height=img_height, bottom_reserve_frac=BOTTOM_RESERVE_FRAC,
    )
    return {
        'map.center': {'lat': center_lat, 'lon': center_lon},
        'map.zoom': float(np.clip(zoom + (zoom_offset or 0.0), 1, 20)),
    }


def _direction_label(line_df):
    """
    'West to East'-style label for a drawn line, from its first to its
    last node (line_df sorted by the 'node' column). Longitude delta is
    scaled by cos(mean latitude) since a degree of longitude covers less
    ground the further from the equator -- otherwise a mostly-N-S line at
    high latitude could get misclassified as E-W.
    """
    line_df = line_df.sort_values('node')
    lat0, lon0 = line_df['latitude'].iloc[0], line_df['longitude'].iloc[0]
    lat1, lon1 = line_df['latitude'].iloc[-1], line_df['longitude'].iloc[-1]
    dlat = lat1 - lat0
    dlon = (lon1 - lon0) * math.cos(math.radians((lat0 + lat1) / 2))
    angle = math.degrees(math.atan2(dlon, dlat)) % 360
    end_dir = _COMPASS_DIRS[int((angle + 22.5) // 45) % 8]
    return f"{_COMPASS_OPPOSITE[end_dir]} to {end_dir}"


def _map_has_colorbar(m1):
    """True when m1's current settings will draw the misfit/doi/date coloraxis colorbar, or the mean-res colorbar (map.py, not here)."""
    return m1.settings.plot_by in ('misfit', 'doi', 'date') or m1.settings.mean_res != -1


def _render_map(m1):
    """
    m1.render() plus the north arrow/scale bar/tick decorations, against
    whatever view is currently set. has_colorbar is derived straight from
    m1.settings so callers can't forget to pass it -- but the view itself
    (m1.settings.view) must still have been fitted with the matching
    has_colorbar via _fit_view(), or the framing won't match what's
    rendered here.
    """
    has_colorbar = _map_has_colorbar(m1)
    return _add_map_decorations(m1.render(), m1.settings.view, has_colorbar=has_colorbar)


# Everything the report can contain, in report order -- the 3D view and the
# line profiles come first, then the QC maps, then the mean-res maps. The
# Report panel (report_panel.py) shows these as checkboxes.
REPORT_SECTIONS = [
    ('model_3d', '3D model view'),
    ('lines', 'Line profiles'),
    ('overview', 'Survey overview'),
    ('enabled_disabled', 'Enabled/disabled sites'),
    ('misfit', 'Data residual (misfit)'),
    ('doi', 'Depth of investigation'),
    ('mean_res', 'Mean resistivity maps'),
]
_QC_SECTIONS = ('overview', 'enabled_disabled', 'misfit', 'doi')

REPORT_DEFAULTS = {
    'sections': [key for key, _ in REPORT_SECTIONS],
    'markersize': REPORT_MARKERSIZE,
    # Added to each map's fitted zoom: 0 = fit to the data, positive zooms
    # in, negative zooms out.
    'zoom_offset': 0.0,
    # How far the mean-res colour extends around each site, in metres --
    # REPORT_GRID_BUFFER_PIXEL cells of Map.grid_pixel_size (25 m).
    'mean_res_radius_m': REPORT_GRID_BUFFER_PIXEL * 25,
}

MODEL_3D_IMG_WIDTH = REPORT_IMG_WIDTH
MODEL_3D_IMG_HEIGHT = 700


def report_options(options=None):
    """
    REPORT_DEFAULTS overlaid with whatever (possibly partial) options the
    Report panel passed in. The panel's number boxes have no browser-side
    limits (those turned typed values into None), so values are parsed
    and clamped here instead; anything unparseable falls back to the
    default.
    """
    merged = dict(REPORT_DEFAULTS)
    for key, value in (options or {}).items():
        if value is not None and key in merged:
            merged[key] = value

    def number(key, lo, hi):
        try:
            value = float(merged[key])
        except (TypeError, ValueError):
            value = float(REPORT_DEFAULTS[key])
        if not math.isfinite(value):
            value = float(REPORT_DEFAULTS[key])
        return min(max(value, lo), hi)

    merged['markersize'] = int(round(number('markersize', 1, 60)))
    merged['zoom_offset'] = number('zoom_offset', -10, 10)
    merged['mean_res_radius_m'] = number('mean_res_radius_m', 1, 5000)
    return merged


def build_report_items(options=None, camera=None):
    """
    Everything the report contains, in order, as a list of dicts:
      {'kind': 'heading',   'text', 'level'}
      {'kind': 'paragraph', 'text'}
      {'kind': 'figure',    'fig', 'caption', 'width_px', 'height_px'}
    Shared by generate_report() (which writes them into a .docx) and the
    Report panel's preview, so the preview is exactly what the report
    will contain.

    Temporarily reassigns the live Map/ModelSection/Model3D panels'
    settings to render each figure, then restores everything those panels
    had before this was called -- so building a report never disturbs
    what's currently on screen. The figures are self-contained go.Figure
    objects, so they stay valid after the restore.

    camera is the 3D view's scene.camera dict (from model_3d's
    relayoutData), so the report's 3D figure matches what's on screen.
    """
    from __main__ import sesh, m1, mod2, mod3d

    opts = report_options(options)
    # opts['sections'] is in the user's chosen report order.
    known = {key for key, _ in REPORT_SECTIONS}
    sections = [key for key in opts['sections'] if key in known]
    markersize = int(opts['markersize'])
    zoom_offset = float(opts['zoom_offset'])
    grid_buffer_pixel = max(1, int(round(float(opts['mean_res_radius_m']) / m1.grid_pixel_size)))

    orig_m1_settings = dict(
        plot_by=m1.settings.plot_by, mean_res=m1.settings.mean_res, view=m1.settings.view,
        markersize=m1.settings.markersize,
    )
    orig_m1 = dict(
        highlighted=m1.highlighted, buffer_sites=m1.buffer_sites, lines=m1.lines,
        suppress_highlight=m1.suppress_highlight, suppress_disabled_overlay=m1.suppress_disabled_overlay,
        grid_buffer_pixel=m1.grid_buffer_pixel, grid=getattr(m1, 'grid', None), _grid_key=getattr(m1, '_grid_key', None),
    )
    orig_mod2_settings = dict(x_axis=mod2.settings.x_axis, y_axis=mod2.settings.y_axis)
    orig_mod2 = dict(highlighted=mod2.highlighted, use_buffer=mod2.use_buffer)
    orig_mod3d = dict(highlighted=mod3d.highlighted, dataframe=mod3d.dataframe)

    items = []

    def heading(text, level):
        items.append(dict(kind='heading', text=text, level=level))

    def paragraph(text):
        items.append(dict(kind='paragraph', text=text))

    def figure(fig, caption, width_px=REPORT_IMG_WIDTH, height_px=REPORT_IMG_HEIGHT):
        items.append(dict(kind='figure', fig=fig, caption=caption, width_px=width_px, height_px=height_px))

    try:
        heading('QC Report', 0)

        overview_df = m1.dataframe
        if overview_df is not None and 'site_id' in overview_df.columns:
            overview_df = overview_df[overview_df['site_id'] != -1]
        n_sites = int(overview_df['site_id'].nunique()) if overview_df is not None else 0
        has_models = sesh.models is not None and not sesh.models.empty

        # 'gates_used' is the same site-level enabled/disabled flag Map.py's
        # disabled-overlay and the Enabled/Disabled figure use (0 = every
        # gate disabled, i.e. the site itself is disabled) -- summarized in
        # words here since the overview figure shows every site the same
        # color ("From Import"), not split by enabled/disabled.
        if overview_df is not None and 'gates_used' in overview_df.columns and n_sites:
            n_disabled = int((overview_df['gates_used'] == 0).sum())
            n_enabled = n_sites - n_disabled
            enabled_disabled_caption = f" Enabled {n_enabled} out of {n_sites} sites, Disabled {n_disabled} out of {n_sites} sites."
        else:
            enabled_disabled_caption = ""

        # Common report-figure state: fixed dot size, no leftover selection/
        # buffer/highlight from the live app, drawn lines and the disabled-
        # sites overlay both off by default -- each turned back on only for
        # the specific figures that actually need them.
        m1.suppress_highlight = True
        m1.suppress_disabled_overlay = True
        m1.highlighted = None
        m1.buffer_sites = None
        m1.lines = None
        m1.settings.markersize = markersize
        m1.settings.mean_res = -1

        # Two fitted views for the same overview bounding box: figures with
        # no colorbar use the taller plot area (overview_view); figures with
        # one (misfit/doi and every mean-res band) use the shorter one that
        # leaves room for it (overview_view_cb) -- see _fit_view/
        # _add_map_decorations' has_colorbar docstrings for why these can't
        # just share one view.
        has_bounds = overview_df is not None and not overview_df.empty
        overview_view = _fit_view(overview_df['latitude'], overview_df['longitude'], zoom_offset=zoom_offset) if has_bounds else None
        overview_view_cb = _fit_view(overview_df['latitude'], overview_df['longitude'], has_colorbar=True, zoom_offset=zoom_offset) if has_bounds else None

        # One chapter per section, in the user's chosen order. Each
        # add_* function adds its heading and figures and returns True, or
        # returns False without adding anything when its data is missing
        # (so chapter numbers stay consecutive).

        def add_model_3d(chapter):
            if not has_models:
                return False
            if mod3d.dataframe is None or mod3d.dataframe.empty:
                mod3d.dataframe = sesh.models.copy()
            heading(f'{chapter}. 3D Resistivity Model', 1)
            mod3d.highlighted = None
            fig3d = mod3d.render()
            if camera:
                fig3d.update_layout(scene_camera=camera)
            figure(fig3d, f"Figure {chapter}-1. 3D resistivity model.",
                   width_px=MODEL_3D_IMG_WIDTH, height_px=MODEL_3D_IMG_HEIGHT)
            return True

        def add_lines(chapter):
            # One location map + resistivity profile per drawn line.
            if sesh.lines is None or sesh.lines.empty or not has_models:
                print("[report] Line profiles skipped: no drawn lines or no inversion results.")
                return False
            print(f"[report] Line profiles: {sesh.lines['line'].nunique()} drawn line(s) found.")
            heading(f'{chapter}. Resistivity Profiles', 1)
            mod2.settings.y_axis = 'elevation'
            mod2.use_buffer = False
            mod2.highlighted = None
            # Enabled/disabled status, not the plain "From Import" view.
            m1.settings.plot_by = 'enabled_disabled'
            m1.suppress_disabled_overlay = False
            for line_id in sorted(sesh.lines['line'].unique()):
                try:
                    line_df = sesh.lines[sesh.lines['line'] == line_id]
                    # Only this one line, not every drawn line -- and only
                    # for these two figures (reset right after).
                    m1.lines = line_df
                    m1.settings.view = _fit_view(line_df['latitude'], line_df['longitude'], zoom_offset=zoom_offset)
                    direction = _direction_label(line_df)
                    map_fig = _render_map(m1)
                    mod2.settings.x_axis = f'line {line_id:.0f}'
                    profile_fig = mod2.render()
                    figure(map_fig, f"Figure {chapter}-{line_id:.0f}a. Location of line {line_id:.0f} ({direction}).")
                    figure(profile_fig, f"Figure {chapter}-{line_id:.0f}b. Resistivity profile for line {line_id:.0f} ({direction}).",
                           width_px=PROFILE_IMG_WIDTH, height_px=PROFILE_IMG_HEIGHT)
                except Exception as e:
                    # A line whose _line_N_x/_line_N_y projection columns
                    # aren't on sesh.models yet would otherwise crash
                    # ModelSection.render() and take the whole report down
                    # with it. Skip just this line instead.
                    print(f"[report] Line profiles: skipping line {line_id} due to error: {e}")
                    continue
                finally:
                    m1.lines = None
            m1.suppress_disabled_overlay = True
            return True

        def add_overview(chapter):
            if not has_bounds:
                return False
            heading(f'{chapter}. Study Area Overview', 1)
            paragraph(f"The survey collected a total of {n_sites} TEM sites.")
            m1.settings.view = overview_view
            m1.settings.plot_by = 'none'
            figure(_render_map(m1), f"Figure {chapter}-1. Overview of surveyed sites.{enabled_disabled_caption}")
            return True

        def add_enabled_disabled(chapter):
            if not has_bounds:
                return False
            heading(f'{chapter}. Model Locations', 1)
            m1.settings.view = overview_view
            m1.suppress_disabled_overlay = False
            m1.settings.plot_by = 'enabled_disabled'
            figure(_render_map(m1), f"Figure {chapter}-1. Enabled/disabled data locations.{enabled_disabled_caption}")
            m1.suppress_disabled_overlay = True
            return True

        def add_misfit(chapter):
            if not has_bounds:
                return False
            heading(f'{chapter}. Data Residual', 1)
            m1.settings.view = overview_view_cb
            m1.settings.plot_by = 'misfit'
            figure(_render_map(m1), f"Figure {chapter}-1. Data residual (misfit).")
            return True

        def add_doi(chapter):
            if not has_bounds:
                return False
            heading(f'{chapter}. Depth of Investigation', 1)
            m1.settings.view = overview_view_cb
            m1.settings.plot_by = 'doi'
            figure(_render_map(m1), f"Figure {chapter}-1. Depth of investigation.")
            return True

        def add_mean_res(chapter):
            if not (has_models and has_bounds):
                print("[report] Mean res maps skipped: no inversion results.")
                return False
            # Forces a grid rebuild with the report's radius -- _ensure_grid()
            # only rebuilds when this (or the site count) actually changes.
            # Done before picking depths, since which bands colour any pixel
            # depends on the grid (see Map.available_mean_res_depths).
            m1.grid_buffer_pixel = grid_buffer_pixel
            m1.grid = None
            depths = m1.available_mean_res_depths()
            print(f"[report] Mean res maps: {len(depths)} depth band(s) with data.")
            if not depths:
                return False
            heading(f'{chapter}. Mean Resistivity Depth Maps', 1)
            # Every band has the mean-res colorbar showing, so this always
            # uses the colorbar-fitted view.
            m1.settings.view = overview_view_cb
            # Enabled/disabled status, so a disabled site's mean-res value
            # isn't mistaken for a real one.
            m1.settings.plot_by = 'enabled_disabled'
            m1.suppress_disabled_overlay = False
            for fig_no, depth in enumerate(depths, start=1):
                try:
                    m1.settings.mean_res = depth
                    figure(_render_map(m1), f"Figure {chapter}-{fig_no}. Mean resistivity, {depth}–{depth + 10} m depth.")
                except Exception as e:
                    print(f"[report] Mean res maps: skipping {depth}-{depth + 10} m band due to error: {e}")
                    continue
            # Sections after this one must not inherit the mean-res layer.
            m1.settings.mean_res = -1
            m1.suppress_disabled_overlay = True
            return True

        section_builders = {
            'model_3d': add_model_3d,
            'lines': add_lines,
            'overview': add_overview,
            'enabled_disabled': add_enabled_disabled,
            'misfit': add_misfit,
            'doi': add_doi,
            'mean_res': add_mean_res,
        }
        chapter = 1
        for key in sections:
            if section_builders[key](chapter):
                chapter += 1

        if not any(item['kind'] == 'figure' for item in items):
            paragraph("Nothing to show: no report sections are selected, or there is no data for the selected ones yet.")
    finally:
        for key, value in orig_m1_settings.items():
            setattr(m1.settings, key, value)
        for key, value in orig_m1.items():
            setattr(m1, key, value)
        for key, value in orig_mod2_settings.items():
            setattr(mod2.settings, key, value)
        for key, value in orig_mod2.items():
            setattr(mod2, key, value)
        for key, value in orig_mod3d.items():
            setattr(mod3d, key, value)

    return items


def generate_report(save_path, options=None, camera=None):
    """
    Build the QC report at save_path (a .docx file path) from
    build_report_items(options, camera). Every figure is queued (see
    _queue_figure) and only actually rendered to PNG once, in batched
    calls, right before the document is saved (see _flush_pending_images).

    Returns the number of maps whose satellite background couldn't be
    downloaded and were rendered without it (0 normally).
    """
    REPORT_PROGRESS.update(current=0, total=0, label='Preparing figures...', done=False, error=None)
    try:
        items = build_report_items(options, camera)

        doc = Document()
        pending = []
        for item in items:
            if item['kind'] == 'heading':
                doc.add_heading(item['text'], level=item['level'])
            elif item['kind'] == 'paragraph':
                doc.add_paragraph(item['text'])
            else:
                _queue_figure(doc, pending, item['fig'], item['caption'],
                              width_px=item['width_px'], height_px=item['height_px'])

        print(f"[report] Rendering {len(pending)} figure(s)...")
        basemaps_dropped = _flush_pending_images(pending)

        doc.save(save_path)
        REPORT_PROGRESS['label'] = 'Done'
        return basemaps_dropped
    except Exception as e:
        REPORT_PROGRESS['error'] = str(e)
        raise
    finally:
        REPORT_PROGRESS['done'] = True
