"""
CampusFix backend

Routes:
  GET    /health
  POST   /items
  GET    /items
  PATCH  /items/{id}

Architecture:
  Frontend -> API Gateway -> Lambda
                         -> Groq AI
                         -> DynamoDB
                         -> Secrets Manager
"""

import json
import os
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone

import boto3


# -------------------------------------------------------------------
# AWS RESOURCES
# -------------------------------------------------------------------

TABLE_NAME = os.environ.get("TABLE_NAME")
GROQ_SECRET_ARN = os.environ.get("GROQ_SECRET_ARN")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None

secrets_client = boto3.client("secretsmanager")

# Cache the secret between warm Lambda invocations.
_groq_api_key = None


# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

VALID_STATUSES = {
    "OPEN",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED",
}


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
}


# -------------------------------------------------------------------
# COMMON RESPONSE
# -------------------------------------------------------------------

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


# -------------------------------------------------------------------
# SECRETS MANAGER
# -------------------------------------------------------------------

def _get_groq_api_key():
    """
    Retrieve the Groq API key from AWS Secrets Manager.

    The secret should contain:

    {
        "GROQ_API_KEY": "your-key"
    }

    The key is cached for warm Lambda invocations.
    """

    global _groq_api_key

    if _groq_api_key:
        return _groq_api_key

    if not GROQ_SECRET_ARN:
        raise RuntimeError("GROQ_SECRET_ARN environment variable is missing.")

    secret_response = secrets_client.get_secret_value(
        SecretId=GROQ_SECRET_ARN
    )

    secret_string = secret_response.get("SecretString")

    if not secret_string:
        raise RuntimeError("Groq secret does not contain SecretString.")

    secret_data = json.loads(secret_string)

    api_key = secret_data.get("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY was not found inside the secret.")

    _groq_api_key = api_key

    return _groq_api_key


# -------------------------------------------------------------------
# GROQ AI ANALYSIS
# -------------------------------------------------------------------

def _analyze_issue_with_groq(title, description, location, category):
    """
    Ask Groq to convert an unstructured campus complaint
    into structured maintenance intelligence.
    """

    api_key = _get_groq_api_key()

    prompt = f"""
You are the AI issue intelligence engine for CampusFix,
a campus infrastructure reporting and maintenance platform.

Analyze this campus issue.

Title:
{title}

Description:
{description}

Location:
{location or "Unknown"}

Student-selected category:
{category or "General"}

Return ONLY valid JSON matching the required schema.

Rules:
- Do not invent a specific location if it was not provided.
- Severity is 1 to 5.
- Priority must be LOW, MEDIUM, HIGH, or CRITICAL.
- Identify the most appropriate maintenance department.
- Give a short professional summary.
- Focus on campus infrastructure and maintenance.
"""

    schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": [
                    "Electrical",
                    "Equipment",
                    "Plumbing",
                    "Furniture",
                    "Internet",
                    "Cleanliness",
                    "Safety",
                    "Other",
                ],
            },
            "subcategory": {
                "type": "string"
            },
            "severity": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
            },
            "priority": {
                "type": "string",
                "enum": [
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                    "CRITICAL",
                ],
            },
            "department": {
                "type": "string",
                "enum": [
                    "Electrical",
                    "IT",
                    "Facilities",
                    "Housekeeping",
                    "Security",
                    "Academic",
                    "Other",
                ],
            },
            "summary": {
                "type": "string"
            },
        },
        "required": [
            "category",
            "subcategory",
            "severity",
            "priority",
            "department",
            "summary",
        ],
        "additionalProperties": False,
    }

    request_body = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a campus infrastructure "
                    "issue classification system."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "campus_issue_analysis",
                "schema": schema,
                "strict": True,
            },
        },
    }

    request_data = json.dumps(request_body).encode("utf-8")

    request = urllib.request.Request(
        GROQ_API_URL,
        data=request_data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        response_body = response.read().decode("utf-8")

    result = json.loads(response_body)

    content = result["choices"][0]["message"]["content"]

    return json.loads(content)


# -------------------------------------------------------------------
# HEALTH
# -------------------------------------------------------------------

def _health():
    return _response(
        200,
        {
            "status": "ok",
            "service": "CampusFix",
            "table": TABLE_NAME,
            "ai": "Groq",
        },
    )


# -------------------------------------------------------------------
# CREATE ISSUE
# -------------------------------------------------------------------

def _create_item(event):

    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(
            400,
            {"error": "Request body must be valid JSON."}
        )

    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    category = (payload.get("category") or "General").strip()
    participant_name = (
        payload.get("participantName") or ""
    ).strip()
    location = (
        payload.get("location") or ""
    ).strip()

    if not title or not description:
        return _response(
            400,
            {
                "error": (
                    "Both 'title' and 'description' "
                    "are required."
                )
            },
        )

    now = datetime.now(timezone.utc).isoformat()

    # ---------------------------------------------------------------
    # AI ANALYSIS
    # ---------------------------------------------------------------

    ai_processed = False

    ai_data = {
        "category": category,
        "subcategory": "General",
        "severity": 2,
        "priority": "MEDIUM",
        "department": "Facilities",
        "summary": title,
    }

    try:
        ai_data = _analyze_issue_with_groq(
            title=title,
            description=description,
            location=location,
            category=category,
        )

        ai_processed = True

    except Exception as error:
        # Do not lose the student's report if AI is temporarily
        # unavailable.
        print(f"Groq analysis failed: {str(error)}")

    # ---------------------------------------------------------------
    # SAFETY OVERRIDE
    # ---------------------------------------------------------------

    combined_text = (
        f"{title} {description}"
    ).lower()

    emergency_terms = [
        "spark",
        "sparking",
        "smoke",
        "burning",
        "fire",
        "exposed wire",
        "electric shock",
        "gas leak",
    ]

    if any(term in combined_text for term in emergency_terms):
        ai_data["priority"] = "CRITICAL"
        ai_data["severity"] = 5

        if ai_data.get("department") == "Other":
            ai_data["department"] = "Electrical"

    # ---------------------------------------------------------------
    # SAVE TO DYNAMODB
    # ---------------------------------------------------------------

    item = {
        "id": str(uuid.uuid4()),

        "title": title,
        "description": description,

        "participantName": participant_name,
        "location": location,

        "category": ai_data.get(
            "category",
            category,
        ),

        "subcategory": ai_data.get(
            "subcategory",
            "General",
        ),

        "severity": int(
            ai_data.get("severity", 2)
        ),

        "priority": ai_data.get(
            "priority",
            "MEDIUM",
        ),

        "department": ai_data.get(
            "department",
            "Facilities",
        ),

        "aiSummary": ai_data.get(
            "summary",
            title,
        ),

        "aiProcessed": ai_processed,

        "status": "OPEN",

        "createdAt": now,
        "updatedAt": now,
    }

    table.put_item(Item=item)

    print(
        f"CampusFix issue created: "
        f"{json.dumps(item)}"
    )

    return _response(
        200,
        {
            "message": "Issue created successfully.",
            "item": item,
        },
    )


# -------------------------------------------------------------------
# LIST / SEARCH / FILTER ISSUES
# -------------------------------------------------------------------

def _list_items(event):

    result = table.scan(Limit=100)

    items = result.get("Items", [])

    query_params = event.get("queryStringParameters") or {}

    status_filter = (
        query_params.get("status") or ""
    ).upper()

    priority_filter = (
        query_params.get("priority") or ""
    ).upper()

    search_query = (
        query_params.get("q") or ""
    ).strip().lower()

    filtered_items = []

    for item in items:

        if (
            status_filter
            and item.get("status", "").upper()
            != status_filter
        ):
            continue

        if (
            priority_filter
            and item.get("priority", "").upper()
            != priority_filter
        ):
            continue

        if search_query:

            searchable_text = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("description", "")),
                    str(item.get("category", "")),
                    str(item.get("location", "")),
                    str(item.get("department", "")),
                ]
            ).lower()

            if search_query not in searchable_text:
                continue

        filtered_items.append(item)

    filtered_items.sort(
        key=lambda i: i.get("createdAt", ""),
        reverse=True,
    )

    return _response(
        200,
        {
            "items": filtered_items,
            "count": len(filtered_items),
        },
    )


