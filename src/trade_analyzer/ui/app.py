"""
Main Streamlit application for Trade Analyzer.

This is the primary UI dashboard for the institutional-grade weekly trading system.
It provides a comprehensive interface for managing the 8-phase trade analysis pipeline.

Dashboard Structure:
    - Sidebar: Navigation and DB connection status
    - Pages:
      * Dashboard: Main control center with all phase metrics and controls
      * Regime: Market regime analysis and probabilities
      * Setups: Trade setup filtering and details
      * Trades: Active/closed trades and performance metrics
      * Settings: System configuration and risk parameters

Main Dashboard Features:

    1. Phase 1 - Universe Setup:
       - NSE EQ count, MTF count, quality tiers
       - Fundamental qualification stats
       - Buttons: "Setup Universe", "Refresh Fund. (Monthly)"

    2. Phase 2 - Momentum Filter:
       - Momentum qualified count, pass rate
       - Buttons: "Run Momentum Filter", "Full Weekend Run"

    3. Phase 3 - Consistency Filter:
       - Consistency qualified count, market regime
       - Buttons: "Run Consistency Filter", "Full Pipeline (1-3)"

    4. Phase 4A - Volume & Liquidity:
       - Liquidity qualified count, pass rate
       - Buttons: "Run Volume Filter", "Phase 4 Pipeline"

    5. Phase 4B - Setup Detection:
       - Trade setups count, qualified rate
       - Buttons: "Run Setup Detection", "Full Analysis (1-4)"

    6. Fundamental Data Cache:
       - Monthly refresh of fundamental data
       - Applied automatically in Phase 1
       - Button: "Refresh Data (Monthly)"

    7. Phase 5-6 - Risk & Portfolio:
       - Risk qualified, final positions, risk %, cash %
       - Buttons: "Run Risk Geometry", "Run Portfolio"

    8. Phase 7 - Execution Display:
       - Pre-market enter/skip counts, system health
       - Buttons: "Pre-Market", "Position Status", "Friday Close"

    9. Phase 8 - Weekly Recommendations:
       - Recommendations count, allocated %, status, regime
       - Buttons: "Generate Recommendations", "FULL WEEKLY PIPELINE"

    10. Stock Universe Tabs:
        - Trade Setups: All qualified trade opportunities
        - Liquidity Qualified: Stocks passing liquidity filters
        - Consistency Qualified: Stocks with statistical consistency
        - Momentum Qualified: Stocks with strong momentum
        - High Quality: Stocks with quality score >= 60
        - All Stocks: Complete universe with pagination

Workflow Execution:
    - All buttons trigger Temporal workflows via asyncio.run()
    - Workflows execute synchronously with progress spinners
    - Success/error messages displayed after completion
    - Dashboard auto-refreshes on workflow completion

Database Integration:
    - Auto-connects to MongoDB on startup using config
    - Displays real-time stats from database collections
    - Supports pagination for large datasets (50 items/page)
    - Search functionality for symbol filtering

Architecture:
    - Single-file Streamlit app (no multi-page structure)
    - Session state for pagination and search
    - Direct MongoDB queries for real-time data
    - Async workflow execution via helper functions

Usage:
    $ streamlit run src/trade_analyzer/ui/app.py
    $ make ui  # Convenient Make target

Dependencies:
    - streamlit: UI framework
    - pandas: Data display
    - MongoDB: Data storage
    - Temporal: Workflow execution
"""

from datetime import datetime

import pandas as pd
import streamlit as st

