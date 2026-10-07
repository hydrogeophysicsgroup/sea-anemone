import base64

from basepanel import *
from dash import ctx, no_update
import plotly.graph_objects as go
import plotly.io as pio

import report


# Preview figures keep their real export size (so map zoom/extent and the
# scale bar look exactly like the .docx) and are shrunk on screen instead.
PREVIEW_SCALE = 0.6

SETTING_LABEL_STYLE = {'fontWeight': 'bold', 'marginTop': '14px', 'marginBottom': '4px'}
HELP_STYLE = {'fontSize': '12px', 'color': '#6c757d'}
SECTION_LABELS = dict(report.REPORT_SECTIONS)
HIDDEN = {'display': 'none'}


# Read straight from the Report tab's controls at click time (Refresh
# preview here, Generate report in app.py). An intermediate store updated
# by its own callback lagged behind: clicking right after typing used the
# previous value.
REPORT_SETTING_STATES = [
    State('report-section-order', 'data'),
    State('report-markersize', 'value'),
    State('report-zoom-offset', 'value'),
    State('report-mean-res-radius', 'value'),
]


def report_settings_from_states(order, markersize, zoom_offset, radius):
    """Options dict for report.build_report_items from REPORT_SETTING_STATES' values (clamped there)."""
    return {
        'sections': [entry['key'] for entry in (order or []) if entry['on']],
        'markersize': markersize,
        'zoom_offset': zoom_offset,
        'mean_res_radius_m': radius,
    }


def _is_3d(fig):
    return any(trace.type in ('mesh3d', 'scatter3d', 'surface') for trace in fig.data)


def _section_rows(order):
    """One row per report section: include checkbox, name, move up/down buttons."""
    rows = []
    for i, entry in enumerate(order):
        key = entry['key']
        rows.append(html.Div([
            dbc.Checkbox(id={'type': 'report-section-on', 'key': key}, value=entry['on']),
            html.Span(f"{i + 1}. {SECTION_LABELS.get(key, key)}",
                      style={'flex': '1', 'color': None if entry['on'] else '#adb5bd'}),
            dbc.Button('▲', id={'type': 'report-section-up', 'key': key}, size='sm',
                       color='secondary', outline=True, disabled=(i == 0)),
            dbc.Button('▼', id={'type': 'report-section-down', 'key': key}, size='sm',
                       color='secondary', outline=True, disabled=(i == len(order) - 1)),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '6px', 'marginBottom': '4px'}))
    return rows


