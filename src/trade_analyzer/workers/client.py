"""
Temporal client configuration for Trade Analyzer.

This module provides a factory function to create Temporal client instances
configured for either local development or cloud deployment.

Architecture:
    - Singleton-like connection pattern (new client per call)
    - Auto-detects local vs cloud based on environment config
    - Handles TLS and API key authentication for Temporal Cloud

Usage:
    >>> client = await get_temporal_client()
    >>> # Use client to start workflows or workers

Environment Detection:
    - Local: Uses localhost:7233 with default namespace
    - Cloud: Uses Temporal Cloud endpoint with API key + TLS

Connected Services:
    - Temporal Cloud (ap-south-1.aws.api.temporal.io:7233)
    - Namespace: trade-discovere.y8vfp
    - Region: Asia Pacific (Mumbai)
"""

from temporalio.client import Client

from trade_analyzer.config import get_temporal_config, is_temporal_cloud


async def get_temporal_client() -> Client:
    """
    Create and return a Temporal client.

    This is the primary factory function for creating Temporal clients
    throughout the application. It automatically configures the client
    for either local development or Temporal Cloud based on environment
    configuration.

    Supports both local Temporal server and Temporal Cloud.

    For Temporal Cloud with API key authentication:
    - TEMPORAL_ADDRESS: ap-south-1.aws.api.temporal.io:7233
    - TEMPORAL_NAMESPACE: trade-discovere.y8vfp
    - TEMPORAL_API_KEY: Your Temporal Cloud API key

    Returns:
        Configured Temporal Client instance ready to execute workflows
        or start workers.

    Raises:
        Exception: If connection to Temporal server fails.
    """
    config = get_temporal_config()

    if is_temporal_cloud():
        # Temporal Cloud connection with API key authentication
        client = await Client.connect(
            config["address"],
            namespace=config["namespace"],
            api_key=config["api_key"],
            tls=True,  # Required for Temporal Cloud
        )
    else:
        # Local Temporal server connection
        client = await Client.connect(
            config["address"],
            namespace=config["namespace"],
        )

    return client
