"""
Configuration settings for Trade Analyzer.

This module centralizes all configuration for the Trade Analyzer application,
including database connections, workflow orchestration, and trading parameters.

Configuration Sources (in order of precedence):
1. Environment variables (for production/deployment)
2. Default values (for development)

Sections:
---------
1. MongoDB Configuration
   - Connection to DigitalOcean MongoDB Atlas cluster
   - Stores: stocks, trade_setups, trades, regime_assessments, etc.

2. Temporal Cloud Configuration
   - Workflow orchestration using Temporal Cloud (Mumbai region)
   - Handles: universe refresh, filtering pipelines, trade detection

3. Task Queue Configuration
   - Named queues for different workflow types
   - Enables worker specialization

4. External API Keys
   - FMP (Financial Modeling Prep) for fundamental data
   - Alpha Vantage for additional market data

5. Portfolio Parameters
   - Risk management settings
   - Position sizing constraints
   - Sector exposure limits

Environment Variables:
---------------------
MONGO_USERNAME, MONGO_PASSWORD, MONGO_HOST, MONGO_DATABASE, MONGO_URI
TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_API_KEY
FMP_API_KEY, ALPHA_VANTAGE_API_KEY
DEFAULT_PORTFOLIO_VALUE, DEFAULT_RISK_PCT, MAX_POSITIONS, MAX_SECTOR_PCT, CASH_RESERVE_PCT

Usage:
------
    from trade_analyzer.config import get_mongo_uri, get_temporal_config

    # Get MongoDB URI
    uri = get_mongo_uri()

    # Get Temporal config dict
    config = get_temporal_config()

    # Check if using Temporal Cloud
    if is_temporal_cloud():
        # Use API key authentication
        pass

Note:
-----
Default credentials are provided for development convenience.
In production, always use environment variables for sensitive data.
"""

import os

# =============================================================================
# MongoDB Configuration
# =============================================================================
# DigitalOcean Managed MongoDB Atlas cluster
# Database: trade_analysis
# Collections: stocks, trade_setups, trades, regime_assessments, etc.

MONGO_USERNAME = os.getenv("MONGO_USERNAME", "doadmin")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "E4l6W02aC9m5U83x")
MONGO_HOST = os.getenv(
    "MONGO_HOST", "mongodb+srv://db-trading-setup-4aad9e87.mongo.ondigitalocean.com"
)
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "trade_analysis")

# Build connection URI with retry writes enabled
MONGO_URI = os.getenv(
    "MONGO_URI",
    f"mongodb+srv://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST.replace('mongodb+srv://', '')}/?retryWrites=true&w=majority",
)

# =============================================================================
# Temporal Cloud Configuration
# =============================================================================
# Temporal Cloud - Asia Pacific (Mumbai) region
# Used for: workflow orchestration, activity execution, retry handling
# Namespace: trade-discovere.y8vfp

TEMPORAL_ADDRESS = os.getenv(
    "TEMPORAL_ADDRESS", "ap-south-1.aws.api.temporal.io:7233"
)
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "trade-discovere.y8vfp")
TEMPORAL_API_KEY = os.getenv(
    "TEMPORAL_API_KEY",
    "eyJhbGciOiJFUzI1NiIsImtpZCI6Ild2dHdhQSJ9.eyJhY2NvdW50X2lkIjoieTh2ZnAiLCJhdWQiOlsidGVtcG9yYWwuaW8iXSwiZXhwIjoxODI4ODY1NjkwLCJpc3MiOiJ0ZW1wb3JhbC5pbyIsImp0aSI6IktvN0draXFTR1pQQTVTdkQyUm9ncGY0YlZyVUJDd2hQIiwia2V5X2lkIjoiS283R2tpcVNHWlBBNVN2RDJSb2dwZjRiVnJVQkN3aFAiLCJzdWIiOiIzNTQ1MTcxMGM1ODQ0YjUwODU1ODE5MGRhMGNiZmYyYyJ9.0t4QLecFwNnRzxVpLiesPuxMiNobXVsdytYqi-KU-n2uF20iqiyB-Ev-hUXnQ04iCou1U1RKc3i6ND4VRL6vvg",
)

# =============================================================================
# Task Queue Configuration
# =============================================================================
# Task queues allow workers to process specific types of workflows
# Multiple workers can listen to the same queue for load balancing

TASK_QUEUE_UNIVERSE_REFRESH = "trade-analyzer-universe-refresh"  # Main pipeline queue
TASK_QUEUE_REGIME_ANALYSIS = "trade-analyzer-regime-analysis"    # Regime-specific
TASK_QUEUE_TRADE_PIPELINE = "trade-analyzer-pipeline"            # Trade execution

# =============================================================================
# External API Configuration
# =============================================================================
# APIs for fundamental and market data
# FMP: Company financials, ratios, EPS data
# Alpha Vantage: Additional market data, earnings calendar

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

# =============================================================================
# Portfolio Configuration (Risk Management)
# =============================================================================
# These parameters control position sizing and risk limits
# Based on professional trading best practices

DEFAULT_PORTFOLIO_VALUE = float(os.getenv("DEFAULT_PORTFOLIO_VALUE", "1000000"))  # Rs.10 Lakhs
DEFAULT_RISK_PCT = float(os.getenv("DEFAULT_RISK_PCT", "0.015"))  # 1.5% risk per trade
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "12"))  # Maximum concurrent positions
MAX_SECTOR_PCT = float(os.getenv("MAX_SECTOR_PCT", "0.25"))  # 25% max sector exposure
CASH_RESERVE_PCT = float(os.getenv("CASH_RESERVE_PCT", "0.30"))  # 30% cash reserve


# =============================================================================
# Configuration Helper Functions
# =============================================================================


def get_mongo_uri() -> str:
    """
    Get the MongoDB connection URI.

    Returns:
        str: Complete MongoDB connection URI with credentials and options.

    Example:
        >>> uri = get_mongo_uri()
        >>> client = MongoClient(uri)
    """
    return MONGO_URI


def get_mongo_database() -> str:
    """
    Get the MongoDB database name.

    Returns:
        str: Database name (default: 'trade_analysis').

    Example:
        >>> db_name = get_mongo_database()
        >>> db = client[db_name]
    """
    return MONGO_DATABASE


def get_temporal_config() -> dict:
    """
    Get Temporal connection configuration as a dictionary.

    Returns:
        dict: Configuration with keys 'address', 'namespace', 'api_key'.

    Example:
        >>> config = get_temporal_config()
        >>> client = await Client.connect(
        ...     config['address'],
        ...     namespace=config['namespace'],
        ...     api_key=config['api_key']
        ... )
    """
    return {
        "address": TEMPORAL_ADDRESS,
        "namespace": TEMPORAL_NAMESPACE,
        "api_key": TEMPORAL_API_KEY,
    }


def is_temporal_cloud() -> bool:
    """
    Check if the application is configured to use Temporal Cloud.

    Temporal Cloud requires API key authentication and uses specific
    domain patterns (tmprl.cloud or temporal.io).

    Returns:
        bool: True if using Temporal Cloud, False for local Temporal.

    Example:
        >>> if is_temporal_cloud():
        ...     # Use API key authentication
        ...     pass
        ... else:
        ...     # Use local connection without auth
        ...     pass
    """
    return bool(TEMPORAL_API_KEY) or "tmprl.cloud" in TEMPORAL_ADDRESS or "temporal.io" in TEMPORAL_ADDRESS
