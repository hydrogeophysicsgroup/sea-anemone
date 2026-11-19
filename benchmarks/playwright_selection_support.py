import importlib.util
import os
import statistics
import sys
import threading
from dataclasses import dataclass
from types import ModuleType
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ARCHIVE = ROOT / "Data" / "L003_S033_2025_1113_125719.zip"
UPLOAD_ARCHIVE = Path(os.getenv("PLAYWRIGHT_UPLOAD_ARCHIVE", SAMPLE_ARCHIVE))
LINKED_GRAPHS = ("sounding", "rhoa", "tTEM")
sys.path.append(str(ROOT / "app"))
import temframe
from session import Session


@dataclass
class UploadBenchmarkApp:
    url: str
    dash_module: ModuleType
    main_module: ModuleType
    archive: Path
    expected_site_ids: list[str]

    def reset(self):
        empty_session = Session()
        self.dash_module.sesh = empty_session
        self.main_module.sesh = empty_session
        for panel in (
            self.dash_module.m1,
            self.dash_module.dbdt1,
            self.dash_module.dbdt2,
            self.dash_module.rhoa,
            self.dash_module.mod1,
            self.dash_module.mod2,
            self.dash_module.Multi_inv,
            self.dash_module.Sing_inv,
        ):
            panel.dataframe = None
        map_buffer = getattr(self.dash_module.m1, "buffer", None)
        if map_buffer is not None:
            map_buffer.reset()


@dataclass
class PointClickBenchmarkApp:
    url: str
    dash_module: ModuleType
    site_ids: list[str]


def _import_app(module_name: str, initial_session: Session):
    app_path = ROOT / "app" / "app.py"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load application module from {app_path}")
    dash_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = dash_module
    spec.loader.exec_module(dash_module)
    dash_module.sesh = initial_session
    return dash_module


