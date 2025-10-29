import os
import asyncio
from pathlib import Path
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from loguru import logger
from dotenv import load_dotenv
import logging
import sys

from handlers.db.database import Database
from handlers.users.keyboard import get_main_keyboard_async
from handlers.db.create_db import create_tables
from handlers.users.sub import free_router, paid_router, vless_router
from handlers.users import tariffs_router, about_router, support_router, vpn_setup_router, lk_router, bonus_router
from handlers.users.promocodes import router as promocodes_router
from handlers.yookassa import yookassa_api
from handlers.yoomoney import router as yoomoney_router
from handlers import check_sub_router
from handlers.check_sub import subscription_checker
from handlers.admin import admin_router
from handlers.admin.users import router as users_router
from handlers.admin.admuser.send_message import router as send_message_router
from handlers.admin.admuser.add_sub import router as add_sub_router
from handlers.admin.admuser.extend_sub import router as extend_sub_router
from handlers.admin.admuser.del_sub import router as delete_sub_router
from handlers.admin.tariffs import router as admin_tariffs_router
from handlers.admin.promocodes import router as admin_promocodes_router
from handlers.admin.show_payments import router as payments_router
from handlers.commands import router as commands_router
from handlers.admin.bonus import router as admin_bonus_router
from handlers.admin.free_tariff import router as free_tariff_router
from handlers.admin.broadcast import router as broadcast_router
from handlers.admin.load_nodes import router as load_nodes_router
from handlers.tgstars import router as tgstars_router
from handlers.admin.service import router as service_router
from handlers.admin.bot_messages import router as bot_messages_router
from handlers.users.crypto_payments import router as crypto_payments_router
from handlers.users.gift_code import router as gift_code_router
from handlers.admin.gift_codes import router as gift_codes_router
from handlers.license import license_router, scheduled_license_check, require_valid_license
from handlers.remnaware import RemnawareAPI
from handlers.watapro import cleanup_watapro
from handlers.users.watapro_payments import router as watapro_payments_router
from handlers.pally import cleanup_pally
from handlers.users.pally_payments import router as pally_payments_router
from handlers.users.platega_payments import router as platega_payments_router
from handlers.platega import platega_api

load_dotenv()

log_path = Path(__file__).parent / "logs" / "bot.log"
logger.add(log_path, rotation="5 MB", level=os.getenv("LOG_LEVEL", "INFO"))

db = Database()

