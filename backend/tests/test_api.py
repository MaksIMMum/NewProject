import uuid

from httpx import AsyncClient


async def make_participant(client: AsyncClient, name: str, email: str) -> dict:
    response = await client.post("/api/participants", json={"name": name, "email": email})
    assert response.status_code == 201, response.text
    return response.json()


def meeting_payload(**overrides) -> dict:
    payload = {
        "title": "Sprint planning",
        "description": "Plan sprint 12",
        "starts_at": "2026-09-22T10:00:00+03:00",
        "ends_at": "2026-09-22T11:00:00+03:00",
        "place": "Room 204",
        "participant_ids": [],
    }
    payload.update(overrides)
    return payload


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_root_redirect(client: AsyncClient) -> None:
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/api/docs"



async def test_create_meeting_with_participants(client: AsyncClient) -> None:
    olena = await make_participant(client, "Olena Koval", "olena@example.com")
    taras = await make_participant(client, "Taras Shevchuk", "taras@example.com")

    response = await client.post(
        "/api/meetings",
        json=meeting_payload(participant_ids=[olena["id"], taras["id"], olena["id"]]),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    uuid.UUID(body["id"])
    assert body["starts_at"] == "2026-09-22T07:00:00Z"
    assert body["ends_at"] == "2026-09-22T08:00:00Z"
    assert [p["id"] for p in body["participants"]] == [olena["id"], taras["id"]]


async def test_same_participant_in_many_meetings(client: AsyncClient) -> None:
    olena = await make_participant(client, "Olena Koval", "olena@example.com")
    for title in ("A", "B"):
        response = await client.post(
            "/api/meetings", json=meeting_payload(title=title, participant_ids=[olena["id"]])
        )
        assert response.status_code == 201

    meetings = (await client.get("/api/meetings")).json()
    assert all(m["participants"][0]["id"] == olena["id"] for m in meetings)


async def test_create_meeting_end_before_start(client: AsyncClient) -> None:
    response = await client.post(
        "/api/meetings",
        json=meeting_payload(ends_at="2026-09-22T09:00:00+03:00"),
    )
    assert response.status_code == 422


async def test_create_meeting_empty_title(client: AsyncClient) -> None:
    response = await client.post("/api/meetings", json=meeting_payload(title="   "))
    assert response.status_code == 422


async def test_create_meeting_unknown_participant(client: AsyncClient) -> None:
    unknown = str(uuid.uuid4())
    response = await client.post("/api/meetings", json=meeting_payload(participant_ids=[unknown]))
    assert response.status_code == 422
    assert unknown in response.json()["detail"]


async def test_list_meetings_sorted_by_start(client: AsyncClient) -> None:
    await client.post(
        "/api/meetings",
        json=meeting_payload(
            title="Later", starts_at="2026-10-01T10:00:00Z", ends_at="2026-10-01T11:00:00Z"
        ),
    )
    await client.post(
        "/api/meetings",
        json=meeting_payload(
            title="Sooner", starts_at="2026-09-25T10:00:00Z", ends_at="2026-09-25T11:00:00Z"
        ),
    )

    response = await client.get("/api/meetings")
    assert [m["title"] for m in response.json()] == ["Sooner", "Later"]


async def test_update_meeting(client: AsyncClient) -> None:
    olena = await make_participant(client, "Olena Koval", "olena@example.com")
    taras = await make_participant(client, "Taras Shevchuk", "taras@example.com")
    created = (
        await client.post("/api/meetings", json=meeting_payload(participant_ids=[olena["id"]]))
    ).json()

    response = await client.put(
        f"/api/meetings/{created['id']}",
        json=meeting_payload(
            title="Sprint review",
            starts_at="2026-09-23T14:00:00Z",
            ends_at="2026-09-23T15:00:00Z",
            participant_ids=[taras["id"]],
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == created["id"]
    assert body["title"] == "Sprint review"
    assert body["starts_at"] == "2026-09-23T14:00:00Z"
    assert [p["id"] for p in body["participants"]] == [taras["id"]]
    assert (await client.get(f"/api/meetings/{created['id']}")).json() == body
    assert len((await client.get("/api/participants")).json()) == 2


async def test_update_meeting_validation(client: AsyncClient) -> None:
    created = (await client.post("/api/meetings", json=meeting_payload())).json()
    url = f"/api/meetings/{created['id']}"

    bad_times = meeting_payload(ends_at="2026-09-22T09:00:00+03:00")
    assert (await client.put(url, json=bad_times)).status_code == 422
    unknown = meeting_payload(participant_ids=[str(uuid.uuid4())])
    assert (await client.put(url, json=unknown)).status_code == 422
    assert (await client.get(url)).json()["title"] == created["title"]


async def test_update_missing_meeting(client: AsyncClient) -> None:
    response = await client.put(f"/api/meetings/{uuid.uuid4()}", json=meeting_payload())
    assert response.status_code == 404


async def test_delete_meeting_keeps_participants(client: AsyncClient) -> None:
    olena = await make_participant(client, "Olena Koval", "olena@example.com")
    created = (
        await client.post("/api/meetings", json=meeting_payload(participant_ids=[olena["id"]]))
    ).json()

    response = await client.delete(f"/api/meetings/{created['id']}")
    assert response.status_code == 204

    assert (await client.get(f"/api/meetings/{created['id']}")).status_code == 404
    participants = (await client.get("/api/participants")).json()
    assert [p["id"] for p in participants] == [olena["id"]]


async def test_delete_missing_meeting(client: AsyncClient) -> None:
    response = await client.delete(f"/api/meetings/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_invalid_uuid_in_path(client: AsyncClient) -> None:
    response = await client.get("/api/meetings/not-a-uuid")
    assert response.status_code == 422


async def test_duplicate_participant_email(client: AsyncClient) -> None:
    await make_participant(client, "Olena Koval", "olena@example.com")
    response = await client.post(
        "/api/participants", json={"name": "Other Olena", "email": "OLENA@example.com"}
    )
    assert response.status_code == 409


async def test_invalid_participant_email(client: AsyncClient) -> None:
    response = await client.post("/api/participants", json={"name": "X", "email": "not-an-email"})
    assert response.status_code == 422
