import os
import json
import time
import boto3
import random

sqs = boto3.client('sqs')
SQS_QUEUE_URL = os.environ['SQS_QUEUE_URL']

def lambda_handler(event, context):
    """
    Emit a realistic sample opportunity to SQS (placeholder for real scraping).
    """
    solicitation_id = f"TEST-RFQ-{random.randint(1000, 9999)}"
    payload = {
        "solicitation_id": solicitation_id,
        "buyer": "Demo Agency",
        "estimatedBudget": "$5,000",
        "dueDate": time.strftime("%Y-%m-%d"),
        "url": "https://example.com/solicitations/demo",
        "source": "demo"
    }
    
    sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(payload))
    return {"statusCode": 200, "body": json.dumps(f"Queued {solicitation_id}")}

