"""
Configuration settings for Trade Analyzer.

This module centralizes all configuration for the Trade Analyzer application,
including database connections, workflow orchestration, and trading parameters.

Configuration Sources:
----------------------
All sensitive configuration is loaded from environment variables.
Use a .env.local file for local development (see .env.local.example).

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

Required Environment Variables:
-------------------------------
MONGO_USERNAME      - MongoDB username
MONGO_PASSWORD      - MongoDB password
MONGO_HOST          - MongoDB host (e.g., mongodb+srv://...)
MONGO_DATABASE      - MongoDB database name (default: trade_analysis)
TEMPORAL_ADDRESS    - Temporal server address
TEMPORAL_NAMESPACE  - Temporal namespace
TEMPORAL_API_KEY    - Temporal API key (for Temporal Cloud)

Optional Environment Variables:
-------------------------------
MONGO_URI                   - Full MongoDB URI (overrides individual components)
FMP_API_KEY                 - Financial Modeling Prep API key
ALPHA_VANTAGE_API_KEY       - Alpha Vantage API key
DEFAULT_PORTFOLIO_VALUE     - Portfolio value in INR (default: 1000000)
DEFAULT_RISK_PCT            - Risk per trade (default: 0.015)
MAX_POSITIONS               - Max concurrent positions (default: 12)
MAX_SECTOR_PCT              - Max sector exposure (default: 0.25)
CASH_RESERVE_PCT            - Cash reserve percentage (default: 0.30)

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

Setup:
------
1. Copy .env.local to your project root
2. Update values with your credentials
3. Load environment variables before running:
   - Using python-dotenv: load_dotenv('.env.local')
   - Or export variables in your shell
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# =============================================================================
# Load Environment Variables
# =============================================================================
# Load from .env.local file if it exists (for local development)
# Searches in current directory and parent directories up to project root

_env_file = Path(".env.local")
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Try to find .env.local in parent directories (up to 3 levels)
    for parent in [Path.cwd()] + list(Path.cwd().parents)[:3]:
        _env_path = parent / ".env.local"
        if _env_path.exists():
            load_dotenv(_env_path)
            break

# =============================================================================
# MongoDB Configuration
# =============================================================================
# DigitalOcean Managed MongoDB Atlas cluster
# Database: trade_analysis
# Collections: stocks, trade_setups, trades, regime_assessments, etc.

MONGO_USERNAME = os.getenv("MONGO_USERNAME", "")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "")
MONGO_HOST = os.getenv("MONGO_HOST", "")
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "trade_analysis")

# Build connection URI with retry writes enabled
# If MONGO_URI is not set, construct from individual components
_default_uri = ""
if MONGO_USERNAME and MONGO_PASSWORD and MONGO_HOST:
    _host = MONGO_HOST.replace("mongodb+srv://", "")
    _default_uri = f"mongodb+srv://{MONGO_USERNAME}:{MONGO_PASSWORD}@{_host}/?retryWrites=true&w=majority"

MONGO_URI = os.getenv("MONGO_URI", _default_uri)

# =============================================================================
# Temporal Cloud Configuration
# =============================================================================
# Temporal Cloud - Asia Pacific (Mumbai) region
# Used for: workflow orchestration, activity execution, retry handling
# Namespace: trade-discovere.y8vfp

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY", "")

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
