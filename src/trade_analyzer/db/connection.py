"""
MongoDB connection handling for Trade Analyzer.

This module provides a singleton-based connection manager for MongoDB,
ensuring efficient connection pooling and automatic index creation.

Architecture:
-------------
The module implements a Singleton pattern to ensure only one MongoDB
connection is maintained throughout the application lifecycle. This is
critical for:
- Efficient connection pooling
- Consistent database state
- Resource management

Collections Managed:
-------------------
1. stocks - Trading universe with quality scores
2. trade_setups - Detected trading opportunities
3. trades - Executed and closed trades
4. regime_assessments - Market regime analysis
5. system_health - System performance metrics
6. fundamental_scores - Fundamental analysis results
7. institutional_holdings - FII/DII ownership data
8. position_sizes - Risk-adjusted position calculations
9. portfolio_allocations - Final portfolio compositions
10. monday_premarket - Pre-market analysis for trade execution
11. friday_summaries - End-of-week performance summaries
12. weekly_recommendations - Actionable trade recommendations

Index Strategy:
--------------
Each collection has optimized indexes for common query patterns:
- Single field indexes for equality lookups (symbol, status)
- Compound indexes for range + equality queries
- Descending indexes for "latest first" queries

Usage:
------
    # Simple usage (recommended)
    from trade_analyzer.db import get_database
    db = get_database()
    stocks = db.stocks.find({"is_active": True})

    # Advanced usage with custom connection
    from trade_analyzer.db.connection import MongoDBConnection
    conn = MongoDBConnection()
    db = conn.connect(custom_uri, custom_db_name)

    # Check connection status
    if conn.is_connected:
        print("Connected to MongoDB")

    # Clean disconnect
    conn.disconnect()

Thread Safety:
--------------
MongoClient is thread-safe and supports connection pooling.
The singleton pattern ensures all threads share the same client.

See Also:
---------
- trade_analyzer.config: Connection configuration
- trade_analyzer.db.models: Pydantic document models
- trade_analyzer.db.repositories: Data access layer
"""

from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

from trade_analyzer.config import get_mongo_database, get_mongo_uri


