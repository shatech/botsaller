from aiogram.fsm.state import State, StatesGroup


class OrderWizardState(StatesGroup):
    waiting_for_field = State()
    confirming_order = State()


class WalletDepositState(StatesGroup):
    selecting_network = State()
    waiting_for_txid = State()

