"""
Interactive argument prompting
Запрос обязательных параметров у пользователя

When a command is issued without its required argument, the handler calls
prompt_arg(...) which puts the user into a waiting state and asks for the value.
The reply is then routed back to the registered executor. /cancel aborts.

This makes commands usable from buttons (a button can just send "/enable" and
the bot will ask for the pair id).
"""

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="interactive")

router = Router()


class AwaitArg(StatesGroup):
    """State for awaiting a command's required argument"""

    value = State()


# action_key -> async executor(message, arg, state)
_executors = {}
# action_key -> prompt text shown to the user
_prompts = {}


def register_action(key: str, executor, prompt: str):
    """Register an executor + prompt for an interactive action"""
    _executors[key] = executor
    _prompts[key] = prompt


def get_command_arg(text: str) -> str:
    """Return everything after the command token (the argument string)"""
    parts = (text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def prompt_arg(message: Message, state: FSMContext, action_key: str):
    """Ask the user to provide the missing argument for action_key"""
    await state.set_state(AwaitArg.value)
    await state.update_data(pending_action=action_key)
    await message.answer(_prompts[action_key], parse_mode="HTML")


async def _on_arg(message: Message, state: FSMContext):
    """Receive the awaited argument and dispatch to the registered executor"""
    data = await state.get_data()
    action = data.get("pending_action")
    arg = (message.text or "").strip()

    # Typing another command cancels the pending prompt instead of being used as arg
    # Ввод другой команды отменяет ожидание, а не используется как аргумент
    if arg.startswith("/"):
        await state.clear()
        await message.answer(Messages.ACTION_CANCELLED, parse_mode="HTML")
        return

    await state.clear()

    executor = _executors.get(action)
    if not executor:
        await message.answer(Messages.GENERIC_ERROR, parse_mode="HTML")
        return

    await executor(message, arg, state)


async def _on_cancel(message: Message, state: FSMContext):
    """Cancel a pending argument prompt"""
    await state.clear()
    await message.answer(Messages.ACTION_CANCELLED, parse_mode="HTML")


def setup_interactive_handlers(dp):
    """Register the interactive prompt handlers (must be included once)"""
    # /cancel first so it takes precedence over the generic text catcher
    router.message.register(_on_cancel, Command("cancel"), StateFilter(AwaitArg.value))
    router.message.register(_on_arg, StateFilter(AwaitArg.value), F.text)
    dp.include_router(router)
