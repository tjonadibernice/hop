async def test_list_topics_returns_all_launch_topics(client):
    response = await client.get("/topics")

    assert response.status_code == 200
    topics = response.json()
    assert len(topics) == 15
    assert topics[0] == {
        "id": topics[0]["id"],
        "slug": "productivity-focus",
        "name": "Productivity & focus",
    }
