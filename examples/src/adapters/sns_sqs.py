import os

from aiobotocore.session import get_session
from types_aiobotocore_sns import SNSClient
from types_aiobotocore_sqs import SQSClient


def get_sns_client() -> SNSClient:
    return get_session().create_client(
        "sns",
        region_name=os.environ["AWS_REGION"],
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        endpoint_url=os.getenv("AWS_SNS_ENDPOINT_URL"),
    )


def get_sqs_client() -> SQSClient:
    return get_session().create_client(
        "sqs",
        region_name=os.environ["AWS_REGION"],
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        endpoint_url=os.getenv("AWS_SQS_ENDPOINT_URL"),
    )
