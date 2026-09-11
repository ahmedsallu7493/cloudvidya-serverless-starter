"""
CampusFix backend

Routes:
  GET    /health
  POST   /items
  GET    /items
  PATCH  /items/{id}

Architecture:
  Frontend -> API Gateway -> Lambda -> DynamoDB
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

TABLE_NAME = os.environ.get("TABLE_NAME")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None


# ---------------------------------------------------------
# CampusFix configuration
# ---------------------------------------------------------

VALID_STATUSES = {
    "OPEN",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED",
}

VALID_PRIORITIES = {
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
}


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": (
        "Content-Type,X-Amz-Date,Authorization,"
        "X-Api-Key,X-Amz-Security-Token"
    ),
    "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
}


# ---------------------------------------------------------
# Response helper
# ---------------------------------------------------------

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

def _health():
    return _response(
        200,
        {
            "status": "ok",
            "service": "CampusFix",
            "table": TABLE_NAME,
            "ai": "disabled",
        },
    )


# ---------------------------------------------------------
# Create issue
# ---------------------------------------------------------

def _create_item(event):
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(
            400,
            {"error": "Request body must be valid JSON."},
        )

    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    category = (payload.get("category") or "Other").strip()
    participant_name = (
        payload.get("participantName") or ""
    ).strip()
    location = (payload.get("location") or "").strip()

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

    # -----------------------------------------------------
    # Simple rule-based priority
    # No LLM required
    # -----------------------------------------------------

    combined_text = f"{title} {description}".lower()

    critical_terms = [
        "spark",
        "sparking",
        "smoke",
        "burning",
        "fire",
        "exposed wire",
        "electric shock",
        "gas leak",
        "dangerous",
        "emergency",
    ]

    high_terms = [
        "broken",
        "not working",
        "leaking",
        "leak",
        "unsafe",
        "damaged",
        "crack",
        "failed",
    ]

    if any(term in combined_text for term in critical_terms):
        priority = "CRITICAL"
        severity = 5

    elif any(term in combined_text for term in high_terms):
        priority = "HIGH"
        severity = 4

    else:
        priority = "MEDIUM"
        severity = 2

    # -----------------------------------------------------
    # Department based on category
    # -----------------------------------------------------

    department_map = {
        "Electrical": "Electrical",
        "Equipment": "Facilities",
        "Plumbing": "Facilities",
        "Furniture": "Facilities",
        "Internet": "IT",
        "Cleanliness": "Housekeeping",
        "Safety": "Security",
        "Other": "Facilities",
    }

    department = department_map.get(
        category,
        "Facilities",
    )

    item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "participantName": participant_name,
        "location": location,
        "category": category,
        "subcategory": "General",
        "severity": severity,
        "priority": priority,
        "department": department,
        "aiSummary": title,
        "aiProcessed": False,
        "status": "OPEN",
        "createdAt": now,
        "updatedAt": now,
    }

    try:
        table.put_item(Item=item)

    except Exception as error:
        print(
            f"Failed to create CampusFix issue: {str(error)}"
        )

        return _response(
            500,
            {"error": "Could not create issue."},
        )

    print(
        f"CampusFix issue created: {json.dumps(item)}"
    )

    return _response(
        200,
        {
            "message": "Issue created successfully.",
            "item": item,
        },
    )


# ---------------------------------------------------------
# List issues
# ---------------------------------------------------------

def _list_items(event):
    try:
        result = table.scan(Limit=100)

        items = result.get("Items", [])

        query_params = (
            event.get("queryStringParameters") or {}
        )

        status_filter = (
            query_params.get("status") or ""
        ).upper().strip()

        priority_filter = (
            query_params.get("priority") or ""
        ).upper().strip()

        search_query = (
            query_params.get("q") or ""
        ).strip().lower()

        filtered_items = []

        for item in items:

            # Status filter
            if status_filter:
                if (
                    item.get("status", "").upper()
                    != status_filter
                ):
                    continue

            # Priority filter
            if priority_filter:
                if (
                    item.get("priority", "").upper()
                    != priority_filter
                ):
                    continue

            # Search
            if search_query:

                searchable_text = " ".join(
                    [
                        str(item.get("title", "")),
                        str(item.get("description", "")),
                        str(item.get("category", "")),
                        str(item.get("location", "")),
                        str(item.get("department", "")),
                        str(item.get("priority", "")),
                        str(item.get("status", "")),
                    ]
                ).lower()

                if search_query not in searchable_text:
                    continue

            filtered_items.append(item)

        # Newest issues first
        filtered_items.sort(
            key=lambda item: item.get(
                "createdAt",
                "",
            ),
            reverse=True,
        )

        return _response(
            200,
            {
                "items": filtered_items,
                "count": len(filtered_items),
            },
        )

    except Exception as error:

        print(
            f"Failed to list CampusFix issues: {str(error)}"
        )

        return _response(
            500,
            {"error": "Could not load issues."},
        )


# ---------------------------------------------------------
# Update issue status
# ---------------------------------------------------------

def _update_item_status(event):

    path_parameters = (
        event.get("pathParameters") or {}
    )

    item_id = path_parameters.get("id")

    if not item_id:
        return _response(
            400,
            {"error": "Issue ID is required."},
        )

    try:
        payload = json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

        return _response(
            400,
            {"error": "Request body must be valid JSON."},
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
                    + ", ".join(
                        sorted(VALID_STATUSES)
                    )
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
            {"error": "Could not update issue."},
        )

    return _response(
        200,
        {
            "message": "Issue updated successfully.",
            "item": result.get("Attributes"),
        },
    )


# ---------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------

def handler(event, context):

    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    # CORS preflight
    if method == "OPTIONS":
        return _response(200, {})

    # Health
    if (
        resource == "/health"
        and method == "GET"
    ):
        return _health()

    # Create issue
    if (
        resource == "/items"
        and method == "POST"
    ):
        return _create_item(event)

    # List issues
    if (
        resource == "/items"
        and method == "GET"
    ):
        return _list_items(event)

    # Update issue
    if (
        resource == "/items/{id}"
        and method == "PATCH"
    ):
        return _update_item_status(event)

    return _response(
        404,
        {
            "error": (
                f"No route for {method} {resource}"
            )
        },
    )