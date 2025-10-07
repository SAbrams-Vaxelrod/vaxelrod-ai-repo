import os
import json
import boto3
import random

# Initialize AWS SQS client
sqs = boto3.client('sqs')

SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')

def lambda_handler(event, context):
    """
    A functional scraper that sends a sample opportunity to the SQS queue
    for end-to-end testing.
    """
    print("Vaxelrod Scraper function started.")
    
    if not SQS_QUEUE_URL:
        print("[ERROR] SQS_QUEUE_URL environment variable is not set.")
        return {'statusCode': 500, 'body': 'SQS_QUEUE_URL not configured.'}

    solicitation_id = f"TEST-RFQ-{random.randint(1000, 9999)}"
    message_body = {
      "solicitation_id": solicitation_id,
      "customer_name": "Department of Commerce",
      "opportunity_details": "Request for pricing on standard office IT equipment.",
      "requested_products": [
        {"product_name": "Lenovo ThinkPad T14", "quantity": 10},
        {"product_name": "Dell UltraSharp 27 inch Monitor", "quantity": 10}
      ]
    }

    try:
        print(f"Sending opportunity {solicitation_id} to SQS queue...")
        sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(message_body))
        print("Message sent successfully.")
        return {
            'statusCode': 200,
            'body': json.dumps(f"Successfully sent opportunity {solicitation_id} to queue.")
        }
    except Exception as e:
        print(f"[ERROR] Failed to send message to SQS: {e}")
        raise e
