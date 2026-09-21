"""
Notification Templates — Preformatted templates for consistent notifications.

Design doc: "Notification Templates: Preformatted templates for consistent and efficient notifications."
"""
import logging
from typing import Optional

from jinja2 import Template

logger = logging.getLogger(__name__)


# Built-in templates
BUILTIN_TEMPLATES = {
    "billing_reminder_push": {
        "title": "Payment Reminder",
        "body": "Hi {{ user_name | default('there') }}, your payment of ${{ amount }} is due on {{ due_date }}.",
    },
    "billing_reminder_email": {
        "title": "Payment Reminder - Action Required",
        "body": """Dear {{ user_name | default('Customer') }},

This is a friendly reminder that your payment of ${{ amount }} is due on {{ due_date }}.

Please ensure your payment is processed on time to avoid any service interruption.

Thank you,
The Team""",
    },
    "billing_reminder_sms": {
        "title": None,
        "body": "Payment reminder: ${{ amount }} due on {{ due_date }}. Reply STOP to opt out.",
    },
    "shipping_update_push": {
        "title": "Shipping Update",
        "body": "Your order #{{ order_id }} has been {{ status }}. Track: {{ tracking_url }}",
    },
    "shipping_update_email": {
        "title": "Order #{{ order_id }} - {{ status }}",
        "body": """Hi {{ user_name | default('there') }},

Your order #{{ order_id }} has been {{ status }}.

{% if tracking_url %}Track your package: {{ tracking_url }}{% endif %}

Thank you for shopping with us!""",
    },
    "shipping_update_sms": {
        "title": None,
        "body": "Order #{{ order_id }}: {{ status }}. Track: {{ tracking_url }}",
    },
    "price_drop_push": {
        "title": "Price Drop Alert!",
        "body": "{{ product_name }} is now ${{ new_price }} (was ${{ old_price }}).",
    },
    "price_drop_email": {
        "title": "Price Drop: {{ product_name }} now ${{ new_price }}!",
        "body": """Hi {{ user_name | default('there') }},

Great news! {{ product_name }} has dropped in price:

Was: ${{ old_price }}
Now: ${{ new_price }}

Shop now before it's gone!""",
    },
    "security_alert_push": {
        "title": "Security Alert",
        "body": "{{ message }}",
    },
    "security_alert_email": {
        "title": "Security Alert - Action Required",
        "body": """Hi {{ user_name | default('there') }},

{{ message }}

If this wasn't you, please secure your account immediately.

- The Security Team""",
    },
    "security_alert_sms": {
        "title": None,
        "body": "Security alert: {{ message }}",
    },
    "promotion_push": {
        "title": "{{ promo_title | default('Special Offer!') }}",
        "body": "{{ promo_message }}",
    },
    "promotion_email": {
        "title": "{{ promo_title | default('Special Offer Just for You!') }}",
        "body": """Hi {{ user_name | default('there') }},

{{ promo_message }}

{% if promo_code %}Use code: {{ promo_code }}{% endif %}

Happy shopping!""",
    },
    "system_push": {
        "title": "{{ title | default('System Notification') }}",
        "body": "{{ message }}",
    },
    "system_email": {
        "title": "{{ title | default('Notification') }}",
        "body": "{{ message }}",
    },
}


class TemplateEngine:
    """Renders notification content from templates."""

    def __init__(self):
        self._templates: dict[str, dict] = dict(BUILTIN_TEMPLATES)

    def register_template(self, template_id: str, title: str, body: str):
        """Register a custom template."""
        self._templates[template_id] = {"title": title, "body": body}

    def render(self, template_id: str, data: dict) -> tuple[Optional[str], str]:
        """
        Render a template with data.
        Returns (title, body). Title may be None for SMS.
        """
        template = self._templates.get(template_id)
        if not template:
            # Fallback: use data directly
            title = data.get("title")
            body = data.get("body", "")
            return title, body

        try:
            title_tmpl = template.get("title")
            body_tmpl = template["body"]

            title = None
            if title_tmpl:
                title = Template(title_tmpl).render(**data)

            body = Template(body_tmpl).render(**data)
            return title, body

        except Exception as e:
            logger.error(f"Template rendering failed for '{template_id}': {e}")
            # Fallback to raw data
            return data.get("title"), data.get("body", "")

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())