@pytest.fixture(scope="module")
def selection_app_url():
    with SAMPLE_ARCHIVE.open("rb") as archive:
        data, forwards = temframe.from_zip_content(archive.read())
    sample_session = Session(data=data, forwards=forwards)
    sample_session.update_site_table()
    main_module = sys.modules["__main__"]
    had_previous_session = hasattr(main_module, "sesh")
    previous_session = getattr(main_module, "sesh", None)
    main_module.sesh = sample_session

    dash_module = _import_app("sea_anemone_benchmark_app", sample_session)
    dash_module.m1.dataframe = sample_session.overview
    dash_module.dbdt1.dataframe = sample_session.data.copy()
    dash_module.dbdt2.dataframe = sample_session.data.copy()
    dash_module.rhoa.dataframe = sample_session.data.copy()
    dash_module.flex_layout.model = dash_module.layouts.data
    dash_module.flex_layout.children = [
        node for panel in dash_module.panels for node in panel.to_nodes()
    ]
    server = make_server("127.0.0.1", 0, dash_module.app.server, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if had_previous_session:
            main_module.sesh = previous_session
        else:
            del main_module.sesh


@pytest.fixture(scope="module")
def point_click_app(selection_app_url):
    dash_module = sys.modules["sea_anemone_benchmark_app"]
    session = dash_module.sesh
    original_models = session.models
    original_mod1_dataframe = dash_module.mod1.dataframe
    original_mod2_dataframe = dash_module.mod2.dataframe
    original_children = dash_module.flex_layout.children
    original_highlighted = (
        dash_module.m1.highlighted,
        dash_module.mod1.highlighted,
        dash_module.mod2.highlighted,
        dash_module.dbdt2.highlighted,
    )
    original_dbdt1_dataframe = dash_module.dbdt1.dataframe
    original_rhoa_dataframe = dash_module.rhoa.dataframe
    map_buffer = dash_module.m1.buffer
    original_buffer_selected = map_buffer.selected.copy()
    original_buffer_start = map_buffer.start
    missing_xlim = object()
    original_dbdt2_xlim = getattr(dash_module.dbdt2, "xlim", missing_xlim)

    sites = session.overview.loc[session.overview["site_id"] != -1]
    site_ids = sorted(sites["site_id"].dropna().unique().tolist(), key=float)
    model_rows = []
    for site in sites.drop_duplicates("site_id").itertuples(index=False):
        for layer, top, bottom, resistivity in (
            (0, 0.0, 10.0, 20.0),
            (1, 10.0, 35.0, 60.0),
        ):
            model_rows.append(
                {
                    "site_id": site.site_id,
                    "layer": layer,
                    "resistivity": resistivity,
                    "misfit": 1.0,
                    "doi": 50.0,
                    "elevation": getattr(site, "elevation", 0.0),
                    "top_depth": top,
                    "bottom_depth": bottom,
                    "center_depth": (top + bottom) / 2.0,
                }
            )

    models = pd.DataFrame(model_rows)
    session.models = models
    dash_module.mod1.dataframe = models
    dash_module.mod2.dataframe = models
    dash_module.flex_layout.children = [
        node for panel in dash_module.panels for node in panel.to_nodes()
    ]

    try:
        yield PointClickBenchmarkApp(
            url=selection_app_url,
            dash_module=dash_module,
            site_ids=site_ids,
        )
    finally:
        session.models = original_models
        dash_module.mod1.dataframe = original_mod1_dataframe
        dash_module.mod2.dataframe = original_mod2_dataframe
        dash_module.flex_layout.children = original_children
        (
            dash_module.m1.highlighted,
            dash_module.mod1.highlighted,
            dash_module.mod2.highlighted,
            dash_module.dbdt2.highlighted,
        ) = original_highlighted
        dash_module.dbdt1.dataframe = original_dbdt1_dataframe
        dash_module.rhoa.dataframe = original_rhoa_dataframe
        map_buffer.selected = original_buffer_selected
        map_buffer.start = original_buffer_start
        if original_dbdt2_xlim is missing_xlim:
            if hasattr(dash_module.dbdt2, "xlim"):
                del dash_module.dbdt2.xlim
        else:
            dash_module.dbdt2.xlim = original_dbdt2_xlim


@pytest.fixture(scope="module")
def upload_benchmark_app():
    if not UPLOAD_ARCHIVE.is_file():
        raise FileNotFoundError(f"Upload benchmark archive not found: {UPLOAD_ARCHIVE}")
    with UPLOAD_ARCHIVE.open("rb") as archive:
        sample_data, _ = temframe.from_zip_content(archive.read())
    expected_session = Session(data=sample_data)
    expected_site_ids = sorted(
        (
            str(site_id)
            for site_id in expected_session.overview.site_id
            if site_id != -1
        ),
        key=float,
    )

    main_module = sys.modules["__main__"]
    had_previous_session = hasattr(main_module, "sesh")
    previous_session = getattr(main_module, "sesh", None)
    empty_session = Session()
    main_module.sesh = empty_session
    dash_module = _import_app("sea_anemone_upload_benchmark_app", empty_session)

    server = make_server("127.0.0.1", 0, dash_module.app.server, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield UploadBenchmarkApp(
            url=f"http://127.0.0.1:{server.server_port}",
            dash_module=dash_module,
            main_module=main_module,
            archive=UPLOAD_ARCHIVE,
            expected_site_ids=expected_site_ids,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if had_previous_session:
            main_module.sesh = previous_session
        else:
            del main_module.sesh


def _site_ids_from_plot(graph):
    return graph.evaluate(
        """gd => [...new Set(gd.data
            .flatMap(trace => trace.customdata?._inputArray ?? trace.customdata ?? [])
            .filter(row => row.length > 2 && row[2] != null)
            .map(row => String(row[2])))]"""
    )


def benchmark_selection_case(
    page: Page,
    benchmark,
    selection_app_url: str,
    capsys,
    selection_size: int | str,
    case_name: str,
):
    response = page.goto(selection_app_url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    expect(page).to_have_title("Sea Anemone")

    page.locator("#process_layout").click()

    for graph_id in ("map", *LINKED_GRAPHS):
        page.locator(f"#{graph_id} .js-plotly-plot").wait_for(
            state="visible", timeout=60_000
        )

    map_graph = page.locator("#map .js-plotly-plot")
    site_trace = map_graph.evaluate(
        """gd => gd.data.findIndex(trace => trace.name === "sites")"""
    )
    assert site_trace >= 0, "Map site trace missing"
    site_count = map_graph.evaluate(
        """(gd, traceIndex) => {
            const customdata = gd.data[traceIndex].customdata;
            return (customdata?._inputArray ?? customdata ?? []).length;
        }""",
        site_trace,
    )
    assert site_count >= 2, f"Expected multiple map sites, got {site_count}"

    all_site_ids = map_graph.evaluate(
        """(gd, traceIndex) => {
            const customdata = gd.data[traceIndex].customdata;
            const rows = customdata?._inputArray ?? customdata ?? [];
            return rows.map(row => String(row[0]));
        }""",
        site_trace,
    )
    selected_count = (
        len(all_site_ids) if selection_size == "all" else selection_size
    )
    assert selected_count <= len(all_site_ids), (
        f"Selection case {case_name} requests {selection_size} sites, "
        f"but the sample has {len(all_site_ids)}"
    )
    linked_graphs = [
        page.locator(f"#{graph_id} .js-plotly-plot") for graph_id in LINKED_GRAPHS
    ]
    section_graph = linked_graphs[-1]
    page.evaluate(
        """graphIds => {
            window.__selectionBenchmarkGraphs = {};
            for (const graphId of graphIds) {
                const graph = document.querySelector(`#${graphId} .js-plotly-plot`);
                graph.__selectionBenchmarkAfterplot = 0;
                graph.on("plotly_afterplot", () => {
                    graph.__selectionBenchmarkAfterplot += 1;
                });
                window.__selectionBenchmarkGraphs[graphId] = graph;
            }
        }""",
        list(LINKED_GRAPHS),
    )
    measured_latencies = []
    selection_index = 0

    def select_site_and_wait():
        nonlocal selection_index
        if selected_count == len(all_site_ids):
            selected_site_ids = all_site_ids.copy()
            if selection_index % 2:
                selected_site_ids.reverse()
        else:
            start = selection_index % len(all_site_ids)
            selected_site_ids = [
                all_site_ids[(start + offset) % len(all_site_ids)]
                for offset in range(selected_count)
            ]
        selection_index += 1
        current_site_trace = map_graph.evaluate(
            """gd => gd.data.findIndex(trace => trace.name === "sites")"""
        )
        assert current_site_trace >= 0, "Map site trace missing after selection"

        page.evaluate(
            """({siteIds, traceIndex, graphIds}) => {
                window.__selectionBenchmarkStart = performance.now();
                window.__selectionBenchmarkEnd = null;
                window.__selectionBenchmarkAfterplotBaseline = Object.fromEntries(
                    graphIds.map(graphId => [
                        graphId,
                        window.__selectionBenchmarkGraphs[graphId].__selectionBenchmarkAfterplot
                    ])
                );
                window.dash_clientside.set_props("map", {
                    selectedData: {
                        points: siteIds.map(siteId => ({
                            curveNumber: traceIndex,
                            customdata: [Number(siteId)]
                        }))
                    }
                });
            }""",
            arg={
                "siteIds": selected_site_ids,
                "traceIndex": current_site_trace,
                "graphIds": list(LINKED_GRAPHS),
            },
        )

        try:
            page.wait_for_function(
                """({siteIds, graphIds}) => {
                    const selected = new Set(siteIds);
                    if (!graphIds.every(graphId => {
                        const graph = window.__selectionBenchmarkGraphs[graphId];
                        return graph.__selectionBenchmarkAfterplot >
                            window.__selectionBenchmarkAfterplotBaseline[graphId];
                    })) return false;
                    const siteRows = graphId => {
                        const graph = document.querySelector(`#${graphId} .js-plotly-plot`);
                        if (!graph) return null;
                        return graph.data.flatMap(trace =>
                            trace.customdata?._inputArray ?? trace.customdata ?? []
                        );
                    };
                    const soundingRows = siteRows("sounding");
                    const rhoaRows = siteRows("rhoa");
                    const sectionRows = siteRows("tTEM");
                    if (!soundingRows?.length || !rhoaRows?.length || !sectionRows?.length) {
                        return false;
                    }
                    const selectedOnly = rows => {
                        const ids = new Set(rows
                            .filter(row => row.length > 2 && row[2] != null)
                            .map(row => String(row[2])));
                        return ids.size === selected.size &&
                            [...selected].every(siteId => ids.has(siteId));
                    };
                    if (!selectedOnly(soundingRows) || !selectedOnly(rhoaRows)) return false;
                    if (![...selected].every(siteId => sectionRows.some(
                        row => String(row[2]) === siteId
                    ))) return false;
                    const section = document.querySelector("#tTEM .js-plotly-plot");
                    const range = section?.layout.xaxis?.range;
                    if (!range || range.length !== 2 ||
                        !Number.isFinite(Number(range[0])) ||
                        !Number.isFinite(Number(range[1])) ||
                        Number(range[0]) >= Number(range[1])) {
                        return false;
                    }
                    const meta = section.layout.meta;
                    const sectionSiteIds = meta?.site_id ?? [];
                    const siteX = meta?.site_x ?? [];
                    const inWindow = [...selected].some(siteId => {
                        const index = sectionSiteIds.findIndex(
                            id => String(id) === siteId
                        );
                        return index >= 0 &&
                            Number(siteX[index]) >= Number(range[0]) &&
                            Number(siteX[index]) <= Number(range[1]);
                    });
                    if (!inWindow || !(section.layout.shapes ?? []).length) {
                        return false;
                    }
                    if (window.__selectionBenchmarkEnd === null) {
                        requestAnimationFrame(() => requestAnimationFrame(() => {
                            window.__selectionBenchmarkEnd = performance.now();
                        }));
                    }
                    return window.__selectionBenchmarkEnd !== null;
                }""",
                arg={
                    "siteIds": selected_site_ids,
                    "graphIds": list(LINKED_GRAPHS),
                },
                polling="raf",
                timeout=15_000,
            )
        except PlaywrightTimeoutError as exc:
            state = {
                graph_id: {
                    "sites": _site_ids_from_plot(graph),
                    "range": graph.evaluate("gd => gd.layout.xaxis?.range"),
                }
                for graph_id, graph in zip(LINKED_GRAPHS, linked_graphs)
            }
            raise AssertionError(
                f"Linked plots did not update for {case_name} "
                f"({selection_size} selected sites): {state}"
            ) from exc

        elapsed_ms = page.evaluate(
            "window.__selectionBenchmarkEnd - window.__selectionBenchmarkStart"
        )
        expected_site_ids = sorted(selected_site_ids, key=float)
        assert _site_ids_from_plot(linked_graphs[0]) == expected_site_ids
        assert _site_ids_from_plot(linked_graphs[1]) == expected_site_ids
        assert set(expected_site_ids).issubset(_site_ids_from_plot(section_graph))
        section_range = section_graph.evaluate("gd => gd.layout.xaxis.range")
        assert section_range is not None and section_range[0] < section_range[1]
        measured_latencies.append(elapsed_ms)

    benchmark.pedantic(
        select_site_and_wait,
        rounds=10,
        iterations=1,
        warmup_rounds=0,
    )
    median_ms = statistics.median(measured_latencies)
    maximum_ms = max(measured_latencies)
    benchmark.extra_info["selection size"] = selected_count
    benchmark.extra_info["browser-visible update median (ms)"] = round(
        median_ms, 2
    )
    benchmark.extra_info["browser-visible update max (ms)"] = round(
        maximum_ms, 2
    )
    with capsys.disabled():
        print(
            f"{case_name} ({selection_size} sites) browser-visible update latency: "
            f"median={median_ms:.2f} ms, max={maximum_ms:.2f} ms"
        )
