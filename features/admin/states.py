"""FSM states for admin feature."""
from aiogram.fsm.state import StatesGroup, State


class ADMIN_States(StatesGroup):
    """Admin feature states following FEAT__GROUP__STEP format."""
    
    # Broadcast states
    BROADCAST_TEXT = State()  # ADMIN__BROADCAST__TEXT
    BROADCAST_PREVIEW = State()  # ADMIN__BROADCAST__PREVIEW
    BROADCAST_ADD_PHOTO = State()  # ADMIN__BROADCAST__ADD_PHOTO
    BROADCAST_ADD_BUTTON_TEXT = State()  # ADMIN__BROADCAST__ADD_BUTTON_TEXT
    BROADCAST_ADD_BUTTON_URL = State()  # ADMIN__BROADCAST__ADD_BUTTON_URL
    BROADCAST_CONFIRM = State()  # ADMIN__BROADCAST__CONFIRM

