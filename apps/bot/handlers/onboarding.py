"""Onboarding FSM handlers — implemented in Task 8."""
from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def start_search_type(message: Message, state: FSMContext) -> None:  # pragma: no cover
    raise NotImplementedError("Onboarding FSM not yet implemented (Task 8)")
