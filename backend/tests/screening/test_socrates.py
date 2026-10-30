"""Validation checks for external report parsing and evidence labels."""

from datetime import timedelta
import json

from scripts.validate_socrates import SocratesEvent, cached_download, compare, parse_socrates

from .test_screening import screen


def test_socrates_csv_reverses_pair_and_dse_epochs():
    csv = ("NORAD_CAT_ID_1,NORAD_CAT_ID_2,TCA,TCA_RANGE,TCA_RELATIVE_SPEED,DSE_1,DSE_2\n"
           "99999,25544,2026-10-30T01:00:00Z,1.234,8.5,0.25,0.5\n")
    event, = parse_socrates(csv, 25544)
    assert (event.primary_id, event.secondary_id, event.miss_m) == (25544, 99999, 1234)
    assert event.primary_epoch == event.tca - timedelta(days=0.5)
    assert event.secondary_epoch == event.tca - timedelta(days=0.25)


def test_comparison_distinguishes_matching_geometry_from_different_elements():
    run = screen()
    encounter = run.encounters[0]
    reference = SocratesEvent(25544, encounter.secondary_norad_id, encounter.tca,
                              encounter.as_conjunction()["missDistanceM"],
                              encounter.as_conjunction()["relSpeedKms"],
                              encounter.primary.epoch, encounter.secondary.epoch)
    matched = compare(run, [reference], catalog_ids={25544, encounter.secondary_norad_id})
    assert matched["statusCounts"] == {"MATCH": 1}
    assert matched["validationPassed"]
    shifted = SocratesEvent(reference.primary_id, reference.secondary_id, reference.tca,
                            reference.miss_m, reference.relative_speed_km_s,
                            reference.primary_epoch - timedelta(hours=1), reference.secondary_epoch)
    assert compare(run, [shifted])["statusCounts"] == {"DIFFERENT_ELEMENTS": 1}
    absent = SocratesEvent(25544, 99999, encounter.tca, 100, 8, None, None)
    assert compare(run, [absent], catalog_ids={25544})["statusCounts"] == {"OUTSIDE_CATALOG": 1}


def test_cached_download_does_not_repeat_request_within_two_hours(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, _maximum):
            return json.dumps([{"NORAD_CAT_ID": 25544}]).encode()

    calls = []

    def fetch(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("scripts.validate_socrates.urlopen", fetch)
    url = "https://example.invalid/gp.php?GROUP=active&FORMAT=JSON"
    first = cached_download(url, tmp_path)
    second = cached_download(url, tmp_path)
    assert first == second
    assert first.suffix == ".json"
    assert len(calls) == 1
