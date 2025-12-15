"""Repository pattern for MongoDB data access.

This module implements the Repository pattern to provide a clean abstraction layer
over MongoDB collections. Each repository class encapsulates CRUD operations and
business logic for a specific document type, isolating the rest of the application
from direct database interactions.

Architecture
------------
The module follows a layered architecture:

    Application Layer (workflows, activities, UI)
            ↓
    Repository Layer (this module)
            ↓
    MongoDB Collections (stocks, trades, setups, regime_assessments)

Repository Pattern Benefits
----------------------------
1. **Separation of Concerns**: Business logic separated from data access
2. **Testability**: Easy to mock repositories in unit tests
3. **Maintainability**: Database changes isolated to repository layer
4. **Type Safety**: Pydantic models ensure data validation
5. **Reusability**: Common queries encapsulated in repository methods

Available Repositories
----------------------
- **StockRepository**: Master stock data and trading universe
- **TradeSetupRepository**: Weekly trade setups (candidate trades)
- **TradeRepository**: Executed trades with P&L tracking
- **RegimeRepository**: Market regime assessments (Risk-On/Choppy/Risk-Off)

Usage Example
-------------
    from trade_analyzer.db.connection import get_database
    from trade_analyzer.db.repositories import StockRepository, RegimeRepository
    from trade_analyzer.db.models import StockDoc

    # Get database connection
    db = get_database()

    # Initialize repositories
    stock_repo = StockRepository(db)
    regime_repo = RegimeRepository(db)

    # Check market regime before proceeding
    regime = regime_repo.get_latest()
    if regime and regime["state"] == "risk_off":
        print("Risk-Off environment: Skipping new trades")
        exit(0)

    # Get tradable universe
    stocks = stock_repo.get_universe(
        min_market_cap=1000,  # ₹1,000 crores
        min_turnover=5  # ₹5 crores daily
    )

    # Upsert stock data
    stock = StockDoc(
        symbol="RELIANCE",
        name="Reliance Industries",
        sector="Energy",
        market_cap=1750000,
        avg_daily_turnover=250,
        is_active=True
    )
    stock_id = stock_repo.upsert(stock)

Threading and Connection Safety
--------------------------------
All repositories are designed to work with PyMongo's connection pooling.
Each repository instance holds a reference to a Database object, which
internally manages thread-safe connection pooling.

For multi-threaded applications (e.g., Temporal workers), create repository
instances per thread/activity, but share the same Database connection:

    db = get_database()  # Singleton with connection pool

    # Thread 1
    stock_repo_1 = StockRepository(db)

    # Thread 2
    stock_repo_2 = StockRepository(db)

    # Both use the same connection pool safely

Notes
-----
- All timestamps use UTC
- MongoDB ObjectIds are converted to strings in returned dicts
- Upsert operations update `last_updated` automatically
- Soft deletes via `is_active` flag (stocks never physically deleted)
"""

from datetime import datetime
from typing import Optional

from bson import ObjectId
from pymongo.database import Database

from trade_analyzer.db.models import (
    RegimeAssessmentDoc,
    RegimeState,
    SetupStatus,
    StockDoc,
    TradeDoc,
    TradeSetupDoc,
    TradeStatus,
)


class BaseRepository:
    """Base repository with common operations.

    Provides utility methods for converting between Pydantic models and MongoDB
    documents. All concrete repositories inherit from this class.

    Attributes
    ----------
    collection : pymongo.collection.Collection
        MongoDB collection for this repository.

    Notes
    -----
    - MongoDB uses `_id` (ObjectId), but we expose `id` (str) to the application
    - All ID conversions happen transparently in _to_doc and _from_doc
    """

    def __init__(self, db: Database, collection_name: str):
        """Initialize repository with database connection.

        Args
        ----
        db : pymongo.database.Database
            MongoDB database instance.
        collection_name : str
            Name of the MongoDB collection to access.
        """
        self.collection = db[collection_name]

    def _to_doc(self, data: dict) -> dict:
        """Convert model dict to MongoDB document.

        Removes the string `id` field since MongoDB uses `_id` (ObjectId).

        Args
        ----
        data : dict
            Dictionary from Pydantic model.

        Returns
        -------
        dict
            MongoDB-ready document.
        """
        doc = data.copy()
        if "_id" not in doc:
            doc.pop("id", None)
        return doc

    def _from_doc(self, doc: dict) -> dict:
        """Convert MongoDB document to dict with string id.

        Transforms MongoDB's ObjectId `_id` to string `id` for application use.

        Args
        ----
        doc : dict
            MongoDB document with _id field.

        Returns
        -------
        dict
            Document with string id field instead of ObjectId _id.
        """
        if doc and "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return doc


