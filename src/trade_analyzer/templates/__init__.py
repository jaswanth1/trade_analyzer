"""
Trade setup templates for recommendation generation.

This package provides template generation for trade recommendations,
transforming pipeline data into human-readable recommendation cards.

Components:
----------
1. TradeSetupTemplate
   - Dataclass holding all recommendation data
   - Combines scores from all pipeline phases
   - Includes entry/exit levels and position sizing

2. generate_recommendation_card()
   - Creates TradeSetupTemplate from position data
   - Calculates final conviction score
   - Generates action steps and gap contingency

3. generate_text_template()
   - Formats recommendation as text card
   - Suitable for display or export

Usage:
------
    from trade_analyzer.templates import (
        generate_recommendation_card,
        generate_text_template,
    )

    # Generate recommendation from position data
    card = generate_recommendation_card(
        position=position_dict,
        portfolio_value=1000000,
        market_regime="risk_on",
    )

    # Generate formatted text
    text = generate_text_template(card)
    print(text)

See Also:
---------
- trade_analyzer.activities.recommendation: Creates position data
- trade_analyzer.workflows.weekly_recommendation: Orchestrates pipeline
"""

from trade_analyzer.templates.trade_setup import (
    TradeSetupTemplate,
    generate_text_template,
    generate_recommendation_card,
)

__all__ = [
    "TradeSetupTemplate",
    "generate_text_template",
    "generate_recommendation_card",
]