# Page config must be first Streamlit command
st.set_page_config(
    page_title="Trade Analyzer",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_db_connection():
    """Initialize database connection using configured credentials."""
    if "db" not in st.session_state:
        st.session_state.db = None
        st.session_state.db_connected = False

    # Auto-connect using configured credentials
    if not st.session_state.db_connected:
        try:
            from trade_analyzer.db import get_database

            st.session_state.db = get_database()
            st.session_state.db_connected = True
        except Exception as e:
            st.session_state.db_error = str(e)


def render_sidebar():
    """
    Render the sidebar navigation.

    Displays:
        - App title
        - Database connection status (green=connected, red=disconnected)
        - Navigation radio buttons for page selection
        - Error message if DB connection failed

    Returns:
        str: Selected page name ("Dashboard", "Regime", "Setups", "Trades", "Settings")
    """
    with st.sidebar:
        st.title("Trade Analyzer")
        st.markdown("---")

        # Connection status
        if st.session_state.get("db_connected"):
            st.success("DB Connected")
        else:
            st.error("DB Not Connected")
            if st.session_state.get("db_error"):
                st.caption(f"Error: {st.session_state.db_error}")

        st.markdown("---")

        # Navigation
        page = st.radio(
            "Navigation",
            ["Dashboard", "Regime", "Setups", "Trades", "Settings"],
            label_visibility="collapsed",
        )

        return page


def render_dashboard():
    """
    Render the main dashboard page with all functionality.

    This is the primary interface showing:
        - Summary metrics for all 8 pipeline phases
        - Control buttons to trigger workflows
        - Last updated timestamps for each phase
        - Tabbed stock universe views with pagination

    Layout:
        1. Phase 1 metrics + Universe Setup button
        2. Phase 2 metrics + Momentum Filter buttons
        3. Phase 3 metrics + Consistency Filter buttons
        4. Phase 4A metrics + Volume Filter buttons
        5. Phase 4B metrics + Setup Detection buttons
        6. Fundamental cache stats + Monthly Refresh button
        7. Phase 5-6 metrics + Risk/Portfolio buttons
        8. Phase 7 metrics + Execution workflow buttons
        9. Phase 8 metrics + Recommendation buttons
        10. Stock universe tabs (setups, liquidity, consistency, momentum, quality, all)

    Database Collections Used:
        - stocks: Universe data
        - momentum_scores: Phase 2 results
        - consistency_scores: Phase 3 results
        - liquidity_scores: Phase 4A results
        - trade_setups: Phase 4B results
        - fundamental_scores: Fundamental cache
        - institutional_holdings: Holdings cache
        - position_sizes: Phase 5 results
        - portfolio_allocations: Phase 6 results
        - monday_premarket: Phase 7 pre-market analysis
        - friday_summaries: Phase 7 weekly summary
        - weekly_recommendations: Phase 8 final output
    """
    st.header("Trade Analyzer Dashboard")

    if not st.session_state.get("db_connected"):
        st.info("Connect to MongoDB to view dashboard data.")
        return

    db = st.session_state.db

    # Get stats from database
    total_nse_eq = db.stocks.count_documents({"is_active": True})
    mtf_count = db.stocks.count_documents({"is_active": True, "is_mtf": True})
    tier_a = db.stocks.count_documents({"is_active": True, "liquidity_tier": "A"})
    tier_b = db.stocks.count_documents({"is_active": True, "liquidity_tier": "B"})
    tier_c = db.stocks.count_documents({"is_active": True, "liquidity_tier": "C"})
    high_quality = db.stocks.count_documents({"is_active": True, "quality_score": {"$gte": 60}})

    # Momentum stats
    momentum_qualified = db.momentum_scores.count_documents({"qualifies": True})
    momentum_total = db.momentum_scores.count_documents({})

    # Consistency stats (Phase 3)
    consistency_qualified = db.consistency_scores.count_documents({"qualifies": True})
    consistency_total = db.consistency_scores.count_documents({})

    # Phase 4A: Liquidity stats
    liquidity_qualified = db.liquidity_scores.count_documents({"liq_qualifies": True})
    liquidity_total = db.liquidity_scores.count_documents({})

    # Phase 4B: Trade setups stats
    setups_qualified = db.trade_setups.count_documents({"qualifies": True, "status": "active"})
    setups_total = db.trade_setups.count_documents({"status": "active"})

    # Get last updated
    latest = db.stocks.find_one(
        {"is_active": True},
        {"last_updated": 1},
        sort=[("last_updated", -1)],
    )
    last_updated = latest.get("last_updated") if latest else None

    # Momentum last updated
    momentum_latest = db.momentum_scores.find_one(
        {},
        {"calculated_at": 1},
        sort=[("calculated_at", -1)],
    )
    momentum_updated = momentum_latest.get("calculated_at") if momentum_latest else None

    # Consistency last updated and regime
    consistency_latest = db.consistency_scores.find_one(
        {},
        {"calculated_at": 1, "market_regime": 1},
        sort=[("calculated_at", -1)],
    )
    consistency_updated = consistency_latest.get("calculated_at") if consistency_latest else None
    market_regime = consistency_latest.get("market_regime", "N/A") if consistency_latest else "N/A"

    # Phase 4 last updated
    liquidity_latest = db.liquidity_scores.find_one(
        {},
        {"calculated_at": 1},
        sort=[("calculated_at", -1)],
    )
    liquidity_updated = liquidity_latest.get("calculated_at") if liquidity_latest else None

    setups_latest = db.trade_setups.find_one(
        {},
        {"detected_at": 1, "market_regime": 1},
        sort=[("detected_at", -1)],
    )
    setups_updated = setups_latest.get("detected_at") if setups_latest else None
    setup_regime = setups_latest.get("market_regime", market_regime) if setups_latest else market_regime

    # Get fundamental qualification stats (Phase 1 now includes fundamental filter)
    fundamentally_qualified = db.stocks.count_documents({
        "is_active": True,
        "fundamentally_qualified": True,
    })

    # Top row: Stats and buttons
    col_stats, col_action = st.columns([4, 1])

    with col_stats:
        stat_cols = st.columns(7)
        with stat_cols[0]:
            st.metric("Total NSE EQ", total_nse_eq)
        with stat_cols[1]:
            st.metric("MTF Eligible", mtf_count)
        with stat_cols[2]:
            st.metric("High Quality", high_quality)
        with stat_cols[3]:
            st.metric("Fund. Qualified", fundamentally_qualified)
        with stat_cols[4]:
            st.metric("Tier A", tier_a)
        with stat_cols[5]:
            st.metric("Tier B", tier_b)
        with stat_cols[6]:
            st.metric("Tier C", tier_c)

    with col_action:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Setup Universe", type="primary"):
                _run_universe_setup()
        with col_btn2:
            if st.button("Refresh Fund. (Monthly)", type="secondary"):
                _run_fundamental_data_refresh()

    # Last updated info
    if last_updated:
        st.caption(f"Universe updated: {last_updated}")
    else:
        st.caption("Never updated - Click 'Setup Universe' to fetch data")

    st.markdown("---")

    # Phase 2: Momentum Filter Section
    st.subheader("Momentum Analysis (Phase 2)")

    mom_col1, mom_col2, mom_col3, mom_col4 = st.columns([1, 1, 1, 2])

    with mom_col1:
        st.metric("Momentum Qualified", momentum_qualified)
    with mom_col2:
        st.metric("Total Analyzed", momentum_total)
    with mom_col3:
        if momentum_total > 0:
            pass_rate = (momentum_qualified / momentum_total) * 100
            st.metric("Pass Rate", f"{pass_rate:.1f}%")
        else:
            st.metric("Pass Rate", "N/A")
    with mom_col4:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Run Momentum Filter", type="secondary"):
                _run_momentum_filter()
        with col_btn2:
            if st.button("Full Weekend Run", type="primary"):
                _run_universe_and_momentum()

    if momentum_updated:
        st.caption(f"Momentum updated: {momentum_updated}")
    else:
        st.caption("No momentum analysis yet - Click 'Run Momentum Filter'")

    st.markdown("---")

    # Phase 3: Consistency Filter Section
    st.subheader("Consistency Analysis (Phase 3)")

    cons_col1, cons_col2, cons_col3, cons_col4, cons_col5 = st.columns([1, 1, 1, 1, 2])

    with cons_col1:
        st.metric("Consistency Qualified", consistency_qualified)
    with cons_col2:
        st.metric("Total Analyzed", consistency_total)
    with cons_col3:
        if consistency_total > 0:
            cons_pass_rate = (consistency_qualified / consistency_total) * 100
            st.metric("Pass Rate", f"{cons_pass_rate:.1f}%")
        else:
            st.metric("Pass Rate", "N/A")
    with cons_col4:
        # Market regime indicator with color
        if market_regime == "BULL":
            st.metric("Market Regime", market_regime)
        elif market_regime == "BEAR":
            st.metric("Market Regime", market_regime)
        else:
            st.metric("Market Regime", market_regime)
    with cons_col5:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Run Consistency Filter", type="secondary"):
                _run_consistency_filter()
        with col_btn2:
            if st.button("Full Pipeline (1-3)", type="primary"):
                _run_full_pipeline()

    if consistency_updated:
        st.caption(f"Consistency updated: {consistency_updated}")
    else:
        st.caption("No consistency analysis yet - Click 'Run Consistency Filter'")

    st.markdown("---")

    # Phase 4A: Volume & Liquidity Filter Section
    st.subheader("Volume & Liquidity (Phase 4A)")

    liq_col1, liq_col2, liq_col3, liq_col4 = st.columns([1, 1, 1, 2])

    with liq_col1:
        st.metric("Liquidity Qualified", liquidity_qualified)
    with liq_col2:
        st.metric("Total Analyzed", liquidity_total)
    with liq_col3:
        if liquidity_total > 0:
            liq_pass_rate = (liquidity_qualified / liquidity_total) * 100
            st.metric("Pass Rate", f"{liq_pass_rate:.1f}%")
        else:
            st.metric("Pass Rate", "N/A")
    with liq_col4:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Run Volume Filter", type="secondary"):
                _run_volume_filter()
        with col_btn2:
            if st.button("Phase 4 Pipeline", type="primary"):
                _run_phase4_pipeline()

    if liquidity_updated:
        st.caption(f"Liquidity updated: {liquidity_updated}")
    else:
        st.caption("No liquidity analysis yet - Click 'Run Volume Filter'")

    st.markdown("---")

    # Phase 4B: Setup Detection Section
    st.subheader("Trade Setups (Phase 4B)")

    setup_col1, setup_col2, setup_col3, setup_col4, setup_col5 = st.columns([1, 1, 1, 1, 2])

    with setup_col1:
        st.metric("Trade Setups", setups_qualified)
    with setup_col2:
        st.metric("Setups Found", setups_total)
    with setup_col3:
        if setups_total > 0:
            setup_pass_rate = (setups_qualified / setups_total) * 100
            st.metric("Qualified Rate", f"{setup_pass_rate:.1f}%")
        else:
            st.metric("Qualified Rate", "N/A")
    with setup_col4:
        st.metric("Regime", setup_regime)
    with setup_col5:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Run Setup Detection", type="secondary"):
                _run_setup_detection()
        with col_btn2:
            if st.button("Full Analysis (1-4)", type="primary"):
                _run_full_analysis()

    if setups_updated:
        st.caption(f"Setups updated: {setups_updated}")
    else:
        st.caption("No setups detected yet - Click 'Run Setup Detection'")

    st.markdown("---")

    # Fundamental Data Cache Section (Monthly refresh, applied in Phase 1)
    st.subheader("Fundamental Data Cache (Monthly Refresh)")
    st.caption("Fundamentals are now applied in Phase 1. Run monthly to refresh cached data.")

    # Get fundamental cache stats
    fund_qualified = db.fundamental_scores.count_documents({"qualifies": True})
    fund_total = db.fundamental_scores.count_documents({})
    inst_qualified = db.institutional_holdings.count_documents({"qualifies": True})

    fund_latest = db.fundamental_scores.find_one({}, {"calculated_at": 1}, sort=[("calculated_at", -1)])
    fund_updated = fund_latest.get("calculated_at") if fund_latest else None

    fund_col1, fund_col2, fund_col3, fund_col4, fund_col5 = st.columns([1, 1, 1, 1, 2])

    with fund_col1:
        st.metric("Fundamental Scores", fund_qualified)
    with fund_col2:
        st.metric("Institutional Data", inst_qualified)
    with fund_col3:
        st.metric("Total Cached", fund_total)
    with fund_col4:
        if fund_total > 0:
            fund_pass_rate = (fund_qualified / fund_total) * 100
            st.metric("Qualified %", f"{fund_pass_rate:.1f}%")
        else:
            st.metric("Qualified %", "N/A")
    with fund_col5:
        if st.button("Refresh Data (Monthly)", type="secondary", key="fund_btn"):
            _run_fundamental_data_refresh()

    if fund_updated:
        st.caption(f"Fundamental data refreshed: {fund_updated}")
    else:
        st.caption("No fundamental data cached - Run 'Refresh Data (Monthly)'")

    st.markdown("---")

    # Phase 5-6: Risk & Portfolio Section (was Phase 6-7)
    st.subheader("Risk & Portfolio (Phase 5-6)")

    # Get Phase 6-7 stats
    risk_qualified = db.position_sizes.count_documents({"risk_qualifies": True})
    portfolio_doc = db.portfolio_allocations.find_one(sort=[("allocation_date", -1)])
    portfolio_positions = portfolio_doc.get("position_count", 0) if portfolio_doc else 0
    portfolio_risk = portfolio_doc.get("total_risk_pct", 0) if portfolio_doc else 0
    portfolio_cash = portfolio_doc.get("cash_reserve_pct", 0) if portfolio_doc else 0

    portfolio_updated = portfolio_doc.get("allocation_date") if portfolio_doc else None

    risk_col1, risk_col2, risk_col3, risk_col4, risk_col5 = st.columns([1, 1, 1, 1, 2])

    with risk_col1:
        st.metric("Risk Qualified", risk_qualified)
    with risk_col2:
        st.metric("Final Positions", portfolio_positions)
    with risk_col3:
        st.metric("Total Risk %", f"{portfolio_risk:.1f}%")
    with risk_col4:
        st.metric("Cash Reserve %", f"{portfolio_cash:.1f}%")
    with risk_col5:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Run Risk Geometry", type="secondary", key="risk_btn"):
                _run_risk_geometry()
        with col_btn2:
            if st.button("Run Portfolio", type="primary", key="portfolio_btn"):
                _run_portfolio_construction()

    if portfolio_updated:
        st.caption(f"Portfolio updated: {portfolio_updated}")
    else:
        st.caption("No portfolio constructed yet - Run Phase 5-7 workflows")

    st.markdown("---")

    # Phase 7: Execution Display Section (was Phase 8)
    st.subheader("Execution Display (Phase 7)")

    # Get Phase 8 stats
    premarket_doc = db.monday_premarket.find_one(sort=[("analysis_date", -1)])
    friday_doc = db.friday_summaries.find_one(sort=[("week_start", -1)])

    exec_col1, exec_col2, exec_col3, exec_col4 = st.columns([1, 1, 1, 2])

    with exec_col1:
        if premarket_doc:
            st.metric("Enter", premarket_doc.get("enter_count", 0))
        else:
            st.metric("Enter", 0)
    with exec_col2:
        if premarket_doc:
            st.metric("Skip", premarket_doc.get("skip_count", 0))
        else:
            st.metric("Skip", 0)
    with exec_col3:
        if friday_doc:
            st.metric("System Health", f"{friday_doc.get('system_health', {}).get('health_score', 50)}/100")
        else:
            st.metric("System Health", "N/A")
    with exec_col4:
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("Pre-Market", type="secondary", key="premarket_btn"):
                _run_premarket_analysis()
        with col_btn2:
            if st.button("Position Status", type="secondary", key="position_btn"):
                _run_position_status()
        with col_btn3:
            if st.button("Friday Close", type="secondary", key="friday_btn"):
                _run_friday_close()

    st.markdown("---")

    # Phase 8: Weekly Recommendations Section (was Phase 9)
    st.subheader("Weekly Recommendations (Phase 8)")

    # Get Phase 9 stats
    rec_doc = db.weekly_recommendations.find_one(
        {"status": {"$ne": "expired"}},
        sort=[("week_start", -1)]
    )

    rec_col1, rec_col2, rec_col3, rec_col4, rec_col5 = st.columns([1, 1, 1, 1, 2])

    with rec_col1:
        if rec_doc:
            st.metric("Recommendations", rec_doc.get("total_setups", 0))
        else:
            st.metric("Recommendations", 0)
    with rec_col2:
        if rec_doc:
            st.metric("Allocated %", f"{rec_doc.get('allocated_pct', 0):.1f}%")
        else:
            st.metric("Allocated %", "0%")
    with rec_col3:
        if rec_doc:
            st.metric("Status", rec_doc.get("status", "N/A").upper())
        else:
            st.metric("Status", "N/A")
    with rec_col4:
        if rec_doc:
            st.metric("Regime", rec_doc.get("market_regime", "N/A").upper())
        else:
            st.metric("Regime", "N/A")
    with rec_col5:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Generate Recommendations", type="secondary", key="rec_btn"):
                _run_weekly_recommendation()
        with col_btn2:
            if st.button("FULL WEEKLY PIPELINE", type="primary", key="weekly_btn"):
                _run_complete_weekly_pipeline()

    if rec_doc:
        st.caption(f"Week of {rec_doc.get('week_start', 'N/A')}")
    else:
        st.caption("No recommendations yet - Run weekly pipeline")

    st.markdown("---")

    # Stock Universe section
    st.subheader("Stock Universe")

    # Tabs for different views
    tab_setups, tab_liquidity, tab_consistency, tab_momentum, tab_quality, tab_all = st.tabs([
        f"Trade Setups ({setups_qualified})",
        f"Liquidity Qualified ({liquidity_qualified})",
        f"Consistency Qualified ({consistency_qualified})",
        f"Momentum Qualified ({momentum_qualified})",
        "High Quality (Score >= 60)",
        "All Stocks",
    ])

    with tab_setups:
        render_trade_setups(db)

    with tab_liquidity:
        render_liquidity_stocks(db)

    with tab_consistency:
        render_consistency_stocks(db)

    with tab_momentum:
        render_momentum_stocks(db)

    with tab_quality:
        render_paginated_stock_list(
            db=db,
            base_query={"is_active": True, "quality_score": {"$gte": 60}},
            total_count=high_quality,
            page_key="quality_page",
            search_key="quality_search",
            title="High Quality",
            show_quality=True,
        )

    with tab_all:
        render_paginated_stock_list(
            db=db,
            base_query={"is_active": True},
            total_count=total_nse_eq,
            page_key="nse_page",
            search_key="nse_search",
            title="NSE EQ",
            show_quality=True,
        )


def render_regime():
    """Render the regime analysis page."""
    st.header("Market Regime")

    if not st.session_state.get("db_connected"):
        st.info("Connect to MongoDB to view regime data.")
        return

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Current Regime Assessment")
        st.info("No regime assessment available. Run regime analysis.")

    with col2:
        st.subheader("Regime Probabilities")
        # Placeholder for gauge charts
        st.metric("Risk-On", "0%")
        st.metric("Choppy", "0%")
        st.metric("Risk-Off", "0%")


def render_setups():
    """Render the trade setups page."""
    st.header("Trade Setups")

    if not st.session_state.get("db_connected"):
        st.info("Connect to MongoDB to view setups.")
        return

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        _setup_type = st.selectbox("Setup Type", ["All", "Pullback", "Breakout", "Retest"])
    with col2:
        _status = st.selectbox("Status", ["All", "Active", "Triggered", "Expired"])
    with col3:
        _week = st.date_input("Week Starting", datetime.now())

    st.markdown("---")

    st.info(f"Use Dashboard 'Trade Setups' tab to view detected setups. Filters: {_setup_type}, {_status}, {_week}")


def render_trades():
    """Render the trades page."""
    st.header("Trades")

    if not st.session_state.get("db_connected"):
        st.info("Connect to MongoDB to view trades.")
        return

    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["Active", "Closed", "Performance"])

    with tab1:
        st.subheader("Active Trades")
        st.info("No active trades.")

    with tab2:
        st.subheader("Trade History")
        st.info("No closed trades.")

    with tab3:
        st.subheader("Performance Metrics")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Trades", "0")
        with col2:
            st.metric("Win Rate", "0%")
        with col3:
            st.metric("Expectancy", "0R")
        with col4:
            st.metric("Total P&L", "Rs.0")


