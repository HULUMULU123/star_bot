from aiogram.fsm.state import State, StatesGroup


class GiftStates(StatesGroup):
    waiting_for_recipient = State()
