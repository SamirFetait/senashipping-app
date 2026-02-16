"""
Sorting utilities for consistent row ordering across all tables.
"""

from __future__ import annotations

import re
from typing import Any


def get_pen_sort_key(pen: Any, deck_field: str = "deck") -> tuple:
    """
    Return tuple (number, letter_order, deck) for 3-level sorting of pens.
    
    Sorting order:
    1. Primary: Extract number from pen name (1, 2, 3...)
    2. Secondary: Extract letter pattern from pen name (A, B, C, D... alphabetical)
    3. Tertiary: Sort by deck (A, B, C, D, E, F, G, H alphabetical)
    
    Example: 1-A (deck A) → 1-B (deck A) → 1-C (deck A) → 1-D (deck A) → 
             2-A (deck A) → 1-A (deck B) → 1-B (deck B)
    
    Args:
        pen: Object with 'name' attribute and deck attribute (field name in deck_field)
        deck_field: Name of the attribute containing deck value (default: "deck")
    
    Returns:
        Tuple (number, letter_order, deck) for sorting
    """
    # Extract number (primary sort)
    name = getattr(pen, "name", "") or ""
    numbers = re.findall(r'\d+', name)
    number = int(numbers[0]) if numbers else 9999
    
    # Extract letter after number (secondary sort: alphabetical A, B, C, D...)
    # Look for pattern like "1-A", "1-B", etc.
    letter_match = re.search(r'\d+[-_]?([A-Za-z])', name)
    if letter_match:
        letter = letter_match.group(1).upper()
        # Use ASCII value for alphabetical sorting (A=65, B=66, C=67, D=68...)
        letter_order = ord(letter)
    else:
        letter_order = 999  # No letter pattern found
    
    # Deck (tertiary sort: alphabetical A-H)
    deck = getattr(pen, deck_field, "") or ""
    if isinstance(deck, str):
        deck = deck.strip().upper()
    else:
        deck = str(deck).strip().upper()
    
    # Normalize deck
    if deck and deck not in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        if deck.startswith("DK") and len(deck) > 2:
            try:
                deck_num = int(deck[2:])
                if 1 <= deck_num <= 8:
                    deck = chr(ord("A") + deck_num - 1)
            except ValueError:
                pass
        elif deck.isdigit():
            try:
                deck_num = int(deck)
                if 1 <= deck_num <= 8:
                    deck = chr(ord("A") + deck_num - 1)
            except ValueError:
                pass
    if deck not in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        deck = "Z"  # Put invalid decks at end
    
    return (number, letter_order, deck)


def get_tank_sort_key(tank: Any, deck_field: str = "deck_name") -> tuple:
    """
    Return tuple (number, letter_order, deck) for 3-level sorting of tanks.
    
    Same pattern as pens: number -> letter pattern (A,B,C,D alphabetical) -> deck (A-H alphabetical)
    
    Args:
        tank: Object with 'name' attribute and deck attribute
        deck_field: Name of the attribute containing deck value (default: "deck_name")
    
    Returns:
        Tuple (number, letter_order, deck) for sorting
    """
    return get_pen_sort_key(tank, deck_field=deck_field)
