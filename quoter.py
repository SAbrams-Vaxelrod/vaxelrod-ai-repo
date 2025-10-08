import os
import json
import logging
import time
from io import BytesIO, StringIO
from typing import Any, Dict, List

import boto3
import pandas as pd
import google.generativeai as genai
from botocore.exceptions import ClientError

# Logging
log = logging.getLogger()
log.setLevel(logging.INFO)

# Environment Variables from Lambda Configuration
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
PRODUCT_CATALOG_KEY = os.environ.get("PRODUCT_CATALOG_KEY", "products.csv")
GEMINI_SECRET_NAME = os.environ.get("GEMINI_API_KEY_SECRET_NAME", "Vaxelrod-Gemini-API-Key-prod")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# AWS Clients
s3 = boto3.client("s3")
ses = boto3.client("ses", region_name=AWS_REGION)
secrets = boto3.client("secretsmanager")

def _get_gemini_api_key(secret_name: str) -> str:
    """Retrieves the Gemini API key from AWS Secrets Manager."""
    resp = secrets.get_secret_value(SecretId=secret_name)
    if "SecretString" in resp:
        return resp["SecretString"]
    return resp["SecretBinary"].decode("utf-8")

def load_product_catalog() -> pd.DataFrame:
    """Loads the product catalog from S3 with robust encoding fallbacks."""
    log.info("Loading catalog %r from bucket %r.", PRODUCT_CATALOG_KEY, S3_BUCKET_NAME)
    obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=PRODUCT_CATALOG_KEY)
    body_bytes = obj["Body"].read()
    try:
        return pd.read_csv(BytesIO(body_bytes))
    except Exception as e1:
        log.warning("BytesIO read failed (%s); trying utf-8-sig fallback", e1)
        try:
            return pd.read_csv(StringIO(body_bytes.decode("utf-8-sig")))
        except UnicodeDecodeError as e2:
            log.warning("utf-8-sig decode failed (%s); trying latin-1 fallback", e2)
            return pd.read_csv(StringIO(body_bytes.decode("latin-1")))

def summarize_products(df: pd.DataFrame, max_rows: int = 8) -> str:
    """Summarizes product data into a TSV string for the AI prompt."""
    cols = [c for c in df.columns if c in ("SKU", "Product_Name", "Unit_Price", "Category", "Description")]
    if not cols:
        cols = list(df.columns)[:5]
    sample = df[cols].head(max_rows).copy()
    lines = ["\t".join([str(c) for c in sample.columns])]
    for _, row in sample.iterrows():
        lines.append("\t".join([str(row.get(c, "")) for c in sample.columns]))
    return "\n".join(lines)

def build_prompt(opportunity: Dict[str, Any], tsv_products: str) -> str:
    """Builds the final prompt for the Gemini AI."""
    opp_lines = [f"{k}: {v}" for k, v in opportunity.items()]
    opp_block = "\n".join(opp_lines)
    return f"""
You are Vaxelrod AI. Draft a concise, professional sales quote email.

Instructions:
First line must be: Subject: <short, compelling subject>
Keep the body 200-300 words, clear paragraphs.
Include a short intro, 3-6 proposed items with unit price and assumptions, total est., lead time, and Net 30 terms.
Friendly close with contact info.

Micropurchase Opportunity:
{opp_block}

Available Products (TSV):
{tsv_products}

Write only the email (no markdown). Use USD formatting.
"""

def pick_supported_model(preferred: str) -> str:
    """Checks for available Gemini models and returns a supported one."""
    try:
        models = genai.list_models() or []
        names = {m.name.split("/")[-1] for m in models}
        for candidate in [preferred, "gemini-2.5-pro", "gemini-2.5-flash"]:
            if candidate in names:
                log.info("Selected supported model: %s", candidate)
                return candidate
    except Exception as e:
        log.warning("Could not list models, using preferred: %s", e)
    return preferred or "gemini-2.5-flash"

def call_gemini_with_retry(model_name: str, prompt: str, max_retries: int = 3, base_delay: float = 1.5) -> str:
    """Calls the Gemini API with retries and a model fallback."""
    model = genai.GenerativeModel(model_name)
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            if not text:
                raise RuntimeError("Gemini returned empty text")
            return text
        except Exception as e:
            last_error = e
            log.warning("Gemini API call attempt %d of %d failed: %s", attempt, max_retries, e)
            if attempt == 1 and "not found" in str(e).lower():
                fallback = "gemini-2.5-flash" if model_name != "gemini-2.5-flash" else "gemini-2.5-pro"
                log.warning("Switching model to fallback: %s", fallback)
                model = genai.GenerativeModel(fallback)
            time.sleep(base_delay ** attempt)
    raise RuntimeError(f"Gemini API call failed after {max_retries} attempts: {last_error}")

def lambda_handler(event, context):
    """The main Lambda handler function."""
    try:
        api_key = _get_gemini_api_key(GEMINI_SECRET_NAME)
        genai.configure(api_key=api_key)
        log.info({"message": "Gemini configured successfully", "gemini_sdk_version": getattr(genai, '__version__', 'unknown')})
        
        df = load_product_catalog()
        tsv = summarize_products(df)
        preferred_model = pick_supported_model(GEMINI_MODEL)
        
        failures: List[Dict[str, str]] = []
        for record in event.get("Records", []):
            message_id = record.get("messageId")
            try:
                body = record.get("body")
                payload = json.loads(body) if body else {}
                solicitation_id = payload.get("solicitation_id") or payload.get("title") or "(no-id)"
                log.info("Processing solicitation_id: %s.", solicitation_id)

                prompt = build_prompt(payload, tsv)
                text = call_gemini_with_retry(preferred_model, prompt)
                
                subject = "Quote from Vaxelrod AI"
                lines = text.splitlines()
                if lines and lines[0].lower().startswith("subject:"):
                    subject = lines[0].split(":", 1)[1].strip() or subject
                    body_text = "\n".join(lines[1:]).strip()
                else:
                    body_text = text

                ses.send_email(
                    Source=SENDER_EMAIL,
                    Destination={"ToAddresses": [RECIPIENT_EMAIL]},
                    Message={
                        "Subject": {"Data": subject},
                        "Body": {"Text": {"Data": body_text}},
                    },
                )
                log.info("Email sent for solicitation_id: %s", solicitation_id)

            except Exception as e:
                log.exception("Failed processing message %s: %s", message_id, e)
                if message_id:
                    failures.append({"itemIdentifier": message_id})

        return {"batchItemFailures": failures}

    except Exception:
        log.exception("A critical error occurred in the Lambda handler.")
        raise

