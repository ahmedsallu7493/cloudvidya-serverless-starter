import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr


# ============================================================
# Configuration
# ============================================================

TABLE_NAME = os.environ.get("TABLE_NAME", "CampusFixItems")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


# ============================================================
# Common Helpers
# ============================================================

def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


def json_safe(value):
    """
    Convert DynamoDB Decimal values into normal Python numbers
    so they can safely be returned as JSON.
    """
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)

    if isinstance(value, list):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {
            key: json_safe(item)
            for key, item in value.items()
        }

    return value


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_body(event):
    body = event.get("body")

    if not body:
        return {}

    if isinstance(body, dict):
        return body

    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return {}


# ============================================================
# CampusFix Rule Engine
# ============================================================

CRITICAL_KEYWORDS = [
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

HIGH_KEYWORDS = [
    "broken",
    "not working",
    "leaking",
    "leak",
    "unsafe",
    "damaged",
    "crack",
    "failed",
]


def calculate_priority(title, description):
    text = f"{title} {description}".lower()

    for keyword in CRITICAL_KEYWORDS:
        if keyword in text:
            return "CRITICAL", 5

    for keyword in HIGH_KEYWORDS:
        if keyword in text:
            return "HIGH", 4

    return "MEDIUM", 2


def determine_department(category):
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

    return department_map.get(category, "Facilities")


# ============================================================
# Health
# ============================================================

def _health():
    return response(
        200,
        {
            "status": "ok",
            "service": "CampusFix",
            "table": TABLE_NAME,
            "ai": "disabled",
        },
    )


# ============================================================
# Create Issue
# ============================================================

def _create_item(event):
    body = get_body(event)

    title = str(body.get("title", "")).strip()
    description = str(body.get("description", "")).strip()

    if not title:
        return response(
            400,
            {
                "error": "Title is required."
            },
        )

    if not description:
        return response(
            400,
            {
                "error": "Description is required."
            },
        )

    category = str(
        body.get("category", "Other")
    ).strip() or "Other"

    location = str(
        body.get("location", "")
    ).strip()

    participant_name = str(
        body.get("participantName", "")
    ).strip()

    priority, severity = calculate_priority(
        title,
        description
    )

    department = determine_department(category)

    timestamp = now_iso()

    item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "participantName": participant_name,
        "location": location,
        "category": category,
        "subcategory": str(
            body.get("subcategory", "General")
        ).strip() or "General",
        "severity": severity,
        "priority": priority,
        "department": department,
        "aiSummary": title,
        "aiProcessed": False,
        "status": "OPEN",
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }

    try:
        table.put_item(Item=item)

        print(
            "CampusFix issue created:",
            json.dumps(item)
        )

        return response(
            201,
            {
                "message": "Issue created successfully.",
                "item": item,
            },
        )

    except Exception as exc:
        print(
            "Failed to create CampusFix issue:",
            str(exc)
        )

        return response(
            500,
            {
                "error": "Could not create issue."
            },
        )


# ============================================================
# List Issues
# ============================================================

