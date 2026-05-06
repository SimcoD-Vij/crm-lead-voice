"""Utility module for applying disposition code mapping."""

from typing import Optional

from loguru import logger

from api.db import db_client
from api.enums import OrganizationConfigurationKey


async def apply_disposition_mapping(value: str, organization_id: Optional[int]) -> str:
    """Apply disposition code mapping if configured.

    Args:
        value: The original disposition value to map
        organization_id: The organization ID

    Returns:
        The mapped value if found in configuration, otherwise the original value
    """
    if not organization_id or not value:
        return value

    try:
        disposition_mapping = await db_client.get_configuration_value(
            organization_id,
            OrganizationConfigurationKey.DISPOSITION_CODE_MAPPING.value,
            default={},
        )

        if not disposition_mapping:
            return value

        # Return mapped value if exists, otherwise original
        # DISPOSITION_CODE_MAPPING looks like {"user_idle_max_duration_exceeded": "DAIR"} etc.
        mapped_value = disposition_mapping.get(value, value)

        if mapped_value != value:
            logger.debug(
                f"Mapped disposition code from '{value}' to '{mapped_value}' "
                f"for organization {organization_id}"
            )

        return mapped_value

    except Exception as e:
        logger.error(f"Error applying disposition mapping: {e}")
        return value


async def get_organization_id_from_workflow_run(
    workflow_run_id: Optional[int],
) -> Optional[int]:
    """Get organization_id from workflow_run_id through the model relationships.

    Args:
        workflow_run_id: The workflow run ID

    Returns:
        The organization ID if found, otherwise None
    """
    if not workflow_run_id:
        return None

    try:
        workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
        if not workflow_run or not workflow_run.workflow:
            return None

        workflow = workflow_run.workflow
        if not workflow.user:
            return None

        return workflow.user.selected_organization_id
    except Exception as e:
        logger.error(f"Error getting organization_id from workflow_run: {e}")
        return None
