from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    search_type = State()
    gender_pref = State()
    budget = State()
    budget_custom = State()
    rooms = State()
    areas = State()
    move_in = State()
    commute_origin = State()
    commute_minutes = State()
    commute_mode = State()
    dealbreakers = State()
    agent_filter = State()
    axis_priority = State()
    free_text_wall = State()
    free_text_1 = State()
    free_text_2 = State()
    free_text_3 = State()


class Settings(StatesGroup):
    main_menu = State()
    edit_budget = State()
    edit_budget_custom = State()
    edit_areas = State()
    edit_search_type = State()
    edit_gender_pref = State()
    edit_commute_origin = State()
    edit_commute_minutes = State()
    edit_commute_mode = State()
    edit_dealbreakers = State()
    edit_agent_filter = State()
