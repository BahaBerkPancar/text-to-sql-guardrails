def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_item(client):
    created = client.post("/items", json={"name": "first"})
    assert created.status_code == 201
    item = created.json()
    assert client.get(f"/items/{item['id']}").json() == item


def test_missing_item_is_404(client):
    assert client.get("/items/999").status_code == 404
