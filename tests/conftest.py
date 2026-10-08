import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_addoption(parser):
    parser.addoption('--run-model', action='store_true', help='Run real GPU/model integration checks')


def pytest_collection_modifyitems(config, items):
    if config.getoption('--run-model'):
        return
    import pytest
    for item in items:
        if 'model' in item.keywords:
            item.add_marker(pytest.mark.skip(reason='Use --run-model to load the local model'))
