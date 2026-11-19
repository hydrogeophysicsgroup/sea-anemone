import statistics
import sys
from pathlib import Path

from playwright.sync_api import Page, expect

from playwright_selection_support import selection_app_url


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ARCHIVE = ROOT / "Data" / "L003_S033_2025_1113_125719.zip"
INVERSION_ROUNDS = 2
PROGRESS_TIMEOUT_MS = 120_000
RESULTS_TIMEOUT_MS = 300_000


class BrowserLatencyTimer:
    def __init__(self):
        self.latencies_ms = []
        self._next_latency = 0
        self._waiting_for_target = False

    def set_latency_ms(self, latency_ms: float):
        self.latencies_ms.append(latency_ms)

    def __call__(self):
        if not self._waiting_for_target:
            self._waiting_for_target = True
            return 0.0

        self._waiting_for_target = False
        if self._next_latency >= len(self.latencies_ms):
            raise RuntimeError("The browser latency was not recorded")
        latency_seconds = self.latencies_ms[self._next_latency] / 1000
        self._next_latency += 1
        return latency_seconds


def _reset_inversion_session(dash_module):
    with SAMPLE_ARCHIVE.open("rb") as archive:
        data, forwards = dash_module.temframe.from_zip_content(archive.read())
    session = dash_module.session.Session(data=data, forwards=forwards)
    session.update_site_table()

    dash_module.sesh = session
    dash_module.m1.dataframe = session.overview
    dash_module.dbdt1.dataframe = session.data.copy()
    dash_module.dbdt2.dataframe = session.data.copy()
    dash_module.rhoa.dataframe = session.data.copy()
    dash_module.mod1.dataframe = session.models
    dash_module.mod2.dataframe = session.models
    dash_module.Multi_inv.dataframe = session.data.copy()
    dash_module.Multi_inv.misfit = []
    dash_module.Multi_inv.iterations = []
    dash_module.Multi_inv.title = "Inversion in progress"
    dash_module.Sing_inv.dataframe = session.data.copy()

    main_module = sys.modules["__main__"]
    main_module.sesh = session
    main_module.buf = dash_module.buf
    return session


def _click_to_progress_ms(page: Page):
    return page.wait_for_function(
        """() => {
            const timer = document.getElementById("inv-timer");
            const button = document.getElementById("invert_all_button");
            const graph = document.querySelector("#multi_inv .js-plotly-plot");
            const has_points = graph?.data?.some(trace => trace.y?.length > 0);
            return button?.disabled && has_points && timer &&
                timer.textContent.trim() !== "Elapsed time: 0:00"
                ? performance.now() - window.__inversionClickAt
                : false;
        }""",
        polling="raf",
        timeout=PROGRESS_TIMEOUT_MS,
    ).json_value()


def _click_to_results_ms(page: Page):
    return page.wait_for_function(
        """() => {
            const button = document.getElementById("invert_all_button");
            const graph = document.querySelector("#multi_inv .js-plotly-plot");
            const title = graph?._fullLayout?.title?.text;
            const rendered = graph?.querySelector(".main-svg") &&
                graph.getBoundingClientRect().width > 0;
            return button && !button.disabled &&
                title === "Inversion Finished" &&
                graph.data?.length > 0 && rendered
                ? performance.now() - window.__inversionClickAt
                : false;
        }""",
        polling="raf",
        timeout=RESULTS_TIMEOUT_MS,
    ).json_value()


def _assert_inverted_models_are_visible(page: Page, expected_site_count: int):
    page.locator("#interpret_layout").click()
    graph = page.locator("#model_section .js-plotly-plot")
    expect(graph).to_be_visible(timeout=30_000)
    page.wait_for_function(
        """() => {
            const graph = document.querySelector("#model_section .js-plotly-plot");
            return graph?.data?.some(trace =>
                trace.type === "heatmap" && trace.x?.length && trace.z?.length
            ) || false;
        }""",
        timeout=30_000,
    )

    page.locator("#review_layout").click()
    graph = page.locator("#model_graph .js-plotly-plot")
    expect(graph).to_be_visible(timeout=30_000)
    page.wait_for_function(
        """expectedSiteCount => {
            const graph = document.querySelector("#model_graph .js-plotly-plot");
            const lineCount = graph?.data?.filter(trace => trace.mode === "lines").length;
            return lineCount === Math.min(expectedSiteCount, 50);
        }""",
        arg=expected_site_count,
        timeout=30_000,
    )


