import statistics

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from playwright_selection_support import PointClickBenchmarkApp


CASES = {
    "map": {
        "layout_button": "process_layout",
        "visible_graphs": ("map", "sounding", "rhoa", "tTEM"),
    },
    "tTEM": {
        "layout_button": "process_layout",
        "visible_graphs": ("map", "sounding", "rhoa", "tTEM"),
    },
    "model_section": {
        "layout_button": "review_layout",
        "visible_graphs": ("map", "model_graph", "sounding", "model_section"),
    },
}


def _point_click_position(page: Page, graph_id: str, site_id: str):
    return page.locator(f"#{graph_id} .js-plotly-plot").evaluate(
        """(gd, {graphId, siteId}) => {
            const values = value => value?._inputArray ?? value ?? [];
            const sameSite = value => String(value) === siteId;

            if (graphId === "map") {
                const trace = gd.data.find(item => item.name === "sites");
                if (!trace) throw new Error("Map site trace missing");
                const customdata = values(trace.customdata);
                const index = customdata.findIndex(row =>
                    sameSite(Array.isArray(row) ? row[0] : row)
                );
                if (index < 0) throw new Error(`Map site ${siteId} missing`);

                const map = gd._fullLayout.map?._subplot?.map;
                if (!map || typeof map.project !== "function") {
                    throw new Error("Plotly map projection is unavailable");
                }
                const container = map.getContainer();
                const bounds = container.getBoundingClientRect();
                const point = map.project([
                    values(trace.lon)[index],
                    values(trace.lat)[index]
                ]);
                return {x: bounds.left + point.x, y: bounds.top + point.y};
            }

            if (graphId === "model_section") {
                const trace = gd.data.find(item => item.type === "heatmap");
                if (!trace) throw new Error("Model-section heatmap missing");
                const x = values(trace.x).find(value => sameSite(value));
                const yValues = values(trace.y);
                if (x === undefined || !yValues.length) {
                    throw new Error(`Model-section site ${siteId} missing`);
                }
                const y = yValues[Math.floor(yValues.length / 2)];
                const bounds = gd.getBoundingClientRect();
                const position = {
                    x: bounds.left + gd._fullLayout.xaxis._offset +
                        gd._fullLayout.xaxis.d2p(x),
                    y: bounds.top + gd._fullLayout.yaxis._offset +
                        gd._fullLayout.yaxis.d2p(y)
                };
                if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) {
                    throw new Error(
                        `Invalid model-section position for site ${siteId}`
                    );
                }
                return position;
            }

            for (const trace of gd.data) {
                const customdata = values(trace.customdata);
                const index = customdata.findIndex(row =>
                    Array.isArray(row) && row.length > 2 && sameSite(row[2])
                );
                if (index < 0) continue;

                const x = values(trace.x)[index];
                const y = values(trace.y)[index];
                if (!Number.isFinite(Number(x)) || !Number.isFinite(Number(y))) {
                    continue;
                }
                const bounds = gd.getBoundingClientRect();
                const position = {
                    x: bounds.left + gd._fullLayout.xaxis._offset +
                        gd._fullLayout.xaxis.d2p(x),
                    y: bounds.top + gd._fullLayout.yaxis._offset +
                        gd._fullLayout.yaxis.d2p(y)
                };
                if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) {
                    continue;
                }
                return position;
            }
            throw new Error(`No plotted point for site ${siteId} in ${graphId}`);
        }""",
        {"graphId": graph_id, "siteId": site_id},
    )


def _prepare_graph_counters(page: Page, graph_ids: tuple[str, ...]):
    page.evaluate(
        """graphIds => {
            window.__pointClickGraphs = {};
            for (const graphId of graphIds) {
                const graph = document.querySelector(
                    `#${graphId} .js-plotly-plot`
                );
                if (!graph) throw new Error(`Graph ${graphId} is missing`);
                graph.__pointClickAfterplot = 0;
                graph.on("plotly_afterplot", () => {
                    graph.__pointClickAfterplot += 1;
                });
                graph.__pointClickEvents = 0;
                graph.__pointClickHovers = 0;
                graph.__pointClickLastPoints = [];
                graph.on("plotly_hover", () => {
                    graph.__pointClickHovers += 1;
                });
                graph.on("plotly_click", event => {
                    graph.__pointClickEvents += 1;
                    graph.__pointClickLastPoints = event.points.map(point => ({
                        curveNumber: point.curveNumber,
                        pointNumber: point.pointNumber,
                        x: point.x,
                        y: point.y,
                        lon: point.lon,
                        lat: point.lat,
                        customdata: point.customdata
                    }));
                    if (graph.__pointClickLastPoints.length) {
                        const point = graph.__pointClickLastPoints[0];
                        let site = graphId === "map"
                            ? point.customdata
                            : point.x;
                        while (Array.isArray(site)) site = site[0];
                        graph.__pointClickExpectedSite = site;
                        window.dash_clientside.set_props(graphId, {
                            clickData: {
                                points: graph.__pointClickLastPoints
                            }
                        });
                    }
                });
                window.__pointClickGraphs[graphId] = graph;
            }
        }""",
        list(graph_ids),
    )


def _hoverable_site_ids(page: Page, graph_id: str, site_ids: list[str]):
    graph_selector = f"#{graph_id} .js-plotly-plot"
    hoverable_site_ids = []
    for site_id in site_ids:
        position = _point_click_position(page, graph_id, str(site_id))
        baseline = page.locator(graph_selector).evaluate(
            "gd => gd.__pointClickHovers"
        )
        page.mouse.move(position["x"], position["y"])
        try:
            page.wait_for_function(
                """({graphId, baseline}) =>
                    window.__pointClickGraphs[graphId].__pointClickHovers >
                    baseline""",
                arg={"graphId": graph_id, "baseline": baseline},
                timeout=200,
            )
        except PlaywrightTimeoutError:
            continue
        hoverable_site_ids.append(str(site_id))
        if len(hoverable_site_ids) == 10:
            break
    assert hoverable_site_ids, f"No hit-testable points found in {graph_id}"
    return hoverable_site_ids


