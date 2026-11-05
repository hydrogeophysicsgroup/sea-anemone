from playwright.sync_api import Page

from playwright_selection_support import benchmark_selection_case


def test_map_selection_updates_linked_plots(
    page: Page, benchmark, selection_app_url: str, capsys
):
    benchmark_selection_case(
        page=page,
        benchmark=benchmark,
        selection_app_url=selection_app_url,
        capsys=capsys,
        selection_size=1,
        case_name="one-site",
    )