def render_paginated_stock_list(
    db,
    base_query: dict,
    total_count: int,
    page_key: str,
    search_key: str,
    title: str,
    show_quality: bool = False,
):
    """
    Render a paginated stock list with search.

    Generic function to display any stock list with pagination and search.
    Used for displaying universe stocks, high-quality stocks, etc.

    Args:
        db: MongoDB database connection
        base_query: Base MongoDB query dict (e.g., {"is_active": True})
        total_count: Total number of documents matching base query
        page_key: Session state key for pagination (must be unique per list)
        search_key: Session state key for search box (must be unique per list)
        title: Display title for the list
        show_quality: If True, display quality-related columns (score, tier, indices)

    Features:
        - 50 items per page
        - Symbol search with case-insensitive regex
        - Prev/Next pagination buttons
        - Shows "X-Y of Z" counter
        - Resets to page 1 on new search
        - Sorts by quality_score (desc) if show_quality=True

    UI Components:
        - Search text input
        - Dataframe with configurable columns
        - Pagination controls (Prev, Page X of Y, Next)
    """
    PAGE_SIZE = 50

    # Make a copy of the query to avoid modifying the original
    query = base_query.copy()

    # Initialize session state for pagination
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    # Search box
    search = st.text_input(
        "Search Symbol",
        placeholder="e.g., RELIANCE",
        key=search_key,
    )

    # Apply search filter
    if search:
        query["symbol"] = {"$regex": search.upper(), "$options": "i"}
        # Reset to first page on search
        if st.session_state.get(f"{search_key}_prev") != search:
            st.session_state[page_key] = 0
        st.session_state[f"{search_key}_prev"] = search

    # Get filtered count
    filtered_count = db.stocks.count_documents(query)
    total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = st.session_state[page_key]

    # Ensure current page is valid
    if current_page >= total_pages:
        current_page = total_pages - 1
        st.session_state[page_key] = current_page

    # Fetch stocks for current page (sort by quality_score if available)
    skip = current_page * PAGE_SIZE
    sort_field = [("quality_score", -1), ("symbol", 1)] if show_quality else [("symbol", 1)]
    stocks = list(
        db.stocks.find(query, {"_id": 0})
        .sort(sort_field)
        .skip(skip)
        .limit(PAGE_SIZE)
    )

    # Display dataframe
    if stocks:
        df = pd.DataFrame(stocks)
        if show_quality:
            display_cols = [
                "symbol",
                "name",
                "quality_score",
                "liquidity_tier",
                "is_mtf",
                "in_nifty_50",
                "in_nifty_100",
                "in_nifty_500",
            ]
        else:
            display_cols = [
                "symbol",
                "name",
                "instrument_key",
                "lot_size",
                "tick_size",
                "security_type",
            ]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[display_cols],
            width="stretch",
            hide_index=True,
            height=400,
        )

        # Pagination controls
        col_info, col_prev, col_page, col_next = st.columns([2, 1, 2, 1])

        with col_info:
            start_idx = skip + 1
            end_idx = min(skip + PAGE_SIZE, filtered_count)
            st.caption(f"Showing {start_idx}-{end_idx} of {filtered_count}")

        with col_prev:
            if st.button("Prev", key=f"{page_key}_prev", disabled=current_page == 0):
                st.session_state[page_key] = current_page - 1
                st.rerun()

        with col_page:
            st.caption(f"Page {current_page + 1} of {total_pages}")

        with col_next:
            if st.button(
                "Next", key=f"{page_key}_next", disabled=current_page >= total_pages - 1
            ):
                st.session_state[page_key] = current_page + 1
                st.rerun()
    else:
        st.info("No stocks found matching your criteria.")


