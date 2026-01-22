from pathlib import Path

from fastapi.testclient import TestClient


def test_root_serves_index_html(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    index_file = Path(__file__).resolve().parent.parent / "static" / "index.html"
    expected_content = index_file.read_text()
    assert response.text == expected_content
