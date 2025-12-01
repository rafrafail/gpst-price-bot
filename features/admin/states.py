"""FSM states for admin feature."""
from aiogram.fsm.state import StatesGroup, State


class ADMIN_States(StatesGroup):
    """Admin feature states following FEAT__GROUP__STEP format."""
    
    # Broadcast states
    BROADCAST_TEXT = State()  # ADMIN__BROADCAST__TEXT
    BROADCAST_CONFIRM = State()  # ADMIN__BROADCAST__CONFIRM