def render_consistency_stocks(db):
    """Render the consistency-qualified stocks list."""
    PAGE_SIZE = 50

    # Initialize session state for pagination
    if "consistency_page" not in st.session_state:
        st.session_state.consistency_page = 0

    # Search box
    search = st.text_input(
        "Search Symbol",
        placeholder="e.g., RELIANCE",
        key="consistency_search",
    )

    # Build query
    query = {"qualifies": True}
    if search:
        query["symbol"] = {"$regex": search.upper(), "$options": "i"}
        if st.session_state.get("consistency_search_prev") != search:
            st.session_state.consistency_page = 0
        st.session_state.consistency_search_prev = search

    # Get filtered count
    filtered_count = db.consistency_scores.count_documents(query)
    total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = st.session_state.consistency_page

    # Ensure current page is valid
    if current_page >= total_pages:
        current_page = total_pages - 1
        st.session_state.consistency_page = current_page

    # Fetch stocks for current page
    skip = current_page * PAGE_SIZE
    stocks = list(
        db.consistency_scores.find(query, {"_id": 0})
        .sort("final_score", -1)
        .skip(skip)
        .limit(PAGE_SIZE)
    )

    # Display dataframe
    if stocks:
        df = pd.DataFrame(stocks)
        display_cols = [
            "symbol",
            "final_score",
            "consistency_score",
            "regime_score",
            "pos_pct_52w",
            "plus3_pct_52w",
            "std_dev_52w",
            "sharpe_52w",
            "filters_passed",
            "passes_pos_pct",
            "passes_plus3_pct",
            "passes_volatility",
            "passes_sharpe",
            "passes_consistency",
            "passes_regime",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        # Style boolean columns
        def style_bool(val):
            if isinstance(val, bool):
                return "background-color: #90EE90" if val else "background-color: #FFB6C1"
            return ""

        styled_df = df[display_cols].style.map(style_bool)
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # Pagination controls
        col_info, col_prev, col_page, col_next = st.columns([2, 1, 2, 1])

        with col_info:
            start_idx = skip + 1
            end_idx = min(skip + PAGE_SIZE, filtered_count)
            st.caption(f"Showing {start_idx}-{end_idx} of {filtered_count}")

        with col_prev:
            if st.button("Prev", key="consistency_prev", disabled=current_page == 0):
                st.session_state.consistency_page = current_page - 1
                st.rerun()

        with col_page:
            st.caption(f"Page {current_page + 1} of {total_pages}")

        with col_next:
            if st.button(
                "Next", key="consistency_next", disabled=current_page >= total_pages - 1
            ):
                st.session_state.consistency_page = current_page + 1
                st.rerun()
    else:
        st.info("No consistency-qualified stocks found. Run 'Consistency Filter' to analyze stocks.")


def render_momentum_stocks(db):
    """Render the momentum-qualified stocks list."""
    PAGE_SIZE = 50

    # Initialize session state for pagination
    if "momentum_page" not in st.session_state:
        st.session_state.momentum_page = 0

    # Search box
    search = st.text_input(
        "Search Symbol",
        placeholder="e.g., RELIANCE",
        key="momentum_search",
    )

    # Build query
    query = {"qualifies": True}
    if search:
        query["symbol"] = {"$regex": search.upper(), "$options": "i"}
        if st.session_state.get("momentum_search_prev") != search:
            st.session_state.momentum_page = 0
        st.session_state.momentum_search_prev = search

    # Get filtered count
    filtered_count = db.momentum_scores.count_documents(query)
    total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = st.session_state.momentum_page

    # Ensure current page is valid
    if current_page >= total_pages:
        current_page = total_pages - 1
        st.session_state.momentum_page = current_page

    # Fetch stocks for current page
    skip = current_page * PAGE_SIZE
    stocks = list(
        db.momentum_scores.find(query, {"_id": 0})
        .sort("momentum_score", -1)
        .skip(skip)
        .limit(PAGE_SIZE)
    )

    # Display dataframe
    if stocks:
        df = pd.DataFrame(stocks)
        display_cols = [
            "symbol",
            "momentum_score",
            "filters_passed",
            "proximity_52w",
            "ma_alignment_score",
            "rs_3m",
            "volatility_ratio",
            "filter_2a_pass",
            "filter_2b_pass",
            "filter_2c_pass",
            "filter_2d_pass",
            "filter_2e_pass",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        # Style boolean columns
        def style_bool(val):
            if isinstance(val, bool):
                return "background-color: #90EE90" if val else "background-color: #FFB6C1"
            return ""

        styled_df = df[display_cols].style.map(style_bool)
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # Pagination controls
        col_info, col_prev, col_page, col_next = st.columns([2, 1, 2, 1])

        with col_info:
            start_idx = skip + 1
            end_idx = min(skip + PAGE_SIZE, filtered_count)
            st.caption(f"Showing {start_idx}-{end_idx} of {filtered_count}")

        with col_prev:
            if st.button("Prev", key="momentum_prev", disabled=current_page == 0):
                st.session_state.momentum_page = current_page - 1
                st.rerun()

        with col_page:
            st.caption(f"Page {current_page + 1} of {total_pages}")

        with col_next:
            if st.button(
                "Next", key="momentum_next", disabled=current_page >= total_pages - 1
            ):
                st.session_state.momentum_page = current_page + 1
                st.rerun()
    else:
        st.info("No momentum-qualified stocks found. Run 'Momentum Filter' to analyze stocks.")


def render_liquidity_stocks(db):
    """Render the liquidity-qualified stocks list."""
    PAGE_SIZE = 50

    # Initialize session state for pagination
    if "liquidity_page" not in st.session_state:
        st.session_state.liquidity_page = 0

    # Search box
    search = st.text_input(
        "Search Symbol",
        placeholder="e.g., RELIANCE",
        key="liquidity_search",
    )

    # Build query
    query = {"liq_qualifies": True}
    if search:
        query["symbol"] = {"$regex": search.upper(), "$options": "i"}
        if st.session_state.get("liquidity_search_prev") != search:
            st.session_state.liquidity_page = 0
        st.session_state.liquidity_search_prev = search

    # Get filtered count
    filtered_count = db.liquidity_scores.count_documents(query)
    total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = st.session_state.liquidity_page

    # Ensure current page is valid
    if current_page >= total_pages:
        current_page = total_pages - 1
        st.session_state.liquidity_page = current_page

    # Fetch stocks for current page
    skip = current_page * PAGE_SIZE
    stocks = list(
        db.liquidity_scores.find(query, {"_id": 0})
        .sort("liquidity_score", -1)
        .skip(skip)
        .limit(PAGE_SIZE)
    )

    # Display dataframe
    if stocks:
        df = pd.DataFrame(stocks)
        display_cols = [
            "symbol",
            "liquidity_score",
            "turnover_20d_cr",
            "turnover_60d_cr",
            "vol_ratio_5d",
            "vol_stability",
            "circuit_hits_30d",
            "avg_gap_pct",
            "passes_liq_score",
            "passes_turnover",
            "passes_circuit",
            "passes_gap",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        # Style boolean columns
        def style_bool(val):
            if isinstance(val, bool):
                return "background-color: #90EE90" if val else "background-color: #FFB6C1"
            return ""

        styled_df = df[display_cols].style.map(style_bool)
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # Pagination controls
        col_info, col_prev, col_page, col_next = st.columns([2, 1, 2, 1])

        with col_info:
            start_idx = skip + 1
            end_idx = min(skip + PAGE_SIZE, filtered_count)
            st.caption(f"Showing {start_idx}-{end_idx} of {filtered_count}")

        with col_prev:
            if st.button("Prev", key="liquidity_prev", disabled=current_page == 0):
                st.session_state.liquidity_page = current_page - 1
                st.rerun()

        with col_page:
            st.caption(f"Page {current_page + 1} of {total_pages}")

        with col_next:
            if st.button(
                "Next", key="liquidity_next", disabled=current_page >= total_pages - 1
            ):
                st.session_state.liquidity_page = current_page + 1
                st.rerun()
    else:
        st.info("No liquidity-qualified stocks found. Run 'Volume Filter' to analyze stocks.")


def render_trade_setups(db):
    """
    Render the trade setups list.

    Displays all qualified trade setups from Phase 4B (Setup Detection).
    This is the main output showing actionable trading opportunities.

    Features:
        - Filters by setup type (PULLBACK, VCP_BREAKOUT, RETEST, GAP_FILL)
        - Shows only qualified and active setups
        - Displays entry zones, stops, targets, R:R ratio
        - Includes quality scores from previous phases
        - 20 items per page
        - Sorted by rank (best setups first)

    Columns Displayed:
        - rank: Setup ranking (1 = best)
        - symbol: Stock ticker
        - type: Technical pattern type
        - entry_low/entry_high: Entry price range
        - stop: Stop-loss price
        - target_1/target_2: Profit targets
        - rr_ratio: Reward-to-risk ratio
        - confidence: Setup confidence score
        - overall_quality: Combined quality from all phases
        - momentum_score, consistency_score, liquidity_score

    UI Behavior:
        - Shows "No setups found" if none available
        - Updates after running Setup Detection workflow
    """
    PAGE_SIZE = 20

    # Initialize session state for pagination
    if "setups_page" not in st.session_state:
        st.session_state.setups_page = 0

    # Filter controls
    col1, col2 = st.columns([1, 3])
    with col1:
        setup_type = st.selectbox(
            "Setup Type",
            ["All", "PULLBACK", "VCP_BREAKOUT", "RETEST", "GAP_FILL"],
            key="setup_type_filter",
        )

    # Build query
    query = {"qualifies": True, "status": "active"}
    if setup_type != "All":
        query["type"] = setup_type

    # Get filtered count
    filtered_count = db.trade_setups.count_documents(query)
    total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = st.session_state.setups_page

    # Ensure current page is valid
    if current_page >= total_pages:
        current_page = total_pages - 1
        st.session_state.setups_page = current_page

    # Fetch setups for current page
    skip = current_page * PAGE_SIZE
    setups = list(
        db.trade_setups.find(query, {"_id": 0, "df": 0})
        .sort("rank", 1)
        .skip(skip)
        .limit(PAGE_SIZE)
    )

    # Display dataframe
    if setups:
        df = pd.DataFrame(setups)
        display_cols = [
            "rank",
            "symbol",
            "type",
            "entry_low",
            "entry_high",
            "stop",
            "target_1",
            "target_2",
            "rr_ratio",
            "confidence",
            "overall_quality",
            "momentum_score",
            "consistency_score",
            "liquidity_score",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        # Format numeric columns
        for col in ["entry_low", "entry_high", "stop", "target_1", "target_2"]:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "")

        st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        # Pagination controls
        col_info, col_prev, col_page, col_next = st.columns([2, 1, 2, 1])

        with col_info:
            start_idx = skip + 1
            end_idx = min(skip + PAGE_SIZE, filtered_count)
            st.caption(f"Showing {start_idx}-{end_idx} of {filtered_count}")

        with col_prev:
            if st.button("Prev", key="setups_prev", disabled=current_page == 0):
                st.session_state.setups_page = current_page - 1
                st.rerun()

        with col_page:
            st.caption(f"Page {current_page + 1} of {total_pages}")

        with col_next:
            if st.button(
                "Next", key="setups_next", disabled=current_page >= total_pages - 1
            ):
                st.session_state.setups_page = current_page + 1
                st.rerun()
    else:
        st.info("No trade setups found. Run 'Setup Detection' to find trading opportunities.")


def _run_universe_setup():
    """
    Run the universe setup workflow via Temporal.

    This is the Phase 1 workflow that:
        - Fetches NSE EQ instruments from Upstox
        - Fetches MTF instrument list
        - Fetches Nifty 50/100/500 constituents
        - Calculates quality scores (A/B/C/D tiers)
        - Applies fundamental filter using cached data
        - Saves everything to MongoDB

    Duration: 2-5 minutes
    Runs: Weekly (typically Saturday morning)

    UI Behavior:
        - Shows spinner with progress message
        - Displays success message with stats on completion
        - Auto-refreshes dashboard on success
        - Shows error message on failure
    """
    import asyncio

    from trade_analyzer.workers.start_workflow import start_universe_setup

    with st.spinner("Running Universe Setup workflow... This may take a few minutes."):
        try:
            result = asyncio.run(start_universe_setup())

            if result["success"]:
                st.success(
                    f"Universe setup complete!\n\n"
                    f"- NSE EQ: {result['total_nse_eq']}\n"
                    f"- MTF: {result['total_mtf']}\n"
                    f"- High Quality: {result['high_quality_count']}\n"
                    f"- Tier A: {result['tier_a_count']}, B: {result['tier_b_count']}, C: {result['tier_c_count']}"
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_momentum_filter():
    """
    Run the momentum filter workflow via Temporal.

    This is the Phase 2 workflow that:
        - Fetches historical price data for high-quality stocks
        - Calculates 52-week high proximity
        - Analyzes MA alignment (50/200 DMA)
        - Computes relative strength vs Nifty 50
        - Checks volatility ratio
        - Scores and qualifies stocks (4+ filters pass)

    Duration: 10-15 minutes
    Runs: Weekly (after Phase 1)

    UI Behavior:
        - Shows spinner with estimated time
        - Displays qualified count and top 10 stocks
        - Auto-refreshes dashboard
    """
    import asyncio

    from trade_analyzer.workers.start_workflow import start_momentum_filter

    with st.spinner("Running Momentum Filter workflow... This may take 10-15 minutes."):
        try:
            result = asyncio.run(start_momentum_filter())

            if result["success"]:
                st.success(
                    f"Momentum analysis complete!\n\n"
                    f"- Analyzed: {result['total_analyzed']}\n"
                    f"- Qualified (4+ filters): {result['total_qualified']}\n"
                    f"- Avg Momentum Score: {result['avg_momentum_score']:.1f}\n"
                    f"- Nifty 3M Return: {result['nifty_return_3m']:.1f}%\n\n"
                    f"Top 10 by Momentum Score:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']}: {s['momentum_score']:.1f} ({s['filters_passed']}/5 filters)"
                        for i, s in enumerate(result["top_10"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_universe_and_momentum():
    """Run the combined universe + momentum workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_universe_and_momentum

    with st.spinner("Running Full Weekend Workflow... This may take 15-20 minutes."):
        try:
            result = asyncio.run(start_universe_and_momentum())

            if result["success"]:
                st.success(
                    f"Full weekend analysis complete!\n\n"
                    f"**Universe Setup:**\n"
                    f"- NSE EQ: {result['total_nse_eq']}\n"
                    f"- MTF: {result['total_mtf']}\n"
                    f"- High Quality: {result['high_quality_count']}\n\n"
                    f"**Momentum Analysis:**\n"
                    f"- Analyzed: {result['momentum_analyzed']}\n"
                    f"- Qualified: {result['momentum_qualified']}\n"
                    f"- Avg Score: {result['avg_momentum_score']:.1f}\n\n"
                    f"Top 10 by Momentum Score:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']}: {s['momentum_score']:.1f}"
                        for i, s in enumerate(result["top_10"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_consistency_filter():
    """Run the consistency filter workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_consistency_filter

    with st.spinner("Running Consistency Filter workflow... This may take 5-10 minutes."):
        try:
            result = asyncio.run(start_consistency_filter())

            if result["success"]:
                st.success(
                    f"Consistency analysis complete!\n\n"
                    f"- Analyzed: {result['total_analyzed']}\n"
                    f"- Qualified (5+ filters): {result['total_qualified']}\n"
                    f"- Avg Final Score: {result['avg_final_score']:.1f}\n"
                    f"- Avg Consistency Score: {result['avg_consistency_score']:.1f}\n"
                    f"- Market Regime: {result['market_regime']}\n\n"
                    f"Top 10 by Final Score:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']}: {s['final_score']:.1f} (C:{s['consistency_score']:.1f}, R:{s['regime_score']:.2f})"
                        for i, s in enumerate(result["top_10"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_full_pipeline():
    """Run the full pipeline workflow (Universe + Momentum + Consistency) via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_full_pipeline

    with st.spinner("Running Full Pipeline (Phase 1-3)... This may take 20-30 minutes."):
        try:
            result = asyncio.run(start_full_pipeline())

            if result["success"]:
                st.success(
                    f"Full Pipeline (Phase 1-3) complete!\n\n"
                    f"**Phase 1 - Universe Setup:**\n"
                    f"- NSE EQ: {result['total_nse_eq']}\n"
                    f"- High Quality: {result['high_quality_count']}\n\n"
                    f"**Phase 2 - Momentum Filter:**\n"
                    f"- Qualified: {result['momentum_qualified']}\n\n"
                    f"**Phase 3 - Consistency Filter:**\n"
                    f"- Qualified: {result['consistency_qualified']}\n"
                    f"- Avg Final Score: {result['avg_final_score']:.1f}\n"
                    f"- Market Regime: {result['market_regime']}\n\n"
                    f"Top 10 by Final Score:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']}: {s['final_score']:.1f}"
                        for i, s in enumerate(result["top_10"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_volume_filter():
    """Run the volume & liquidity filter workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_volume_filter

    with st.spinner("Running Volume & Liquidity Filter... This may take 5-10 minutes."):
        try:
            result = asyncio.run(start_volume_filter())

            if result["success"]:
                st.success(
                    f"Volume & Liquidity analysis complete!\n\n"
                    f"- Analyzed: {result['total_analyzed']}\n"
                    f"- Qualified: {result['total_qualified']}\n"
                    f"- Avg Liquidity Score: {result['avg_liquidity_score']:.1f}\n"
                    f"- Avg Turnover (20D): Rs.{result['avg_turnover_20d']:.1f} Cr\n\n"
                    f"Top 10 by Liquidity Score:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']}: {s['liquidity_score']:.1f} (T/O: Rs.{s['turnover_20d_cr']:.1f}Cr)"
                        for i, s in enumerate(result["top_10"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_setup_detection():
    """Run the setup detection workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_setup_detection

    with st.spinner("Running Setup Detection... This may take 5-10 minutes."):
        try:
            result = asyncio.run(start_setup_detection())

            if result["success"]:
                setup_types = ", ".join(f"{k}: {v}" for k, v in result["setups_by_type"].items())
                st.success(
                    f"Setup Detection complete!\n\n"
                    f"- Stocks Analyzed: {result['total_analyzed']}\n"
                    f"- Setups Found: {result['total_setups_found']}\n"
                    f"- Setups Qualified: {result['total_qualified']}\n"
                    f"- Avg Confidence: {result['avg_confidence']:.1f}%\n"
                    f"- Avg R:R Ratio: {result['avg_rr_ratio']:.2f}\n"
                    f"- Market Regime: {result['market_regime']}\n"
                    f"- By Type: {setup_types}\n\n"
                    f"Top Setups:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']} ({s['type']}): Entry {s.get('entry_low', 0):.0f}-{s.get('entry_high', 0):.0f}, Stop {s.get('stop', 0):.0f}, R:R {s.get('rr_ratio', 0):.1f}"
                        for i, s in enumerate(result["top_setups"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_phase4_pipeline():
    """Run the Phase 4 pipeline (Volume + Setup Detection) via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_phase4_pipeline

    with st.spinner("Running Phase 4 Pipeline... This may take 10-15 minutes."):
        try:
            result = asyncio.run(start_phase4_pipeline())

            if result["success"]:
                setup_types = ", ".join(f"{k}: {v}" for k, v in result["setups_by_type"].items())
                st.success(
                    f"Phase 4 Pipeline complete!\n\n"
                    f"**Phase 4A - Volume Filter:**\n"
                    f"- Analyzed: {result['volume_analyzed']}\n"
                    f"- Qualified: {result['volume_qualified']}\n"
                    f"- Avg Liquidity: {result['avg_liquidity_score']:.1f}\n\n"
                    f"**Phase 4B - Setup Detection:**\n"
                    f"- Setups Found: {result['setups_found']}\n"
                    f"- Setups Qualified: {result['setups_qualified']}\n"
                    f"- By Type: {setup_types}\n"
                    f"- Avg Confidence: {result['avg_confidence']:.1f}%\n"
                    f"- Market Regime: {result['market_regime']}\n\n"
                    f"Top Setups:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']} ({s['type']}): R:R {s.get('rr_ratio', 0):.1f}"
                        for i, s in enumerate(result["top_setups"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_full_analysis():
    """Run the full analysis pipeline (Phase 1-4) via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_full_analysis_pipeline

    with st.spinner("Running Full Analysis Pipeline (Phase 1-4)... This may take 30-45 minutes."):
        try:
            result = asyncio.run(start_full_analysis_pipeline())

            if result["success"]:
                setup_types = ", ".join(f"{k}: {v}" for k, v in result["setups_by_type"].items())
                st.success(
                    f"Full Analysis Pipeline (Phase 1-4) complete!\n\n"
                    f"**Phase 1 - Universe:**\n"
                    f"- NSE EQ: {result['total_nse_eq']}\n"
                    f"- High Quality: {result['high_quality_count']}\n\n"
                    f"**Phase 2 - Momentum:**\n"
                    f"- Qualified: {result['momentum_qualified']}\n\n"
                    f"**Phase 3 - Consistency:**\n"
                    f"- Qualified: {result['consistency_qualified']}\n\n"
                    f"**Phase 4 - Setups:**\n"
                    f"- Liquidity Qualified: {result['liquidity_qualified']}\n"
                    f"- Trade Setups: {result['setups_qualified']}\n"
                    f"- By Type: {setup_types}\n"
                    f"- Market Regime: {result['market_regime']}\n\n"
                    f"Top Trade Setups:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']} ({s['type']}): Entry {s.get('entry_low', 0):.0f}-{s.get('entry_high', 0):.0f}"
                        for i, s in enumerate(result["top_setups"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


# ============================================================================
# Monthly Fundamental Data Refresh + Phase 5-8 Workflow Runners
# ============================================================================


def _run_fundamental_data_refresh():
    """
    Run the MONTHLY fundamental data refresh workflow via Temporal.

    This is a monthly maintenance workflow (NOT part of weekly pipeline) that:
        - Fetches fundamental metrics from FMP/Alpha Vantage APIs
        - Calculates fundamental scores (PE, ROE, debt ratios, etc.)
        - Fetches institutional holding percentages
        - Caches all data in MongoDB
        - Data is used by Phase 1 for weekly filtering

    Duration: 30-60 minutes (API rate limits)
    Runs: Monthly (after quarterly earnings)
    Cost: API calls (respects rate limits)

    UI Behavior:
        - Shows long-running spinner with time estimate
        - Displays cached data stats on completion
        - Explains this feeds into Phase 1
    """
    import asyncio

    from trade_analyzer.workers.start_workflow import start_fundamental_data_refresh

    with st.spinner("Running Fundamental Data Refresh (Monthly)... This may take 30-60 minutes."):
        try:
            result = asyncio.run(start_fundamental_data_refresh())

            if result["success"]:
                st.success(
                    f"Fundamental Data Refresh complete!\n\n"
                    f"This data will be used by Phase 1 (Universe Setup) for weekly filtering.\n\n"
                    f"- Symbols Analyzed: {result['symbols_analyzed']}\n"
                    f"- Fundamental Saved: {result['fundamental_saved']}\n"
                    f"- Fundamental Qualified: {result['fundamental_qualified']}\n"
                    f"- Holdings Saved: {result['holdings_saved']}\n"
                    f"- Holdings Qualified: {result['holdings_qualified']}\n"
                    f"- Combined Qualified: {result['combined_qualified']}\n"
                    f"- Avg Score: {result['avg_fundamental_score']:.1f}\n\n"
                    f"Top 10 by Fundamental Score:\n"
                    + "\n".join(
                        f"  {i+1}. {s['symbol']}: {s['fundamental_score']:.1f}"
                        for i, s in enumerate(result["top_10"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_fundamental_filter():
    """Run the fundamental filter workflow via Temporal (legacy - uses data refresh)."""
    _run_fundamental_data_refresh()


def _run_risk_geometry():
    """Run the risk geometry workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_risk_geometry

    with st.spinner("Running Risk Geometry... This may take 10-15 minutes."):
        try:
            result = asyncio.run(start_risk_geometry())

            if result["success"]:
                st.success(
                    f"Risk Geometry complete!\n\n"
                    f"- Setups Analyzed: {result['setups_analyzed']}\n"
                    f"- Risk Qualified: {result['risk_qualified']}\n"
                    f"- Total Risk: Rs.{result['total_risk']:,.0f}\n"
                    f"- Total Value: Rs.{result['total_value']:,.0f}\n"
                    f"- Avg R:R Ratio: {result['avg_rr_ratio']:.2f}\n\n"
                    f"Top Positions:\n"
                    + "\n".join(
                        f"  {i+1}. {p['symbol']}: Entry {p['entry']:.0f}, Stop {p['stop']:.0f}, R:R {p['rr_ratio']:.1f}"
                        for i, p in enumerate(result["top_positions"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_portfolio_construction():
    """Run the portfolio construction workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_portfolio_construction

    with st.spinner("Running Portfolio Construction... This may take 10-15 minutes."):
        try:
            result = asyncio.run(start_portfolio_construction())

            if result["success"]:
                sector_alloc = ", ".join(f"{k}: {v:.1f}%" for k, v in result["sector_allocation"].items())
                st.success(
                    f"Portfolio Construction complete!\n\n"
                    f"- Input Setups: {result['setups_input']}\n"
                    f"- After Correlation: {result['after_correlation_filter']}\n"
                    f"- After Sector Limits: {result['after_sector_limits']}\n"
                    f"- Final Positions: {result['final_positions']}\n"
                    f"- Invested %: {result['total_invested_pct']:.1f}%\n"
                    f"- Risk %: {result['total_risk_pct']:.1f}%\n"
                    f"- Cash Reserve %: {result['cash_reserve_pct']:.1f}%\n"
                    f"- Sector Allocation: {sector_alloc}\n\n"
                    f"Final Positions:\n"
                    + "\n".join(
                        f"  {i+1}. {p['symbol']}: {p.get('shares', 0)} shares, Rs.{p.get('position_value', 0):,.0f}"
                        for i, p in enumerate(result["positions"][:10])
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_premarket_analysis():
    """Run the pre-market analysis workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_premarket_analysis

    with st.spinner("Running Pre-Market Analysis..."):
        try:
            result = asyncio.run(start_premarket_analysis())

            if result["success"]:
                st.success(
                    f"Pre-Market Analysis complete!\n\n"
                    f"- Total Setups: {result['total_setups']}\n"
                    f"- ENTER: {result['enter_count']}\n"
                    f"- SKIP: {result['skip_count']}\n"
                    f"- WAIT: {result['wait_count']}\n\n"
                    f"Gap Analysis:\n"
                    + "\n".join(
                        f"  {g['symbol']}: {g['action']} ({g['reason'][:50]}...)"
                        for g in result["gap_analyses"][:10]
                    )
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_position_status():
    """Run the position status workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_position_status

    with st.spinner("Updating Position Status..."):
        try:
            result = asyncio.run(start_position_status())

            if result["success"]:
                st.success(
                    f"Position Status Updated!\n\n"
                    f"- Total Positions: {result['total_positions']}\n"
                    f"- In Profit: {result['in_profit']}\n"
                    f"- In Loss: {result['in_loss']}\n"
                    f"- Stopped Out: {result['stopped_out']}\n"
                    f"- Target Hit: {result['target_hit']}\n"
                    f"- Total P&L: Rs.{result['total_pnl']:,.0f}\n"
                    f"- Total R: {result['total_r_multiple']:.2f}R\n\n"
                    f"Alerts:\n"
                    + "\n".join(result["alerts"][:10]) if result["alerts"] else "No alerts"
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_friday_close():
    """Run the Friday close workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_friday_close

    with st.spinner("Generating Friday Summary..."):
        try:
            result = asyncio.run(start_friday_close())

            if result["success"]:
                st.success(
                    f"Friday Summary Generated!\n\n"
                    f"**Week: {result['week_start']} to {result['week_end']}**\n\n"
                    f"- Total Trades: {result['total_trades']}\n"
                    f"- Wins: {result['wins']}, Losses: {result['losses']}\n"
                    f"- Win Rate: {result['win_rate']:.1f}%\n"
                    f"- Realized P&L: Rs.{result['realized_pnl']:,.0f}\n"
                    f"- Unrealized P&L: Rs.{result['unrealized_pnl']:,.0f}\n"
                    f"- Total P&L: Rs.{result['total_pnl']:,.0f}\n"
                    f"- Total R: {result['total_r']:.2f}R\n\n"
                    f"**System Health: {result['system_health_score']}/100**\n"
                    f"Recommended Action: {result['recommended_action']}"
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_weekly_recommendation():
    """Run the weekly recommendation workflow via Temporal."""
    import asyncio

    from trade_analyzer.workers.start_workflow import start_weekly_recommendation

    with st.spinner("Generating Weekly Recommendations..."):
        try:
            result = asyncio.run(start_weekly_recommendation())

            if result["success"]:
                st.success(
                    f"Weekly Recommendations Generated!\n\n"
                    f"**Week of {result['week_display']}**\n"
                    f"- Market Regime: {result['market_regime'].upper()}\n"
                    f"- Confidence: {result['regime_confidence']:.0f}%\n\n"
                    f"- Total Setups: {result['total_setups']}\n"
                    f"- Allocated Capital: Rs.{result['allocated_capital']:,.0f}\n"
                    f"- Allocated %: {result['allocated_pct']:.1f}%\n"
                    f"- Total Risk %: {result['total_risk_pct']:.1f}%\n\n"
                    f"View recommendations in the Phase 9 section."
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def _run_complete_weekly_pipeline():
    """
    Run the complete weekly pipeline (Phase 4B-8) via Temporal.

    This is the MASTER WEEKEND WORKFLOW that runs the entire system end-to-end:
        - Phase 4B: Setup Detection (technical patterns)
        - Phase 5: Risk Geometry (position sizing)
        - Phase 6: Portfolio Construction (correlation, sector limits)
        - Phase 8: Weekly Recommendations (final trade list)

    Assumes Phase 1-4A already completed earlier in the week.

    Duration: 45-60 minutes
    Runs: Saturday/Sunday (main weekend analysis)
    Output: 3-7 trade recommendations for Monday

    UI Behavior:
        - Shows long-running spinner
        - Displays full pipeline summary
        - Shows final recommendation count and allocation
        - This is the "one-click" weekend run button
    """
    import asyncio

    from trade_analyzer.workers.start_workflow import start_complete_weekly_pipeline

    with st.spinner("Running Complete Weekly Pipeline (Phase 4B-9)... This may take 45-60 minutes."):
        try:
            result = asyncio.run(start_complete_weekly_pipeline())

            if result["success"]:
                st.success(
                    f"Complete Weekly Pipeline Finished!\n\n"
                    f"**Week of {result['week_display']}**\n"
                    f"- Market Regime: {result['market_regime'].upper()}\n\n"
                    f"**Pipeline Summary:**\n"
                    f"- Phase 4B (Setups): {result['phase_4_setups']}\n"
                    f"- Phase 5 (Fundamental): {result['phase_5_fundamental']}\n"
                    f"- Phase 6 (Risk): {result['phase_6_risk_qualified']}\n"
                    f"- Phase 7 (Portfolio): {result['phase_7_final_positions']}\n\n"
                    f"**Final Output:**\n"
                    f"- Total Recommendations: {result['total_setups']}\n"
                    f"- Allocated Capital: Rs.{result['allocated_capital']:,.0f}\n"
                    f"- Allocated %: {result['allocated_pct']:.1f}%\n"
                    f"- Total Risk %: {result['total_risk_pct']:.1f}%\n\n"
                    f"View detailed recommendations in Phase 9 section."
                )
                st.rerun()
            else:
                st.error(f"Workflow failed: {result['error']}")
        except Exception as e:
            st.error(f"Failed to run workflow: {e}")


def render_settings():
    """
    Render the settings page.

    Displays system configuration and parameters:
        - Database connection status with disconnect option
        - Risk parameters (editable via number inputs):
          * Max risk per trade (%)
          * Max sector exposure (%)
          * Min reward:risk ratio
          * Max stop distance (%)

    Note:
        Currently for display only. Parameter changes not yet persisted
        to database. Will be implemented in future version.

    UI Components:
        - Connection status indicator
        - Disconnect button (if connected)
        - Risk parameter input controls (2 columns)
    """
    st.header("Settings")

    st.subheader("Database Configuration")
    if st.session_state.get("db_connected"):
        st.success("Connected to MongoDB")
        if st.button("Disconnect"):
            from trade_analyzer.db import MongoDBConnection

            MongoDBConnection().disconnect()
            st.session_state.db_connected = False
            st.session_state.db = None
            st.rerun()
    else:
        st.warning("Not connected to database")

    st.markdown("---")

    st.subheader("Risk Parameters")
    col1, col2 = st.columns(2)
    with col1:
        st.number_input("Max Risk per Trade (%)", value=1.5, min_value=0.5, max_value=3.0)
        st.number_input("Max Sector Exposure (%)", value=25.0, min_value=10.0, max_value=50.0)
    with col2:
        st.number_input("Min Reward:Risk Ratio", value=2.0, min_value=1.5, max_value=5.0)
        st.number_input("Max Stop Distance (%)", value=7.0, min_value=3.0, max_value=10.0)


def run_app():
    """
    Main entry point for the Streamlit app.

    This function:
        1. Initializes database connection
        2. Renders sidebar navigation
        3. Routes to appropriate page based on selection

    Pages:
        - Dashboard: Main control center (default)
        - Regime: Market regime analysis (placeholder)
        - Setups: Trade setup filtering (placeholder)
        - Trades: Trade tracking and performance (placeholder)
        - Settings: System configuration

    Called automatically when running as a script or via streamlit run.
    """
    init_db_connection()

    page = render_sidebar()

    if page == "Dashboard":
        render_dashboard()
    elif page == "Regime":
        render_regime()
    elif page == "Setups":
        render_setups()
    elif page == "Trades":
        render_trades()
    elif page == "Settings":
        render_settings()


if __name__ == "__main__":
    run_app()