def _list_items(event):
    try:
        query_params = event.get("queryStringParameters") or {}

        status_filter = str(
            query_params.get("status", "")
        ).strip().upper()

        priority_filter = str(
            query_params.get("priority", "")
        ).strip().upper()

        search_query = str(
            query_params.get("q", "")
        ).strip().lower()

        scan_kwargs = {
            "Limit": 100
        }

        items = []

        while True:
            result = table.scan(**scan_kwargs)

            items.extend(
                result.get("Items", [])
            )

            last_key = result.get("LastEvaluatedKey")

            if not last_key or len(items) >= 100:
                break

            scan_kwargs["ExclusiveStartKey"] = last_key

        # ----------------------------------------------------
        # Status filter
        # ----------------------------------------------------

        if status_filter:
            items = [
                item
                for item in items
                if str(
                    item.get("status", "")
                ).upper() == status_filter
            ]

        # ----------------------------------------------------
        # Priority filter
        # ----------------------------------------------------

        if priority_filter:
            items = [
                item
                for item in items
                if str(
                    item.get("priority", "")
                ).upper() == priority_filter
            ]

        # ----------------------------------------------------
        # Search
        # ----------------------------------------------------

        if search_query:
            searchable_fields = [
                "title",
                "description",
                "category",
                "location",
                "department",
                "priority",
                "status",
            ]

            filtered_items = []

            for item in items:
                searchable_text = " ".join(
                    str(item.get(field, ""))
                    for field in searchable_fields
                ).lower()

                if search_query in searchable_text:
                    filtered_items.append(item)

            items = filtered_items

        # ----------------------------------------------------
        # Newest first
        # ----------------------------------------------------

        items.sort(
            key=lambda item: str(
                item.get("createdAt", "")
            ),
            reverse=True,
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # DynamoDB numbers are Decimal objects.
        # Convert them before json.dumps().
        # ----------------------------------------------------

        safe_items = json_safe(items)

        return response(
            200,
            {
                "items": safe_items,
                "count": len(safe_items),
            },
        )

    except Exception as exc:
        print(
            "Failed to list CampusFix issues:",
            str(exc)
        )

        return response(
            500,
            {
                "error": "Could not load issues."
            },
        )


# ============================================================
# Update Issue
# ============================================================

def _update_item_status(event, item_id):
    body = get_body(event)

    new_status = str(
        body.get("status", "")
    ).strip().upper()

    allowed_statuses = {
        "OPEN",
        "ACKNOWLEDGED",
        "IN_PROGRESS",
        "RESOLVED",
        "CLOSED",
    }

    if new_status not in allowed_statuses:
        return response(
            400,
            {
                "error": (
                    "Invalid status. Allowed values: "
                    "OPEN, ACKNOWLEDGED, IN_PROGRESS, "
                    "RESOLVED, CLOSED."
                )
            },
        )

    admin_note = str(
        body.get("adminNote", "")
    ).strip()

    timestamp = now_iso()

    update_expression = (
        "SET #status = :status, "
        "#updatedAt = :updatedAt"
    )

    expression_attribute_names = {
        "#status": "status",
        "#updatedAt": "updatedAt",
    }

    expression_attribute_values = {
        ":status": new_status,
        ":updatedAt": timestamp,
    }

    if admin_note:
        update_expression += ", #adminNote = :adminNote"

        expression_attribute_names[
            "#adminNote"
        ] = "adminNote"

        expression_attribute_values[
            ":adminNote"
        ] = admin_note

    if new_status == "RESOLVED":
        update_expression += ", #resolvedAt = :resolvedAt"

        expression_attribute_names[
            "#resolvedAt"
        ] = "resolvedAt"

        expression_attribute_values[
            ":resolvedAt"
        ] = timestamp

    try:
        result = table.update_item(
            Key={
                "id": item_id
            },
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ReturnValues="ALL_NEW",
        )

        updated_item = result.get(
            "Attributes",
            {}
        )

        return response(
            200,
            {
                "message": "Issue updated successfully.",
                "item": json_safe(updated_item),
            },
        )

    except Exception as exc:
        print(
            "Failed to update CampusFix issue:",
            str(exc)
        )

        return response(
            500,
            {
                "error": "Could not update issue."
            },
        )


# ============================================================
# Lambda Handler
# ============================================================

def handler(event, context):
    try:
        http_method = event.get(
            "httpMethod",
            ""
        ).upper()

        resource = event.get(
            "resource",
            ""
        )

        path = event.get(
            "path",
            ""
        )

        # ----------------------------------------------------
        # CORS preflight
        # ----------------------------------------------------

        if http_method == "OPTIONS":
            return response(
                200,
                {
                    "message": "OK"
                },
            )

        # ----------------------------------------------------
        # Health
        # ----------------------------------------------------

        if (
            http_method == "GET"
            and (
                resource == "/health"
                or path.endswith("/health")
            )
        ):
            return _health()

        # ----------------------------------------------------
        # Create Issue
        # ----------------------------------------------------

        if (
            http_method == "POST"
            and (
                resource == "/items"
                or path.endswith("/items")
            )
        ):
            return _create_item(event)

        # ----------------------------------------------------
        # List Issues
        # ----------------------------------------------------

        if (
            http_method == "GET"
            and (
                resource == "/items"
                or path.endswith("/items")
            )
        ):
            return _list_items(event)

        # ----------------------------------------------------
        # Update Issue
        # ----------------------------------------------------

        if http_method == "PATCH":
            path_parameters = (
                event.get("pathParameters")
                or {}
            )

            item_id = path_parameters.get("id")

            if not item_id:
                match = re.search(
                    r"/items/([^/]+)",
                    path
                )

                if match:
                    item_id = match.group(1)

            if item_id:
                return _update_item_status(
                    event,
                    item_id
                )

        # ----------------------------------------------------
        # Not Found
        # ----------------------------------------------------

        return response(
            404,
            {
                "error": "Route not found."
            },
        )

    except Exception as exc:
        print(
            "CampusFix Lambda error:",
            str(exc)
        )

        return response(
            500,
            {
                "error": "Internal server error."
            },
        )