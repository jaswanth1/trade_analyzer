"""
MongoDB database layer for Trade Analyzer.

This package provides the complete data persistence layer for the
Trade Analyzer application, including:

Components:
----------
1. Connection Management (connection.py)
   - Singleton-based MongoDB connection
   - Automatic index creation
   - Connection pooling

2. Document Models (models.py)
   - Pydantic models for all document types
   - Validation and serialization
   - Enums for state machines

3. Repositories (repositories.py)
   - Data access patterns
   - CRUD operations
   - Query helpers

Collections:
-----------
- stocks: Trading universe with quality scores
- trade_setups: Detected trading opportunities
- trades: Executed trades with P&L
- regime_assessments: Market regime analysis
- system_health: Performance metrics
- fundamental_scores: Fundamental analysis (monthly)
- institutional_holdings: FII/DII data (monthly)
- position_sizes: Risk-adjusted positions
- portfolio_allocations: Final portfolios
- monday_premarket: Gap analysis
- friday_summaries: Weekly summaries
- weekly_recommendations: Final output

Usage:
------
    # Simple database access
    from trade_analyzer.db import get_database
    db = get_database()
    stocks = list(db.stocks.find({"is_active": True}))

    # Using repositories
    from trade_analyzer.db import StockRepository
    repo = StockRepository()
    high_quality = repo.find_high_quality(min_score=70)

    # Using models
    from trade_analyzer.db import StockDoc
    stock = StockDoc(symbol="RELIANCE", name="Reliance Industries")

See Also:
---------
- trade_analyzer.config: Database configuration
"""

from trade_analyzer.db.connection import MongoDBConnection, get_database
from trade_analyzer.db.models import (
    RegimeAssessmentDoc,
    StockDoc,
    TradeSetupDoc,
    TradeDoc,
    SystemHealthDoc,
)
from trade_analyzer.db.repositories import (
    StockRepository,
    TradeSetupRepository,
    TradeRepository,
    RegimeRepository,
)

__all__ = [
    # Connection
    "MongoDBConnection",
    "get_database",
    # Models
    "RegimeAssessmentDoc",
    "StockDoc",
    "TradeSetupDoc",
    "TradeDoc",
    "SystemHealthDoc",
    # Repositories
    "StockRepository",
    "TradeSetupRepository",
    "TradeRepository",
    "RegimeRepository",
]
