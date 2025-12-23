import pytest
from fastapi.testclient import TestClient

from impostor.main import app_factory
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:7-alpine") as c:
        host = c.get_container_host_ip()
        port = c.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
def app(redis_url):
    return app_factory(redis_url)


@pytest.fixture
def client(app):
    with TestClient(app) as tc:
        yield tc
