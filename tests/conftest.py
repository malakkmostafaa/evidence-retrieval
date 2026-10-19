import pytest


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False, help="run tests that use the real network")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: uses the real network (skipped unless --run-live)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="live network test; use --run-live")
    for it in items:
        if "live" in it.keywords:
            it.add_marker(skip)