class MongoDBConnection:
    """
    Singleton MongoDB connection manager.

    This class implements the Singleton pattern to ensure only one MongoDB
    connection exists throughout the application. It handles:
    - Connection establishment with automatic retry
    - Index creation for all collections
    - Connection verification via ping
    - Clean disconnection

    Attributes:
        _instance: Singleton instance reference
        _client: PyMongo MongoClient instance
        _database: Active database reference

    Example:
        >>> conn = MongoDBConnection()
        >>> db = conn.connect()
        >>> print(conn.is_connected)  # True
        >>> conn.disconnect()
    """

    _instance: Optional["MongoDBConnection"] = None
    _client: Optional[MongoClient] = None
    _database: Optional[Database] = None

    def __new__(cls) -> "MongoDBConnection":
        """
        Create or return existing singleton instance.

        Returns:
            MongoDBConnection: The singleton instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(
        self,
        connection_string: Optional[str] = None,
        database_name: Optional[str] = None,
    ) -> Database:
        """
        Connect to MongoDB.

        Args:
            connection_string: MongoDB connection URI. If not provided,
                               uses configured default from config.py.
            database_name: Name of the database to use. Defaults to trade_analysis.

        Returns:
            MongoDB database instance.

        Raises:
            ConnectionFailure: If connection cannot be established.
            ValueError: If no connection string is provided.
        """
        if self._database is not None:
            return self._database

        uri = connection_string or get_mongo_uri()
        db_name = database_name or get_mongo_database()

        if not uri:
            raise ValueError(
                "MongoDB connection string not provided. "
                "Set MONGO_URI environment variable or configure in config.py."
            )

        self._client = MongoClient(uri)

        # Verify connection
        try:
            self._client.admin.command("ping")
        except ConnectionFailure as e:
            raise ConnectionFailure(f"Failed to connect to MongoDB: {e}") from e

        self._database = self._client[db_name]
        self._ensure_indexes()
        return self._database

    def _ensure_indexes(self) -> None:
        """
        Create indexes for optimal query performance.

        This method is called automatically on connection. It creates
        indexes for all collections used by the Trade Analyzer system.

        Index Design Principles:
        -----------------------
        1. Unique indexes where appropriate (symbol, timestamp)
        2. Compound indexes for common query patterns
        3. Descending indexes for "most recent" queries
        4. Background creation to avoid blocking

        Note:
        -----
        MongoDB's create_index is idempotent - it won't recreate
        existing indexes, making this safe to call multiple times.
        """
        if self._database is None:
            return

        # =====================================================================
        # STOCKS COLLECTION
        # Primary trading universe with quality scores and tier information
        # =====================================================================
        self._database.stocks.create_index("symbol", unique=True)  # Primary key
        self._database.stocks.create_index("sector")  # Sector filtering
        self._database.stocks.create_index("market_cap")  # Market cap filtering
        self._database.stocks.create_index("fundamentally_qualified")  # Phase 1 filter
        self._database.stocks.create_index(
            [("quality_score", -1), ("fundamentally_qualified", 1)]
        )  # Compound for high-quality fundamentally qualified

        # =====================================================================
        # TRADE SETUPS COLLECTION
        # Detected trading opportunities from technical analysis
        # =====================================================================
        self._database.trade_setups.create_index("stock_symbol")  # Symbol lookup
        self._database.trade_setups.create_index("created_at")  # Time-based queries
        self._database.trade_setups.create_index("setup_type")  # Filter by type
        self._database.trade_setups.create_index([("week_start", 1), ("status", 1)])  # Weekly view

        # =====================================================================
        # TRADES COLLECTION
        # Executed trades with entry/exit details
        # =====================================================================
        self._database.trades.create_index("stock_symbol")  # Symbol lookup
        self._database.trades.create_index("entry_date")  # Date filtering
        self._database.trades.create_index("status")  # Active/closed
        self._database.trades.create_index([("entry_date", -1)])  # Recent trades first

        # =====================================================================
        # REGIME ASSESSMENTS COLLECTION
        # Market regime analysis (Risk-On/Choppy/Risk-Off)
        # =====================================================================
        self._database.regime_assessments.create_index("timestamp", unique=True)
        self._database.regime_assessments.create_index([("timestamp", -1)])  # Latest first

        # =====================================================================
        # SYSTEM HEALTH COLLECTION
        # Performance monitoring and health metrics
        # =====================================================================
        self._database.system_health.create_index("timestamp")
        self._database.system_health.create_index([("timestamp", -1)])  # Latest first

        # =====================================================================
        # FUNDAMENTAL SCORES COLLECTION (Monthly refresh)
        # EPS growth, ROCE, debt ratios, etc.
        # =====================================================================
        self._database.fundamental_scores.create_index([("symbol", 1), ("calculated_at", -1)])
        self._database.fundamental_scores.create_index([("fundamental_score", -1)])  # Top scores
        self._database.fundamental_scores.create_index("qualifies")  # Pass/fail filter

        # =====================================================================
        # INSTITUTIONAL HOLDINGS COLLECTION (Monthly refresh)
        # FII, DII, promoter holding percentages
        # =====================================================================
        self._database.institutional_holdings.create_index([("symbol", 1), ("fetched_at", -1)])
        self._database.institutional_holdings.create_index("qualifies")  # Pass/fail filter

        # =====================================================================
        # POSITION SIZES COLLECTION (Phase 5: Risk Geometry)
        # Risk-adjusted position calculations
        # =====================================================================
        self._database.position_sizes.create_index([("symbol", 1), ("calculated_at", -1)])
        self._database.position_sizes.create_index("risk_qualifies")  # Pass/fail filter
        self._database.position_sizes.create_index([("overall_quality", -1)])  # Best first

        # =====================================================================
        # PORTFOLIO ALLOCATIONS COLLECTION (Phase 6: Portfolio)
        # Final portfolio compositions with sector/correlation limits
        # =====================================================================
        self._database.portfolio_allocations.create_index([("allocation_date", -1)])  # Latest
        self._database.portfolio_allocations.create_index("status")  # Active/executed
        self._database.portfolio_allocations.create_index("regime_state")  # Regime filter

        # =====================================================================
        # MONDAY PREMARKET COLLECTION (Phase 7: Execution)
        # Pre-market gap analysis for trade execution decisions
        # =====================================================================
        self._database.monday_premarket.create_index([("analysis_date", -1)])

        # =====================================================================
        # FRIDAY SUMMARIES COLLECTION (Phase 7: Execution)
        # End-of-week performance summaries
        # =====================================================================
        self._database.friday_summaries.create_index([("week_start", -1)])

        # =====================================================================
        # WEEKLY RECOMMENDATIONS COLLECTION (Phase 8: Output)
        # Final trade recommendations with action templates
        # =====================================================================
        self._database.weekly_recommendations.create_index([("week_start", -1)])  # Latest
        self._database.weekly_recommendations.create_index("status")  # Draft/approved/expired
        self._database.weekly_recommendations.create_index([("market_regime", 1), ("week_start", -1)])

    def disconnect(self) -> None:
        """
        Close MongoDB connection and release resources.

        This method should be called during application shutdown
        to ensure clean disconnection from the database.

        Note:
        -----
        After calling disconnect(), the singleton can be reconnected
        by calling connect() again.
        """
        if self._client is not None:
            self._client.close()
            self._client = None
            self._database = None

    @property
    def database(self) -> Optional[Database]:
        """
        Get the current database instance.

        Returns:
            Optional[Database]: The active database or None if not connected.
        """
        return self._database

    @property
    def is_connected(self) -> bool:
        """
        Check if currently connected to MongoDB.

        Returns:
            bool: True if connected, False otherwise.
        """
        return self._database is not None


# =============================================================================
# Convenience Functions
# =============================================================================


def get_database(
    connection_string: Optional[str] = None,
    database_name: Optional[str] = None,
) -> Database:
    """
    Get MongoDB database instance (convenience function).

    This is the recommended way to access the database throughout
    the application. It automatically handles connection management
    through the singleton pattern.

    Args:
        connection_string: Optional custom MongoDB URI.
                          Uses config.py default if not provided.
        database_name: Optional custom database name.
                      Uses 'trade_analysis' if not provided.

    Returns:
        Database: PyMongo database instance ready for queries.

    Example:
        >>> from trade_analyzer.db import get_database
        >>> db = get_database()
        >>> # Find all active stocks
        >>> stocks = list(db.stocks.find({"is_active": True}))
        >>> # Find high-quality stocks
        >>> quality = list(db.stocks.find({"quality_score": {"$gte": 60}}))

    Note:
    -----
    This function is re-exported from trade_analyzer.db.__init__ for
    convenient importing: `from trade_analyzer.db import get_database`
    """
    conn = MongoDBConnection()
    return conn.connect(connection_string, database_name)