class StockRepository(BaseRepository):
    """Repository for stock master data.

    Manages the trading universe of NSE stocks, including:
    - Master stock data (symbol, name, sector, market cap)
    - Liquidity metrics (turnover, trading days)
    - Quality scoring (MTF status, index membership tiers)
    - Active/inactive status (soft deletes)

    The stocks collection is the foundation of the trading system. Every stock
    in the NSE EQ segment is stored here, along with metadata used for universe
    filtering and quality scoring.

    Collection: stocks
    ------------------
    Indexes:
        - symbol (unique): Fast lookups by stock symbol
        - sector: Filter stocks by sector for portfolio construction
        - is_active: Quickly get active trading universe

    Usage Pattern
    -------------
    Weekend workflow:
        1. Refresh universe from Upstox API (via UniverseRefreshWorkflow)
        2. Enrich with quality scores (via UniverseSetupWorkflow)
        3. Filter universe with get_universe() for factor analysis

    Daily monitoring:
        1. Check stock status (active/inactive)
        2. Verify liquidity metrics still meet thresholds
        3. Track sector exposures in portfolio

    Example
    -------
        from trade_analyzer.db.connection import get_database
        from trade_analyzer.db.models import StockDoc

        db = get_database()
        repo = StockRepository(db)

        # Get high-quality, liquid stocks
        universe = repo.get_universe(
            min_market_cap=1000,  # ₹1,000 crores
            min_turnover=5  # ₹5 crores daily
        )
        print(f"Tradable universe: {len(universe)} stocks")

        # Check sector exposure
        it_stocks = repo.get_by_sector("Information Technology")
        print(f"IT sector has {len(it_stocks)} active stocks")

        # Upsert new stock data
        stock = StockDoc(
            symbol="TCS",
            name="Tata Consultancy Services",
            sector="Information Technology",
            market_cap=1450000,
            avg_daily_turnover=320,
            is_active=True,
            is_mtf_available=True,
            liquidity_tier="A"
        )
        stock_id = repo.upsert(stock)
    """

    def __init__(self, db: Database):
        """Initialize stock repository.

        Args
        ----
        db : pymongo.database.Database
            MongoDB database instance.
        """
        super().__init__(db, "stocks")

    def upsert(self, stock: StockDoc) -> str:
        """Insert or update a stock by symbol.

        If a stock with the same symbol exists, updates all fields.
        If not, inserts a new document. Automatically updates last_updated timestamp.

        Args
        ----
        stock : StockDoc
            Stock document to upsert.

        Returns
        -------
        str
            MongoDB document ID (as string).

        Example
        -------
            stock = StockDoc(
                symbol="INFY",
                name="Infosys",
                sector="Information Technology",
                market_cap=650000,
                avg_daily_turnover=180,
                is_active=True
            )
            stock_id = repo.upsert(stock)
            print(f"Upserted stock with ID: {stock_id}")
        """
        data = stock.model_dump()
        data["last_updated"] = datetime.utcnow()
        result = self.collection.update_one(
            {"symbol": stock.symbol}, {"$set": data}, upsert=True
        )
        if result.upserted_id:
            return str(result.upserted_id)
        doc = self.collection.find_one({"symbol": stock.symbol})
        return str(doc["_id"]) if doc else ""

    def get_by_symbol(self, symbol: str) -> Optional[dict]:
        """Get stock by symbol.

        Args
        ----
        symbol : str
            Stock symbol (e.g., "RELIANCE", "TCS"). Case-insensitive.

        Returns
        -------
        dict or None
            Stock document dict with id field, or None if not found.

        Example
        -------
            stock = repo.get_by_symbol("RELIANCE")
            if stock:
                print(f"{stock['name']} - Sector: {stock['sector']}")
            else:
                print("Stock not found")
        """
        doc = self.collection.find_one({"symbol": symbol.upper()})
        return self._from_doc(doc) if doc else None

    def get_all_active(self) -> list[dict]:
        """Get all active stocks.

        Returns only stocks with is_active=True. Inactive stocks are soft-deleted
        and excluded from the trading universe.

        Returns
        -------
        list[dict]
            List of active stock documents.

        Example
        -------
            active_stocks = repo.get_all_active()
            print(f"Active universe size: {len(active_stocks)}")
        """
        docs = self.collection.find({"is_active": True})
        return [self._from_doc(doc) for doc in docs]

    def get_by_sector(self, sector: str) -> list[dict]:
        """Get active stocks by sector.

        Used for portfolio construction to enforce sector exposure limits.
        Example: Max 3 stocks per sector, max 25% sector exposure.

        Args
        ----
        sector : str
            Sector name (e.g., "Information Technology", "Energy", "Banking").

        Returns
        -------
        list[dict]
            List of active stock documents in the sector.

        Example
        -------
            # Check current IT sector holdings
            it_stocks = repo.get_by_sector("Information Technology")
            if len(it_stocks) >= 3:
                print("Already have 3 IT stocks, skip new IT setups")
        """
        docs = self.collection.find({"sector": sector, "is_active": True})
        return [self._from_doc(doc) for doc in docs]

    def get_universe(
        self, min_market_cap: float = 1000, min_turnover: float = 5
    ) -> list[dict]:
        """Get filtered stock universe.

        Returns stocks meeting minimum liquidity and market cap thresholds.
        This is the starting point for factor analysis and setup detection.

        Args
        ----
        min_market_cap : float, optional
            Minimum market cap in crores (default: 1000 = ₹1,000 crores).
        min_turnover : float, optional
            Minimum average daily turnover in crores (default: 5 = ₹5 crores).

        Returns
        -------
        list[dict]
            List of stock documents meeting filter criteria.

        Notes
        -----
        Default thresholds align with system requirements:
            - Market cap ≥ ₹1,000 crores (avoids micro-caps)
            - Turnover ≥ ₹5 crores (ensures reasonable liquidity)

        Typical universe sizes:
            - NSE EQ (all stocks): ~1,800
            - After liquidity filters: ~500
            - After momentum filters: ~80
            - Final setups: 3-7 per week

        Example
        -------
            # Get institutional-grade universe
            universe = repo.get_universe(
                min_market_cap=1000,  # ₹1,000 crores
                min_turnover=5  # ₹5 crores
            )
            print(f"Tradable universe: {len(universe)} stocks")

            # More restrictive filter for conservative strategy
            universe_conservative = repo.get_universe(
                min_market_cap=5000,  # Large-cap only
                min_turnover=20  # High liquidity
            )
            print(f"Conservative universe: {len(universe_conservative)} stocks")
        """
        docs = self.collection.find(
            {
                "is_active": True,
                "market_cap": {"$gte": min_market_cap},
                "avg_daily_turnover": {"$gte": min_turnover},
            }
        )
        return [self._from_doc(doc) for doc in docs]