def _benchmark_point_click(
    page: Page,
    benchmark,
    app: PointClickBenchmarkApp,
    capsys,
    graph_id: str,
):
    case = CASES[graph_id]
    response = page.goto(app.url, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    page.locator(f"#{case['layout_button']}").click()
    for visible_graph_id in case["visible_graphs"]:
        page.locator(f"#{visible_graph_id} .js-plotly-plot").wait_for(
            state="visible", timeout=60_000
        )
    _prepare_graph_counters(page, case["visible_graphs"])

    site_ids = app.site_ids
    assert len(site_ids) >= 2, "Point-click benchmark requires multiple sites"
    target_site_ids = _hoverable_site_ids(page, graph_id, site_ids)
    latencies_ms = []
    round_index = 0
    callback_changes = []

    def record_dash_request(request):
        if request.method != "POST" or not request.url.endswith(
            "/_dash-update-component"
        ):
            return
        try:
            payload = request.post_data_json
        except (TypeError, ValueError):
            return
        changed = payload.get("changedPropIds", [])
        callback_changes.append(changed)

    page.on("request", record_dash_request)

    def click_site_and_wait():
        nonlocal round_index
        site_id = str(target_site_ids[round_index % len(target_site_ids)])
        round_index += 1
        position = _point_click_position(page, graph_id, site_id)
        page.evaluate(
            """({graphIds, graphId}) => {
                window.__pointClickStart = performance.now();
                window.__pointClickBaseline = Object.fromEntries(
                    graphIds.map(graphId => [
                        graphId,
                        window.__pointClickGraphs[graphId].__pointClickAfterplot
                    ])
                );
                window.__pointClickEventBaseline = window
                    .__pointClickGraphs[graphId].__pointClickEvents;
            }""",
            {"graphIds": list(case["visible_graphs"]), "graphId": graph_id},
        )
        page.mouse.click(position["x"], position["y"])
        try:
            page.wait_for_function(
                """({graphId, baseline}) =>
                    window.__pointClickGraphs[graphId].__pointClickEvents >
                    baseline""",
                arg={
                    "graphId": graph_id,
                    "baseline": page.evaluate("window.__pointClickEventBaseline"),
                },
                timeout=5_000,
            )
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"No Plotly point event for {graph_id} at {position}; "
                f"trace data={page.locator(f'#{graph_id} .js-plotly-plot').evaluate('gd => gd.data.map(trace => ({type: trace.type, name: trace.name, points: trace.x?.length ?? trace.lat?.length}))')}"
            ) from exc

        try:
            page.wait_for_function(
                """graphIds => graphIds.every(graphId => {
                    const graph = window.__pointClickGraphs[graphId];
                    return graph.__pointClickAfterplot >
                        window.__pointClickBaseline[graphId];
                })""",
                arg=list(case["visible_graphs"]),
                polling="raf",
                timeout=30_000,
            )
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                "Visible linked plots did not redraw after point click; "
                f"selected={app.dash_module.m1.highlighted}, "
                f"recent callback changes={callback_changes[-5:]}, "
                f"plotly points={page.locator(f'#{graph_id} .js-plotly-plot').evaluate('gd => gd.__pointClickLastPoints')}"
            ) from exc
        elapsed_ms = page.evaluate(
            """() => new Promise(resolve => requestAnimationFrame(() =>
                requestAnimationFrame(() =>
                    resolve(performance.now() - window.__pointClickStart)
                )
            ))"""
        )

        actual_site = app.dash_module.m1.highlighted
        expected_site = page.locator(
            f"#{graph_id} .js-plotly-plot"
        ).evaluate("gd => gd.__pointClickExpectedSite")
        while isinstance(expected_site, (list, tuple)):
            expected_site = expected_site[0]
        assert actual_site is not None
        if expected_site is not None:
            assert float(actual_site) == float(expected_site), (
                f"{graph_id} click selected site {actual_site}, "
                f"expected hit-tested site {expected_site} (target {site_id})"
            )
        else:
            assert float(actual_site) in {float(value) for value in site_ids}
        latencies_ms.append(elapsed_ms)

    benchmark.pedantic(
        click_site_and_wait,
        rounds=10,
        iterations=1,
        warmup_rounds=0,
    )
    median_ms = statistics.median(latencies_ms)
    maximum_ms = max(latencies_ms)
    benchmark.extra_info["source plot"] = graph_id
    benchmark.extra_info["browser-visible point-click median (ms)"] = round(
        median_ms, 2
    )
    benchmark.extra_info["browser-visible point-click max (ms)"] = round(
        maximum_ms, 2
    )
    with capsys.disabled():
        print(
            f"{graph_id} point-click to linked plots: "
            f"median={median_ms:.2f} ms, max={maximum_ms:.2f} ms"
        )


def test_map_point_click_updates_linked_plots(
    page: Page, benchmark, capsys, point_click_app: PointClickBenchmarkApp
):
    _benchmark_point_click(page, benchmark, point_click_app, capsys, "map")


def test_section_point_click_updates_linked_plots(
    page: Page, benchmark, capsys, point_click_app: PointClickBenchmarkApp
):
    _benchmark_point_click(page, benchmark, point_click_app, capsys, "tTEM")


def test_model_section_point_click_updates_linked_plots(
    page: Page, benchmark, capsys, point_click_app: PointClickBenchmarkApp
):
    _benchmark_point_click(
        page, benchmark, point_click_app, capsys, "model_section"
    )
