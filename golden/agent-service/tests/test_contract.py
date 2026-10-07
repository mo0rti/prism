"""The contract and the code describe the same service.

`openapi.yml` in the app's folder is this service's own contract. The shared contract describes the backend, and
the tool `get_my_profile` reads the backend's `GET /api/me`, so its model of a profile must match what the shared
contract promises. Change a contract and the code together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.tools.backend_profile import ME_PATH, BackendUserProfile
from tests.support import FakeBackend, SigningKey, build_app

APP_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = APP_ROOT / "openapi.yml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def shared_contract() -> Path:
    """`shared/api-contracts/openapi.yml` of the workspace this app lives in, found by walking up from the app."""

    for parent in APP_ROOT.parents:
        candidate = parent / "shared" / "api-contracts" / "openapi.yml"
        if candidate.is_file():
            return candidate
    pytest.fail(
        "The shared API contract (shared/api-contracts/openapi.yml) is not above this app. "
        "If the service moved to its own repository, point this test at the backend's contract."
    )


def operations(contract: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method, path): operation
        for path, item in contract["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def resolve(contract: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    node: Any = contract
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return resolve(contract, node)


def json_schema(contract: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    return resolve(contract, body["content"]["application/json"]["schema"])


@pytest.fixture(scope="module")
def served(signing_key: SigningKey) -> dict[str, Any]:
    app = build_app(FakeBackend(signing_key))
    schema: dict[str, Any] = app.openapi()
    return schema


def test_the_contract_defines_the_routes_the_service_serves(served: dict[str, Any]) -> None:
    contract = load(CONTRACT)

    assert set(operations(contract)) == set(operations(served))
    for key, operation in operations(contract).items():
        assert operation["operationId"] == operations(served)[key]["operationId"], key


def test_the_contract_has_no_dev_identity_route() -> None:
    contract = load(CONTRACT)

    assert not [path for path in contract["paths"] if "dev-identity" in path]
    assert not [key for key in operations(contract) if "x-prism-dev-only" in operations(contract)[key]]


def test_the_request_and_response_bodies_match(served: dict[str, Any]) -> None:
    contract = load(CONTRACT)
    declared = operations(contract)[("post", "/api/assist")]
    actual = operations(served)[("post", "/api/assist")]

    contract_request = json_schema(contract, declared["requestBody"])
    served_request = json_schema(served, actual["requestBody"])
    assert set(contract_request["properties"]) == set(served_request["properties"]) == {"question"}
    assert contract_request["required"] == served_request["required"] == ["question"]
    assert (
        contract_request["properties"]["question"]["maxLength"] == served_request["properties"]["question"]["maxLength"]
    )

    contract_response = json_schema(contract, declared["responses"]["200"])
    served_response = json_schema(served, actual["responses"]["200"])
    assert set(contract_response["properties"]) == set(served_response["properties"])
    assert set(contract_response["required"]) == set(served_response["required"])


def test_every_error_status_the_contract_names_is_one_the_service_answers(served: dict[str, Any]) -> None:
    contract = load(CONTRACT)
    declared = {code for code in operations(contract)[("post", "/api/assist")]["responses"]}
    actual = {code for code in operations(served)[("post", "/api/assist")]["responses"]}

    assert declared <= actual | {"200"}


def test_the_security_the_contract_states_is_the_security_the_service_enforces(signing_key: SigningKey) -> None:
    contract = load(CONTRACT)
    assert contract["security"] == [{"bearerAuth": []}]
    assert contract["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }

    with TestClient(
        build_app(FakeBackend(signing_key)), base_url="http://localhost", client=("127.0.0.1", 50000)
    ) as client:
        for (method, path), operation in operations(contract).items():
            response = client.request(method, path, json={"question": "hi"} if method == "post" else None)
            if operation.get("security") == []:
                assert response.status_code != 401, f"{method} {path} is open"
            else:
                assert response.status_code == 401, f"{method} {path} needs a bearer token"


def test_the_tools_model_of_a_profile_covers_what_the_shared_contract_promises() -> None:
    shared = load(shared_contract())
    get_me = operations(shared)[("get", ME_PATH)]
    profile = json_schema(shared, get_me["responses"]["200"])

    modelled = set(BackendUserProfile.model_fields)
    assert set(profile["required"]) <= modelled, "a field the backend always sends is one the tool reads"
    assert modelled <= set(profile["properties"]), "the tool reads no field the backend does not define"
    assert shared["security"] == [{"bearerAuth": []}] and "security" not in get_me, (
        "GET /api/me needs the caller's bearer token"
    )