# -------------------------------------------------------------------
# UPDATE ISSUE STATUS
# -------------------------------------------------------------------

def _update_item_status(event):

    path_parameters = event.get("pathParameters") or {}

    item_id = path_parameters.get("id")

    if not item_id:
        return _response(
            400,
            {"error": "Issue ID is required."}
        )

    try:
        payload = json.loads(
            event.get("body") or "{}"
        )
    except json.JSONDecodeError:
        return _response(
            400,
            {"error": "Request body must be valid JSON."}
        )

    new_status = (
        payload.get("status") or ""
    ).upper().strip()

    admin_note = (
        payload.get("adminNote") or ""
    ).strip()

    if new_status not in VALID_STATUSES:
        return _response(
            400,
            {
                "error": (
                    "Invalid status. Allowed values: "
                    + ", ".join(sorted(VALID_STATUSES))
                )
            },
        )

    now = datetime.now(timezone.utc).isoformat()

    expression_values = {
        ":status": new_status,
        ":updatedAt": now,
        ":adminNote": admin_note,
    }

    if new_status == "RESOLVED":
        expression = (
            "SET #s = :status, "
            "updatedAt = :updatedAt, "
            "adminNote = :adminNote, "
            "resolvedAt = :resolvedAt"
        )

        expression_values[":resolvedAt"] = now

    else:
        expression = (
            "SET #s = :status, "
            "updatedAt = :updatedAt, "
            "adminNote = :adminNote"
        )

    try:

        result = table.update_item(
            Key={"id": item_id},

            UpdateExpression=expression,

            ExpressionAttributeNames={
                "#s": "status"
            },

            ExpressionAttributeValues=expression_values,

            ReturnValues="ALL_NEW",
        )

    except Exception as error:

        print(
            f"Failed to update issue "
            f"{item_id}: {str(error)}"
        )

        return _response(
            500,
            {"error": "Could not update issue."}
        )

    return _response(
        200,
        {
            "message": "Issue updated successfully.",
            "item": result.get("Attributes"),
        },
    )


# -------------------------------------------------------------------
# MAIN LAMBDA HANDLER
# -------------------------------------------------------------------

def handler(event, context):

    method = event.get(
        "httpMethod",
        "",
    )

    resource = event.get(
        "resource",
        "",
    )

    # CORS preflight
    if method == "OPTIONS":
        return _response(200, {})

    # Health
    if (
        resource == "/health"
        and method == "GET"
    ):
        return _health()

    # Create
    if (
        resource == "/items"
        and method == "POST"
    ):
        return _create_item(event)

    # List / search / filter
    if (
        resource == "/items"
        and method == "GET"
    ):
        return _list_items(event)

    # Update
    if (
        resource == "/items/{id}"
        and method == "PATCH"
    ):
        return _update_item_status(event)

    return _response(
        404,
        {
            "error": (
                f"No route for "
                f"{method} {resource}"
            )
        },
    )