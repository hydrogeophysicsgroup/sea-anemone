import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import plotly.io as pio
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import temframe
from session import Session
from panels import dbdtSection, dbdtSounding, rhoaSounding
from model import ModelGraph
from map import Map
from inversion_panels import MultiInversion
from anemone.inversion import LogResistivity
from torch import tensor


@pytest.fixture(scope="session")
def sample_session():
    archive_path = ROOT / "Data" / "L003_S033_2025_1113_125719.zip"
    with archive_path.open("rb") as archive:
        data, forwards = temframe.from_zip_content(archive.read())

    session = Session(data=data, forwards=forwards)
    sys.modules["__main__"].sesh = session
    session.update_site_table()
    return session


@pytest.fixture(scope="session")
def saved_session_folder(sample_session, tmp_path_factory):
    folder = str(tmp_path_factory.mktemp("sample-session")) + os.sep
    sample_session.save(folder)
    return folder


@pytest.fixture(scope="session")
def plot_panels(sample_session):
    selected_site = sample_session.site.site_id.iloc[len(sample_session.site) // 2]
    return {
        "map": Map(data=sample_session.site),
        "section": dbdtSection(dataframe=sample_session.data),
        "sounding": dbdtSounding(dataframe=sample_session.data),
        "apparent_resistivity": rhoaSounding(dataframe=sample_session.data),
        "single_site_sounding": dbdtSounding(
            dataframe=sample_session.data[
                sample_session.data.site_id == selected_site
            ].copy()
        ),
    }


@pytest.fixture(scope="session")
def model_graph_panel(sample_session):
    site_ids = sample_session.site.site_id.dropna().unique().tolist()
    model_rows = []
    for site_id in site_ids:
        model_rows.extend([
            {
                "site_id": site_id,
                "layer": 0,
                "resistivity": 20.0,
                "top_depth": 0.0,
                "bottom_depth": 10.0,
            },
            {
                "site_id": site_id,
                "layer": 1,
                "resistivity": 60.0,
                "top_depth": 10.0,
                "bottom_depth": 35.0,
            },
        ])
    panel = ModelGraph(dataframe=pd.DataFrame(model_rows))
    panel.buffer_len = len(site_ids)
    return panel


@pytest.mark.benchmark(group="session loading")
def test_load_usf_archive(benchmark):
    archive_path = ROOT / "Data" / "L003_S033_2025_1113_125719.zip"

    def load_archive():
        with archive_path.open("rb") as archive:
            return temframe.from_zip_content(archive.read())

    data, forwards = benchmark.pedantic(
        load_archive, rounds=3, iterations=1, warmup_rounds=0
    )
    assert len(data) > 0
    assert len(forwards) == 2


@pytest.mark.benchmark(group="session loading")
def test_restore_saved_session(benchmark, saved_session_folder):
    session = benchmark.pedantic(
        Session.from_folder,
        args=(saved_session_folder,),
        rounds=3,
        iterations=1,
        warmup_rounds=0,
    )
    assert len(session.data) > 0
    assert len(session.forwards) == 2


@pytest.mark.benchmark(group="plotting")
@pytest.mark.parametrize(
    "panel_name",
    ["map", "section", "sounding", "apparent_resistivity", "single_site_sounding"],
)
def test_render_plot(benchmark, plot_panels, panel_name):
    figure = benchmark.pedantic(
        plot_panels[panel_name].render,
        rounds=3,
        iterations=1,
        warmup_rounds=0,
    )
    assert figure is not None


def test_rhoa_lines_keep_site_boundaries(plot_panels):
    observed_panel = plot_panels["apparent_resistivity"]
    synthetic_panel = rhoaSounding(
        dataframe=observed_panel.dataframe.assign(
            dbdt_syn=observed_panel.dataframe["dbdt"]
        )
    )

    for panel in (observed_panel, synthetic_panel):
        figure = panel.render()
        line_traces = [trace for trace in figure.data if trace.mode == "lines"]

        assert len(line_traces) == 2
        for trace in line_traces:
            current_site = None
            for x_value, point_data in zip(trace.x, trace.customdata):
                site_id = point_data[2]
                if x_value is None:
                    assert site_id is None
                    current_site = None
                    continue
                if current_site is None:
                    current_site = site_id
                assert site_id == current_site


@pytest.mark.benchmark(group="plotting")
def test_render_model_graph(benchmark, model_graph_panel):
    figure = benchmark.pedantic(
        model_graph_panel.render,
        rounds=3,
        iterations=1,
        warmup_rounds=0,
    )
    expected_sites = set(model_graph_panel.dataframe["site_id"].unique())
    assert {trace.name for trace in figure.data} == {
        str(site_id) for site_id in expected_sites
    }


@pytest.mark.benchmark(group="plot serialization")
@pytest.mark.parametrize(
    "panel_name",
    ["map", "section", "sounding", "apparent_resistivity", "single_site_sounding"],
)
def test_serialize_plot(benchmark, plot_panels, panel_name):
    figure = plot_panels[panel_name].render()
    payload = benchmark.pedantic(
        pio.to_json,
        args=(figure,),
        kwargs={"validate": False},
        rounds=3,
        iterations=1,
        warmup_rounds=0,
    )
    assert payload


@pytest.mark.benchmark(group="inversion")
def test_invert_single_site(benchmark, sample_session):
    site_id = sample_session.site.site_id.iloc[len(sample_session.site) // 2]
    dmfwr = sample_session.dmfwr
    result = {}

    def invert():
        with redirect_stdout(io.StringIO()):
            result["value"] = temframe.invert_site(
                sample_session.data,
                dmfwr,
                site_id=site_id,
                res_start=10.0,
                max_iterations=20,
            )

    benchmark.pedantic(invert, rounds=3, iterations=1, warmup_rounds=0)
    layers, site_data, _ = result["value"]
    assert len(layers) > 0
    assert len(site_data) > 0


@pytest.mark.benchmark(group="inversion")
def test_invert_all_sites(benchmark, sample_session):
    dmfwr = sample_session.dmfwr
    panel = MultiInversion(dataframe=sample_session.data)
    depth = panel.build_depth_from_loop(time=sample_session.data.time.unique()[-1])
    rho = tensor(10.0).repeat(31)
    res_start = LogResistivity.smooth(rho, tensor(depth[:-1]))
    result = {}

    def invert():
        with redirect_stdout(io.StringIO()):
            result["value"] = temframe.invert(
                sample_session.data,
                dmfwr,
                res_start,
                vc=0.8,
                hc=0.3,
                max_iterations=50,
            )

    benchmark.pedantic(invert, rounds=2, iterations=1, warmup_rounds=0)
    models, updated_data, overview = result["value"]
    assert len(models) > 0
    assert len(updated_data) == len(sample_session.data)
    assert len(overview) == sample_session.site.site_id.nunique()
