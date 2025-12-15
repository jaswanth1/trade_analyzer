"""Main Streamlit application for Trade Analyzer."""

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
    """Render the sidebar navigation."""
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
    """Render the main dashboard page with all functionality."""
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

    # Top row: Stats and buttons
    col_stats, col_action = st.columns([4, 1])

    with col_stats:
        stat_cols = st.columns(6)
        with stat_cols[0]:
            st.metric("Total NSE EQ", total_nse_eq)
        with stat_cols[1]:
            st.metric("MTF Eligible", mtf_count)
        with stat_cols[2]:
            st.metric("High Quality", high_quality)
        with stat_cols[3]:
            st.metric("Tier A", tier_a)
        with stat_cols[4]:
            st.metric("Tier B", tier_b)
        with stat_cols[5]:
            st.metric("Tier C", tier_c)

    with col_action:
        if st.button("Setup Universe", type="primary"):
            _run_universe_setup()

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
    """Render a paginated stock list with search."""
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
    """Render the trade setups list."""
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
    """Run the universe setup workflow via Temporal."""
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
    """Run the momentum filter workflow via Temporal."""
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


def render_settings():
    """Render the settings page."""
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
    """Main entry point for the Streamlit app."""
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
