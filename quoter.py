import os
import json
import logging
import time
import boto3
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from botocore.exceptions import ClientError

# Setup logging per expert guide to get detailed insights
log = logging.getLogger()
log.setLevel(logging.INFO)

# Initialize AWS Clients
s3 = boto3.client('s3')
ses = boto3.client('ses')
secretsmanager = boto3.client('secretsmanager')

# Load Environment Variables for configuration
S3_BUCKET_NAME = os.environ['S3_BUCKET_NAME']
PRODUCT_CATALOG_KEY = os.environ['PRODUCT_CATALOG_KEY']
SECRET_NAME = os.environ['GEMINI_API_KEY_SECRET_NAME']
SENDER_EMAIL = os.environ['SENDER_EMAIL']
RECIPIENT_EMAIL = os.environ['RECIPIENT_EMAIL']

def get_gemini_api_key():
    """Retrieves and robustly parses the Gemini API key from Secrets Manager."""
    try:
        response = secretsmanager.get_secret_value(SecretId=SECRET_NAME)
        secret_string = response.get('SecretString')
        if not secret_string:
            raise ValueError("SecretString from Secrets Manager is empty.")
        
        # **EXPERT FIX**: Attempt to parse as JSON first, but fall back to raw string
        # This handles secrets stored as {"api_key": "..."} or just the key itself.
        try:
            secret_data = json.loads(secret_string)
            key = secret_data.get('GEMINI_API_KEY') or secret_data.get('api_key') or secret_string
            return key
        except json.JSONDecodeError:
            return secret_string
            
    except ClientError as e:
        log.exception(f"Fatal error: Could not retrieve secret '{SECRET_NAME}' from AWS Secrets Manager.")
        raise

def configure_gemini():
    """Configures the Gemini client and logs the SDK version for verification."""
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Failed to get a valid Gemini API key from Secrets Manager.")
    
    genai.configure(api_key=api_key)
    # **EXPERT FIX**: Log the SDK version to confirm the correct one is installed.
    log.info({"message": "Gemini configured successfully", "gemini_sdk_version": getattr(genai, '__version__', 'unknown')})

def load_product_catalog():
    """Downloads and loads the product catalog from S3 into a pandas DataFrame."""
    log.info(f"Loading catalog '{PRODUCT_CATALOG_KEY}' from bucket '{S3_BUCKET_NAME}'")
    obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=PRODUCT_CATALOG_KEY)
    # Use 'utf-8-sig' to handle potential Byte Order Mark (BOM) in CSV files
    return pd.read_csv(BytesIO(obj['Body'].read().decode('utf-8-sig')))

def call_gemini_with_retry(model_name, prompt, max_retries=3, backoff_factor=1.5):
    """Calls the Gemini API with exponential backoff and robust error handling."""
    last_error = None
    model = genai.GenerativeModel(model_name)
    
    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(prompt)
            text_response = getattr(response, 'text', '').strip()
            # **EXPERT FIX**: Ensure the response from Gemini is not empty.
            if not text_response:
                raise RuntimeError("Received an empty 'text' response from Gemini.")
            return text_response
        except Exception as e:
            log.warning(f"Gemini API call attempt {attempt} of {max_retries} failed: {e}")
            last_error = e
            time.sleep(backoff_factor ** attempt)
            
    raise RuntimeError(f"Gemini API call failed after {max_retries} attempts: {last_error}")

def lambda_handler(event, context):
    try:
        configure_gemini()
        df_catalog = load_product_catalog()

        for record in event.get('Records', []):
            message = json.loads(record['body'])
            solicitation_id = message.get('solicitation_id', 'UNKNOWN')
            log.info(f"Processing solicitation_id: {solicitation_id}")

            quote_lines = []
            for item in message.get('requested_products', []):
                product_name = str(item.get('product_name', '')).strip()
                quantity = int(item.get('quantity', 0))

                if not product_name or quantity <= 0:
                    continue
                
                # Use str.contains for flexible matching of product names
                row = df_catalog[df_catalog['Product_Name'].str.contains(product_name, case=False, na=False)]
                
                if not row.empty:
                    product_info = row.iloc[0]
                    unit_price = float(product_info['Unit_Price'])
                    total_price = unit_price * quantity
                    quote_lines.append(f"- {product_info['Product_Name']}: {quantity} units @ ${unit_price:,.2f} each. Total: ${total_price:,.2f}")

            if not quote_lines:
                log.warning(f"No matching products found for solicitation_id: {solicitation_id}")
                continue

            itemized_list = "\n".join(quote_lines)
            prompt = f"""
            Act as a federal government contract specialist for Vaxelrod LLC.
            Draft a professional plain-text email quote for solicitation {solicitation_id}.

            Include the following itemized list:
            {itemized_list}

            Close with Vaxelrod LLC contact information and a courteous sign-off.
            """.strip()

            quote_body = call_gemini_with_retry('gemini-1.5-pro-latest', prompt)

            ses.send_email(
                Source=SENDER_EMAIL,
                Destination={'ToAddresses': [RECIPIENT_EMAIL]},
                Message={
                    'Subject': {'Data': f'Vaxelrod LLC Quote for Solicitation: {solicitation_id}'},
                    'Body': {'Text': {'Data': quote_body}}
                }
            )
            log.info(f"Email sent for solicitation_id: {solicitation_id}")

        return {'statusCode': 200, 'body': json.dumps('Processing complete.')}

    except Exception:
        log.exception("A critical error occurred in the Lambda handler.")
        raise