def _benchmark_inversion_latency(
    page: Page, benchmark, selection_app_url: str, capsys, metric: str
):
    dash_module = sys.modules["sea_anemone_benchmark_app"]
    main_module = sys.modules["__main__"]
    previous_sesh = main_module.sesh
    had_main_buffer = hasattr(main_module, "buf")
    previous_main_buffer = getattr(main_module, "buf", None)
    previous_app_session = dash_module.sesh
    previous_map_data = dash_module.m1.dataframe
    previous_model_graph_data = dash_module.mod1.dataframe
    previous_model_section_data = dash_module.mod2.dataframe
    multi_inversion_state = {
        name: (
            hasattr(dash_module.Multi_inv, name),
            getattr(dash_module.Multi_inv, name, None),
        )
        for name in ("dataframe", "misfit", "iterations", "title", "starting_rho")
    }
    timer = BrowserLatencyTimer()
    benchmark._timer = timer
    callback_errors = []

    def record_callback_error(response):
        if "/_dash-update-component" in response.url and response.status >= 400:
            callback_errors.append(f"{response.status} {response.url}")

    page.on("response", record_callback_error)

    def run_inversion():
        session = _reset_inversion_session(dash_module)
        response = page.goto(selection_app_url, wait_until="domcontentloaded")
        assert response is not None and response.status == 200
        expect(page).to_have_title("Sea Anemone")

        page.locator("#invert_layout").click()
        invert_button = page.locator("#invert_all_button")
        invert_button.wait_for(state="visible", timeout=30_000)
        expect(invert_button).to_be_enabled()
        page.wait_for_function(
            """() => {
                const graph = document.querySelector("#multi_inv .js-plotly-plot");
                return graph?._fullLayout?.title?.text ===
                    "Spatially Constrained Inversion";
            }""",
            timeout=30_000,
        )
        expect(page.locator("#inv-timer")).to_have_text("Elapsed time: 0:00")

        page.evaluate(
            """() => {
                window.__inversionClickAt = null;
                document.addEventListener("click", event => {
                    if (event.target.closest("#invert_all_button")) {
                        window.__inversionClickAt = performance.now();
                    }
                }, true);
            }"""
        )
        invert_button.click()

        progress_ms = _click_to_progress_ms(page)
        if metric == "progress":
            timer.set_latency_ms(progress_ms)

        result_ms = _click_to_results_ms(page)
        assert session.models is not None and not session.models.empty
        expected_site_count = session.models["site_id"].nunique()
        _assert_inverted_models_are_visible(page, expected_site_count)
        if metric == "results":
            timer.set_latency_ms(result_ms)

    try:
        benchmark.pedantic(
            run_inversion,
            rounds=INVERSION_ROUNDS,
            iterations=1,
            warmup_rounds=0,
        )
    finally:
        page.remove_listener("response", record_callback_error)
        main_module.sesh = previous_sesh
        dash_module.sesh = previous_app_session
        dash_module.m1.dataframe = previous_map_data
        dash_module.mod1.dataframe = previous_model_graph_data
        dash_module.mod2.dataframe = previous_model_section_data
        for name, (was_present, value) in multi_inversion_state.items():
            if was_present:
                setattr(dash_module.Multi_inv, name, value)
            elif hasattr(dash_module.Multi_inv, name):
                delattr(dash_module.Multi_inv, name)
        if had_main_buffer:
            main_module.buf = previous_main_buffer
        elif hasattr(main_module, "buf"):
            del main_module.buf

    assert not callback_errors, f"Dash callbacks failed: {callback_errors}"
    median_ms = statistics.median(timer.latencies_ms)
    maximum_ms = max(timer.latencies_ms)
    metric_label = (
        "click-to-first-progress" if metric == "progress" else "click-to-results"
    )
    benchmark.extra_info["median latency (ms)"] = round(median_ms, 2)
    benchmark.extra_info["maximum latency (ms)"] = round(maximum_ms, 2)
    with capsys.disabled():
        print(
            f"{metric_label}: median={median_ms:.2f} ms, "
            f"maximum={maximum_ms:.2f} ms"
        )


def test_inversion_click_to_first_progress_latency(
    page: Page, benchmark, selection_app_url: str, capsys
):
    _benchmark_inversion_latency(
        page, benchmark, selection_app_url, capsys, metric="progress"
    )


def test_inversion_click_to_results_latency(
    page: Page, benchmark, selection_app_url: str, capsys
):
    _benchmark_inversion_latency(
        page, benchmark, selection_app_url, capsys, metric="results"
    )
