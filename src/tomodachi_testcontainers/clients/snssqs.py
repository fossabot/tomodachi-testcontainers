import inspect
import json
from contextlib import suppress
from typing import Any, Dict, List, Optional, Protocol, Type, TypeVar, Union

from botocore.exceptions import ClientError
from google.protobuf.message import Message
from types_aiobotocore_sns import SNSClient
from types_aiobotocore_sns.type_defs import MessageAttributeValueTypeDef
from types_aiobotocore_sqs import SQSClient
from types_aiobotocore_sqs.literals import QueueAttributeFilterType, QueueAttributeNameType

__all__ = [
    "SNSSQSTestClient",
]

MessageType = TypeVar("MessageType")

TopicARNType = str

QueueARNType = str
QueueURLType = str


class TopicDoesNotExist(Exception):
    pass


class QueueDoesNotExist(Exception):
    pass


class _TomodachiSNSSQSEnvelopeStatic(Protocol):
    @classmethod
    async def build_message(
        cls: "_TomodachiSNSSQSEnvelopeStatic", service: Any, topic: str, data: Any, **kwargs: Any
    ) -> str:
        ...

    @classmethod
    async def parse_message(cls: "_TomodachiSNSSQSEnvelopeStatic", payload: str, **kwargs: Any) -> Union[dict, tuple]:
        ...


class _TomodachiSNSSQSEnvelopeInstance(Protocol):
    async def build_message(
        self: "_TomodachiSNSSQSEnvelopeInstance", service: Any, topic: str, data: Any, **kwargs: Any
    ) -> str:
        ...

    async def parse_message(
        self: "_TomodachiSNSSQSEnvelopeInstance", payload: str, **kwargs: Any
    ) -> Union[dict, tuple]:
        ...


TomodachiSNSSQSEnvelope = Union[_TomodachiSNSSQSEnvelopeStatic, _TomodachiSNSSQSEnvelopeInstance]


class SNSSQSTestClient:
    """Wraps aiobotocore SNS and SQS clients and provides common methods for testing SNS SQS integrations."""

    def __init__(self, sns_client: SNSClient, sqs_client: SQSClient) -> None:
        self.sns_client = sns_client
        self.sqs_client = sqs_client

    async def create_topic(self, topic: str, *, fifo: bool = False) -> TopicARNType:
        with suppress(TopicDoesNotExist):
            return await self.get_topic_arn(topic)
        topic_attributes: Dict[str, str] = {}
        if fifo:
            topic_attributes.update(
                {
                    "FifoTopic": "true",
                    "ContentBasedDeduplication": "false",
                }
            )
        create_topic_response = await self.sns_client.create_topic(Name=topic, Attributes=topic_attributes)
        return create_topic_response["TopicArn"]

    async def create_queue(self, queue: str, *, fifo: bool = False) -> QueueARNType:
        with suppress(QueueDoesNotExist):
            return await self.get_queue_arn(queue)
        queue_attributes: Dict[QueueAttributeNameType, str] = {}
        if fifo:
            queue_attributes.update(
                {
                    "FifoQueue": "true",
                    "ContentBasedDeduplication": "false",
                }
            )
        await self.sqs_client.create_queue(QueueName=queue, Attributes=queue_attributes)
        queue_attributes = await self.get_queue_attributes(queue, attributes=["QueueArn"])
        return queue_attributes["QueueArn"]

    async def subscribe_to(
        self,
        topic: str,
        queue: str,
        subscribe_attributes: Optional[Dict[str, str]] = None,
        *,
        fifo: bool = False,
    ) -> None:
        """Subscribe a SQS queue to a SNS topic; create the topic and queue if they don't exist."""
        topic_arn = await self.create_topic(topic, fifo=fifo)
        queue_arn = await self.create_queue(queue, fifo=fifo)
        await self.sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=queue_arn,
            Attributes=subscribe_attributes or {},
        )

    async def receive(
        self, queue: str, envelope: TomodachiSNSSQSEnvelope, message_type: Type[MessageType], max_messages: int = 10
    ) -> List[MessageType]:
        queue_url = await self.get_queue_url(queue)

        received_messages_response = await self.sqs_client.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=max_messages
        )
        received_messages = received_messages_response.get("Messages")
        if not received_messages:
            return []

        if inspect.isclass(message_type) and issubclass(message_type, Message):
            proto_class = message_type
        else:
            proto_class = None

        parsed_messages: List[MessageType] = []
        for received_message in received_messages:
            payload = json.loads(received_message["Body"])["Message"]
            parsed_message = await envelope.parse_message(payload=payload, proto_class=proto_class)
            parsed_messages.append(parsed_message[0]["data"])
            await self.sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=received_message["ReceiptHandle"])
        return parsed_messages

    async def publish(
        self,
        topic: str,
        data: Any,
        envelope: TomodachiSNSSQSEnvelope,
        message_attributes: Optional[Dict[str, MessageAttributeValueTypeDef]] = None,
        message_deduplication_id: Optional[str] = None,
        message_group_id: Optional[str] = None,
    ) -> None:
        topic_arn = await self.get_topic_arn(topic)
        message = await envelope.build_message(service={}, topic=topic, data=data)
        sns_publish_kwargs: Dict[str, Any] = {}
        if message_attributes:
            sns_publish_kwargs["MessageAttributes"] = message_attributes
        if message_deduplication_id:
            sns_publish_kwargs["MessageDeduplicationId"] = message_deduplication_id
        if message_group_id:
            sns_publish_kwargs["MessageGroupId"] = message_group_id
        await self.sns_client.publish(TopicArn=topic_arn, Message=message, **sns_publish_kwargs)

    async def get_topic_arn(self, topic: str) -> str:
        list_topics_response = await self.sns_client.list_topics()
        topic_arn = next((v["TopicArn"] for v in list_topics_response["Topics"] if v["TopicArn"].endswith(topic)), None)
        if not topic_arn:
            raise TopicDoesNotExist(topic)
        return topic_arn

    async def get_topic_attributes(self, topic: str) -> Dict[str, str]:
        topic_arn = await self.get_topic_arn(topic)
        get_topic_attributes_response = await self.sns_client.get_topic_attributes(TopicArn=topic_arn)
        return get_topic_attributes_response["Attributes"]

    async def get_queue_arn(self, queue: str) -> str:
        attributes = await self.get_queue_attributes(queue, attributes=["QueueArn"])
        return attributes["QueueArn"]

    async def get_queue_url(self, queue: str) -> str:
        try:
            get_queue_response = await self.sqs_client.get_queue_url(QueueName=queue)
            return get_queue_response["QueueUrl"]
        except ClientError as exc:
            raise QueueDoesNotExist(queue) from exc

    async def get_queue_attributes(
        self, queue: str, attributes: List[QueueAttributeFilterType]
    ) -> Dict[QueueAttributeNameType, str]:
        queue_url = await self.get_queue_url(queue)
        get_queue_attributes_response = await self.sqs_client.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=attributes
        )
        return get_queue_attributes_response["Attributes"]
