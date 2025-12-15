"""Configuration settings for Trade Analyzer."""

import os

# MongoDB Configuration
MONGO_USERNAME = os.getenv("MONGO_USERNAME", "doadmin")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "E4l6W02aC9m5U83x")
MONGO_HOST = os.getenv(
    "MONGO_HOST", "mongodb+srv://db-trading-setup-4aad9e87.mongo.ondigitalocean.com"
)
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "trade_analysis")

# Build connection URI
MONGO_URI = os.getenv(
    "MONGO_URI",
    f"mongodb+srv://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST.replace('mongodb+srv://', '')}/?retryWrites=true&w=majority",
)

# Temporal Cloud Configuration
TEMPORAL_ADDRESS = os.getenv(
    "TEMPORAL_ADDRESS", "ap-south-1.aws.api.temporal.io:7233"
)
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "trade-discovere.y8vfp")
TEMPORAL_API_KEY = os.getenv(
    "TEMPORAL_API_KEY",
    "eyJhbGciOiJFUzI1NiIsImtpZCI6Ild2dHdhQSJ9.eyJhY2NvdW50X2lkIjoieTh2ZnAiLCJhdWQiOlsidGVtcG9yYWwuaW8iXSwiZXhwIjoxODI4ODY1NjkwLCJpc3MiOiJ0ZW1wb3JhbC5pbyIsImp0aSI6IktvN0draXFTR1pQQTVTdkQyUm9ncGY0YlZyVUJDd2hQIiwia2V5X2lkIjoiS283R2tpcVNHWlBBNVN2RDJSb2dwZjRiVnJVQkN3aFAiLCJzdWIiOiIzNTQ1MTcxMGM1ODQ0YjUwODU1ODE5MGRhMGNiZmYyYyJ9.0t4QLecFwNnRzxVpLiesPuxMiNobXVsdytYqi-KU-n2uF20iqiyB-Ev-hUXnQ04iCou1U1RKc3i6ND4VRL6vvg",
)

# Task Queue Names
TASK_QUEUE_UNIVERSE_REFRESH = "trade-analyzer-universe-refresh"
TASK_QUEUE_REGIME_ANALYSIS = "trade-analyzer-regime-analysis"
TASK_QUEUE_TRADE_PIPELINE = "trade-analyzer-pipeline"


def get_mongo_uri() -> str:
    """Get MongoDB connection URI."""
    return MONGO_URI


def get_mongo_database() -> str:
    """Get MongoDB database name."""
    return MONGO_DATABASE


def get_temporal_config() -> dict:
    """Get Temporal connection configuration."""
    return {
        "address": TEMPORAL_ADDRESS,
        "namespace": TEMPORAL_NAMESPACE,
        "api_key": TEMPORAL_API_KEY,
    }


def is_temporal_cloud() -> bool:
    """Check if using Temporal Cloud (has API key or non-localhost address)."""
    return bool(TEMPORAL_API_KEY) or "tmprl.cloud" in TEMPORAL_ADDRESS or "temporal.io" in TEMPORAL_ADDRESS
