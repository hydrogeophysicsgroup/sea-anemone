import statistics

from playwright.sync_api import Page, expect

from playwright_selection_support import (
    UploadBenchmarkApp,
)


def _is_upload_callback(response):
    request = response.request
    if request.method != "POST" or not response.url.endswith(
        "/_dash-update-component"
    ):
        return False
    try:
        payload = request.post_data_json
    except (TypeError, ValueError):
        return False
    return any(
        item.get("id") == "upload-data" and item.get("property") == "contents"
        for item in payload.get("inputs", [])
    )


def test_load_data_until_map_and_plots_are_usable(
    page: Page, benchmark, capsys, upload_benchmark_app: UploadBenchmarkApp
):
    latencies_ms = []
    expected_sites = upload_benchmark_app.expected_site_ids
    buffered_sites = expected_sites[:50]

    def upload_and_wait_for_usable_plots():
        upload_benchmark_app.reset()
        page.goto(upload_benchmark_app.url, wait_until="domcontentloaded")
        expect(page).to_have_title("Sea Anemone")
        upload = page.locator("#upload-data input[type='file']")

        page.evaluate("window.__loadBenchmarkStart = performance.now()")
        with page.expect_response(_is_upload_callback, timeout=120_000) as response:
            upload.set_input_files(
                {
                    "name": upload_benchmark_app.archive.name,
                    "mimeType": "application/x-zip-compressed",
                    "buffer": upload_benchmark_app.archive.read_bytes(),
                }
            )
        upload_response = response.value
        assert upload_response.status == 200, (
            f"Sample archive upload callback returned HTTP "
            f"{upload_response.status}: {upload_response.text()[:1000]}"
        )
        expect(page.locator("#output-data-upload")).to_contain_text(
            "File uploaded successfully", timeout=10_000
        )

        page.locator("#process_layout").click()
        for graph_id in ("map", "sounding", "rhoa", "tTEM"):
            page.locator(f"#{graph_id} .js-plotly-plot").wait_for(
                state="visible", timeout=60_000
            )

        page.wait_for_function(
            """({expectedSites, bufferedSites}) => {
                const readSiteIds = graphId => {
                    const graph = document.querySelector(`#${graphId} .js-plotly-plot`);
                    if (!graph || !graph._fullLayout || !graph.querySelector(".main-svg") ||
                        graph.getBoundingClientRect().width === 0 ||
                        graph.getBoundingClientRect().height === 0) {
                        return null;
                    }
                    return [...new Set(graph.data.flatMap(trace =>
                        trace.customdata?._inputArray ?? trace.customdata ?? []
                    ).filter(row => row.length > 2 && row[2] != null)
                     .map(row => String(row[2])))];
                };
                const map = document.querySelector("#map .js-plotly-plot");
                if (!map || !map._fullLayout || !map.querySelector(".main-svg") ||
                    map.getBoundingClientRect().width === 0 ||
                    map.getBoundingClientRect().height === 0) {
                    return false;
                }
                const mapTrace = map.data.find(trace => trace.name === "sites");
                const mapRows = mapTrace?.customdata?._inputArray ??
                    mapTrace?.customdata ?? [];
                const mapSiteIds = mapRows.map(row => String(row[0]));
                const soundingSiteIds = readSiteIds("sounding");
                const rhoaSiteIds = readSiteIds("rhoa");
                const sectionSiteIds = readSiteIds("tTEM");
                const sameSites = (actual, expected) =>
                    actual && actual.length === expected.length &&
                    expected.every(siteId => actual.includes(siteId));
                return sameSites(mapSiteIds, expectedSites) &&
                    sameSites(soundingSiteIds, bufferedSites) &&
                    sameSites(rhoaSiteIds, bufferedSites) &&
                    expectedSites.every(siteId => sectionSiteIds?.includes(siteId));
            }""",
            arg={"expectedSites": expected_sites, "bufferedSites": buffered_sites},
            polling="raf",
            timeout=60_000,
        )

        latencies_ms.append(
            page.evaluate("performance.now() - window.__loadBenchmarkStart")
        )

    benchmark.pedantic(
        upload_and_wait_for_usable_plots,
        rounds=3,
        iterations=1,
        warmup_rounds=0,
    )

    median_ms = statistics.median(latencies_ms)
    maximum_ms = max(latencies_ms)
    benchmark.extra_info["browser-visible load median (ms)"] = round(median_ms, 2)
    benchmark.extra_info["browser-visible load max (ms)"] = round(maximum_ms, 2)
    with capsys.disabled():
        print(
            "Load-to-usable-plots latency: "
            f"median={median_ms:.2f} ms, max={maximum_ms:.2f} ms"
        )