async def get_available_nodes_list() -> str:
    """Получение списка доступных нод для замены в тексте сообщения"""
    try:
        api = RemnawareAPI()
        await api._ensure_session()
        await api._ensure_auth()
        nodes_data = await api.get_all_nodes()
        logger.debug(f"Получены данные о нодах для списка: {nodes_data}")
        
        nodes_list = []
        
        if isinstance(nodes_data, list):
            for node in nodes_data:
                if isinstance(node, dict) and 'name' in node:
                    nodes_list.append(f"• {node['name']}")
        
        if nodes_list:
            return "\n".join(sorted(set(nodes_list)))
        else:
            logger.warning(f"Не удалось извлечь список нод из ответа: {nodes_data}")
            return "• Список нод временно недоступен"
            
    except Exception as e:
        logger.error(f"Ошибка при получении списка нод: {e}")
        return "• Список нод временно недоступен"
    finally:
        if 'api' in locals() and hasattr(api, 'close'):
            await api.close()

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    try:
        args = message.text.split()
        ref_code = args[1] if len(args) > 1 else None
        is_new_user = False
        
        user_data = {
            "telegram_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "status": "active"
        }
        
        existing_user = await db.get_user(message.from_user.id)
        if not existing_user:
            is_new_user = True
        
        await db.register_user(user_data)
        
        if ref_code and is_new_user:
            referrer_id = await db.get_referrer_by_code(ref_code)
            if referrer_id and referrer_id != message.from_user.id:
                ref_settings = await db.get_referral_settings()
                if ref_settings and ref_settings['is_enabled']:
                    await db.create_referral(referrer_id, message.from_user.id)
                    logger.info(f"Создана реферальная связь: реферер {referrer_id}, реферал {message.from_user.id}")
        
        welcome_message = await db.get_bot_message("start")
        
        if welcome_message:
            text = welcome_message["text"]
            username = message.from_user.username or message.from_user.first_name or "Пользователь"
            text = text.replace("{username}", username)
            
            if "{nodes_list}" in text:
                nodes_list = await get_available_nodes_list()
                text = text.replace("{nodes_list}", nodes_list)
            
            keyboard = await get_main_keyboard_async()
            
            if welcome_message.get("image"):
                image_path = Path(__file__).parent / "static" / "images" / welcome_message["image"]
                
                if image_path.exists():
                    try:
                        await message.answer_photo(
                            photo=FSInputFile(image_path),
                            caption=text,
                            reply_markup=keyboard,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as img_error:
                        logger.error(f"Ошибка при отправке изображения: {img_error}")
                        await message.answer(
                            text,
                            reply_markup=keyboard,
                            parse_mode=ParseMode.HTML
                        )
                else:
                    logger.warning(f"Изображение {image_path} не найдено")
                    await message.answer(
                        text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML
                    )
            else:
                await message.answer(
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
        else:
            username = message.from_user.username or message.from_user.first_name or "Пользователь"
            await message.answer(
                f"Привет, {username}! Добро пожаловать!.",
                reply_markup=await get_main_keyboard_async(),
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /start: {e}")
        await message.answer("Произошла ошибка при обработке запроса.")

@router.callback_query(F.data == "back")
async def process_back_button(callback: CallbackQuery):
    """Обработчик нажатия на кнопку 'Назад'."""
    try:
        await callback.answer()
        
        welcome_message = await db.get_bot_message("start")
        
        if welcome_message:
            text = welcome_message["text"]
            username = callback.from_user.username or callback.from_user.first_name or "Пользователь"
            text = text.replace("{username}", username)
            
            if "{nodes_list}" in text:
                nodes_list = await get_available_nodes_list()
                text = text.replace("{nodes_list}", nodes_list)
            
            keyboard = await get_main_keyboard_async()
            
            try:
                await callback.message.delete()
                
                if welcome_message.get("image"):
                    image_path = Path(__file__).parent / "static" / "images" / welcome_message["image"]
                    if image_path.exists():
                        try:
                            await callback.message.answer_photo(
                                photo=FSInputFile(image_path),
                                caption=text,
                                reply_markup=keyboard,
                                parse_mode=ParseMode.HTML
                            )
                        except Exception as img_error:
                            logger.error(f"Ошибка при отправке изображения: {img_error}")
                            await callback.message.answer(
                                text,
                                reply_markup=keyboard,
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        logger.warning(f"Изображение {image_path} не найдено")
                        await callback.message.answer(
                            text,
                            reply_markup=keyboard,
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await callback.message.answer(
                        text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e:
                logger.error(f"Ошибка при удалении или отправке сообщения: {e}")
                if welcome_message.get("image"):
                    image_path = Path(__file__).parent / "static" / "images" / welcome_message["image"]
                    if image_path.exists():
                        try:
                            await callback.message.answer_photo(
                                photo=FSInputFile(image_path),
                                caption=text,
                                reply_markup=keyboard,
                                parse_mode=ParseMode.HTML
                            )
                        except Exception as img_error:
                            logger.error(f"Ошибка при отправке изображения (запасной вариант): {img_error}")
                            await callback.message.answer(
                                text,
                                reply_markup=keyboard,
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        await callback.message.answer(
                            text,
                            reply_markup=keyboard,
                            parse_mode=ParseMode.HTML
                        )
        else:
            try:
                await callback.message.delete()
                username = callback.from_user.username or callback.from_user.first_name or "Пользователь"
                await callback.message.answer(
                    f"Добро пожаловать в главное меню, {username}!",
                    reply_markup=await get_main_keyboard_async(),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Ошибка при удалении или отправке сообщения: {e}")
                username = callback.from_user.username or callback.from_user.first_name or "Пользователь"
                await callback.message.answer(
                    f"Добро пожаловать в главное меню, {username}!",
                    reply_markup=await get_main_keyboard_async(),
                    parse_mode=ParseMode.HTML
                )
    except Exception as e:
        logger.error(f"Ошибка при обработке кнопки 'Назад': {e}")

dp: Dispatcher = None

async def main():
    bot = Bot(
        token=os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    global dp
    dp = Dispatcher(storage=MemoryStorage())
    
    await create_tables()
    
    global_pool = await db.get_global_pool()
    if not global_pool:
        logger.error("Не удалось создать глобальный пул соединений с БД. Завершение работы.")
        return
    
    logger.info("Создан глобальный пул соединений с БД для всего приложения")
    
    dp.include_router(router)
    dp.include_router(commands_router)  
    dp.include_router(free_router)
    dp.include_router(paid_router)
    dp.include_router(tariffs_router)
    dp.include_router(about_router)
    dp.include_router(support_router)
    dp.include_router(vpn_setup_router)
    dp.include_router(lk_router)
    dp.include_router(promocodes_router)
    dp.include_router(check_sub_router)
    dp.include_router(admin_router)
    dp.include_router(users_router)
    dp.include_router(send_message_router)
    dp.include_router(add_sub_router)
    dp.include_router(extend_sub_router)
    dp.include_router(delete_sub_router)
    dp.include_router(admin_tariffs_router)
    dp.include_router(admin_promocodes_router)
    dp.include_router(payments_router)
    dp.include_router(bonus_router)
    dp.include_router(admin_bonus_router)
    dp.include_router(free_tariff_router)
    dp.include_router(broadcast_router)
    dp.include_router(load_nodes_router)
    dp.include_router(tgstars_router)
    dp.include_router(service_router)
    dp.include_router(vless_router)
    dp.include_router(bot_messages_router)
    dp.include_router(crypto_payments_router)
    dp.include_router(yoomoney_router)
    dp.include_router(gift_code_router)
    dp.include_router(gift_codes_router)
    dp.include_router(watapro_payments_router)
    dp.include_router(pally_payments_router)
    dp.include_router(platega_payments_router)
    dp.include_router(license_router)
    asyncio.create_task(subscription_checker(bot))
    asyncio.create_task(scheduled_license_check(bot))
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        logger.info("Бот остановлен")
        await db.close_pool()
        await cleanup_watapro()  # Очистка ресурсов WataPro
        await cleanup_pally()  # Очистка ресурсов Pally

if __name__ == "__main__":
    asyncio.run(main())