class ReportPanel(Panel):
    """
    Interpret tab's "Report" sub-tab: report settings on the left, a
    figure-by-figure preview on the right. app.py's generate_report_button
    reads the same controls (REPORT_SETTING_STATES), so the generated
    .docx uses the same settings as the preview.

    The preview shows one figure at a time (picked from a dropdown of the
    report's captions) rather than all of them at once -- a report can
    have 40+ map figures, and browsers only allow ~16 live WebGL maps per
    page. Built figures are cached here server-side; only the selected
    one is sent to the browser. The 3D figure is shown as a PNG rendered
    the same way the .docx renders it (kaleido), because a live 3D scene
    in the shrunk, static preview frame showed up empty.
    """

    def __init__(self):
        super().__init__(id='report_panel', childname='children')
        self._preview_items = []

    def render(self):
        return None

    def initialize(self):
        defaults = report.REPORT_DEFAULTS
        default_order = [{'key': key, 'on': key in defaults['sections']} for key, _ in report.REPORT_SECTIONS]
        settings_col = html.Div([
            dcc.Store(id='report-section-order', data=default_order),
            html.H5('Report settings'),

            html.Div('Report contents', style=SETTING_LABEL_STYLE),
            html.Div('Tick to include, use ▲/▼ to change the order.', style=HELP_STYLE),
            html.Div(_section_rows(default_order), id='report-sections-list', style={'marginTop': '6px'}),

            # No min/max/step on these boxes: the browser reports a value
            # that breaks them as empty, which silently dropped typed
            # values. report.report_options() clamps them instead.
            html.Div('Point size', style=SETTING_LABEL_STYLE),
            dbc.Input(id='report-markersize', type='number', step='any', value=defaults['markersize']),
            html.Div('Size of the site markers on the report maps (1–60).', style=HELP_STYLE),

            html.Div('Map zoom', style=SETTING_LABEL_STYLE),
            dbc.Input(id='report-zoom-offset', type='number', step='any', value=defaults['zoom_offset']),
            html.Div('0 fits the maps to the data. Positive values zoom in, negative values '
                     '(e.g. -1) zoom out. Each step of 1 doubles or halves the scale.', style=HELP_STYLE),

            html.Div('Mean resistivity map radius (m)', style=SETTING_LABEL_STYLE),
            dbc.Input(id='report-mean-res-radius', type='number', step='any', value=defaults['mean_res_radius_m']),
            html.Div('How far the mean resistivity colour extends around each site. '
                     'Rounded to the 25 m map grid.', style=HELP_STYLE),

            html.Div([
                dbc.Button('Refresh preview', id='report-preview-button', color='secondary', style={'width': '100%'}),
                html.Div(style={'height': '8px'}),
                dbc.Button('📄 Generate report', id='report-generate-button', color='primary', style={'width': '100%'}),
            ], style={'marginTop': '20px'}),
        ], style={'width': '300px', 'flexShrink': 0, 'padding': '12px', 'overflowY': 'auto',
                  'borderRight': '1px solid #ddd'})

        preview_col = html.Div([
            html.H5('Preview'),
            html.Div("Click 'Refresh preview' to build the report figures.", id='report-preview-status',
                     style={'marginBottom': '8px'}),
            html.Div([
                dbc.Button('◀', id='report-preview-prev', color='secondary', outline=True),
                dbc.Select(id='report-preview-select', options=[], value=None, style={'flex': '1'}),
                dbc.Button('▶', id='report-preview-next', color='secondary', outline=True),
            ], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center', 'marginBottom': '10px'}),
            dcc.Loading([
                html.Div(
                    html.Div(
                        dcc.Graph(id='report-preview-graph', figure=go.Figure(),
                                  config={'staticPlot': True}, responsive=False),
                        id='report-preview-inner', style={'transformOrigin': 'top left'},
                    ),
                    id='report-preview-outer', style={'overflow': 'hidden'},
                ),
                html.Img(id='report-preview-image', style=HIDDEN),
            ]),
            html.Div(id='report-preview-caption', style={'fontStyle': 'italic', 'fontSize': '13px', 'marginTop': '6px'}),
        ], style={'flex': '1', 'padding': '12px', 'overflow': 'auto', 'minWidth': 0})

        return html.Div([settings_col, preview_col],
                        style={'display': 'flex', 'height': '100%', 'minHeight': 0})

    def add_callbacks(self, app):

        @app.callback(
            Output('report-section-order', 'data'),
            Input({'type': 'report-section-up', 'key': ALL}, 'n_clicks'),
            Input({'type': 'report-section-down', 'key': ALL}, 'n_clicks'),
            Input({'type': 'report-section-on', 'key': ALL}, 'value'),
            State('report-section-order', 'data'),
            prevent_initial_call=True,
        )
        def update_section_order(_up, _down, _on, order):
            trigger = ctx.triggered_id
            if not trigger or not ctx.triggered:
                raise PreventUpdate
            value = ctx.triggered[0]['value']
            keys = [entry['key'] for entry in order]
            if trigger['key'] not in keys:
                raise PreventUpdate
            i = keys.index(trigger['key'])
            order = [dict(entry) for entry in order]

            if trigger['type'] == 'report-section-on':
                # Also fires when the rows are re-drawn -- only act on a real change.
                if value is None or bool(value) == order[i]['on']:
                    raise PreventUpdate
                order[i]['on'] = bool(value)
            else:
                if not value:  # freshly re-drawn button, not a click
                    raise PreventUpdate
                j = i - 1 if trigger['type'] == 'report-section-up' else i + 1
                if not 0 <= j < len(order):
                    raise PreventUpdate
                order[i], order[j] = order[j], order[i]
            return order

        @app.callback(
            Output('report-sections-list', 'children'),
            Input('report-section-order', 'data'),
            prevent_initial_call=True,
        )
        def redraw_section_rows(order):
            return _section_rows(order)

        @app.callback(
            Output('report-preview-select', 'options'),
            Output('report-preview-select', 'value'),
            Output('report-preview-status', 'children'),
            Input('report-preview-button', 'n_clicks'),
            *REPORT_SETTING_STATES,
            State('model-3d-camera', 'data'),
            running=[(Output('report-preview-button', 'disabled'), True, False)],
            prevent_initial_call=True,
        )
        def refresh_preview(n_clicks, order, markersize, zoom_offset, radius, camera):
            from __main__ import sesh
            settings = report_settings_from_states(order, markersize, zoom_offset, radius)
            if sesh.data is None:
                self._preview_items = []
                return [], None, 'No data loaded yet.'
            try:
                items = report.build_report_items(settings, camera=camera)
            except Exception as e:
                print(f'Report preview failed: {e}')
                self._preview_items = []
                return [], None, f'Preview failed: {e}'

            self._preview_items = [item for item in items if item['kind'] == 'figure']
            if not self._preview_items:
                message = next((item['text'] for item in items if item['kind'] == 'paragraph'), 'Nothing to show.')
                return [], None, message

            # Prefix each caption with the chapter heading it sits under,
            # so the dropdown doubles as the report's outline.
            options, current_heading = [], ''
            fig_index = 0
            for item in items:
                if item['kind'] == 'heading' and item['level'] == 1:
                    current_heading = item['text']
                elif item['kind'] == 'figure':
                    options.append({'label': f"{current_heading} — {item['caption']}", 'value': str(fig_index)})
                    fig_index += 1
            return options, '0', f'{len(self._preview_items)} figure(s) in the report.'

        @app.callback(
            Output('report-preview-select', 'value', allow_duplicate=True),
            Input('report-preview-prev', 'n_clicks'),
            Input('report-preview-next', 'n_clicks'),
            State('report-preview-select', 'value'),
            prevent_initial_call=True,
        )
        def step_preview(_prev, _next, value):
            if not self._preview_items or value is None:
                raise PreventUpdate
            step = -1 if ctx.triggered_id == 'report-preview-prev' else 1
            return str((int(value) + step) % len(self._preview_items))

        @app.callback(
            Output('report-preview-graph', 'figure'),
            Output('report-preview-graph', 'style'),
            Output('report-preview-inner', 'style'),
            Output('report-preview-outer', 'style'),
            Output('report-preview-image', 'src'),
            Output('report-preview-image', 'style'),
            Output('report-preview-caption', 'children'),
            Input('report-preview-select', 'value'),
            prevent_initial_call=True,
        )
        def show_preview_figure(value):
            if value is None or not self._preview_items:
                return go.Figure(), no_update, no_update, HIDDEN, None, HIDDEN, ''
            item = self._preview_items[int(value) % len(self._preview_items)]
            width, height = item['width_px'], item['height_px']
            shown_size = {'width': f'{width * PREVIEW_SCALE:.0f}px', 'height': f'{height * PREVIEW_SCALE:.0f}px'}

            if _is_3d(item['fig']):
                if 'png' not in item:
                    png = pio.to_image(item['fig'], format='png', width=width, height=height, engine='kaleido')
                    item['png'] = 'data:image/png;base64,' + base64.b64encode(png).decode()
                return (go.Figure(), no_update, no_update, HIDDEN,
                        item['png'], {**shown_size, 'border': '1px solid #ddd'}, item['caption'])

            fig = go.Figure(item['fig'])
            fig.update_layout(width=width, height=height, autosize=False)
            return (
                fig,
                {'width': f'{width}px', 'height': f'{height}px'},
                {'transformOrigin': 'top left', 'transform': f'scale({PREVIEW_SCALE})',
                 'width': f'{width}px', 'height': f'{height}px'},
                {'overflow': 'hidden', 'border': '1px solid #ddd', **shown_size},
                None, HIDDEN,
                item['caption'],
            )
