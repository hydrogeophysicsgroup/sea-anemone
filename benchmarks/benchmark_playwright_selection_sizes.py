import pytest
from playwright.sync_api import Page

from playwright_selection_support import benchmark_selection_case


@pytest.mark.parametrize(
    ("selection_size", "case_name"),
    [
        (1, "one-site"),
        (10, "ten-sites"),
        (25, "twenty-five-sites"),
        ("all", "all-sites"),
    ],
)
def test_map_selection_latency_by_selection_size(
    page: Page,
    benchmark,
    selection_app_url: str,
    capsys,
    selection_size: int | str,
    case_name: str,
):
    benchmark_selection_case(
        page=page,
        benchmark=benchmark,
        selection_app_url=selection_app_url,
        capsys=capsys,
        selection_size=selection_size,
        case_name=case_name,
    )
