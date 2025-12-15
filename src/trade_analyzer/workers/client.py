"""Temporal client configuration for Trade Analyzer."""

from temporalio.client import Client

from trade_analyzer.config import get_temporal_config, is_temporal_cloud


async def get_temporal_client() -> Client:
    """
    Create and return a Temporal client.

    Supports both local Temporal server and Temporal Cloud.

    For Temporal Cloud with API key authentication:
    - TEMPORAL_ADDRESS: ap-south-1.aws.api.temporal.io:7233
    - TEMPORAL_NAMESPACE: trade-discovere.y8vfp
    - TEMPORAL_API_KEY: Your Temporal Cloud API key

    Returns:
        Configured Temporal Client instance.
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