class TradeSetupRepository(BaseRepository):
    """Repository for trade setups.

    Manages weekly trade setups - candidate trades identified during weekend
    analysis. Each setup represents a potential trade opportunity with defined
    entry, stop, and target levels.

    A setup is NOT an executed trade - it's a "trade idea" or "watchlist item"
    that may or may not get executed depending on Monday gap behavior.

    Collection: trade_setups
    -------------------------
    Indexes:
        - week_start: Query setups by week
        - status: Filter active vs triggered/invalidated setups
        - composite_score: Sort by quality ranking

    Setup Lifecycle
    ---------------
    1. ACTIVE: Setup identified on weekend, waiting for Monday entry
    2. TRIGGERED: Entry executed, becomes a Trade (in trades collection)
    3. INVALIDATED: Setup conditions no longer valid (gap, price action)
    4. EXPIRED: Week passed without trigger

    Usage Pattern
    -------------
    Weekend:
        1. Pipeline generates 3-7 setups via factor analysis
        2. Store each setup with create()
        3. Setups remain ACTIVE until Monday

    Monday morning:
        1. Check gap behavior vs entry zone
        2. If gap through stop: Mark INVALIDATED
        3. If entry triggered: Mark TRIGGERED, create Trade
        4. If still valid: Keep ACTIVE for intraday entry

    End of week:
        1. Any un-triggered setups → Mark EXPIRED
        2. Archive for performance analysis

    Example
    -------
        from trade_analyzer.db.connection import get_database
        from trade_analyzer.db.models import TradeSetupDoc, SetupStatus
        from datetime import datetime

        db = get_database()
        repo = TradeSetupRepository(db)

        # Weekend: Create new setup
        setup = TradeSetupDoc(
            symbol="RELIANCE",
            setup_type="pullback",
            week_start=datetime(2025, 12, 15),
            entry_zone=(2650, 2680),
            stop_loss=2580,
            target_1=2780,
            target_2=2850,
            composite_score=8.5,
            status=SetupStatus.ACTIVE
        )
        setup_id = repo.create(setup)

        # Monday: Check active setups
        active = repo.get_active_setups()
        for s in active:
            if should_trigger(s):
                repo.update_status(s["id"], SetupStatus.TRIGGERED)
                # Create corresponding Trade

        # Review this week's performance
        this_week = repo.get_by_week(datetime(2025, 12, 15))
        triggered = [s for s in this_week if s["status"] == "triggered"]
        print(f"Triggered {len(triggered)} out of {len(this_week)} setups")
    """

    def __init__(self, db: Database):
        """Initialize trade setup repository.

        Args
        ----
        db : pymongo.database.Database
            MongoDB database instance.
        """
        super().__init__(db, "trade_setups")

    def create(self, setup: TradeSetupDoc) -> str:
        """Create a new trade setup.

        Args
        ----
        setup : TradeSetupDoc
            Trade setup document to insert.

        Returns
        -------
        str
            MongoDB document ID (as string).

        Example
        -------
            setup = TradeSetupDoc(
                symbol="TCS",
                setup_type="breakout",
                week_start=datetime(2025, 12, 15),
                entry_zone=(4200, 4230),
                stop_loss=4050,
                target_1=4400,
                target_2=4520,
                composite_score=9.2,
                status=SetupStatus.ACTIVE
            )
            setup_id = repo.create(setup)
        """
        data = setup.model_dump()
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_by_id(self, setup_id: str) -> Optional[dict]:
        """Get setup by ID.

        Args
        ----
        setup_id : str
            MongoDB document ID (string format).

        Returns
        -------
        dict or None
            Setup document dict, or None if not found.

        Example
        -------
            setup = repo.get_by_id("507f1f77bcf86cd799439011")
            if setup:
                print(f"{setup['symbol']} - {setup['setup_type']}")
        """
        doc = self.collection.find_one({"_id": ObjectId(setup_id)})
        return self._from_doc(doc) if doc else None

    def get_active_setups(self, week_start: Optional[datetime] = None) -> list[dict]:
        """Get all active setups, optionally for a specific week.

        Active setups are waiting for entry trigger. Used on Monday morning
        to check which setups are still valid after weekend gaps.

        Args
        ----
        week_start : datetime, optional
            If provided, filter to specific week. Otherwise, get all active setups.

        Returns
        -------
        list[dict]
            List of setup documents, sorted by composite_score (descending).

        Example
        -------
            # Monday morning: Check all active setups
            active = repo.get_active_setups()
            print(f"Monitoring {len(active)} active setups today")

            # Check specific week's active setups
            this_week = repo.get_active_setups(week_start=datetime(2025, 12, 15))
        """
        query = {"status": SetupStatus.ACTIVE.value}
        if week_start:
            query["week_start"] = week_start
        docs = self.collection.find(query).sort("composite_score", -1)
        return [self._from_doc(doc) for doc in docs]

    def get_by_week(self, week_start: datetime) -> list[dict]:
        """Get all setups for a specific week.

        Returns all setups regardless of status (active, triggered, invalidated, expired).
        Used for weekly performance analysis and reporting.

        Args
        ----
        week_start : datetime
            Week start date (typically a Monday).

        Returns
        -------
        list[dict]
            List of setup documents, sorted by composite_score (descending).

        Example
        -------
            # End of week: Analyze this week's setups
            week = datetime(2025, 12, 15)
            setups = repo.get_by_week(week)

            triggered = [s for s in setups if s["status"] == "triggered"]
            invalidated = [s for s in setups if s["status"] == "invalidated"]

            print(f"Week of {week.date()}:")
            print(f"  Total setups: {len(setups)}")
            print(f"  Triggered: {len(triggered)}")
            print(f"  Invalidated: {len(invalidated)}")
            print(f"  Trigger rate: {len(triggered)/len(setups)*100:.1f}%")
        """
        docs = self.collection.find({"week_start": week_start}).sort(
            "composite_score", -1
        )
        return [self._from_doc(doc) for doc in docs]

    def update_status(self, setup_id: str, status: SetupStatus) -> bool:
        """Update setup status.

        Used to transition setup through its lifecycle:
        ACTIVE → TRIGGERED (when entry executed)
        ACTIVE → INVALIDATED (when gap through stop or conditions fail)
        ACTIVE → EXPIRED (when week passes without trigger)

        Args
        ----
        setup_id : str
            MongoDB document ID (string format).
        status : SetupStatus
            New status (ACTIVE, TRIGGERED, INVALIDATED, EXPIRED).

        Returns
        -------
        bool
            True if update succeeded, False if setup not found.

        Example
        -------
            # Monday morning: Gap analysis
            setup = repo.get_by_id(setup_id)
            monday_open = 2550

            if monday_open < setup["stop_loss"]:
                # Gapped through stop
                repo.update_status(setup_id, SetupStatus.INVALIDATED)
                print("Setup invalidated: Gap through stop")
            elif monday_open in range(setup["entry_zone"][0], setup["entry_zone"][1]):
                # Entry triggered
                repo.update_status(setup_id, SetupStatus.TRIGGERED)
                # Create Trade
        """
        result = self.collection.update_one(
            {"_id": ObjectId(setup_id)}, {"$set": {"status": status.value}}
        )
        return result.modified_count > 0

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get most recent setups.

        Used for UI display and recent performance monitoring.

        Args
        ----
        limit : int, optional
            Maximum number of setups to return (default: 20).

        Returns
        -------
        list[dict]
            List of setup documents, sorted by created_at (descending).

        Example
        -------
            recent = repo.get_recent(limit=10)
            for s in recent:
                print(f"{s['created_at']} - {s['symbol']} - {s['status']}")
        """
        docs = self.collection.find().sort("created_at", -1).limit(limit)
        return [self._from_doc(doc) for doc in docs]


class TradeRepository(BaseRepository):
    """Repository for executed trades.

    Manages actual executed trades with entry/exit prices, P&L tracking, and
    performance metrics. A trade is created when a setup gets triggered and
    entry is executed.

    Key differences from TradeSetupRepository:
    - **Setup**: Trade idea, may or may not execute
    - **Trade**: Actual position, money at risk, tracked P&L

    Collection: trades
    ------------------
    Indexes:
        - symbol: Group trades by stock
        - status: Filter active vs closed trades
        - entry_date: Time-series analysis
        - exit_date: Performance analysis by close date

    Trade Lifecycle
    ---------------
    1. ACTIVE: Position open, monitoring for exit signals
    2. CLOSED_WIN: Position closed with profit (pnl > 0)
    3. CLOSED_LOSS: Position closed with loss (pnl <= 0)

    Exit reasons:
    - "target_1": First target hit
    - "target_2": Second target hit
    - "stop_loss": Stop hit
    - "trailing_stop": Trailing stop hit
    - "time_exit": Time-based exit (holding too long)
    - "regime_exit": Market regime changed to Risk-Off

    Usage Pattern
    -------------
    Monday morning (entry):
        1. Setup triggers → Create Trade with entry_date, entry_price
        2. Calculate shares based on risk management
        3. Trade stays ACTIVE

    During the week (monitoring):
        1. Check if stop or target hit
        2. If exit triggered → Call close_trade()
        3. Automatically calculates P&L, R-multiple, holding days

    Weekend (analysis):
        1. Review active trades, adjust stops if needed
        2. Calculate performance stats with get_performance_stats()
        3. Use metrics for regime assessment and health checks

    Example
    -------
        from trade_analyzer.db.connection import get_database
        from trade_analyzer.db.models import TradeDoc, TradeStatus
        from datetime import datetime

        db = get_database()
        repo = TradeRepository(db)

        # Monday: Setup triggered, create trade
        trade = TradeDoc(
            setup_id="507f1f77bcf86cd799439011",
            symbol="RELIANCE",
            entry_date=datetime(2025, 12, 15),
            entry_price=2665,
            stop_loss=2580,
            target_1=2780,
            target_2=2850,
            shares=100,
            status=TradeStatus.ACTIVE
        )
        trade_id = repo.create(trade)

        # Wednesday: Target hit, close trade
        repo.close_trade(
            trade_id=trade_id,
            exit_price=2785,
            exit_date=datetime(2025, 12, 17),
            exit_reason="target_1"
        )

        # Weekend: Analyze performance
        stats = repo.get_performance_stats(days=90)
        print(f"12-week win rate: {stats['win_rate']*100:.1f}%")
        print(f"Expectancy: {stats['expectancy']:.2f}R")
        print(f"Total P&L: ₹{stats['total_pnl']:,.0f}")
    """

    def __init__(self, db: Database):
        """Initialize trade repository.

        Args
        ----
        db : pymongo.database.Database
            MongoDB database instance.
        """
        super().__init__(db, "trades")

    def create(self, trade: TradeDoc) -> str:
        """Create a new trade.

        Args
        ----
        trade : TradeDoc
            Trade document to insert.

        Returns
        -------
        str
            MongoDB document ID (as string).

        Example
        -------
            trade = TradeDoc(
                setup_id="507f1f77bcf86cd799439011",
                symbol="TCS",
                entry_date=datetime(2025, 12, 15),
                entry_price=4215,
                stop_loss=4050,
                target_1=4400,
                target_2=4520,
                shares=50,
                status=TradeStatus.ACTIVE
            )
            trade_id = repo.create(trade)
        """
        data = trade.model_dump()
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_by_id(self, trade_id: str) -> Optional[dict]:
        """Get trade by ID.

        Args
        ----
        trade_id : str
            MongoDB document ID (string format).

        Returns
        -------
        dict or None
            Trade document dict, or None if not found.

        Example
        -------
            trade = repo.get_by_id("507f1f77bcf86cd799439011")
            if trade and trade["status"] == "active":
                print(f"Monitoring {trade['symbol']} at ₹{trade['entry_price']}")
        """
        doc = self.collection.find_one({"_id": ObjectId(trade_id)})
        return self._from_doc(doc) if doc else None

    def get_active_trades(self) -> list[dict]:
        """Get all active (open) trades.

        Returns trades with status=ACTIVE. Used for daily monitoring,
        portfolio risk checks, and exit signal detection.

        Returns
        -------
        list[dict]
            List of active trade documents.

        Example
        -------
            # Daily monitoring: Check all open positions
            active = repo.get_active_trades()
            print(f"Currently holding {len(active)} positions:")

            total_risk = 0
            for t in active:
                risk_per_share = t["entry_price"] - t["stop_loss"]
                position_risk = risk_per_share * t["shares"]
                total_risk += position_risk
                print(f"  {t['symbol']}: {t['shares']} shares @ ₹{t['entry_price']}")
                print(f"    Risk: ₹{position_risk:,.0f}")

            print(f"Total portfolio risk: ₹{total_risk:,.0f}")
        """
        docs = self.collection.find({"status": TradeStatus.ACTIVE.value})
        return [self._from_doc(doc) for doc in docs]

    def get_by_status(self, status: TradeStatus) -> list[dict]:
        """Get trades by status.

        Args
        ----
        status : TradeStatus
            Trade status (ACTIVE, CLOSED_WIN, CLOSED_LOSS).

        Returns
        -------
        list[dict]
            List of trade documents with the specified status.

        Example
        -------
            # Analyze winning trades
            wins = repo.get_by_status(TradeStatus.CLOSED_WIN)
            avg_hold_days = sum(t["holding_days"] for t in wins) / len(wins)
            print(f"Average winning trade held {avg_hold_days:.1f} days")
        """
        docs = self.collection.find({"status": status.value})
        return [self._from_doc(doc) for doc in docs]

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_date: datetime,
        exit_reason: str,
    ) -> bool:
        """Close a trade with exit details.

        Automatically calculates P&L, R-multiple, holding days, and sets status
        to CLOSED_WIN or CLOSED_LOSS based on profitability.

        Args
        ----
        trade_id : str
            MongoDB document ID of the trade to close.
        exit_price : float
            Price at which position was exited.
        exit_date : datetime
            Date/time of exit.
        exit_reason : str
            Reason for exit (e.g., "target_1", "stop_loss", "trailing_stop",
            "time_exit", "regime_exit").

        Returns
        -------
        bool
            True if trade was closed successfully, False if trade not found.

        Notes
        -----
        Automatically calculated fields:
            - pnl: Absolute profit/loss in currency
            - pnl_percent: Percentage return on entry price
            - r_multiple: Multiples of initial risk (1R = stop distance)
            - holding_days: Number of days position was held
            - status: CLOSED_WIN if pnl > 0, else CLOSED_LOSS

        R-multiple calculation:
            R = (entry_price - stop_loss)  # Initial risk per share
            r_multiple = (exit_price - entry_price) / R

        Examples:
            - Exit at entry + 2R: r_multiple = 2.0
            - Exit at stop: r_multiple = -1.0
            - Exit at breakeven: r_multiple = 0.0

        Example
        -------
            # Target hit
            success = repo.close_trade(
                trade_id="507f1f77bcf86cd799439011",
                exit_price=2785,
                exit_date=datetime(2025, 12, 17),
                exit_reason="target_1"
            )

            if success:
                trade = repo.get_by_id("507f1f77bcf86cd799439011")
                print(f"Trade closed:")
                print(f"  P&L: ₹{trade['pnl']:,.0f} ({trade['pnl_percent']:.1f}%)")
                print(f"  R-multiple: {trade['r_multiple']:.2f}R")
                print(f"  Held for {trade['holding_days']} days")

            # Stop hit
            repo.close_trade(
                trade_id=trade_id,
                exit_price=2575,
                exit_date=datetime(2025, 12, 16),
                exit_reason="stop_loss"
            )

            # Regime exit (Risk-Off triggered)
            repo.close_trade(
                trade_id=trade_id,
                exit_price=2700,
                exit_date=datetime.utcnow(),
                exit_reason="regime_exit"
            )
        """
        trade = self.get_by_id(trade_id)
        if not trade:
            return False

        entry_price = trade["entry_price"]
        stop_loss = trade["stop_loss"]
        risk_per_share = entry_price - stop_loss
        pnl_per_share = exit_price - entry_price
        shares = trade["shares"]

        pnl = pnl_per_share * shares
        pnl_percent = (pnl_per_share / entry_price) * 100
        r_multiple = pnl_per_share / risk_per_share if risk_per_share != 0 else 0

        status = TradeStatus.CLOSED_WIN if pnl > 0 else TradeStatus.CLOSED_loss

        entry_date = trade.get("entry_date") or datetime.utcnow()
        holding_days = (exit_date - entry_date).days

        result = self.collection.update_one(
            {"_id": ObjectId(trade_id)},
            {
                "$set": {
                    "exit_price": exit_price,
                    "exit_date": exit_date,
                    "exit_reason": exit_reason,
                    "status": status.value,
                    "pnl": pnl,
                    "pnl_percent": pnl_percent,
                    "r_multiple": r_multiple,
                    "holding_days": holding_days,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        return result.modified_count > 0

    def get_performance_stats(self, days: int = 365) -> dict:
        """Calculate performance statistics for closed trades.

        Computes key metrics for system health monitoring and regime assessment.
        CRITICAL for determining if the trading edge is still present.

        Args
        ----
        days : int, optional
            Lookback period in days (default: 365 = 1 year).
            Common values:
                - 84 days (12 weeks): Short-term health check
                - 365 days (52 weeks): Long-term health check

        Returns
        -------
        dict
            Performance statistics with keys:
                - total_trades: Number of closed trades
                - wins: Number of winning trades
                - losses: Number of losing trades
                - win_rate: Percentage of winning trades (0-1)
                - avg_win_r: Average R-multiple for winners
                - avg_loss_r: Average R-multiple for losers (negative)
                - expectancy: Expected R per trade
                - total_pnl: Total profit/loss in currency

        Notes
        -----
        Expectancy formula:
            E = (WinRate × AvgWin) + ((1 - WinRate) × AvgLoss)

        System health interpretation:
            - expectancy > 0.30R: Excellent (original target)
            - expectancy > 0.10R: Good (realistic target)
            - expectancy > 0.00R: Break-even after costs
            - expectancy < 0.00R: System failing, stop trading

        Win rate interpretation:
            - > 55%: Excellent
            - 50-55%: Good (realistic)
            - 45-50%: Acceptable if R:R is good
            - < 45%: Concerning

        CRITICAL: Transaction costs (~0.27% round-trip) mean you need
        positive expectancy AFTER costs. If raw expectancy is < 0.20R,
        net expectancy may be near zero.

        Example
        -------
            # 12-week health check
            stats_12w = repo.get_performance_stats(days=84)
            print(f"12-week performance:")
            print(f"  Trades: {stats_12w['total_trades']}")
            print(f"  Win rate: {stats_12w['win_rate']*100:.1f}%")
            print(f"  Avg win: {stats_12w['avg_win_r']:.2f}R")
            print(f"  Avg loss: {stats_12w['avg_loss_r']:.2f}R")
            print(f"  Expectancy: {stats_12w['expectancy']:.2f}R")
            print(f"  Total P&L: ₹{stats_12w['total_pnl']:,.0f}")

            # Health check logic
            if stats_12w['expectancy'] < 0:
                print("WARNING: Negative expectancy. Stop trading!")
            elif stats_12w['expectancy'] < 0.10:
                print("CAUTION: Low expectancy. Review system.")
            else:
                print("System healthy. Continue trading.")

            # Compare 12-week vs 52-week
            stats_52w = repo.get_performance_stats(days=365)
            if stats_12w['expectancy'] < stats_52w['expectancy'] * 0.5:
                print("Recent performance degrading. Possible edge decay.")
        """
        cutoff = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = cutoff.replace(day=cutoff.day - days if cutoff.day > days else 1)

        closed_trades = list(
            self.collection.find(
                {
                    "status": {"$in": [TradeStatus.CLOSED_WIN.value, TradeStatus.CLOSED_loss.value]},
                    "exit_date": {"$gte": cutoff},
                }
            )
        )

        if not closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_win_r": 0.0,
                "avg_loss_r": 0.0,
                "expectancy": 0.0,
                "total_pnl": 0.0,
            }

        wins = [t for t in closed_trades if t["pnl"] > 0]
        losses = [t for t in closed_trades if t["pnl"] <= 0]

        win_rate = len(wins) / len(closed_trades) if closed_trades else 0
        avg_win_r = sum(t["r_multiple"] for t in wins) / len(wins) if wins else 0
        avg_loss_r = sum(t["r_multiple"] for t in losses) / len(losses) if losses else 0
        expectancy = (win_rate * avg_win_r) + ((1 - win_rate) * avg_loss_r)
        total_pnl = sum(t["pnl"] for t in closed_trades)

        return {
            "total_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "avg_win_r": avg_win_r,
            "avg_loss_r": avg_loss_r,
            "expectancy": expectancy,
            "total_pnl": total_pnl,
        }


class RegimeRepository(BaseRepository):
    """Repository for regime assessments.

    Manages market regime classifications - THE MOST CRITICAL component of the
    trading system. Regime awareness determines whether to trade at all, trade
    at reduced size, or stay in cash.

    CRITICAL INSIGHT: Most retail systems ignore regime. Trading pullbacks
    in Risk-Off environments destroys capital. This is the system's primary
    edge over naive momentum strategies.

    Collection: regime_assessments
    -------------------------------
    Indexes:
        - timestamp: Time-series queries
        - state: Filter by regime type

    Regime States
    -------------
    1. **RISK_ON** (70%+ confidence):
        - Nifty in uptrend, breadth strong, VIX low
        - Full position sizing (1.0x multiplier)
        - All setup types valid
        - Target: 3-7 positions

    2. **CHOPPY** (50-70% Risk-On, or mixed signals):
        - Sideways or uncertain market
        - Reduced position sizing (0.5x multiplier)
        - Only high-probability pullbacks
        - Target: 2-4 positions

    3. **RISK_OFF** (50%+ confidence):
        - Nifty downtrend, breadth weak, VIX spiking
        - NO NEW POSITIONS (0.0x multiplier)
        - Exit all existing positions
        - Target: 0 positions (cash)

    Assessment Frequency
    --------------------
    - Weekend: Full regime analysis (4 indicators, equal weights)
    - Daily: Quick check for regime shift
    - Intraday: Optional for VIX spikes

    Regime Indicators (Equal 25% Weights)
    --------------------------------------
    1. **Trend** (25%): Nifty vs 20/50/200 DMA, MA slopes
    2. **Breadth** (25%): % stocks above 200 DMA (Advance-Decline)
    3. **Volatility** (25%): India VIX level and trend
    4. **Leadership** (25%): Cyclicals vs Defensives spread

    Usage Pattern
    -------------
    Weekend:
        1. Run full regime assessment workflow
        2. Store assessment with create()
        3. Use regime to adjust position sizing and filters

    Daily:
        1. Check latest regime with get_latest()
        2. If Risk-Off: Skip new trades, consider exits
        3. If regime changed: Adjust positions immediately

    CRITICAL Decision Gate:
        regime = repo.get_latest()
        if regime["state"] == "risk_off":
            # STOP: Do not generate setups
            # Exit all positions
            return []

    Example
    -------
        from trade_analyzer.db.connection import get_database
        from trade_analyzer.db.models import RegimeAssessmentDoc, RegimeState
        from datetime import datetime

        db = get_database()
        repo = RegimeRepository(db)

        # Weekend: Create regime assessment
        assessment = RegimeAssessmentDoc(
            timestamp=datetime.utcnow(),
            state=RegimeState.RISK_ON,
            risk_on_prob=0.75,
            choppy_prob=0.20,
            risk_off_prob=0.05,
            confidence=0.85,
            indicators={
                "trend": {"score": 0.80, "signals": ["above_20dma", "above_50dma"]},
                "breadth": {"score": 0.72, "pct_above_200dma": 0.68},
                "volatility": {"score": 0.78, "vix": 12.5, "vix_trend": "falling"},
                "leadership": {"score": 0.70, "cyclical_spread": 0.15}
            }
        )
        assessment_id = repo.create(assessment)

        # Daily: Check regime before trading
        regime = repo.get_latest()
        if not regime:
            print("ERROR: No regime assessment found!")
            exit(1)

        print(f"Current regime: {regime['state']}")
        print(f"Confidence: {regime['confidence']*100:.0f}%")

        if regime["state"] == "risk_off":
            print("Risk-Off environment: NO NEW TRADES")
            print("Exiting all positions...")
            # Exit logic here
            exit(0)

        # Calculate position multiplier
        if regime["risk_on_prob"] > 0.70:
            multiplier = 1.0
        elif regime["risk_on_prob"] > 0.50:
            multiplier = 0.7
        elif regime["risk_off_prob"] > 0.50:
            multiplier = 0.0
        else:
            multiplier = 0.5

        print(f"Position size multiplier: {multiplier}x")

        # Analyze regime history for trends
        history = repo.get_history(limit=12)  # 12 weeks
        risk_off_weeks = [r for r in history if r["state"] == "risk_off"]
        print(f"Risk-Off weeks in last 12: {len(risk_off_weeks)}")

        # Study past Risk-Off periods
        risk_off_periods = repo.get_by_state(RegimeState.RISK_OFF, limit=20)
        avg_duration = calculate_avg_duration(risk_off_periods)
        print(f"Average Risk-Off duration: {avg_duration} weeks")
    """

    def __init__(self, db: Database):
        """Initialize regime repository.

        Args
        ----
        db : pymongo.database.Database
            MongoDB database instance.
        """
        super().__init__(db, "regime_assessments")

    def create(self, assessment: RegimeAssessmentDoc) -> str:
        """Create a new regime assessment.

        Args
        ----
        assessment : RegimeAssessmentDoc
            Regime assessment document to insert.

        Returns
        -------
        str
            MongoDB document ID (as string).

        Example
        -------
            assessment = RegimeAssessmentDoc(
                timestamp=datetime.utcnow(),
                state=RegimeState.CHOPPY,
                risk_on_prob=0.55,
                choppy_prob=0.35,
                risk_off_prob=0.10,
                confidence=0.70,
                indicators={...}
            )
            assessment_id = repo.create(assessment)
        """
        data = assessment.model_dump()
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_latest(self) -> Optional[dict]:
        """Get the most recent regime assessment.

        This is the MOST IMPORTANT query in the entire system. Every trading
        decision starts with checking the current regime.

        Returns
        -------
        dict or None
            Most recent regime assessment, or None if no assessments exist.

        Notes
        -----
        If this returns None, the system MUST NOT proceed with trading.
        Always have a fallback regime or manual override.

        Example
        -------
            regime = repo.get_latest()
            if not regime:
                print("FATAL: No regime assessment. Manual intervention required.")
                exit(1)

            if regime["state"] == "risk_off":
                print("Risk-Off: Cash position")
                return []
            elif regime["state"] == "choppy":
                print("Choppy: Reduced size, high-probability only")
            else:
                print("Risk-On: Full system active")
        """
        doc = self.collection.find_one(sort=[("timestamp", -1)])
        return self._from_doc(doc) if doc else None

    def get_history(self, limit: int = 52) -> list[dict]:
        """Get regime history.

        Used for analyzing regime transitions, system behavior in different
        environments, and backtest validation.

        Args
        ----
        limit : int, optional
            Number of recent assessments to return (default: 52 = 1 year of weeks).

        Returns
        -------
        list[dict]
            List of regime assessments, sorted by timestamp (descending).

        Example
        -------
            # Analyze regime distribution over last year
            history = repo.get_history(limit=52)
            risk_on = [r for r in history if r["state"] == "risk_on"]
            choppy = [r for r in history if r["state"] == "choppy"]
            risk_off = [r for r in history if r["state"] == "risk_off"]

            print(f"Regime distribution (52 weeks):")
            print(f"  Risk-On: {len(risk_on)} weeks ({len(risk_on)/52*100:.0f}%)")
            print(f"  Choppy: {len(choppy)} weeks ({len(choppy)/52*100:.0f}%)")
            print(f"  Risk-Off: {len(risk_off)} weeks ({len(risk_off)/52*100:.0f}%)")

            # Typical Indian market distribution:
            # Risk-On: 40-50%, Choppy: 30-40%, Risk-Off: 15-25%
        """
        docs = self.collection.find().sort("timestamp", -1).limit(limit)
        return [self._from_doc(doc) for doc in docs]

    def get_by_state(self, state: RegimeState, limit: int = 10) -> list[dict]:
        """Get assessments by regime state.

        Used for studying system performance in specific regimes.

        Args
        ----
        state : RegimeState
            Regime state to filter by (RISK_ON, CHOPPY, RISK_OFF).
        limit : int, optional
            Maximum number of assessments to return (default: 10).

        Returns
        -------
        list[dict]
            List of regime assessments with the specified state,
            sorted by timestamp (descending).

        Example
        -------
            # Study last 10 Risk-Off periods
            risk_off_periods = repo.get_by_state(RegimeState.RISK_OFF, limit=10)
            for period in risk_off_periods:
                print(f"{period['timestamp']} - Confidence: {period['confidence']}")
                vix = period['indicators']['volatility']['vix']
                print(f"  VIX: {vix}")

            # Analyze what triggered Risk-Off
            avg_vix = sum(p['indicators']['volatility']['vix']
                         for p in risk_off_periods) / len(risk_off_periods)
            print(f"Average VIX during Risk-Off: {avg_vix:.1f}")
        """
        docs = (
            self.collection.find({"state": state.value})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return [self._from_doc(doc) for doc in docs]
