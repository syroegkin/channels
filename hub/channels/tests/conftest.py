import json
import os

import pytest


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run live integration tests that hit real third-party services",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live (hits real services)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, content=None, headers=None):
        self.status_code = status_code
        self._json = json_body
        if content is None and json_body is not None:
            content = json.dumps(json_body).encode("utf-8")
        elif isinstance(content, str):
            content = content.encode("utf-8")
        self.content = content or b""
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            return json.loads(self.content.decode("utf-8"))
        return self._json


class FakeSession:
    """Stand-in for requests.Session. Routes GETs via a (substring -> response) map,
    records POSTs for assertions."""

    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params=None, headers=None, **kwargs):
        self.get_calls.append((url, params))
        for needle, resp in self.routes.items():
            if needle in url:
                if callable(resp):
                    return resp(url, params=params, **kwargs)
                return resp
        raise AssertionError("no route matched URL: {0} (params={1})".format(url, params))

    def post(self, url, data=None, headers=None, **kwargs):
        self.post_calls.append((url, data))
        for needle, resp in self.routes.items():
            if needle in url:
                if callable(resp):
                    return resp(url, data=data, **kwargs)
                return resp
        raise AssertionError("no route matched URL: {0}".format(url))


def load_fixture(*parts):
    path = os.path.join(FIXTURES_DIR, *parts)
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".json"):
        return json.loads(data.decode("utf-8"))
    return data


def fixture_path(*parts):
    return os.path.join(FIXTURES_DIR, *parts)


@pytest.fixture
def fake_response():
    return FakeResponse


@pytest.fixture
def fake_session():
    return FakeSession


@pytest.fixture
def fixtures():
    return load_fixture


@pytest.fixture
def fixtures_path():
    return fixture_path
