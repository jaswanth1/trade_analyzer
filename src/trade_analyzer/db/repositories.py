"""Repository pattern for MongoDB data access."""

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
    """Base repository with common operations."""

    def __init__(self, db: Database, collection_name: str):
        self.collection = db[collection_name]

    def _to_doc(self, data: dict) -> dict:
        """Convert model dict to MongoDB document."""
        doc = data.copy()
        if "_id" not in doc:
            doc.pop("id", None)
        return doc

    def _from_doc(self, doc: dict) -> dict:
        """Convert MongoDB document to dict with string id."""
        if doc and "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        return doc


class StockRepository(BaseRepository):
    """Repository for stock master data."""

    def __init__(self, db: Database):
        super().__init__(db, "stocks")

    def upsert(self, stock: StockDoc) -> str:
        """Insert or update a stock by symbol."""
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
        """Get stock by symbol."""
        doc = self.collection.find_one({"symbol": symbol.upper()})
        return self._from_doc(doc) if doc else None

    def get_all_active(self) -> list[dict]:
        """Get all active stocks."""
        docs = self.collection.find({"is_active": True})
        return [self._from_doc(doc) for doc in docs]

    def get_by_sector(self, sector: str) -> list[dict]:
        """Get stocks by sector."""
        docs = self.collection.find({"sector": sector, "is_active": True})
        return [self._from_doc(doc) for doc in docs]

    def get_universe(
        self, min_market_cap: float = 1000, min_turnover: float = 5
    ) -> list[dict]:
        """Get filtered stock universe."""
        docs = self.collection.find(
            {
                "is_active": True,
                "market_cap": {"$gte": min_market_cap},
                "avg_daily_turnover": {"$gte": min_turnover},
            }
        )
        return [self._from_doc(doc) for doc in docs]


class TradeSetupRepository(BaseRepository):
    """Repository for trade setups."""

    def __init__(self, db: Database):
        super().__init__(db, "trade_setups")

    def create(self, setup: TradeSetupDoc) -> str:
        """Create a new trade setup."""
        data = setup.model_dump()
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_by_id(self, setup_id: str) -> Optional[dict]:
        """Get setup by ID."""
        doc = self.collection.find_one({"_id": ObjectId(setup_id)})
        return self._from_doc(doc) if doc else None

    def get_active_setups(self, week_start: Optional[datetime] = None) -> list[dict]:
        """Get all active setups, optionally for a specific week."""
        query = {"status": SetupStatus.ACTIVE.value}
        if week_start:
            query["week_start"] = week_start
        docs = self.collection.find(query).sort("composite_score", -1)
        return [self._from_doc(doc) for doc in docs]

    def get_by_week(self, week_start: datetime) -> list[dict]:
        """Get all setups for a specific week."""
        docs = self.collection.find({"week_start": week_start}).sort(
            "composite_score", -1
        )
        return [self._from_doc(doc) for doc in docs]

    def update_status(self, setup_id: str, status: SetupStatus) -> bool:
        """Update setup status."""
        result = self.collection.update_one(
            {"_id": ObjectId(setup_id)}, {"$set": {"status": status.value}}
        )
        return result.modified_count > 0

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get most recent setups."""
        docs = self.collection.find().sort("created_at", -1).limit(limit)
        return [self._from_doc(doc) for doc in docs]


class TradeRepository(BaseRepository):
    """Repository for executed trades."""

    def __init__(self, db: Database):
        super().__init__(db, "trades")

    def create(self, trade: TradeDoc) -> str:
        """Create a new trade."""
        data = trade.model_dump()
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_by_id(self, trade_id: str) -> Optional[dict]:
        """Get trade by ID."""
        doc = self.collection.find_one({"_id": ObjectId(trade_id)})
        return self._from_doc(doc) if doc else None

    def get_active_trades(self) -> list[dict]:
        """Get all active (open) trades."""
        docs = self.collection.find({"status": TradeStatus.ACTIVE.value})
        return [self._from_doc(doc) for doc in docs]

    def get_by_status(self, status: TradeStatus) -> list[dict]:
        """Get trades by status."""
        docs = self.collection.find({"status": status.value})
        return [self._from_doc(doc) for doc in docs]

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_date: datetime,
        exit_reason: str,
    ) -> bool:
        """Close a trade with exit details."""
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
        """Calculate performance statistics."""
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
    """Repository for regime assessments."""

    def __init__(self, db: Database):
        super().__init__(db, "regime_assessments")

    def create(self, assessment: RegimeAssessmentDoc) -> str:
        """Create a new regime assessment."""
        data = assessment.model_dump()
        result = self.collection.insert_one(data)
        return str(result.inserted_id)

    def get_latest(self) -> Optional[dict]:
        """Get the most recent regime assessment."""
        doc = self.collection.find_one(sort=[("timestamp", -1)])
        return self._from_doc(doc) if doc else None

    def get_history(self, limit: int = 52) -> list[dict]:
        """Get regime history."""
        docs = self.collection.find().sort("timestamp", -1).limit(limit)
        return [self._from_doc(doc) for doc in docs]

    def get_by_state(self, state: RegimeState, limit: int = 10) -> list[dict]:
        """Get assessments by regime state."""
        docs = (
            self.collection.find({"state": state.value})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return [self._from_doc(doc) for doc in docs]
