"""MongoDB connection handling."""

import os
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

from trade_analyzer.config import get_mongo_database, get_mongo_uri


class MongoDBConnection:
    """Singleton MongoDB connection manager."""

    _instance: Optional["MongoDBConnection"] = None
    _client: Optional[MongoClient] = None
    _database: Optional[Database] = None

    def __new__(cls) -> "MongoDBConnection":
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
        """Create indexes for optimal query performance."""
        if self._database is None:
            return

        # Stocks collection indexes
        self._database.stocks.create_index("symbol", unique=True)
        self._database.stocks.create_index("sector")
        self._database.stocks.create_index("market_cap")

        # Trade setups collection indexes
        self._database.trade_setups.create_index("stock_symbol")
        self._database.trade_setups.create_index("created_at")
        self._database.trade_setups.create_index("setup_type")
        self._database.trade_setups.create_index([("week_start", 1), ("status", 1)])

        # Trades collection indexes
        self._database.trades.create_index("stock_symbol")
        self._database.trades.create_index("entry_date")
        self._database.trades.create_index("status")
        self._database.trades.create_index([("entry_date", -1)])

        # Regime assessments collection indexes
        self._database.regime_assessments.create_index("timestamp", unique=True)
        self._database.regime_assessments.create_index([("timestamp", -1)])

        # System health collection indexes
        self._database.system_health.create_index("timestamp")
        self._database.system_health.create_index([("timestamp", -1)])

    def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._database = None

    @property
    def database(self) -> Optional[Database]:
        """Get current database instance."""
        return self._database

    @property
    def is_connected(self) -> bool:
        """Check if connected to MongoDB."""
        return self._database is not None


# Convenience function
def get_database(
    connection_string: Optional[str] = None,
    database_name: Optional[str] = None,
) -> Database:
    """Get MongoDB database instance."""
    conn = MongoDBConnection()
    return conn.connect(connection_string, database_name)
