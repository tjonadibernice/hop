async def topic_ids(client, count: int) -> list[int]:
    topics = (await client.get("/topics")).json()
    return [topic["id"] for topic in topics[:count]]


async def test_interests_require_login(client):
    assert (await client.get("/me/interests")).status_code == 401
    response = await client.put("/me/interests", json={"topic_ids": [1, 2, 3]})
    assert response.status_code == 401


async def test_new_user_has_no_interests(logged_in_client):
    response = await logged_in_client.get("/me/interests")

    assert response.status_code == 200
    assert response.json() == {"topics": []}


async def test_set_and_get_interests(logged_in_client):
    ids = await topic_ids(logged_in_client, 3)

    response = await logged_in_client.put("/me/interests", json={"topic_ids": ids})

    assert response.status_code == 200
    assert [t["id"] for t in response.json()["topics"]] == ids
    saved = (await logged_in_client.get("/me/interests")).json()
    assert [t["id"] for t in saved["topics"]] == ids


async def test_set_interests_replaces_previous_ones(logged_in_client):
    ids = await topic_ids(logged_in_client, 6)
    await logged_in_client.put("/me/interests", json={"topic_ids": ids[:3]})

    await logged_in_client.put("/me/interests", json={"topic_ids": ids[3:]})

    saved = (await logged_in_client.get("/me/interests")).json()
    assert [t["id"] for t in saved["topics"]] == ids[3:]


async def test_interests_need_at_least_three(logged_in_client):
    ids = await topic_ids(logged_in_client, 2)

    response = await logged_in_client.put("/me/interests", json={"topic_ids": ids})

    assert response.status_code == 422


async def test_interests_reject_duplicates(logged_in_client):
    ids = await topic_ids(logged_in_client, 2)

    response = await logged_in_client.put(
        "/me/interests", json={"topic_ids": [ids[0], ids[0], ids[1]]}
    )

    assert response.status_code == 422


async def test_interests_reject_unknown_topics(logged_in_client):
    ids = await topic_ids(logged_in_client, 2)

    response = await logged_in_client.put(
        "/me/interests", json={"topic_ids": [*ids, 999_999]}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown topic."}
