import statistics

from playwright.sync_api import Page, expect

from playwright_selection_support import LINKED_GRAPHS


WORKFLOW = (
    ("invert_layout", "Invert", ("map", "multi_inv")),
    ("review_layout", "QC", ("map", "model_graph", "model_section")),
    ("interpret_layout", "Interpret", ("map", "model_section")),
    ("process_layout", "Process", ("map", *LINKED_GRAPHS)),
)


def _wait_for_view(page: Page, button_id: str, graph_ids: tuple[str, ...]):
    return page.wait_for_function(
        """({buttonId, graphIds}) => {
            const ready = graphIds.every(graphId => {
            const container = document.getElementById(graphId);
            const graph = container?.querySelector(".js-plotly-plot");
            if (!container || !graph || !graph._fullLayout ||
                !graph.querySelector(".main-svg")) {
                return false;
            }
            const bounds = graph.getBoundingClientRect();
            return bounds.width > 0 && bounds.height > 0;
            });
            return ready
                ? performance.now() - window.__viewSwitchStartedAt[buttonId]
                : false;
        }""",
        arg={"buttonId": button_id, "graphIds": list(graph_ids)},
        polling="raf",
        timeout=30_000,
    ).json_value()


def _verify_map_interaction(page: Page):
    return page.locator("#map .js-plotly-plot").evaluate(
        """graph => {
            return Boolean(
                graph._fullLayout.map &&
                graph._context?.staticPlot !== true &&
                typeof graph.on === "function"
            );
        }"""
    )


def test_workflow_views_become_visible_and_interactive(
    page: Page, benchmark, selection_app_url: str, capsys
):
    switch_latencies = {label: [] for _, label, _ in WORKFLOW}

    def switch_workflow_views():
        response = page.goto(selection_app_url, wait_until="domcontentloaded")
        assert response is not None and response.status == 200
        expect(page).to_have_title("Sea Anemone")
        page.locator("#process_layout").wait_for(state="visible")
        page.locator("#map .js-plotly-plot").wait_for(
            state="visible", timeout=30_000
        )

        page.evaluate(
            """() => {
                window.__viewSwitchStartedAt = {};
                document.addEventListener("click", event => {
                    const button = event.target.closest("button[id]");
                    if (button && [
                        "invert_layout",
                        "review_layout",
                        "interpret_layout",
                        "process_layout"
                    ].includes(button.id)) {
                        window.__viewSwitchStartedAt[button.id] = performance.now();
                    }
                }, true);
            }"""
        )

        for button_id, label, expected_graphs in WORKFLOW:
            page.locator(f"#{button_id}").click()
            elapsed_ms = _wait_for_view(page, button_id, expected_graphs)
            interaction = _verify_map_interaction(page)
            assert interaction, f"Map is not interactive after {label}"
            switch_latencies[label].append(elapsed_ms)

    benchmark.pedantic(
        switch_workflow_views,
        rounds=3,
        iterations=1,
        warmup_rounds=0,
    )

    median_latencies = {
        label: statistics.median(latencies)
        for label, latencies in switch_latencies.items()
    }
    benchmark.extra_info["view-switch median latency (ms)"] = {
        label: round(latency, 2)
        for label, latency in median_latencies.items()
    }
    with capsys.disabled():
        print(
            "View-switch latency medians: "
            + ", ".join(
                f"{label}={latency:.2f} ms"
                for label, latency in median_latencies.items()
            )
        )
