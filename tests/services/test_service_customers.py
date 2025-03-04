import re
import uuid
from datetime import datetime
from typing import AsyncGenerator, Generator, cast

import httpx
import pytest
import pytest_asyncio
from docker.models.images import Image
from tomodachi.envelope.json_base import JsonBase
from types_aiobotocore_sns import SNSClient
from types_aiobotocore_sqs import SQSClient

from tomodachi_testcontainers import LocalStackContainer, TomodachiContainer
from tomodachi_testcontainers.clients import SNSSQSTestClient
from tomodachi_testcontainers.pytest.assertions import UUID4_PATTERN, assert_datetime_within_range
from tomodachi_testcontainers.pytest.async_probes import probe_until
from tomodachi_testcontainers.utils import get_available_port

pytestmark = pytest.mark.usefixtures("_purge_queues_on_teardown")


@pytest.fixture(scope="module")
def snssqs_tc(localstack_sns_client: SNSClient, localstack_sqs_client: SQSClient) -> SNSSQSTestClient:
    return SNSSQSTestClient.create(localstack_sns_client, localstack_sqs_client)


@pytest_asyncio.fixture(scope="module")
async def _create_topics_and_queues(snssqs_tc: SNSSQSTestClient) -> None:
    await snssqs_tc.subscribe_to(topic="order--created", queue="customer--order-created")


@pytest_asyncio.fixture()
async def _purge_queues_on_teardown(snssqs_tc: SNSSQSTestClient) -> AsyncGenerator[None, None]:
    yield
    await snssqs_tc.purge_queue("customer--order-created")


@pytest.fixture(scope="module")
def service_customers_container(
    testcontainers_docker_image: Image, localstack_container: LocalStackContainer, _create_topics_and_queues: None
) -> Generator[TomodachiContainer, None, None]:
    with (
        TomodachiContainer(
            image=str(testcontainers_docker_image.id),
            edge_port=get_available_port(),
            http_healthcheck_path="/health",
        )
        .with_env("AWS_REGION", "us-east-1")
        .with_env("AWS_ACCESS_KEY_ID", "testing")
        .with_env("AWS_SECRET_ACCESS_KEY", "testing")
        .with_env("AWS_SNS_ENDPOINT_URL", localstack_container.get_internal_url())
        .with_env("AWS_SQS_ENDPOINT_URL", localstack_container.get_internal_url())
        .with_env("AWS_DYNAMODB_ENDPOINT_URL", localstack_container.get_internal_url())
        .with_env("DYNAMODB_TABLE_NAME", "customers")
        .with_command("tomodachi run src/customers.py --production")
    ) as container:
        yield cast(TomodachiContainer, container)


@pytest_asyncio.fixture(scope="module")
async def http_client(service_customers_container: TomodachiContainer) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=service_customers_container.get_external_url()) as client:
        yield client


@pytest.mark.asyncio()
async def test_customer_not_found(http_client: httpx.AsyncClient) -> None:
    customer_id = uuid.uuid4()
    response = await http_client.get(f"/customer/{customer_id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": "Customer not found",
        "_links": {
            "self": {"href": f"/customer/{customer_id}"},
        },
    }


@pytest.mark.asyncio()
async def test_create_customer(http_client: httpx.AsyncClient) -> None:
    response = await http_client.post("/customers", json={"name": "John Doe"})
    body = response.json()
    customer_id = body["customer_id"]
    get_customer_link = body["_links"]["self"]["href"]

    assert response.status_code == 200
    assert re.match(UUID4_PATTERN, customer_id)
    assert body == {
        "customer_id": customer_id,
        "_links": {
            "self": {"href": f"/customer/{customer_id}"},
        },
    }

    response = await http_client.get(get_customer_link)
    body = response.json()

    assert response.status_code == 200
    assert_datetime_within_range(datetime.fromisoformat(body["created_at"]))
    assert body == {
        "customer_id": customer_id,
        "name": "John Doe",
        "orders": [],
        "created_at": body["created_at"],
        "_links": {
            "self": {"href": f"/customer/{customer_id}"},
        },
    }


@pytest.mark.asyncio()
async def test_register_created_order(http_client: httpx.AsyncClient, snssqs_tc: SNSSQSTestClient) -> None:
    response = await http_client.post("/customers", json={"name": "John Doe"})
    body = response.json()
    customer_id = body["customer_id"]
    get_customer_link = body["_links"]["self"]["href"]

    assert response.status_code == 200

    order_ids = ["6c403295-2755-4178-a4f1-e3b698927971", "c8bb390a-71f4-4e8f-8879-c92261b0e18e"]
    for order_id in order_ids:
        await snssqs_tc.publish(
            topic="order--created",
            data={
                "event_id": str(uuid.uuid4()),
                "order_id": order_id,
                "customer_id": customer_id,
                "products": ["foo", "bar"],
                "created_at": datetime.utcnow().isoformat(),
            },
            envelope=JsonBase,
        )

    async def _new_order_associated_with_customer() -> None:
        response = await http_client.get(get_customer_link)
        body = response.json()

        assert response.status_code == 200
        assert_datetime_within_range(datetime.fromisoformat(body["created_at"]))
        assert body == {
            "customer_id": customer_id,
            "name": "John Doe",
            "orders": [
                {"order_id": order_ids[0]},
                {"order_id": order_ids[1]},
            ],
            "created_at": body["created_at"],
            "_links": {
                "self": {"href": f"/customer/{customer_id}"},
            },
        }

    await probe_until(_new_order_associated_with_customer)
